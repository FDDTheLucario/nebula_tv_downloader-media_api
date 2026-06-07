import time
from unittest.mock import Mock

from api.worker import DownloadWorker
from tests.api.conftest import make_episode
from utils import jobs_db


class TestDownloadWorker:
    def test_run_once_no_jobs_returns_false(self, tmp_path, config, fake_auth):
        """run_once returns False when queue is empty."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)

        worker = DownloadWorker(config, fake_auth)
        result = worker.run_once()

        assert result is False

    def test_run_once_processes_and_marks_done(self, tmp_path, config, fake_auth):
        """run_once claims a job, calls process, and marks it done."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)

        ep = make_episode(slug="ep1", attributes=["is_nebula_plus"])
        job_dict = {
            "id": 1,
            "channel_slug": "ch-slug",
            "episode_slug": "ep1",
            "episode_json": ep.model_dump_json(),
            "state": "queued",
            "error": None,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }

        # Enqueue a job
        jobs_db.enqueue_job(
            download_path,
            job_dict["channel_slug"],
            job_dict["episode_slug"],
            job_dict["episode_json"],
        )

        # Create a spy process function
        spy_process = Mock()

        worker = DownloadWorker(config, fake_auth, process=spy_process)
        result = worker.run_once()

        # Should return True (job was claimed)
        assert result is True

        # Verify process was called once
        assert spy_process.call_count == 1
        called_job = spy_process.call_args[0][0]
        assert called_job["episode_slug"] == "ep1"

        # Verify job is now done
        jobs_list = jobs_db.list_jobs(download_path)
        assert len(jobs_list) == 1
        assert jobs_list[0]["state"] == "done"

    def test_run_once_marks_failed_on_exception(self, tmp_path, config, fake_auth):
        """run_once marks job as failed if process raises an exception."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)

        ep = make_episode(slug="ep2", attributes=["is_nebula_plus"])
        jobs_db.enqueue_job(
            download_path,
            "ch-slug",
            ep.slug,
            ep.model_dump_json(),
        )

        # Create a process function that raises
        def failing_process(job, config, auth):
            raise RuntimeError("boom")

        worker = DownloadWorker(config, fake_auth, process=failing_process)
        result = worker.run_once()

        # Should return True (job was claimed)
        assert result is True

        # Verify job is marked failed
        jobs_list = jobs_db.list_jobs(download_path)
        assert len(jobs_list) == 1
        assert jobs_list[0]["state"] == "failed"
        assert "boom" in jobs_list[0]["error"]

    def test_run_once_processes_one_at_a_time(self, tmp_path, config, fake_auth):
        """run_once processes jobs one at a time."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)

        ep1 = make_episode(slug="ep1", attributes=["is_nebula_plus"])
        ep2 = make_episode(slug="ep2", attributes=["is_nebula_plus"])

        jobs_db.enqueue_job(download_path, "ch-slug", ep1.slug, ep1.model_dump_json())
        jobs_db.enqueue_job(download_path, "ch-slug", ep2.slug, ep2.model_dump_json())

        spy_process = Mock()
        worker = DownloadWorker(config, fake_auth, process=spy_process)

        # First run_once
        result1 = worker.run_once()
        assert result1 is True
        assert spy_process.call_count == 1

        # Second run_once
        result2 = worker.run_once()
        assert result2 is True
        assert spy_process.call_count == 2

        # Verify both are done
        jobs_list = jobs_db.list_jobs(download_path)
        assert all(job["state"] == "done" for job in jobs_list)

    def test_start_then_stop_drains_queue(self, tmp_path, config, fake_auth):
        """start() drains the queue in background; stop() halts the thread."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)

        ep1 = make_episode(slug="ep1", attributes=["is_nebula_plus"])
        ep2 = make_episode(slug="ep2", attributes=["is_nebula_plus"])

        jobs_db.enqueue_job(download_path, "ch-slug", ep1.slug, ep1.model_dump_json())
        jobs_db.enqueue_job(download_path, "ch-slug", ep2.slug, ep2.model_dump_json())

        # Create a fast process spy
        spy_process = Mock()

        worker = DownloadWorker(
            config, fake_auth, poll_interval=0.05, process=spy_process
        )
        worker.start()

        # Poll until both jobs are done or timeout (5 seconds)
        timeout = 5.0
        start_time = time.time()
        while time.time() - start_time < timeout:
            counts = jobs_db.count_jobs_by_state(download_path)
            if counts["done"] == 2:
                break
            time.sleep(0.05)

        # Stop the worker
        worker.stop()

        # Verify worker is no longer running
        assert worker.running is False

        # Verify both jobs are done
        counts = jobs_db.count_jobs_by_state(download_path)
        assert counts["done"] == 2
        assert counts["queued"] == 0
        assert counts["running"] == 0
