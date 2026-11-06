"""Shared fixtures: an isolated config/data dir, a migrated database, and image builders."""

import copy
from pathlib import Path

import pytest
from PIL import Image

from studio import db
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
