"""Hardware monitor (Stage 5): samplers, ring buffer, warnings, recorded runs and the API.

Everything runs on fake samplers and a fake clock, so no GPU, no sleeping and no threads are needed
(Development Rule 8). One test reads the real machine and only checks its shape."""

import copy
import sqlite3
import time

import pytest

from studio import db
from studio.config import load_config
from studio.hardware import nvml_sampler, psutil_sampler, warnings
from studio.hardware.base import Reading, safe_sample
from studio.hardware.fake import FakeGpuSampler, FakeSystemSampler
from studio.hardware.monitor import Monitor, RunActive
from studio.hardware.registry import build_samplers


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def hardware():
    hw = copy.deepcopy(load_config()["hardware"])
    hw.update(
        sampler="fake",
        autostart=False,
        monitor_interval_s=1.0,
        history_interval_s=5,
        ring_buffer_seconds=10,
    )
    return hw


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "monitor.sqlite"
    with db.connect(path) as conn:
        db.migrate(conn)
    return path


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def monitor(hardware, db_file, clock):
    return Monitor(hardware, db_file, clock=clock)


def tick(monitor, clock, times=1, step=1.0):
    for _ in range(times):
        monitor.tick()
        clock.advance(step)


# ---- samplers ------------------------------------------------------------------------------------
def test_fake_samplers_are_deterministic_and_mirror_real_keys():
    first = [(r.key, r.value) for r in FakeSystemSampler(cores=4).sample()]
    second = [(r.key, r.value) for r in FakeSystemSampler(cores=4).sample()]
    assert first == second
    keys = {key for key, _ in first}
    assert {"cpu.total", "cpu.core.3", "ram.percent", "ram.used", "disk.read", "disk.write"} <= keys
    gpu_keys = {r.key for r in FakeGpuSampler().sample()}
    assert {"gpu0.vram_used", "gpu0.vram_total", "gpu0.util", "gpu0.temp", "gpu0.power"} <= gpu_keys


def test_fake_without_gpu_reports_unavailable_with_a_reason():
    [reading] = FakeGpuSampler(present=False).sample()
    assert not reading.available and reading.reason


def test_a_failing_sampler_becomes_one_unavailable_reading():
    class Broken:
        name = "broken"

        def sample(self):
            raise RuntimeError("boom")

    [reading] = safe_sample(Broken())
    assert not reading.available and "boom" in reading.reason


def test_unknown_sampler_choice_is_an_error(hardware):
    hardware["sampler"] = "gpu-magic"
    with pytest.raises(ValueError, match="hardware.sampler"):
        build_samplers(hardware)


def test_nvml_without_the_library_says_so(monkeypatch):
    monkeypatch.setattr(nvml_sampler, "pynvml", None)
    readings = nvml_sampler.NvmlSampler().sample()
    assert len(readings) == 1 and not readings[0].available
    assert "not installed" in readings[0].reason


def test_psutil_missing_reports_unavailable(monkeypatch):
    monkeypatch.setattr(psutil_sampler, "psutil", None)
    readings = psutil_sampler.PsutilSampler().sample()
    assert readings and all(not r.available for r in readings)


def test_real_sampler_returns_sane_numbers(hardware, db_file):
    """Reads this machine: checks ranges only, so it passes with or without a GPU."""
    hardware["sampler"] = "auto"
    monitor = Monitor(hardware, db_file)
    try:
        sample = monitor.tick()
        values = sample["values"]
        assert 0 <= values["cpu.total"] <= 100
        assert 0 <= values["ram.percent"] <= 100
        assert values["ram.used"] > 0
        assert any(key.startswith("cpu.core.") for key in values)
    finally:
        monitor.stop()


def test_sampling_overhead_is_small(hardware, db_file):
    """Plan criterion: under 2 % of one CPU at the configured period. Measured as time per tick."""
    hardware["sampler"] = "auto"
    monitor = Monitor(hardware, db_file)
    try:
        monitor.tick()
        started = time.perf_counter()
        for _ in range(20):
            monitor.tick()
        per_tick = (time.perf_counter() - started) / 20
    finally:
        monitor.stop()
    assert per_tick / hardware["monitor_interval_s"] < 0.02, f"{per_tick * 1000:.1f} ms per tick"


# ---- live buffer ---------------------------------------------------------------------------------
def test_ring_buffer_keeps_only_the_configured_history(monitor, clock):
    tick(monitor, clock, 25)  # buffer holds 10 s at 1 s per sample
    samples = monitor.samples()
    assert len(samples) == 10
    assert samples[-1]["seq"] == 25 and samples[0]["seq"] == 16


