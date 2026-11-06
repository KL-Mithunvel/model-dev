"""Tiny in-process job runner for long tasks (imports). One worker thread, so database writes
from jobs never overlap. State is kept in memory; it is a progress display, not a record
(durable results live in the ``batches`` table)."""

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

JobFunction = Callable[[Callable[[int, int, dict[str, Any] | None], None]], dict[str, Any]]


class JobManager:
    """Run jobs one at a time and expose a snapshot of each job's progress."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="studio-job")
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, function: JobFunction, kind: str) -> str:
        """Queue ``function``; it receives ``progress(done, total, partial_report)``."""
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "kind": kind,
                "state": "queued",
                "done": 0,
                "total": 0,
                "report": None,
                "error": None,
            }
        self._executor.submit(self._run, job_id, function)
        return job_id

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(fields)

    def _run(self, job_id: str, function: JobFunction) -> None:
        self._update(job_id, state="running")

        def progress(done: int, total: int, partial: dict[str, Any] | None = None) -> None:
            self._update(job_id, done=done, total=total, report=partial)

        try:
            report = function(progress)
        except Exception as error:  # a failed job must never take the worker thread down
            logger.exception("Job %s failed", job_id)
            self._update(job_id, state="failed", error=str(error) or type(error).__name__)
        else:
            self._update(job_id, state="done", report=report)

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return a copy of the job's current state, or ``None`` if unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
