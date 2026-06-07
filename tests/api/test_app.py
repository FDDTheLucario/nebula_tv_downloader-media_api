import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from tests.api.conftest import make_content, make_episode
from utils import db, jobs_db
from utils.db import ChannelNotFoundError, load_channel_info, save_channel_info


def test_healthz(config, fake_auth):
    """GET /healthz returns ok."""
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_status_empty(config, fake_auth):
    """GET /api/status with no jobs returns empty counts and scheduler_running=False."""
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"] == {"queued": 0, "running": 0, "done": 0, "failed": 0}
    assert data["last_check"] is None
    assert data["scheduler_running"] is False


def test_status_reflects_jobs(config, fake_auth):
    """GET /api/status reflects job counts."""
    # Enqueue some jobs
    jobs_db.enqueue_job("ch1", "ep1", '{"slug": "ep1"}')
    jobs_db.enqueue_job("ch1", "ep2", '{"slug": "ep2"}')

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"]["queued"] == 2


def test_channels_endpoint_lists_saved_channels(config, fake_auth):
    """GET /api/channels lists saved channels as enriched dicts."""
    from tests.api.conftest import make_content, make_episode

    download_path = config.downloader.download_path
    ep = make_episode(slug="ep-slug", title="Test Ep")
    content = make_content(ep)

    save_channel_info(
        "test-channel",
        content.details,
        content.episodes,
        download_path,
    )

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/channels")
    assert resp.status_code == 200
    channels = resp.json()
    assert any(c["slug"] == "test-channel" for c in channels)
    entry = next(c for c in channels if c["slug"] == "test-channel")
    assert "title" in entry
    assert "episode_count" in entry


def test_jobs_endpoint_returns_jobs(config, fake_auth):
    """GET /api/jobs returns all jobs."""
    jobs_db.enqueue_job("ch1", "ep1", '{"slug": "ep1"}')

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) > 0
    assert jobs[0]["channel_slug"] == "ch1"


def test_jobs_endpoint_filters_by_state(config, fake_auth):
    """GET /api/jobs?state=queued filters by state."""
    # Enqueue and mark one as done
    jobs_db.enqueue_job("ch1", "ep1", '{"slug": "ep1"}')
    job = jobs_db.claim_next_job()
    jobs_db.mark_job_done(job["id"])

    # Enqueue another
    jobs_db.enqueue_job("ch1", "ep2", '{"slug": "ep2"}')

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/jobs?state=queued")
    assert resp.status_code == 200
    jobs = resp.json()
    assert all(j["state"] == "queued" for j in jobs)


def test_post_check_invokes_service(config, fake_auth, monkeypatch):
    """POST /api/check invokes service and returns enqueued."""

    def fake_check(cfg, auth):
        return {"ch-slug": 2}

    monkeypatch.setattr("api.service.check_all_channels", fake_check)

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.post("/api/check")
    assert resp.status_code == 200
    assert resp.json() == {"enqueued": {"ch-slug": 2}}


def test_post_retry_requeues_failed_job(config, fake_auth):
    """POST /api/jobs/{id}/retry requeues a failed job."""
    # Enqueue, claim, and fail a job
    jobs_db.enqueue_job("ch1", "ep1", '{"slug": "ep1"}')
    job = jobs_db.claim_next_job()
    jobs_db.mark_job_failed(job["id"], "test error")

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.post(f"/api/jobs/{job['id']}/retry")
    assert resp.status_code == 200
    assert resp.json() == {"requeued": True}

    # Verify job is back to queued
    requeued = jobs_db.get_job(job["id"])
    assert requeued["state"] == "queued"


def test_dashboard_renders_html(config, fake_auth):
    """GET / renders dashboard.html."""
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Nebula" in resp.text


