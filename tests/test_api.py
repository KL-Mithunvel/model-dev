import time

import pytest
from conftest import make_image
from fastapi.testclient import TestClient

from studio import paths
from studio.api.app import create_app


@pytest.fixture
def client(config):
    app = create_app(config, allowed_hosts=["testserver"])
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Demo"}).json()


def wait_for_job(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def import_images(client, project_id, folder, count, start=0):
    for i in range(start, start + count):
        make_image(folder / f"img_{i:02d}.png", color=(i, 10, 10))
    response = client.post(f"/api/projects/{project_id}/imports", json={"path": str(folder)})
    assert response.status_code == 202
    job = wait_for_job(client, response.json()["job_id"])
    assert job["state"] == "done", job
    return job


# ---- projects ---------------------------------------------------------------------------------


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_project_lifecycle(client, config):
    created = client.post("/api/projects", json={"name": "  My   project "})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "My project" and body["image_count"] == 0
    assert client.get("/api/projects").json()[0]["id"] == body["id"]
    assert client.get(f"/api/projects/{body['id']}").json()["name"] == "My project"
    assert client.delete(f"/api/projects/{body['id']}").status_code == 204
    assert client.get(f"/api/projects/{body['id']}").status_code == 404
    assert client.delete(f"/api/projects/{body['id']}").status_code == 404


def test_project_name_validation(client):
    assert client.post("/api/projects", json={"name": "   "}).status_code == 400
    assert client.post("/api/projects", json={"name": "x" * 81}).status_code == 400
    assert client.post("/api/projects", json={"name": "dup"}).status_code == 201
    duplicate = client.post("/api/projects", json={"name": "dup"})
    assert duplicate.status_code == 409 and "already exists" in duplicate.json()["detail"]
    assert client.post("/api/projects", json={}).status_code == 422


def test_foreign_host_header_is_rejected(config):
    app = create_app(config, allowed_hosts=["127.0.0.1"])
    with TestClient(app, base_url="http://evil.example") as evil:
        assert evil.get("/api/health").status_code == 400


def test_deleting_a_project_removes_its_files(client, config, project, tmp_path):
    import_images(client, project["id"], tmp_path / "src", 2)
    folder = paths.project_dir(config, project["id"])
    assert folder.is_dir()
    client.delete(f"/api/projects/{project['id']}")
    assert not folder.exists()


# ---- import + images ----------------------------------------------------------------------------


def test_import_serve_and_cache_headers(client, project, tmp_path):
    job = import_images(client, project["id"], tmp_path / "src", 3)
    assert job["report"]["added"] == 3 and job["done"] == job["total"] == 3

    page = client.get(f"/api/projects/{project['id']}/images").json()
    assert page["total"] == 3 and len(page["items"]) == 3
    item = page["items"][0]
    assert "stored_name" not in item
    thumb = client.get(item["thumb_url"])
    original = client.get(item["file_url"])
    assert thumb.status_code == original.status_code == 200
    assert thumb.headers["content-type"] == "image/jpeg"
    assert "immutable" in thumb.headers["cache-control"]
    assert client.get(f"/api/images/{item['id']}").json()["width"] == 40
    assert client.get("/api/images/99999").status_code == 404
    assert client.get("/api/images/99999/thumb").status_code == 404
    assert client.get(f"/api/projects/{project['id']}").json()["image_count"] == 3


def test_missing_file_on_disk_is_a_clear_404(client, config, project, tmp_path):
    import_images(client, project["id"], tmp_path / "src", 1)
    item = client.get(f"/api/projects/{project['id']}/images").json()["items"][0]
    (paths.images_dir(config, project["id"]) / f"{item['sha256']}.png").unlink()
    response = client.get(item["file_url"])
    assert response.status_code == 404 and "missing" in response.json()["detail"]


def test_import_request_errors(client, project, tmp_path):
    base = f"/api/projects/{project['id']}/imports"
    assert client.post(base, json={"path": str(tmp_path / "nope")}).status_code == 400
    plain = tmp_path / "x.txt"
    plain.write_text("x", encoding="utf-8")
    assert client.post(base, json={"path": str(plain)}).status_code == 400
    assert client.post(base, json={"path": ""}).status_code == 422
    assert client.post("/api/projects/999/imports", json={"path": str(tmp_path)}).status_code == 404


def test_failed_job_reports_error(client, project, tmp_path):
    fake = tmp_path / "bad.zip"
    fake.write_bytes(b"not a zip")
    response = client.post(f"/api/projects/{project['id']}/imports", json={"path": str(fake)})
    job = wait_for_job(client, response.json()["job_id"])
    assert job["state"] == "failed" and "zip" in job["error"]


def test_job_websocket_streams_until_done(client, project, tmp_path):
    folder = tmp_path / "src"
    for i in range(4):
        make_image(folder / f"w{i}.png", color=(i, 1, 1))
    job_id = client.post(
        f"/api/projects/{project['id']}/imports", json={"path": str(folder)}
    ).json()["job_id"]
    with client.websocket_connect(f"/api/jobs/{job_id}/ws") as socket:
        messages = []
        while True:
            try:
                messages.append(socket.receive_json())
            except Exception:
                break
    assert messages and messages[-1]["state"] == "done"
    assert messages[-1]["report"]["added"] == 4


def test_unknown_job(client):
    assert client.get("/api/jobs/nope").status_code == 404
    with pytest.raises(Exception):  # noqa: B017 - starlette raises WebSocketDisconnect
        with client.websocket_connect("/api/jobs/nope/ws") as socket:
            socket.receive_json()


def test_batches_are_listed(client, project, tmp_path):
    import_images(client, project["id"], tmp_path / "src", 2)
    batches = client.get(f"/api/projects/{project['id']}/batches").json()
    assert len(batches) == 1 and batches[0]["added"] == 2


# ---- listing, filters, tags, splits -----------------------------------------------------


def test_pagination_and_page_size_cap(client, config, project, tmp_path):
    import_images(client, project["id"], tmp_path / "src", 5)
    url = f"/api/projects/{project['id']}/images"
    first = client.get(url, params={"limit": 2}).json()
    second = client.get(url, params={"limit": 2, "offset": 2}).json()
    assert first["total"] == 5 and len(first["items"]) == 2
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in second["items"]})
    huge = client.get(url, params={"limit": 100000}).json()
    assert huge["limit"] == config["gallery"]["max_page_size"]
    assert client.get(url, params={"limit": 0}).status_code == 422
    assert client.get(url, params={"offset": -1}).status_code == 422


