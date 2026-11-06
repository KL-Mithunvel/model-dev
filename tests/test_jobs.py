import threading
import time

from studio.jobs import JobManager


def wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_job_runs_and_reports_progress_and_result():
    manager = JobManager()

    def work(progress, cancelled):
        progress(1, 2, {"x": 1})
        progress(2, 2, {"x": 2})
        return {"ok": True}

    job_id = manager.submit(work, kind="t")
    assert wait_until(lambda: manager.get(job_id)["state"] == "done")
    job = manager.get(job_id)
    assert job["done"] == job["total"] == 2 and job["report"] == {"ok": True}
    manager.shutdown()


def test_failing_job_is_recorded_and_worker_survives():
    manager = JobManager()

    def boom(progress, cancelled):
        raise ValueError("bad thing")

    first = manager.submit(boom, kind="t")
    second = manager.submit(lambda progress, cancelled: {"fine": True}, kind="t")
    assert wait_until(lambda: manager.get(second)["state"] == "done")
    assert manager.get(first)["state"] == "failed" and "bad thing" in manager.get(first)["error"]
    manager.shutdown()


def test_cancel_sets_flag_for_a_running_job_only():
    manager = JobManager()
    started = threading.Event()

    def wait_for_cancel(progress, cancelled):
        started.set()
        while not cancelled():
            time.sleep(0.01)
        return {"stopped": True}

    job_id = manager.submit(wait_for_cancel, kind="t", project_id=7)
    assert started.wait(2)
    assert manager.has_active(7) and not manager.has_active(8)
    assert manager.cancel(job_id) is True
    assert wait_until(lambda: manager.get(job_id)["state"] == "done")
    assert manager.get(job_id)["cancel_requested"] is True
    assert manager.cancel(job_id) is False  # already finished
    assert manager.cancel("unknown") is False
    assert not manager.has_active(7)
    manager.shutdown()


def test_finished_jobs_are_pruned_but_active_ones_are_kept():
    manager = JobManager(keep_finished=2)
    ids = [manager.submit(lambda p, c: {}, kind="t") for _ in range(6)]
    assert wait_until(lambda: manager.get(ids[-1]) and manager.get(ids[-1])["state"] == "done")
    gate = threading.Event()
    blocker = manager.submit(lambda p, c: gate.wait(5) and {}, kind="t")
    manager.submit(lambda p, c: {}, kind="t")  # triggers pruning while `blocker` is active
    kept_old = [i for i in ids if manager.get(i) is not None]
    assert len(kept_old) <= 2
    assert manager.get(blocker) is not None
    gate.set()
    manager.shutdown()
