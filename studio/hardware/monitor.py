"""The hardware monitor: samples on a timer, keeps a ring buffer, records named runs.

* **Live data** — every ``hardware.monitor_interval_s`` seconds the samplers are read and the
  result is appended to an in-memory ring buffer (``ring_buffer_seconds`` of history).
* **Recorded runs** — ``start_run(name)`` / ``stop_run()`` (Stage 6 training will call these).
  While a
  run is recording, raw samples are averaged into one SQLite row per ``history_interval_s`` seconds.
  Per-metric average and peak over the raw samples are stored when the run stops.

``tick()`` takes one sample synchronously; the background thread only calls ``tick()`` on a
timer, so
tests drive the monitor without threads or sleeping.
"""

import json
import logging
import re
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from studio import db
from studio.hardware import warnings
from studio.hardware.base import Reading, Sampler, safe_sample
from studio.hardware.registry import build_samplers

logger = logging.getLogger(__name__)


class RunActive(Exception):
    """A run is already recording, or the run asked about is the one recording."""


class _Recording:
    """Accumulates raw samples of the active run into averaged rows."""

    def __init__(self, run_id: int, name: str, started_t: float, interval: float) -> None:
        self.run_id = run_id
        self.name = name
        self.started_t = started_t
        self.interval = interval
        self.bucket_start = started_t
        self.bucket: dict[str, list[float]] = {}  # key -> [sum, count]
        self.totals: dict[str, list[float]] = {}  # key -> [sum, count, max]
        self.stored = 0
        self.truncated = False

    def add(self, t: float, values: dict[str, float]) -> list[tuple[float, dict[str, float]]]:
        """Add one raw sample; return the rows (t_since_start, averages) that are now complete."""
        rows = []
        if t - self.bucket_start >= self.interval and self.bucket:
            rows.append(self.flush(t))
        for key, value in values.items():
            slot = self.bucket.setdefault(key, [0.0, 0])
            slot[0] += value
            slot[1] += 1
            total = self.totals.setdefault(key, [0.0, 0, value])
            total[0] += value
            total[1] += 1
            total[2] = max(total[2], value)
        return rows

    def flush(self, t: float) -> tuple[float, dict[str, float]]:
        averages = {key: round(s / n, 3) for key, (s, n) in self.bucket.items()}
        self.bucket = {}
        self.bucket_start = t
        return (round(t - self.started_t, 3), averages)

    def summary(self) -> dict[str, dict[str, float]]:
        return {
            key: {"avg": round(s / n, 3), "max": round(peak, 3)}
            for key, (s, n, peak) in self.totals.items()
        }


def _clean_name(name: str, max_length: int) -> str:
    cleaned = re.sub(r"\s+", " ", name or "").strip()
    if not cleaned:
        raise ValueError("Give the run a name.")
    if len(cleaned) > max_length:
        raise ValueError(f"Run names are at most {max_length} characters.")
    return cleaned


