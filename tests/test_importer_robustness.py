"""Importer behaviour under bad input and failures (findings from the v0.1 independent review)."""

import os
import sqlite3
import warnings
import zipfile

import pytest
from conftest import make_image
from PIL import Image

from studio import importer
from studio.importer import import_source


def batch_row(conn, batch_id):
    return conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()


def test_zip_file_and_folder_name_clash_does_not_abort_the_import(conn, config, tmp_path):
    good = make_image(tmp_path / "w" / "ok.png", color=(5, 5, 5))
    archive = tmp_path / "clash.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(good, "ok.png")
        zf.writestr("a", b"i am a file")
        zf.writestr("a/b.png", good.read_bytes())  # needs "a" to be a folder -> clash

    report = import_source(conn, config, 1, archive)

    assert report.added == 1
    assert any("could not extract" in p["reason"] for p in report.problems)
    assert report.corrupt >= 1


def test_duplicate_member_names_in_a_zip_are_reported(conn, config, tmp_path):
    good = make_image(tmp_path / "w" / "ok.png", color=(6, 6, 6))
    other = make_image(tmp_path / "w" / "other.png", color=(7, 7, 7))
    archive = tmp_path / "twice.zip"
    with zipfile.ZipFile(archive, "w") as zf, warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # zipfile warns about duplicate names
        zf.writestr("same.png", good.read_bytes())
        zf.writestr("same.png", other.read_bytes())

    report = import_source(conn, config, 1, archive)

    assert report.added == 1
    assert any("twice" in p["reason"] for p in report.problems)


def test_encrypted_zip_member_is_reported_not_fatal(conn, config, tmp_path, monkeypatch):
    good = make_image(tmp_path / "w" / "ok.png", color=(8, 8, 8))
    archive = tmp_path / "enc.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(good, "ok.png")
        zf.writestr("secret.png", good.read_bytes())

    real_open = zipfile.ZipFile.open

    def fake_open(self, member, *args, **kwargs):
        if getattr(member, "filename", member) == "secret.png":
            raise RuntimeError("File 'secret.png' is encrypted, password required")
        return real_open(self, member, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", fake_open)
    report = import_source(conn, config, 1, archive)
    assert report.added == 1 and report.corrupt == 1


def test_unexpected_error_on_one_file_is_counted_and_the_rest_continue(
    conn, config, tmp_path, monkeypatch
):
    src = tmp_path / "src"
    for i in range(5):
        make_image(src / f"f{i}.png", color=(i, 9, 9))
    real = importer._classify_and_store
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise ZeroDivisionError("odd EXIF")
        return real(*args, **kwargs)

    monkeypatch.setattr(importer, "_classify_and_store", flaky)
    report = import_source(conn, config, 1, src)

    assert (report.added, report.corrupt) == (4, 1)
    assert any("ZeroDivisionError" in p["reason"] for p in report.problems)
    row = batch_row(conn, report.batch_id)  # batch row agrees with what is really stored
    assert row["added"] == 4 == conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]


def test_database_error_aborts_but_batch_keeps_counts_so_far(conn, config, tmp_path, monkeypatch):
    src = tmp_path / "src"
    for i in range(4):
        make_image(src / f"d{i}.png", color=(i, 19, 9))
    real = importer._classify_and_store
    calls = {"n": 0}

    def breaks(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise sqlite3.OperationalError("database is locked")
        return real(*args, **kwargs)

    monkeypatch.setattr(importer, "_classify_and_store", breaks)
    batch_id = None
    with pytest.raises(sqlite3.OperationalError):
        import_source(conn, config, 1, src)
    batch_id = conn.execute("SELECT MAX(id) FROM batches").fetchone()[0]
    stored = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    assert stored == 2 and batch_row(conn, batch_id)["added"] == 2


def test_cancel_stops_cleanly_and_keeps_what_was_imported(conn, config, tmp_path):
    src = tmp_path / "src"
    for i in range(6):
        make_image(src / f"c{i}.png", color=(i, 29, 9))
    seen = {"n": 0}

    def cancelled():
        seen["n"] += 1
        return seen["n"] > 3  # allow three files, then cancel

    report = import_source(conn, config, 1, src, cancelled=cancelled)

    assert report.cancelled is True and report.added == 3
    assert any("cancelled" in p["reason"] for p in report.problems)
    assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 3


def test_symlinked_files_and_folders_are_reported_not_dropped(conn, config, tmp_path):
    src = tmp_path / "src"
    real = make_image(src / "real.png", color=(40, 1, 1))
    outside = tmp_path / "outside"
    make_image(outside / "elsewhere.png", color=(41, 1, 1))
    try:
        os.symlink(real, src / "link.png")
        os.symlink(outside, src / "linked_dir", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account may not create symlinks (Windows needs a privilege)")

    report = import_source(conn, config, 1, src)

    assert report.added == 1  # only the real file; nothing outside the folder was imported
    assert report.unsupported == 2
    assert sum("symbolic link" in p["reason"] for p in report.problems) == 2


def test_thumbnail_settings_come_from_config(conn, config, tmp_path):
    config["images"]["thumbnail_px"] = 32
    src = tmp_path / "src"
    make_image(src / "big.png", size=(400, 300), color=(50, 1, 1))
    import_source(conn, config, 1, src)
    sha = conn.execute("SELECT sha256 FROM images").fetchone()["sha256"]
    from studio import paths

    with Image.open(paths.thumbs_dir(config, 1) / f"{sha}.jpg") as thumb:
        assert max(thumb.size) <= 32


@pytest.mark.skipif(os.name != "nt", reason="junctions exist only on Windows")
def test_windows_junction_is_not_followed_and_is_reported(conn, config, tmp_path):
    import subprocess

    src = tmp_path / "src"
    make_image(src / "real.png", color=(70, 1, 1))
    outside = tmp_path / "outside"
    make_image(outside / "elsewhere.png", color=(71, 1, 1))
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(src / "jct"), str(outside)], capture_output=True
    )
    if made.returncode != 0:
        pytest.skip("could not create a junction here")

    report = import_source(conn, config, 1, src)

    assert report.added == 1  # elsewhere.png is outside the chosen folder and must not be imported
    assert report.unsupported == 1
    assert any("junction" in p["reason"] for p in report.problems)