def test_samples_after_a_sequence_number_and_by_window(monitor, clock):
    tick(monitor, clock, 8)
    assert [s["seq"] for s in monitor.samples(after_seq=6)] == [7, 8]
    assert [s["seq"] for s in monitor.samples(seconds=2)] == [6, 7, 8]
    assert monitor.samples(after_seq=99) == []


def test_catalog_lists_metrics_and_marks_unavailable_ones(monitor, clock):
    tick(monitor, clock)
    catalog = monitor.catalog()
    assert catalog["cpu.total"]["available"] and catalog["cpu.total"]["unit"] == "%"
    assert catalog["gpu0.vram_used"]["max"] == 6.0
    assert not catalog["gpu.other"]["available"] and catalog["gpu.other"]["reason"]


def test_info_readings_never_enter_samples(monitor, clock):
    tick(monitor, clock)
    assert "gpu0.name" not in monitor.latest()["values"]
    assert monitor.catalog()["gpu0.name"]["label"] == "Fake GPU"


def test_device_resolves_from_config_and_findings(hardware, db_file, clock):
    monitor = Monitor(hardware, db_file, clock=clock)
    tick(monitor, clock)
    assert (
        monitor.device()["resolved"] == "cuda" and monitor.device()["gpus"][0]["name"] == "Fake GPU"
    )
    hardware["sampler"] = "fake_no_gpu"
    no_gpu = Monitor(hardware, db_file, clock=clock)
    no_gpu.tick()
    device = no_gpu.device()
    assert device["resolved"] == "cpu" and not device["gpu_present"] and device["gpu_reason"]


def test_background_thread_samples_and_stops(hardware, db_file):
    hardware["monitor_interval_s"] = 0.05
    monitor = Monitor(hardware, db_file)
    monitor.start()
    try:
        deadline = time.time() + 5
        while len(monitor.samples()) < 4 and time.time() < deadline:
            time.sleep(0.02)
        assert len(monitor.samples()) >= 4 and monitor.running
    finally:
        monitor.stop()
    assert not monitor.running


def test_stop_closes_an_open_recording(hardware, db_file):
    monitor = Monitor(hardware, db_file)
    monitor.tick()
    run = monitor.start_run("open at shutdown")
    monitor.stop()
    assert monitor.get_run(run["id"], with_samples=False)["status"] == "finished"


# ---- warnings ------------------------------------------------------------------------------------
def test_no_warning_for_the_calm_defaults(monitor, clock):
    tick(monitor, clock)
    assert monitor.warnings() == []


def test_vram_and_temperature_warnings_carry_a_fix(hardware, db_file, clock):
    hardware["fake"].update(vram_fraction=0.95, gpu_temp_c=90)
    monitor = Monitor(hardware, db_file, clock=clock)
    tick(monitor, clock)
    found = {w["id"]: w for w in monitor.warnings()}
    assert {"vram_high", "gpu_hot"} <= set(found)
    assert "batch size" in found["vram_high"]["fix"] and "5.7" in found["vram_high"]["message"]
    assert found["gpu_hot"]["severity"] == "warning"


def test_no_gpu_is_a_note_not_a_warning(hardware, db_file, clock):
    hardware["sampler"] = "fake_no_gpu"
    monitor = Monitor(hardware, db_file, clock=clock)
    tick(monitor, clock)
    [only] = [w for w in monitor.warnings() if w["id"].startswith("no_gpu")]
    assert only["id"] == "no_gpu" and only["severity"] == "info"


def test_device_cuda_without_a_gpu_is_a_warning(hardware, db_file, clock):
    hardware.update(sampler="fake_no_gpu", device="cuda")
    monitor = Monitor(hardware, db_file, clock=clock)
    tick(monitor, clock)
    assert [w["id"] for w in monitor.warnings()] == ["no_gpu_but_cuda"]


def test_ram_warning_at_the_threshold():
    hardware = load_config()["hardware"]
    entry = {"available": True}
    catalog = {"gpu0.util": entry}
    below = warnings.evaluate({"ram.percent": 89.0}, catalog, hardware)
    at = warnings.evaluate({"ram.percent": 90.0, "ram.used": 28.8}, catalog, hardware)
    assert not [w for w in below if w["id"] == "ram_high"]
    assert [w["id"] for w in at if w["id"] == "ram_high"]


# ---- recorded runs -------------------------------------------------------------------------------
def test_run_stores_one_averaged_row_per_interval(monitor, clock):
    monitor.tick()  # a sample before the run must not count
    clock.advance(1)
    run = monitor.start_run("  my   run ")
    assert run["name"] == "my run" and run["status"] == "recording"
    tick(monitor, clock, 12)  # 12 s of samples with 5 s rows
    done = monitor.stop_run(run["id"])
    assert done["status"] == "finished" and done["ended_at"]
    stored = monitor.get_run(run["id"])
    assert done["sample_count"] == len(stored["samples"]) == 3
    assert [s["t"] for s in stored["samples"]] == sorted(s["t"] for s in stored["samples"])
    cpu = [s["values"]["cpu.total"] for s in stored["samples"]]
    assert all(0 <= value <= 100 for value in cpu)
    assert (
        "cpu.total" in stored["summary"]
        and stored["summary"]["cpu.total"]["max"] >= stored["summary"]["cpu.total"]["avg"]
    )
    assert "gpu0.name" not in stored["catalog"] and "gpu.other" not in stored["catalog"]