class Monitor:
    def __init__(
        self,
        hardware: dict[str, Any],
        db_path: Path | str,
        samplers: list[Sampler] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.hardware = hardware
        self.db_path = db_path
        self.interval = float(hardware["monitor_interval_s"])
        self.samplers = samplers if samplers is not None else build_samplers(hardware)
        self._clock = clock
        size = max(1, round(hardware["ring_buffer_seconds"] / self.interval))
        self._buffer: deque[dict[str, Any]] = deque(maxlen=size)
        self._catalog: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self._lock = threading.RLock()
        self._active: _Recording | None = None
        # Counts every start/stop of a run. A client compares it with the value its own start/stop
        # call returned, so a message built just before that call cannot undo it on screen.
        self.run_epoch = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._mark_interrupted_runs()

    # ---- sampling ---------------------------------------------------------------------------
    def tick(self) -> dict[str, Any]:
        """Read every sampler once, store the sample, and return it."""
        readings: list[Reading] = []
        for sampler in self.samplers:
            readings.extend(safe_sample(sampler))
        t = self._clock()
        values = {r.key: round(r.value, 3) for r in readings if r.value is not None and not r.info}
        with self._lock:
            for reading in readings:
                self._catalog[reading.key] = _catalog_entry(reading)
            self._seq += 1
            sample = {"seq": self._seq, "t": round(t, 3), "values": values}
            self._buffer.append(sample)
            recording = self._active
            rows = recording.add(t, values) if recording else []
        if rows:
            self._store_rows(recording, rows)
        return sample

    def start(self) -> None:
        """Start the sampling thread (no-op if running). Samples once now."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="hardware-monitor", daemon=True)
        self.tick()  # the dashboard has something to show immediately
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread, close an open recording cleanly, and release the samplers."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self.interval + 5)
        if self._active is not None:
            self.stop_run()
        for sampler in self.samplers:
            close = getattr(sampler, "close", None)
            if close:
                close()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        next_due = time.monotonic() + self.interval
        while not self._stop.wait(max(0.0, next_due - time.monotonic())):
            try:
                self.tick()
            except Exception:  # a database hiccup must not kill sampling
                logger.exception("monitor tick failed")
            next_due += self.interval
            now = time.monotonic()
            if next_due < now:  # fell behind (machine asleep): do not burst to catch up
                next_due = now + self.interval

    # ---- reading ----------------------------------------------------------------------------
    def samples(self, after_seq: int = 0, seconds: float | None = None) -> list[dict[str, Any]]:
        """Buffered samples newer than ``after_seq``; with ``seconds``, only the last N seconds."""
        with self._lock:
            items = [s for s in self._buffer if s["seq"] > after_seq]
        if seconds is not None and items:
            cutoff = items[-1]["t"] - seconds
            items = [s for s in items if s["t"] >= cutoff]
        return items

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    def catalog(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: dict(entry) for key, entry in self._catalog.items()}

    def warnings(self) -> list[dict[str, str]]:
        latest = self.latest()
        if latest is None:
            return []
        return warnings.evaluate(latest["values"], self.catalog(), self.hardware)

    def device(self) -> dict[str, Any]:
        """The compute device training should use, resolved from config and what was found."""
        catalog = self.catalog()
        gpus = [
            {"index": int(key.split(".")[0][3:]), "name": entry["label"]}
            for key, entry in catalog.items()
            if key.endswith(".name") and key.startswith("gpu") and entry["available"]
        ]
        reason = ""
        if not gpus:
            reason = catalog.get("gpu.nvidia", {}).get("reason", "No GPU reading has arrived yet.")
        configured = self.hardware["device"]
        resolved = configured if configured != "auto" else ("cuda" if gpus else "cpu")
        return {
            "configured": configured,
            "resolved": resolved,
            "gpus": gpus,
            "gpu_present": bool(gpus),
            "gpu_reason": reason,
        }

    def status(self) -> dict[str, Any]:
        hw = self.hardware
        buffer_seconds = hw["ring_buffer_seconds"]
        with self._lock:
            active = (
                {
                    "id": self._active.run_id,
                    "name": self._active.name,
                    "started_t": self._active.started_t,
                }
                if self._active
                else None
            )
        return {
            "running": self.running,
            "samplers": [s.name for s in self.samplers],
            "interval_s": self.interval,
            "buffer_seconds": buffer_seconds,
            "windows_s": [w for w in hw["chart_windows_s"] if w <= buffer_seconds],
            "history_interval_s": hw["history_interval_s"],
            "device": self.device(),
            "catalog": self.catalog(),
            "warnings": self.warnings(),
            "thresholds": hw["warnings"],
            "active_run": active,
            "run_epoch": self.run_epoch,
            "max_run_name_length": hw["max_run_name_length"],
        }

    # ---- recorded runs ----------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        return db.connect(self.db_path)

    def _mark_interrupted_runs(self) -> None:
        """A run still 'recording' at start-up belonged to a process that died."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE monitor_runs SET status = 'interrupted', ended_at = ?"
                " WHERE status = 'recording'",
                (db.utc_now(),),
            )
            conn.commit()
        finally:
            conn.close()

    def start_run(self, name: str) -> dict[str, Any]:
        """Begin recording. Raises ValueError (bad name) or RunActive (one is already recording)."""
        name = _clean_name(name, self.hardware["max_run_name_length"])
        with self._lock:
            if self._active is not None:
                raise RunActive(f"“{self._active.name}” is already recording. Stop it first.")
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                run_id = conn.execute(
                    "INSERT INTO monitor_runs (name, started_at, interval_s, catalog)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        name,
                        db.utc_now(),
                        self.hardware["history_interval_s"],
                        json.dumps(_catalog_for_storage(self._catalog)),
                    ),
                ).lastrowid
                self._prune_old_runs(conn)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
            self._active = _Recording(
                run_id, name, self._clock(), float(self.hardware["history_interval_s"])
            )
            self.run_epoch += 1
        return self.get_run(run_id, with_samples=False)

    def _prune_old_runs(self, conn: sqlite3.Connection) -> None:
        keep = self.hardware["max_runs"]
        conn.execute(
            "DELETE FROM monitor_runs WHERE status != 'recording' AND id NOT IN"
            " (SELECT id FROM monitor_runs ORDER BY id DESC LIMIT ?)",
            (keep,),
        )

    def stop_run(self, run_id: int | None = None) -> dict[str, Any]:
        """Finish the active run (``run_id``, if given, must be it). Raises LookupError if none."""
        with self._lock:
            active = self._active
            if active is None or (run_id is not None and run_id != active.run_id):
                raise LookupError("That run is not recording.")
            self._active = None
            self.run_epoch += 1
            rows = [active.flush(self._clock())] if active.bucket else []
        self._store_rows(active, rows)
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE monitor_runs SET status = 'finished', ended_at = ?, summary = ?,"
                " catalog = ? WHERE id = ?",
                (
                    db.utc_now(),
                    json.dumps(active.summary()),
                    json.dumps(_catalog_for_storage(self.catalog(), active.totals)),
                    active.run_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_run(active.run_id, with_samples=False)

    def _store_rows(
        self, recording: _Recording, rows: list[tuple[float, dict[str, float]]]
    ) -> None:
        if not rows:
            return
        run_id = recording.run_id
        room = self.hardware["max_run_samples"] - recording.stored
        to_write = rows[: max(room, 0)]
        truncated = len(to_write) < len(rows)
        conn = self._connect()
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO monitor_samples (run_id, t, metrics) VALUES (?, ?, ?)",
                [(run_id, t, json.dumps(values)) for t, values in to_write],
            )
            conn.execute(
                "UPDATE monitor_runs SET sample_count = sample_count + ?, truncated = ?"
                " WHERE id = ?",
                (len(to_write), int(truncated or recording.truncated), run_id),
            )
            conn.commit()
        finally:
            conn.close()
        recording.stored += len(to_write)
        recording.truncated = recording.truncated or truncated

    def list_runs(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM monitor_runs ORDER BY id DESC").fetchall()
        finally:
            conn.close()
        return [_run_dict(row) for row in rows]

    def get_run(self, run_id: int, with_samples: bool = True) -> dict[str, Any]:
        """One run (with its stored rows). Raises LookupError if it does not exist."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM monitor_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise LookupError(f"Run {run_id} not found.")
            run = _run_dict(row)
            if with_samples:
                run["samples"] = [
                    {"t": r["t"], "values": json.loads(r["metrics"])}
                    for r in conn.execute(
                        "SELECT t, metrics FROM monitor_samples WHERE run_id = ? ORDER BY t",
                        (run_id,),
                    )
                ]
        finally:
            conn.close()
        return run

    def delete_run(self, run_id: int) -> None:
        """Remove a finished run and its rows. Raises RunActive / LookupError."""
        with self._lock:
            if self._active is not None and self._active.run_id == run_id:
                raise RunActive("Stop the recording before deleting it.")
        conn = self._connect()
        try:
            deleted = conn.execute("DELETE FROM monitor_runs WHERE id = ?", (run_id,)).rowcount
            conn.commit()
        finally:
            conn.close()
        if not deleted:
            raise LookupError(f"Run {run_id} not found.")


def _catalog_entry(reading: Reading) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "label": reading.label,
        "unit": reading.unit,
        "group": reading.group,
        "available": reading.available,
        "reason": reading.reason,
    }
    if reading.maximum is not None:
        entry["max"] = round(reading.maximum, 3)
    return entry


def _catalog_for_storage(catalog, totals=None) -> dict[str, Any]:
    """Available metrics only (what the run can hold); with ``totals``, only those that got data."""
    return {
        key: {
            "label": e["label"],
            "unit": e["unit"],
            "group": e["group"],
            **({"max": e["max"]} if "max" in e else {}),
        }
        for key, e in catalog.items()
        if e["available"] and not key.endswith(".name") and (totals is None or key in totals)
    }


def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
    run = dict(row)
    run["truncated"] = bool(run["truncated"])
    run["catalog"] = json.loads(run["catalog"])
    run["summary"] = json.loads(run["summary"])
    return run
