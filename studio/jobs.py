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

Progress = Callable[[int, int, dict[str, Any] | None], None]
Cancelled = Callable[[], bool]
JobFunction = Callable[[Progress, Cancelled], dict[str, Any]]
ACTIVE_STATES = ("queued", "running")


class JobManager:
    """Run jobs one at a time and expose a snapshot of each job's progress."""

    def __init__(self, keep_finished: int = 50) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="studio-job")
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._keep_finished = keep_finished
        self._lock = threading.Lock()

    def submit(self, function: JobFunction, kind: str, project_id: int | None = None) -> str:
        """Queue ``function``; it gets ``progress(done, total, partial)`` and ``cancelled()``."""
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "kind": kind,
                "project_id": project_id,
                "state": "queued",
                "done": 0,
                "total": 0,
                "report": None,
                "error": None,
                "cancel_requested": False,
            }
            self._cancel_flags[job_id] = threading.Event()
            self._prune()
        self._executor.submit(self._run, job_id, function)
        return job_id

    def _prune(self) -> None:
        """Forget the oldest finished jobs beyond ``keep_finished`` (caller holds the lock)."""
        finished = [j for j in self._jobs.values() if j["state"] not in ACTIVE_STATES]
        for job in finished[: max(0, len(finished) - self._keep_finished)]:
            self._jobs.pop(job["id"], None)
            self._cancel_flags.pop(job["id"], None)

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(fields)

    def _run(self, job_id: str, function: JobFunction) -> None:
        self._update(job_id, state="running")
        flag = self._cancel_flags[job_id]

        def progress(done: int, total: int, partial: dict[str, Any] | None = None) -> None:
            self._update(job_id, done=done, total=total, report=partial)

        try:
            report = function(progress, flag.is_set)
        except Exception as error:  # a failed job must never take the worker thread down
            logger.exception("Job %s failed", job_id)
            self._update(job_id, state="failed", error=str(error) or type(error).__name__)
        else:
            self._update(job_id, state="done", report=report)

    def cancel(self, job_id: str) -> bool:
        """Ask a job to stop. Returns False for an unknown or already finished job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["state"] not in ACTIVE_STATES:
                return False
            self._cancel_flags[job_id].set()
            job["cancel_requested"] = True
            return True

    def has_active(self, project_id: int) -> bool:
        """True if a queued or running job belongs to this project."""
        with self._lock:
            return any(
                job["project_id"] == project_id and job["state"] in ACTIVE_STATES
                for job in self._jobs.values()
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return a copy of the job's current state, or ``None`` if unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def shutdown(self) -> None:
        for flag in self._cancel_flags.values():
            flag.set()  # let a running import stop at the next file instead of blocking exit
        self._executor.shutdown(wait=False, cancel_futures=True)
