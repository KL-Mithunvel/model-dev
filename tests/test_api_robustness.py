"""API and data-layer behaviour found by the v0.1 independent review."""

import threading
import time

import pytest
from conftest import make_image, wait_for_job

from studio import db, paths, repo


def blocking_job(client, project_id):
    """Queue a job that runs until cancelled, so tests can act while an import is 'active'."""
    started = threading.Event()

    def work(progress, cancelled):
        started.set()
        while not cancelled():
            time.sleep(0.01)
        return {"cancelled": True}

    job_id = client.app.state.jobs.submit(work, kind="import", project_id=project_id)
    assert started.wait(5)
    return job_id


def test_cannot_delete_a_project_while_its_import_runs(client, project):
    job_id = blocking_job(client, project["id"])
    blocked = client.delete(f"/api/projects/{project['id']}")
    assert blocked.status_code == 409 and "import" in blocked.json()["detail"].lower()
    assert client.get(f"/api/projects/{project['id']}").status_code == 200  # still there

    assert client.post(f"/api/jobs/{job_id}/cancel").json() == {"cancel_requested": True}
    wait_for_job(client, job_id)
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204


def test_cancel_endpoint_unknown_and_finished_jobs(client, project):
    assert client.post("/api/jobs/nope/cancel").status_code == 404
    job_id = blocking_job(client, project["id"])
    client.post(f"/api/jobs/{job_id}/cancel")
    wait_for_job(client, job_id)
    assert client.post(f"/api/jobs/{job_id}/cancel").json() == {"cancel_requested": False}


def test_cancelling_a_real_import_keeps_partial_results(client, project, tmp_path, monkeypatch):
    folder = tmp_path / "src"
    for i in range(8):
        make_image(folder / f"i{i}.png", color=(i, 3, 3))
    gate = threading.Event()
    from studio import importer

    real = importer._classify_and_store

    def slow(*args, **kwargs):
        gate.wait(5)  # hold the first file until we have asked for cancellation
        return real(*args, **kwargs)

    monkeypatch.setattr(importer, "_classify_and_store", slow)
    job_id = client.post(
        f"/api/projects/{project['id']}/imports", json={"path": str(folder)}
    ).json()["job_id"]
    deadline = time.time() + 5
    while client.get(f"/api/jobs/{job_id}").json()["state"] != "running" and time.time() < deadline:
        time.sleep(0.01)
    client.post(f"/api/jobs/{job_id}/cancel")
    gate.set()
    job = wait_for_job(client, job_id)

    assert job["state"] == "done" and job["report"]["cancelled"] is True
    assert job["report"]["added"] < 8
    listed = client.get(f"/api/projects/{project['id']}/images").json()["total"]
    assert listed == job["report"]["added"]


def test_new_project_does_not_inherit_files_of_a_deleted_one(client, config):
    first = client.post("/api/projects", json={"name": "one"}).json()
    client.delete(f"/api/projects/{first['id']}")
    leftover = paths.project_dir(config, first["id"])
    leftover.mkdir(parents=True)
    (leftover / "stale.txt").write_text("old", encoding="utf-8")

    second = client.post("/api/projects", json={"name": "two"}).json()

    assert second["id"] == first["id"]  # SQLite reused the id, as the review predicted
    assert not leftover.exists()


def test_delete_reports_files_that_could_not_be_removed(client, project, tmp_path, monkeypatch):
    monkeypatch.setattr(repo.shutil, "rmtree", lambda *a, **k: None)  # pretend removal failed
    pid = project["id"]
    paths.project_dir(client.app.state.config, pid).mkdir(parents=True)
    response = client.delete(f"/api/projects/{pid}")
    assert response.status_code == 200 and "could not be removed" in response.json()["warning"]


