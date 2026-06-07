from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from jinja2 import Environment, FileSystemLoader, select_autoescape

from api import presentation, service
from api.worker import DownloadWorker
from api.scheduler import CheckScheduler
from config.config import Config
from nebula_api.authorization import NebulaUserAuthorization
from utils import db, jobs_db
from utils.db import list_channels_with_info


def create_app(
    config: Config,
    auth: NebulaUserAuthorization,
    *,
    start_background: bool = True,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        config: Configuration object
        auth: Authorization object
        start_background: If True, start worker and scheduler on startup

    Returns:
        Configured FastAPI application
    """
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        if start_background:
            service.seed_subscriptions_from_config(config)
            jobs_db.reset_running_jobs()
            worker = DownloadWorker(config, auth)
            worker.start()
            app.state.worker = worker

            scheduler = CheckScheduler(
                config,
                auth,
                interval_hours=config.downloader.check_interval_hours,
            )
            scheduler.start()
            app.state.scheduler = scheduler
        yield
        # Shutdown
        if start_background:
            if hasattr(app.state, "worker"):
                app.state.worker.stop()
            if hasattr(app.state, "scheduler"):
                app.state.scheduler.shutdown()

    app = FastAPI(lifespan=lifespan)

    # Store config and auth on app state
    app.state.config = config
    app.state.auth = auth

    def _channels_view() -> list[dict]:
        channels = list_channels_with_info()
        for c in channels:
            c["last_check"] = jobs_db.get_state(f"last_check:{c['slug']}")
        return channels

    def _subscriptions_view() -> list[dict]:
        subs = db.list_subscriptions()
        info_by_slug = {c["slug"]: c for c in list_channels_with_info()}
        rows = []
        for slug in subs:
            info = info_by_slug.get(slug)
            rows.append(
                {
                    "slug": slug,
                    "subscribed": True,
                    "title": (info or {}).get("title", slug),
                    "avatar_url": (info or {}).get("avatar_url"),
                    "url": (info or {}).get("url", f"https://nebula.tv/{slug}"),
                    "episode_count": (info or {}).get("episode_count", 0),
                    "last_check": jobs_db.get_state(f"last_check:{slug}"),
                    "has_data": info is not None,
                }
            )
        return rows

    # Routes
    @app.get("/healthz")
    async def healthz():
        """Health check endpoint."""
        return {"status": "ok"}

    @app.get("/api/status")
    async def get_status():
        """Get current status: job counts, last check time, scheduler state."""
        counts = jobs_db.count_jobs_by_state()
        last_check = jobs_db.get_state("last_check")
        scheduler_running = (
            getattr(app.state, "scheduler", None) is not None
            and app.state.scheduler.running
        )
        return {
            "counts": counts,
            "last_check": last_check,
            "scheduler_running": scheduler_running,
        }

    @app.get("/api/channels")
    async def get_channels():
        """Get list of saved channels with enriched info."""
        return _channels_view()

    @app.get("/api/jobs")
    async def get_jobs(state: str | None = Query(None)):
        """Get list of jobs, optionally filtered by state."""
        return jobs_db.list_jobs(state=state)

    @app.post("/api/check")
    async def post_check():
        """Trigger a check for new episodes."""
        # Use scheduler if available, else call service directly
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is not None:
            enqueued = scheduler.trigger_now()
        else:
            enqueued = service.check_all_channels(config, auth)
        return {"enqueued": enqueued}

    @app.post("/api/jobs/{job_id}/retry")
    async def retry_job(job_id: int):
        """Retry a failed job."""
        requeued = jobs_db.requeue_job(job_id)
        return {"requeued": requeued}

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        """Render the dashboard."""
        counts = jobs_db.count_jobs_by_state()
        last_check = jobs_db.get_state("last_check")
        channels = _channels_view()
        jobs = [
            presentation.decorate_job(dict(j))
            for j in jobs_db.list_jobs(limit=50)
        ]
        context = {
            "request": request,
            "counts": counts,
            "last_check": last_check,
            "channels": channels,
            "jobs": jobs,
        }
        template = env.get_template("dashboard.html")
        html = template.render(context)
        return HTMLResponse(content=html)

    @app.get("/partials/jobs", response_class=HTMLResponse)
    async def partials_jobs(request: Request):
        """Render the jobs table rows."""
        jobs = [
            presentation.decorate_job(dict(j))
            for j in jobs_db.list_jobs(limit=50)
        ]
        context = {
            "request": request,
            "jobs": jobs,
        }
        template = env.get_template("partials/jobs.html")
        html = template.render(context)
        return HTMLResponse(content=html)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        """Render the settings page."""
        template = env.get_template("settings.html")
        return HTMLResponse(
            template.render(
                {
                    "request": request,
                    "subscriptions": _subscriptions_view(),
                    "config": config.as_view(),
                }
            )
        )

    @app.post("/api/config", response_class=HTMLResponse)
    async def save_config_route(request: Request):
        """Validate and persist edited config, applying changes live."""
        form = await request.form()
        data = {k: v for k, v in form.items()}
        old_path = config.downloader.download_path
        old_interval = config.downloader.check_interval_hours
        old_db_path = config.as_view()["db_path"]
        new_db_path = (data.get("db_path") or "").strip()

        try:
            config.apply_updates(data)
        except Exception as exc:  # noqa: BLE001 - surface validation errors in UI
            template = env.get_template("partials/config_form.html")
            return HTMLResponse(
                template.render(
                    {
                        "request": request,
                        "config": config.as_view(),
                        "error": str(exc),
                    }
                ),
                status_code=400,
            )

        new_interval = config.downloader.check_interval_hours
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is not None and new_interval != old_interval:
            scheduler.reschedule(new_interval)

        db_path_changed = bool(new_db_path) and new_db_path != old_db_path
        if db_path_changed:
            config.set_db_location(new_db_path)

        restart_required = (
            config.downloader.download_path != old_path or db_path_changed
        )
        template = env.get_template("partials/config_form.html")
        return HTMLResponse(
            template.render(
                {
                    "request": request,
                    "config": config.as_view(),
                    "saved": True,
                    "restart_required": restart_required,
                }
            )
        )

    @app.get("/api/channels/search", response_class=HTMLResponse)
    async def search_channels_route(request: Request, q: str = Query("")):
        """Render channel search suggestions for the add form."""
        results = service.search_channels(config, auth, q)
        template = env.get_template("partials/channel_search.html")
        return HTMLResponse(
            template.render({"request": request, "results": results, "q": q})
        )

    @app.post("/api/channels/add", response_class=HTMLResponse)
    async def add_channel_route(slug: str = Form(...)):
        """Subscribe to a channel and trigger an immediate check."""
        service.add_channel(config, auth, slug)
        template = env.get_template("partials/subscriptions.html")
        return HTMLResponse(template.render({"subscriptions": _subscriptions_view()}))

    @app.post("/api/channels/remove", response_class=HTMLResponse)
    async def remove_channel_route(
        slug: str = Form(...),
        delete_data: bool = Form(False),
    ):
        """Unsubscribe from a channel, optionally purging DB data."""
        service.remove_channel(config, slug, delete_data=delete_data)
        template = env.get_template("partials/subscriptions.html")
        return HTMLResponse(template.render({"subscriptions": _subscriptions_view()}))

    @app.get("/partials/subscriptions", response_class=HTMLResponse)
    async def partials_subscriptions(request: Request):
        """Render the subscriptions partial."""
        template = env.get_template("partials/subscriptions.html")
        return HTMLResponse(template.render({"subscriptions": _subscriptions_view()}))

    return app