def test_tags_filter_and_validation(client, project, tmp_path):
    import_images(client, project["id"], tmp_path / "src", 3)
    items = client.get(f"/api/projects/{project['id']}/images").json()["items"]
    first = items[0]["id"]
    put = client.put(f"/api/images/{first}/tags", json={"tags": [" Night ", "night", "Rain"]})
    assert put.json() == {"tags": ["night", "rain"]}
    url = f"/api/projects/{project['id']}/images"
    assert client.get(url, params={"tag": "NIGHT"}).json()["total"] == 1
    assert client.get(url).json()["items"][0]["tags"] == ["night", "rain"]
    assert client.get(f"/api/projects/{project['id']}/tags").json() == [
        {"tag": "night", "count": 1},
        {"tag": "rain", "count": 1},
    ]
    tags_url = f"/api/images/{first}/tags"
    assert client.put(tags_url, json={"tags": ["a", ""]}).status_code == 400
    assert client.put(tags_url, json={"tags": ["x" * 41]}).status_code == 400
    too_many = [f"t{i}" for i in range(21)]
    assert client.put(tags_url, json={"tags": too_many}).status_code == 400
    assert client.put("/api/images/9999/tags", json={"tags": []}).status_code == 404
    assert client.put(tags_url, json={"tags": []}).json() == {"tags": []}


def test_name_search_treats_wildcards_literally(client, project, tmp_path):
    folder = tmp_path / "src"
    make_image(folder / "100%_real.png", color=(1, 1, 1))
    make_image(folder / "other.png", color=(2, 2, 2))
    started = client.post(f"/api/projects/{project['id']}/imports", json={"path": str(folder)})
    wait_for_job(client, started.json()["job_id"])
    url = f"/api/projects/{project['id']}/images"
    assert client.get(url, params={"q": "%"}).json()["total"] == 1
    assert client.get(url, params={"q": "OTHER"}).json()["total"] == 1


def test_manual_and_automatic_splits(client, project, tmp_path):
    import_images(client, project["id"], tmp_path / "src", 10)
    url = f"/api/projects/{project['id']}/images"
    split_url = f"/api/projects/{project['id']}/split"
    ids = [i["id"] for i in client.get(url).json()["items"]]

    manual = client.put(split_url, json={"image_ids": ids[:2], "split": "test"})
    assert manual.json() == {"changed": 2}
    assert client.get(url, params={"split": "test"}).json()["total"] == 2
    assert client.get(url, params={"split": "unassigned"}).json()["total"] == 8
    assert client.get(url, params={"split": "bogus"}).status_code == 400
    bad = client.put(split_url, json={"image_ids": ids, "split": "dev"})
    assert bad.status_code == 400

    auto = client.post(f"{split_url}/auto", json={"seed": 3})
    assert auto.status_code == 200
    # only the 8 unassigned were touched; the 2 manual "test" images stayed
    assert sum(auto.json()["assigned"].values()) == 8
    assert client.get(url, params={"split": "unassigned"}).json()["total"] == 0
    counts = auto.json()["split_counts"]
    assert counts["test"] >= 2 and sum(v for k, v in counts.items() if k != "unassigned") == 10

    again = client.post(
        f"{split_url}/auto",
        json={"only_unassigned": False, "seed": 3, "ratios": {"train": 1.0}},
    )
    assert again.json()["split_counts"]["train"] == 10
    cleared = client.put(split_url, json={"image_ids": ids, "split": None})
    assert cleared.json() == {"changed": 10}


def test_invalid_auto_split_ratios(client, project):
    response = client.post(
        f"/api/projects/{project['id']}/split/auto", json={"ratios": {"train": 0.5}}
    )
    assert response.status_code == 400 and "sum to 1" in response.json()["detail"]


def test_batch_filter(client, project, tmp_path):
    import_images(client, project["id"], tmp_path / "a", 2)
    import_images(client, project["id"], tmp_path / "b", 3, start=50)
    batches = client.get(f"/api/projects/{project['id']}/batches").json()
    newest = batches[0]["id"]
    url = f"/api/projects/{project['id']}/images"
    assert client.get(url, params={"batch_id": newest}).json()["total"] == 3