def test_partials_jobs_renders_rows(config, fake_auth):
    """GET /partials/jobs renders job rows."""
    jobs_db.enqueue_job("ch1", "test-ep-slug", '{"slug": "test-ep-slug"}')

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/partials/jobs")
    assert resp.status_code == 200
    assert "test-ep-slug" in resp.text


def test_channels_endpoint_includes_last_check(config, fake_auth):
    """GET /api/channels includes per-channel last_check from app_state."""
    download_path = config.downloader.download_path
    ep = make_episode()
    content = make_content(ep)
    save_channel_info("test-channel", content.details, content.episodes, download_path)
    jobs_db.set_state("last_check:test-channel", "2026-06-07T00:00:00")

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/channels")
    assert resp.status_code == 200
    channels = resp.json()
    entry = next(c for c in channels if c["slug"] == "test-channel")
    assert entry["last_check"] == "2026-06-07T00:00:00"


def test_dashboard_shows_channel_title_and_count(config, fake_auth):
    """GET / shows channel title, episode count, and channel link."""
    download_path = config.downloader.download_path
    ep1 = make_episode(slug="ep1")
    ep2 = make_episode(slug="ep2")
    content = make_content(ep1, ep2)
    save_channel_info("ch-slug", content.details, content.episodes, download_path)

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Channel" in resp.text
    assert "2" in resp.text
    assert "https://nebula.tv/ch-slug" in resp.text


def test_dashboard_shows_video_title_and_duration(config, fake_auth):
    """GET / shows video title and formatted duration in job rows."""
    ep = make_episode(title="My Video", duration=125)
    jobs_db.enqueue_job("ch", "ep", ep.model_dump_json())

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "My Video" in resp.text
    assert "2:05" in resp.text


def test_partials_jobs_shows_badge_and_thumbnail(config, fake_auth):
    """GET /partials/jobs shows badges, thumbnail, and watch link."""
    ep = make_episode(attributes=["is_nebula_plus"])
    jobs_db.enqueue_job("ch", "ep", ep.model_dump_json())

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/partials/jobs")
    assert resp.status_code == 200
    assert "Plus" in resp.text
    assert "https://example.com/img.jpg" in resp.text
    assert "https://nebula.tv/ep" in resp.text


def test_partials_jobs_malformed_episode_json_renders_slug(config, fake_auth):
    """GET /partials/jobs with non-dict episode_json returns 200 and falls back to slug."""
    # Enqueue a job where episode_json is valid JSON but not a dict (a list)
    jobs_db.enqueue_job("ch", "bad-ep-slug", "[]")

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/partials/jobs")
    assert resp.status_code == 200
    assert "bad-ep-slug" in resp.text


# ── settings page tests ───────────────────────────────────────────────────────


def test_settings_page_renders(config, fake_auth):
    """GET /settings returns 200 with Settings heading and add-channel form."""
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Settings" in resp.text
    assert "/api/channels/add" in resp.text


def test_settings_lists_subscriptions(config, fake_auth):
    """GET /settings lists subscribed channel slugs."""
    db.add_subscription("ch-a")

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "ch-a" in resp.text


def test_add_channel_route_subscribes(config, fake_auth, mocker):
    """POST /api/channels/add subscribes the channel (no network)."""
    mock_add = mocker.patch(
        "api.app.service.add_channel",
        side_effect=lambda cfg, a, s: db.add_subscription(s),
    )

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.post("/api/channels/add", data={"slug": "new-ch"})
    assert resp.status_code == 200
    assert db.is_subscribed("new-ch") is True
    assert "new-ch" in resp.text
    mock_add.assert_called_once()


