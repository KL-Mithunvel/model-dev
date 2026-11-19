-- v0.7 (Stage 5): recorded hardware-monitor runs.
-- A run is a named recording (Stage 6 training starts one per training run). While it is recording,
-- the monitor stores one down-sampled row per `hardware.history_interval_s` seconds: the average of
-- the raw samples in that interval. The live ring buffer is in memory only and is not stored.
-- Runs are not tied to projects (a run may be a plain "watch this" recording).

CREATE TABLE monitor_runs (
    id            INTEGER PRIMARY KEY,
    name          TEXT    NOT NULL,
    started_at    TEXT    NOT NULL,                       -- UTC ISO-8601 with Z
    ended_at      TEXT,                                   -- NULL while recording
    status        TEXT    NOT NULL DEFAULT 'recording'
                  CHECK (status IN ('recording', 'finished', 'interrupted')),
    interval_s    REAL    NOT NULL,                       -- seconds between stored rows
    sample_count  INTEGER NOT NULL DEFAULT 0,             -- stored rows
    truncated     INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
    catalog       TEXT    NOT NULL DEFAULT '{}',          -- JSON: key -> label, unit, group
    summary       TEXT    NOT NULL DEFAULT '{}'           -- JSON: key -> {avg, max} over the raw samples
);

CREATE TABLE monitor_samples (
    run_id  INTEGER NOT NULL REFERENCES monitor_runs(id) ON DELETE CASCADE,
    t       REAL    NOT NULL,                             -- seconds since the run started
    metrics TEXT      NOT NULL,                             -- JSON: key -> averaged value
    PRIMARY KEY (run_id, t)
);
