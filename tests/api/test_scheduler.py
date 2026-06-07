from unittest.mock import Mock

from api.scheduler import CheckScheduler


class TestCheckScheduler:
    def test_trigger_now_calls_check_and_returns_result(self, config, fake_auth):
        """trigger_now directly calls check and returns its result."""
        stub_check = Mock(return_value={"ch-slug": 3})

        scheduler = CheckScheduler(config, fake_auth, check=stub_check)
        result = scheduler.trigger_now()

        assert result == {"ch-slug": 3}
        stub_check.assert_called_once_with(config, fake_auth)

    def test_start_registers_interval_job(self, config, fake_auth):
        """start() registers an interval job and starts the scheduler."""
        fake_scheduler = Mock()
        scheduler = CheckScheduler(
            config, fake_auth, scheduler_factory=lambda: fake_scheduler
        )

        scheduler.start()

        # Verify scheduler factory was called
        assert scheduler._scheduler is fake_scheduler

        # Verify add_job was called with correct params
        add_job_call = fake_scheduler.add_job.call_args
        args, kwargs = add_job_call
        assert args[1] == "interval"  # Second positional arg is the trigger
        assert kwargs["hours"] == 1
        assert kwargs["id"] == "check_channels"

        # Verify scheduler.start() was called
        fake_scheduler.start.assert_called_once()

    def test_shutdown_stops_scheduler(self, config, fake_auth):
        """shutdown() stops the scheduler if it's running."""
        fake_scheduler = Mock()
        scheduler = CheckScheduler(
            config, fake_auth, scheduler_factory=lambda: fake_scheduler
        )

        scheduler.start()
        scheduler.shutdown()

        fake_scheduler.shutdown.assert_called_once_with(wait=False)
        assert scheduler.running is False

    def test_run_swallows_check_exception(self, config, fake_auth):
        """_run() does not propagate exceptions from check."""
        failing_check = Mock(side_effect=RuntimeError("check failed"))

        scheduler = CheckScheduler(
            config, fake_auth, check=failing_check, scheduler_factory=Mock
        )

        # _run should not raise
        scheduler._run()

        failing_check.assert_called_once()