def test_remove_channel_route_keeps_data(config, fake_auth):
    """POST /api/channels/remove without delete_data keeps channel data."""
    download_path = config.downloader.download_path
    download_path.mkdir(parents=True, exist_ok=True)
    ep = make_episode(slug="ep1")
    content = make_content(ep)
    save_channel_info("rm-ch", content.details, content.episodes, download_path)
    db.add_subscription("rm-ch")
    jobs_db.enqueue_job("rm-ch", "ep1", '{"slug":"ep1"}')
    jobs_db.set_state("last_check:rm-ch", "2026-06-07T00:00:00")

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.post("/api/channels/remove", data={"slug": "rm-ch"})
    assert resp.status_code == 200
    assert db.is_subscribed("rm-ch") is False
    loaded = load_channel_info("rm-ch")
    assert len(loaded.episodes.results) == 1
    remaining_jobs = [
        j for j in jobs_db.list_jobs() if j["channel_slug"] == "rm-ch"
    ]
    assert len(remaining_jobs) > 0
    assert jobs_db.get_state("last_check:rm-ch") == "2026-06-07T00:00:00"


def test_remove_channel_route_delete_data_purges(config, fake_auth):
    """POST /api/channels/remove with delete_data=true purges channel data."""
    download_path = config.downloader.download_path
    download_path.mkdir(parents=True, exist_ok=True)
    ep = make_episode(slug="ep1")
    content = make_content(ep)
    save_channel_info("rm-ch", content.details, content.episodes, download_path)
    db.add_subscription("rm-ch")
    jobs_db.enqueue_job("rm-ch", "ep1", '{"slug":"ep1"}')
    jobs_db.set_state("last_check:rm-ch", "2026-06-07T00:00:00")

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.post(
        "/api/channels/remove", data={"slug": "rm-ch", "delete_data": "true"}
    )
    assert resp.status_code == 200
    with pytest.raises(ChannelNotFoundError):
        load_channel_info("rm-ch")
    remaining_jobs = [
        j for j in jobs_db.list_jobs() if j["channel_slug"] == "rm-ch"
    ]
    assert remaining_jobs == []
    assert jobs_db.get_state("last_check:rm-ch") is None


def test_dashboard_has_settings_link(config, fake_auth):
    """GET / dashboard contains a link to /settings."""
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'href="/settings"' in resp.text


# ── lifespan / background-startup tests ──────────────────────────────────────


def test_lifespan_starts_and_stops_background(config, fake_auth, mocker):
    """With start_background=True the worker and scheduler are started then stopped."""
    mock_worker_cls = mocker.patch("api.app.DownloadWorker")
    mock_sched_cls = mocker.patch("api.app.CheckScheduler")

    app = create_app(config, fake_auth, start_background=True)
    with TestClient(app):
        mock_worker_cls.return_value.start.assert_called_once()
        mock_sched_cls.return_value.start.assert_called_once()

    mock_worker_cls.return_value.stop.assert_called_once()
    mock_sched_cls.return_value.shutdown.assert_called_once()


def test_post_check_uses_scheduler_when_present(config, fake_auth, mocker):
    """POST /api/check delegates to scheduler.trigger_now() when scheduler is on app state."""
    mocker.patch("api.app.DownloadWorker")
    mock_sched_cls = mocker.patch("api.app.CheckScheduler")
    mock_sched_cls.return_value.trigger_now.return_value = {"ch-slug": 3}

    app = create_app(config, fake_auth, start_background=True)
    with TestClient(app) as client:
        resp = client.post("/api/check")

    assert resp.status_code == 200
    assert resp.json() == {"enqueued": {"ch-slug": 3}}


def test_partials_subscriptions_renders_slug(config, fake_auth):
    """GET /partials/subscriptions returns 200 and includes the subscribed slug."""
    db.add_subscription("my-test-channel")

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/partials/subscriptions")
    assert resp.status_code == 200
    assert "my-test-channel" in resp.text


