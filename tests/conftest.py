"""Shared fixtures: an isolated config/data dir, a migrated database, and image builders."""

import copy
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from studio import db
from studio.api.app import create_app
from studio.config import load_config


@pytest.fixture
def config(tmp_path):
    cfg = copy.deepcopy(load_config())
    cfg["app"]["data_dir"] = str(tmp_path / "data")
    return cfg


@pytest.fixture
def conn(config):
    connection = db.connect(":memory:")
    db.migrate(connection)
    connection.execute("INSERT INTO projects (id, name, created_at) VALUES (1, 'demo', 'now')")
    connection.commit()
    yield connection
    connection.close()


@pytest.fixture
def client(config):
    app = create_app(config, allowed_hosts=["testserver"])
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Demo"}).json()


def seed_images(
    client, project_id: int, count: int, width: int = 200, height: int = 100
) -> list[int]:
    """Insert image rows directly (no files): fast set-up for annotation/API tests."""
    conn = db.connect(client.app.state.db_path)
    try:
        batch = conn.execute(
            "INSERT INTO batches (project_id, source, created_at) VALUES (?, 'seed', 'now')",
            (project_id,),
        ).lastrowid
        ids = []
        for i in range(count):
            ids.append(
                conn.execute(
                    "INSERT INTO images (project_id, batch_id, sha256, stored_name, original_name,"
                    " width, height, bytes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'now')",
                    (project_id, batch, f"seed{project_id}_{i}", f"seed{i}.png", f"seed{i}.png",
                     width, height),
                ).lastrowid
            )
        conn.commit()
        return ids
    finally:
        conn.close()


def wait_for_job(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def make_image(
    path: Path,
    size: tuple[int, int] = (40, 30),
    color: tuple[int, int, int] = (200, 30, 30),
    mode: str = "RGB",
    orientation: int | None = None,
) -> Path:
    """Write a small test image; ``color`` varies content so hashes differ."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new(mode, size, color if mode == "RGB" else None)
    if mode == "RGBA":
        image = Image.new("RGBA", size, (*color, 128))
    kwargs = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        kwargs["exif"] = exif
    image.save(path, **kwargs)
    return path
