from fastapi.testclient import TestClient

from api.app import create_app
from utils import jobs_db
from utils.db import save_channel_info


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
    download_path = config.downloader.download_path

    # Enqueue some jobs
    jobs_db.enqueue_job(download_path, "ch1", "ep1", '{"slug": "ep1"}')
    jobs_db.enqueue_job(download_path, "ch1", "ep2", '{"slug": "ep2"}')

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"]["queued"] == 2


def test_channels_endpoint_lists_saved_channels(config, fake_auth):
    """GET /api/channels lists saved channels."""
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
    slugs = resp.json()
    assert "test-channel" in slugs


def test_jobs_endpoint_returns_jobs(config, fake_auth):
    """GET /api/jobs returns all jobs."""
    download_path = config.downloader.download_path

    jobs_db.enqueue_job(download_path, "ch1", "ep1", '{"slug": "ep1"}')

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) > 0
    assert jobs[0]["channel_slug"] == "ch1"


def test_jobs_endpoint_filters_by_state(config, fake_auth):
    """GET /api/jobs?state=queued filters by state."""
    download_path = config.downloader.download_path

    # Enqueue and mark one as done
    jobs_db.enqueue_job(download_path, "ch1", "ep1", '{"slug": "ep1"}')
    job = jobs_db.claim_next_job(download_path)
    jobs_db.mark_job_done(download_path, job["id"])

    # Enqueue another
    jobs_db.enqueue_job(download_path, "ch1", "ep2", '{"slug": "ep2"}')

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
    download_path = config.downloader.download_path

    # Enqueue, claim, and fail a job
    jobs_db.enqueue_job(download_path, "ch1", "ep1", '{"slug": "ep1"}')
    job = jobs_db.claim_next_job(download_path)
    jobs_db.mark_job_failed(download_path, job["id"], "test error")

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.post(f"/api/jobs/{job['id']}/retry")
    assert resp.status_code == 200
    assert resp.json() == {"requeued": True}

    # Verify job is back to queued
    requeued = jobs_db.get_job(download_path, job["id"])
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
    download_path = config.downloader.download_path

    jobs_db.enqueue_job(
        download_path, "ch1", "test-ep-slug", '{"slug": "test-ep-slug"}'
    )

    client = TestClient(create_app(config, fake_auth, start_background=False))
    resp = client.get("/partials/jobs")
    assert resp.status_code == 200
    assert "test-ep-slug" in resp.text