def test_search_route_returns_matches(config, fake_auth, mocker):
    """GET /api/channels/search renders matched suggestions, no network."""
    mock = mocker.patch(
        "api.app.service.search_channels",
        return_value=[
            {"slug": "jetlag", "title": "Jetlag", "avatar_url": None,
             "subscribed": False, "source": "remote"},
            {"slug": "jet-lag-the-game", "title": "Jet Lag", "avatar_url": None,
             "subscribed": False, "source": "remote"},
        ],
    )
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/channels/search", params={"q": "jet"})
    assert resp.status_code == 200
    assert "jetlag" in resp.text
    assert "jet-lag-the-game" in resp.text
    assert mock.call_args.args[2] == "jet"


def test_search_route_empty_query(config, fake_auth, mocker):
    """GET /api/channels/search with no q renders an empty dropdown."""
    mocker.patch("api.app.service.search_channels", return_value=[])
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/channels/search")
    assert resp.status_code == 200
    assert "search-row" not in resp.text


def test_search_route_subscribed_marker(config, fake_auth, mocker):
    """A subscribed result shows the added marker."""
    mocker.patch(
        "api.app.service.search_channels",
        return_value=[
            {"slug": "jetlag", "title": "Jetlag", "avatar_url": None,
             "subscribed": True, "source": "local"},
        ],
    )
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/channels/search", params={"q": "jet"})
    assert resp.status_code == 200
    assert "added" in resp.text


def test_search_route_no_network(config, fake_auth, mocker):
    """Route makes no live HTTP when the directory layer is stubbed empty."""
    mocker.patch("api.app.service.get_channel_directory", return_value=[])
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/channels/search", params={"q": "jet"})
    assert resp.status_code == 200


def test_settings_input_has_search_wiring(config, fake_auth):
    """Settings add-form input is wired for live search."""
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert 'hx-get="/api/channels/search"' in resp.text
    assert 'id="slug-input"' in resp.text


def _config_form(**overrides):
    """Build a full config form payload, overridable per test."""
    data = {
        "user_api_token": "",
        "authorization_header": "",
        "user_agent": "ua",
        "token_refresh_interval_hours": "6",
        "category_search": "",
        "channels_to_parse": "",
        "download_path": "/tmp/out",
        "check_interval_hours": "1",
        "db_path": "",
    }
    data.update(overrides)
    return data


def test_settings_renders_config_form(config, fake_auth):
    """GET /settings renders the config edit form."""
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert 'name="user_api_token"' in resp.text
    assert 'name="db_path"' in resp.text
    assert "Configuration" in resp.text


def test_post_config_saves_and_applies_live(config, fake_auth):
    """POST /api/config persists changes and mutates the live config."""
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.post(
        "/api/config",
        data=_config_form(channels_to_parse="a,b", include_nebula_first="true"),
    )
    assert resp.status_code == 200
    assert "saved" in resp.text.lower()
    assert config.nebula_filters.channels_to_parse == ["a", "b"]
    assert config.nebula_filters.include_nebula_first is True


def test_post_config_invalid_returns_400(config, fake_auth):
    """POST /api/config with a bad value re-renders the form with an error."""
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.post(
        "/api/config", data=_config_form(check_interval_hours="not-a-number")
    )
    assert resp.status_code == 400
    assert "✗" in resp.text


def test_post_config_reschedules_on_interval_change(config, fake_auth):
    """Changing check_interval_hours reschedules the running scheduler."""
    from unittest.mock import Mock

    app = create_app(config, fake_auth, start_background=False)
    app.state.scheduler = Mock()
    client = TestClient(app)
    resp = client.post("/api/config", data=_config_form(check_interval_hours="7"))
    assert resp.status_code == 200
    app.state.scheduler.reschedule.assert_called_once_with(7)


def test_post_config_db_path_change_requires_restart(config, fake_auth, monkeypatch):
    """Changing db_path persists the pointer and flags a restart."""
    from config import config as config_module

    monkeypatch.setattr(config_module, "set_db_path", lambda *a, **k: None)
    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.post(
        "/api/config", data=_config_form(db_path="/tmp/moved/nebula.db")
    )
    assert resp.status_code == 200
    assert "restart" in resp.text.lower()
