from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from jinja2 import Environment, FileSystemLoader, select_autoescape

from api import presentation, service
from api.worker import DownloadWorker
from api.scheduler import CheckScheduler
from config.config import Config
from nebula_api.authorization import NebulaUserAuthorization
from utils import jobs_db
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
    download_path = config.downloader.download_path
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        if start_background:
            jobs_db.reset_running_jobs(download_path)
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
        channels = list_channels_with_info(download_path)
        for c in channels:
            c["last_check"] = jobs_db.get_state(
                download_path, f"last_check:{c['slug']}"
            )
        return channels

    # Routes
    @app.get("/healthz")
    async def healthz():
        """Health check endpoint."""
        return {"status": "ok"}

    @app.get("/api/status")
    async def get_status():
        """Get current status: job counts, last check time, scheduler state."""
        counts = jobs_db.count_jobs_by_state(download_path)
        last_check = jobs_db.get_state(download_path, "last_check")
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
        return jobs_db.list_jobs(download_path, state=state)

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
        requeued = jobs_db.requeue_job(download_path, job_id)
        return {"requeued": requeued}

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        """Render the dashboard."""
        counts = jobs_db.count_jobs_by_state(download_path)
        last_check = jobs_db.get_state(download_path, "last_check")
        channels = _channels_view()
        jobs = [
            presentation.decorate_job(dict(j))
            for j in jobs_db.list_jobs(download_path, limit=50)
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
            for j in jobs_db.list_jobs(download_path, limit=50)
        ]
        context = {
            "request": request,
            "jobs": jobs,
        }
        template = env.get_template("partials/jobs.html")
        html = template.render(context)
        return HTMLResponse(content=html)

    return app