def test_averages_are_real_means(hardware, db_file, clock):
    class Ramp:
        name = "ramp"

        def __init__(self):
            self.value = 0.0

        def sample(self):
            self.value += 10.0
            return [Reading("x", "X", "u", self.value, "g")]

    hardware["history_interval_s"] = 3
    monitor = Monitor(hardware, db_file, samplers=[Ramp()], clock=clock)
    monitor.tick()
    run = monitor.start_run("ramp")
    tick(monitor, clock, 4)  # readings 20, 30, 40, 50
    monitor.stop_run()
    rows = monitor.get_run(run["id"])["samples"]
    assert rows[0]["values"]["x"] == pytest.approx(30.0)  # mean of 20, 30, 40
    assert monitor.get_run(run["id"])["summary"]["x"] == {"avg": pytest.approx(35.0), "max": 50.0}


def test_only_one_run_records_at_a_time(monitor, clock):
    tick(monitor, clock)
    first = monitor.start_run("one")
    with pytest.raises(RunActive, match="one"):
        monitor.start_run("two")
    with pytest.raises(RunActive):
        monitor.delete_run(first["id"])
    with pytest.raises(LookupError):
        monitor.stop_run(first["id"] + 1)
    monitor.stop_run()
    with pytest.raises(LookupError):
        monitor.stop_run()


@pytest.mark.parametrize("name", ["", "   ", None, "x" * 81])
def test_bad_run_names_are_refused(monitor, name):
    with pytest.raises(ValueError):
        monitor.start_run(name)


def test_a_long_run_stops_storing_and_is_marked_truncated(hardware, db_file, clock):
    hardware.update(history_interval_s=1, max_run_samples=3)
    monitor = Monitor(hardware, db_file, clock=clock)
    tick(monitor, clock, 1)
    run = monitor.start_run("long")
    tick(monitor, clock, 10)
    done = monitor.stop_run()
    assert done["truncated"] and done["sample_count"] == 3
    assert len(monitor.get_run(run["id"])["samples"]) == 3
    assert done["summary"]["cpu.total"]  # the summary still covers every raw sample


def test_oldest_finished_run_is_removed_over_the_limit(hardware, db_file, clock):
    hardware["max_runs"] = 2
    monitor = Monitor(hardware, db_file, clock=clock)
    names = []
    for index in range(4):
        tick(monitor, clock, 2)
        monitor.start_run(f"run {index}")
        monitor.stop_run()
        names = [run["name"] for run in monitor.list_runs()]
    assert names == ["run 3", "run 2"]


def test_a_run_left_recording_by_a_dead_process_is_marked_interrupted(hardware, db_file, clock):
    first = Monitor(hardware, db_file, clock=clock)
    tick(first, clock, 2)
    run = first.start_run("crashed")  # never stopped: simulates a killed process
    second = Monitor(hardware, db_file, clock=clock)
    assert second.get_run(run["id"], with_samples=False)["status"] == "interrupted"
    second.start_run("fresh")  # and a new recording is allowed


def test_delete_removes_the_run_and_its_rows(monitor, clock, db_file):
    tick(monitor, clock, 7)
    run = monitor.start_run("gone")
    tick(monitor, clock, 7)
    monitor.stop_run()
    monitor.delete_run(run["id"])
    with pytest.raises(LookupError):
        monitor.get_run(run["id"])
    with pytest.raises(LookupError):
        monitor.delete_run(run["id"])
    with sqlite3.connect(db_file) as raw:
        assert raw.execute("SELECT COUNT(*) FROM monitor_samples").fetchone()[0] == 0


# ---- API -----------------------------------------------------------------------------------------
def test_status_and_samples_endpoints(client):
    client.app.state.monitor.tick()
    status = client.get("/api/monitor/status").json()
    assert status["samplers"][0] == "fake-system" and status["device"]["gpu_present"]
    assert status["windows_s"] == [60, 300, 900] and status["active_run"] is None
    body = client.get("/api/monitor/samples?seconds=60").json()
    assert body["samples"] and "cpu.total" in body["catalog"] and body["warnings"] == []
    seq = body["samples"][-1]["seq"]
    assert client.get(f"/api/monitor/samples?after={seq}").json()["samples"] == []
    assert client.get("/api/monitor/samples?after=-1").status_code == 422
    assert client.get("/api/monitor/samples?seconds=0").status_code == 422


