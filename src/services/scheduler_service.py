"""Background task scheduler service using APScheduler."""

from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.common.logger import get_logger
from src.common.settings import Settings
from src.services.scanner_service import ScannerService

logger = get_logger(__name__)


class SchedulerServiceError(Exception):
    """Base exception for scheduler service errors."""


class SchedulerService:
    """Service for managing background scan jobs using APScheduler."""

    def __init__(
        self,
        settings: Settings,
        scanner_service: ScannerService,
    ) -> None:
        self.settings = settings
        self.scanner_service = scanner_service
        self._scheduler: AsyncIOScheduler | None = None
        self._jobs: dict[str, str] = {}  # connection_id -> job_id
        self._last_scan_times: dict[str, datetime] = {}

    def _get_scheduler(self) -> AsyncIOScheduler:
        """Get or create the scheduler instance."""
        if self._scheduler is None:
            self._scheduler = AsyncIOScheduler()
        return self._scheduler

    def start(self) -> None:
        """Start the scheduler."""
        if not self.settings.scanner_enabled:
            logger.info("Scanner is disabled, not starting scheduler")
            return

        scheduler = self._get_scheduler()
        if not scheduler.running:
            scheduler.start()
            logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")

    async def _run_scan(self, connection_id: str) -> None:
        """Run a scan for a connection and update last scan time."""
        try:
            logger.debug(f"Running scheduled scan for connection: {connection_id}")
            result = await self.scanner_service.scan_connection(connection_id)
            self._last_scan_times[connection_id] = result.scan_time
        except Exception as e:
            logger.error(f"Scheduled scan failed for {connection_id}: {e}")

    def add_scan_job(
        self,
        connection_id: str,
        interval_seconds: int | None = None,
    ) -> str:
        """Add a periodic scan job for a connection.

        Args:
            connection_id: The connection to scan
            interval_seconds: Scan interval in seconds (uses default if None)

        Returns:
            The job ID
        """
        if not self.settings.scanner_enabled:
            logger.warning("Scanner is disabled, not adding scan job")
            raise SchedulerServiceError("Scanner is disabled")

        interval = interval_seconds or self.settings.scanner_default_interval

        # Remove existing job if any
        if connection_id in self._jobs:
            self.remove_scan_job(connection_id)

        scheduler = self._get_scheduler()

        job = scheduler.add_job(
            self._run_scan,
            trigger=IntervalTrigger(seconds=interval),
            args=[connection_id],
            id=f"scan_{connection_id}",
            name=f"Table scan for {connection_id}",
            replace_existing=True,
            max_instances=1,  # Prevent overlapping scans
        )

        self._jobs[connection_id] = job.id
        logger.info(
            f"Added scan job for {connection_id} with {interval}s interval"
        )

        return job.id

    def remove_scan_job(self, connection_id: str) -> None:
        """Remove the scan job for a connection.

        Args:
            connection_id: The connection to stop scanning
        """
        if connection_id not in self._jobs:
            return

        scheduler = self._get_scheduler()
        job_id = self._jobs[connection_id]

        try:
            scheduler.remove_job(job_id)
            logger.info(f"Removed scan job for {connection_id}")
        except Exception as e:
            logger.warning(f"Failed to remove job {job_id}: {e}")

        del self._jobs[connection_id]
        self._last_scan_times.pop(connection_id, None)

    def get_job_status(self, connection_id: str) -> dict[str, Any] | None:
        """Get the status of a scan job.

        Args:
            connection_id: The connection to check

        Returns:
            Job status dictionary or None if no job exists
        """
        if connection_id not in self._jobs:
            return None

        scheduler = self._get_scheduler()
        job_id = self._jobs[connection_id]

        try:
            job = scheduler.get_job(job_id)
            if job is None:
                # Job was removed externally
                del self._jobs[connection_id]
                return None

            next_run = job.next_run_time
            last_scan = self._last_scan_times.get(connection_id)

            return {
                "connection_id": connection_id,
                "job_id": job_id,
                "if_active": True,
                "next_run_time": next_run.isoformat() if next_run else None,
                "last_scan_time": last_scan.isoformat() if last_scan else None,
                "interval_seconds": self.settings.scanner_default_interval,
            }

        except Exception as e:
            logger.error(f"Failed to get job status for {connection_id}: {e}")
            return None

    def list_active_jobs(self) -> list[dict[str, Any]]:
        """List all active scan jobs.

        Returns:
            List of job status dictionaries
        """
        jobs = []
        for connection_id in list(self._jobs.keys()):
            status = self.get_job_status(connection_id)
            if status:
                jobs.append(status)
        return jobs

    async def trigger_immediate_scan(self, connection_id: str) -> None:
        """Trigger an immediate scan for a connection.

        Args:
            connection_id: The connection to scan immediately
        """
        logger.info(f"Triggering immediate scan for {connection_id}")
        await self._run_scan(connection_id)


__all__ = ["SchedulerService", "SchedulerServiceError"]
