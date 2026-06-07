import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from api import service
from config.config import Config
from nebula_api.authorization import NebulaUserAuthorization

logger = logging.getLogger(__name__)


class CheckScheduler:
    """Scheduler that periodically checks for new episodes across all channels."""

    def __init__(
        self,
        config: Config,
        auth: NebulaUserAuthorization,
        *,
        interval_hours: int = 1,
        check=service.check_all_channels,
        scheduler_factory=BackgroundScheduler,
    ):
        """
        Initialize the check scheduler.

        Args:
            config: Configuration object
            auth: Authorization object
            interval_hours: Hours between check runs (default 1)
            check: Callable to check all channels (default: service.check_all_channels)
            scheduler_factory: Factory to create a BackgroundScheduler (for testing)
        """
        self.config = config
        self.auth = auth
        self.interval_hours = interval_hours
        self._check = check
        self._scheduler_factory = scheduler_factory
        self._scheduler = None

    def start(self) -> None:
        """Start the scheduler and register the periodic check job."""
        self._scheduler = self._scheduler_factory()
        self._scheduler.add_job(
            self._run,
            "interval",
            hours=self.interval_hours,
            id="check_channels",
        )
        self._scheduler.start()

    def shutdown(self) -> None:
        """Stop the scheduler if running."""
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def trigger_now(self) -> dict[str, int]:
        """
        Trigger a check immediately.

        Works whether or not the scheduler is running.
        Returns the result of the check (dict mapping channel_slug -> count of jobs).
        """
        return self._check(self.config, self.auth)

    def _run(self) -> None:
        """
        Wrapper called by the scheduler to run checks.
        Logs results and swallows exceptions.
        """
        try:
            result = self._check(self.config, self.auth)
            logger.info(f"Scheduled check completed: {result}")
        except Exception as e:
            logger.error(f"Scheduled check failed: {e}")

    @property
    def running(self) -> bool:
        """Check if the scheduler is running."""
        return self._scheduler is not None and self._scheduler.running

    @property
    def next_run_time(self) -> datetime | None:
        """Get the next scheduled run time, or None if no job exists."""
        if self._scheduler is None:
            return None

        job = self._scheduler.get_job("check_channels")
        return job.next_run_time if job else None