def test_limits_endpoint_mirrors_the_config(client, config):
    limits = client.get("/api/limits").json()
    assert limits["project_name_max"] == config["projects"]["max_name_length"]
    assert limits["tag_max_length"] == config["tags"]["max_length"]
    assert limits["page_size"] == config["gallery"]["default_page_size"]


def test_cross_site_style_posts_are_rejected(client):
    """A web page on another origin can only send 'simple' content types without a preflight.
    The API must refuse them (JSON only), otherwise any site could create projects or start
    imports on a user's machine."""
    plain = client.post(
        "/api/projects", content='{"name": "evil"}', headers={"Content-Type": "text/plain"}
    )
    form = client.post("/api/projects", data={"name": "evil"})
    assert plain.status_code == 422 and form.status_code == 422
    assert client.get("/api/projects").json() == []


def test_setting_a_split_for_tens_of_thousands_of_ids_works():
    conn = db.connect(":memory:")
    db.migrate(conn)
    conn.execute("INSERT INTO projects (id, name, created_at) VALUES (1, 'big', 'n')")
    conn.execute("INSERT INTO batches (id, project_id, source, created_at) VALUES (1, 1, 's', 'n')")
    total = 40_000  # above SQLite's 32,766 bound-variable limit
    conn.executemany(
        "INSERT INTO images (project_id, batch_id, sha256, stored_name, original_name, width,"
        " height, bytes, created_at) VALUES (1, 1, ?, 'a', 'a', 1, 1, 1, 'n')",
        [(str(i),) for i in range(total)],
    )
    ids = [r[0] for r in conn.execute("SELECT id FROM images")]
    assert repo.set_split(conn, 1, ids, "train") == total
    assert conn.execute("SELECT COUNT(*) FROM images WHERE split = 'train'").fetchone()[0] == total


def test_splits_on_an_empty_project_and_tiny_projects():
    conn = db.connect(":memory:")
    db.migrate(conn)
    conn.execute("INSERT INTO projects (id, name, created_at) VALUES (1, 'p', 'n')")
    conn.execute("INSERT INTO batches (id, project_id, source, created_at) VALUES (1, 1, 's', 'n')")
    ratios = {"train": 0.8, "val": 0.1, "test": 0.1}
    counts, previous = repo.apply_splits(conn, 1, ratios, 1, only_unassigned=True)
    assert counts == {"train": 0, "val": 0, "test": 0} and previous["unassigned"] == []

    for i in range(3):  # with 1-3 images everything lands in train (documented, not an error)
        conn.execute(
            "INSERT INTO images (project_id, batch_id, sha256, stored_name, original_name, width,"
            " height, bytes, created_at) VALUES (1, 1, ?, 'a', 'a', 1, 1, 1, 'n')",
            (str(i),),
        )
    counts, _ = repo.apply_splits(conn, 1, ratios, 1, only_unassigned=True)
    assert counts == {"train": 3, "val": 0, "test": 0}


def test_tag_filter_uses_the_same_normalisation_as_storage(client, project, tmp_path):
    folder = tmp_path / "src"
    make_image(folder / "t.png", color=(60, 1, 1))
    started = client.post(f"/api/projects/{project['id']}/imports", json={"path": str(folder)})
    wait_for_job(client, started.json()["job_id"])
    image_id = client.get(f"/api/projects/{project['id']}/images").json()["items"][0]["id"]
    client.put(f"/api/images/{image_id}/tags", json={"tags": ["Night   Rain"]})
    found = client.get(f"/api/projects/{project['id']}/images", params={"tag": "  NIGHT   rain "})
    assert found.json()["total"] == 1


@pytest.mark.parametrize("path", ["/api/projects/1/images", "/api/limits"])
def test_foreign_host_is_refused_on_every_route(config, path):
    from fastapi.testclient import TestClient

    from studio.api.app import create_app

    app = create_app(config, allowed_hosts=["127.0.0.1"])
    with TestClient(app, base_url="http://attacker.example") as evil:
        assert evil.get(path).status_code == 400
