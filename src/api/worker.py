import logging
import threading

from api import service
from config.config import Config
from nebula_api.authorization import NebulaUserAuthorization
from utils import jobs_db

logger = logging.getLogger(__name__)


class DownloadWorker:
    """Background worker that drains the download job queue."""

    def __init__(
        self,
        config: Config,
        auth: NebulaUserAuthorization,
        *,
        poll_interval: float = 2.0,
        process=service.process_job,
    ):
        """
        Initialize the download worker.

        Args:
            config: Configuration object
            auth: Authorization object
            poll_interval: Seconds to wait between polls when queue is empty
            process: Callable to process a job (default: service.process_job)
        """
        self.config = config
        self.auth = auth
        self.poll_interval = poll_interval
        self._process = process
        self._stop = threading.Event()
        self._thread = None

    def run_once(self) -> bool:
        """
        Claim and process one job.

        Returns:
            True if a job was claimed and processed (or failed).
            False if no job was available.
        """
        download_path = self.config.downloader.download_path
        job = jobs_db.claim_next_job(download_path)

        if job is None:
            return False

        try:
            self._process(job, self.config, self.auth)
            jobs_db.mark_job_done(download_path, job["id"])
        except Exception as e:
            jobs_db.mark_job_failed(download_path, job["id"], str(e))

        return True

    def start(self) -> None:
        """Start the background worker thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop.clear()

        def worker_loop():
            while not self._stop.is_set():
                if not self.run_once():
                    # No job available, wait a bit before polling again
                    self._stop.wait(self.poll_interval)

        self._thread = threading.Thread(target=worker_loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the background worker thread.

        Args:
            timeout: Maximum seconds to wait for thread to finish
        """
        if self._thread is None or not self._thread.is_alive():
            return

        self._stop.set()
        self._thread.join(timeout=timeout)

    @property
    def running(self) -> bool:
        """Check if the worker thread is running."""
        return self._thread is not None and self._thread.is_alive()