def test_run_lifecycle_over_http(client):
    client.app.state.monitor.tick()
    epoch_before = client.get("/api/monitor/status").json()["run_epoch"]
    started = client.post("/api/monitor/runs", json={"name": "http run"})
    assert started.status_code == 201
    assert started.json()["run_epoch"] == epoch_before + 1
    run_id = started.json()["id"]
    assert client.post("/api/monitor/runs", json={"name": "other"}).status_code == 409
    assert client.post("/api/monitor/runs", json={"name": " "}).status_code == 400
    assert client.delete(f"/api/monitor/runs/{run_id}").status_code == 409
    assert client.get("/api/monitor/status").json()["active_run"]["id"] == run_id
    stopped = client.post(f"/api/monitor/runs/{run_id}/stop")
    assert stopped.status_code == 200 and stopped.json()["status"] == "finished"
    assert stopped.json()["run_epoch"] == epoch_before + 2
    assert client.get("/api/monitor/samples").json()["run_epoch"] == epoch_before + 2
    assert client.post(f"/api/monitor/runs/{run_id}/stop").status_code == 409
    assert [r["id"] for r in client.get("/api/monitor/runs").json()] == [run_id]
    assert client.get(f"/api/monitor/runs/{run_id}").json()["name"] == "http run"
    assert client.delete(f"/api/monitor/runs/{run_id}").status_code == 204
    assert client.get(f"/api/monitor/runs/{run_id}").status_code == 404
    assert client.delete(f"/api/monitor/runs/{run_id}").status_code == 404


def test_run_ids_are_strict(client):
    assert client.get("/api/monitor/runs/abc").status_code == 422
    assert client.get("/api/monitor/runs/99999999999999999999").status_code == 422


def test_websocket_sends_new_samples_then_only_newer_ones(client):
    monitor = client.app.state.monitor
    monitor.tick()
    with client.websocket_connect("/api/monitor/ws?after=0") as socket:
        first = socket.receive_json()
        assert first["samples"][-1]["seq"] == 1 and "cpu.total" in first["catalog"]
        monitor.tick()
        second = socket.receive_json()
        assert [s["seq"] for s in second["samples"]] == [2]
        assert "catalog" not in second  # unchanged catalog is not resent


def test_autostart_runs_a_thread_with_the_app(config):
    from fastapi.testclient import TestClient

    from studio.api.app import create_app

    config["hardware"]["autostart"] = True
    with TestClient(create_app(config, allowed_hosts=["testserver"])) as test_client:
        assert test_client.app.state.monitor.running
        assert test_client.get("/api/monitor/status").json()["running"]
    assert not test_client.app.state.monitor.running


def test_migration_is_recorded(db_file):
    with sqlite3.connect(db_file) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] >= 4
        tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"monitor_runs", "monitor_samples"} <= tables


# ---- review fixes --------------------------------------------------------------------------------
def test_a_failed_stop_does_not_leave_the_run_recording(monitor, clock, monkeypatch):
    tick(monitor, clock, 2)
    run = monitor.start_run("will fail")
    tick(monitor, clock, 2)

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(monitor, "_store_rows", broken)
    with pytest.raises(sqlite3.OperationalError):
        monitor.stop_run()
    assert monitor.get_run(run["id"], with_samples=False)["status"] == "interrupted"
    monitor.start_run("a new one is allowed")  # nothing is stuck


def test_concurrent_start_calls_start_one_thread(hardware, db_file):
    import threading

    hardware["monitor_interval_s"] = 0.05
    monitor = Monitor(hardware, db_file)
    errors = []

    def go():
        try:
            monitor.start()
        except Exception as error:  # the old code raised "threads can only be started once"
            errors.append(error)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    try:
        assert errors == [] and monitor.running
    finally:
        monitor.stop()


def test_a_client_from_an_older_process_is_told_to_reset(client):
    monitor = client.app.state.monitor
    monitor.tick()
    assert client.get("/api/monitor/samples?after=5000").json()["reset"] is True
    body = client.get("/api/monitor/samples?after=5000").json()
    assert body["samples"]  # it gets the current samples from the start
    assert client.get("/api/monitor/samples?after=1").json()["reset"] is False
    with client.websocket_connect("/api/monitor/ws?after=5000") as socket:
        first = socket.receive_json()
        assert first["reset"] is True and first["samples"][0]["seq"] == 1


def test_websocket_ends_when_the_browser_leaves(client):
    client.app.state.monitor.tick()
    with client.websocket_connect("/api/monitor/ws?after=0") as socket:
        socket.receive_json()
    # leaving the block closed the socket; the server task must have ended (no hang on exit)
