import json
import zipfile

import pytest
from conftest import make_image
from PIL import Image

from studio import paths
from studio.importer import ImportFailed, import_source, list_candidate_files, sha256_of


def rows(conn):
    return conn.execute("SELECT * FROM images ORDER BY id").fetchall()


def test_imports_a_folder_and_stores_files_and_thumbnails(conn, config, tmp_path):
    src = tmp_path / "src"
    make_image(src / "a.jpg", color=(1, 2, 3))
    make_image(src / "sub" / "b.png", color=(4, 5, 6))
    make_image(src / "c.webp", color=(7, 8, 9))

    report = import_source(conn, config, 1, src)

    assert (report.added, report.duplicates, report.corrupt, report.oversize) == (3, 0, 0, 0)
    stored = rows(conn)
    assert len(stored) == 3
    for row in stored:
        assert (paths.images_dir(config, 1) / row["stored_name"]).is_file()
        assert (paths.thumbs_dir(config, 1) / f"{row['sha256']}.jpg").is_file()
        assert (row["width"], row["height"]) == (40, 30)
    batch = conn.execute("SELECT * FROM batches WHERE id = ?", (report.batch_id,)).fetchone()
    assert batch["added"] == 3 and batch["source"] == str(src)


def test_duplicates_are_skipped_within_and_across_imports(conn, config, tmp_path):
    src = tmp_path / "src"
    make_image(src / "a.png", color=(9, 9, 9))
    (src / "copy.png").write_bytes((src / "a.png").read_bytes())  # same content, other name

    first = import_source(conn, config, 1, src)
    second = import_source(conn, config, 1, src)

    assert (first.added, first.duplicates) == (1, 1)
    assert (second.added, second.duplicates) == (0, 2)
    assert len(rows(conn)) == 1


def test_same_image_can_exist_in_two_projects(conn, config, tmp_path):
    conn.execute("INSERT INTO projects (id, name, created_at) VALUES (2, 'other', 'now')")
    src = tmp_path / "src"
    make_image(src / "a.png")
    assert import_source(conn, config, 1, src).added == 1
    assert import_source(conn, config, 2, src).added == 1


def test_corrupt_and_unsupported_files_are_reported_not_hidden(conn, config, tmp_path):
    src = tmp_path / "src"
    make_image(src / "ok.png")
    (src / "broken.jpg").write_bytes(b"this is not an image")
    (src / "notes.txt").write_text("hello", encoding="utf-8")

    report = import_source(conn, config, 1, src)

    assert (report.added, report.corrupt, report.unsupported) == (1, 1, 1)
    assert report.problems[0]["path"] == "broken.jpg"
    stored = json.loads(conn.execute("SELECT problems FROM batches").fetchone()["problems"])
    assert stored == report.problems


def test_truncated_image_is_corrupt(conn, config, tmp_path):
    src = tmp_path / "src"
    good = make_image(src / "t.png", size=(200, 200))
    good.write_bytes(good.read_bytes()[:-40])
    assert import_source(conn, config, 1, src).corrupt == 1


def test_oversize_by_bytes_and_by_side(conn, config, tmp_path):
    src = tmp_path / "src"
    make_image(src / "wide.png", size=(100, 10), color=(1, 1, 1))
    make_image(src / "small.png", size=(10, 10), color=(2, 2, 2))
    config["images"]["max_side_px"] = 50
    report = import_source(conn, config, 1, src)
    assert (report.added, report.oversize) == (1, 1)

    config["images"]["max_file_mb"] = 0.000001
    other = tmp_path / "other"
    make_image(other / "x.png", color=(3, 3, 3))
    assert import_source(conn, config, 1, other).oversize == 1


def test_exif_orientation_is_applied_to_stored_dimensions(conn, config, tmp_path):
    src = tmp_path / "src"
    make_image(src / "rot.jpg", size=(40, 30), orientation=6)  # rotate 90: 40x30 displays 30x40
    import_source(conn, config, 1, src)
    row = rows(conn)[0]
    assert (row["width"], row["height"]) == (30, 40)


def test_rgba_and_palette_images_get_thumbnails(conn, config, tmp_path):
    src = tmp_path / "src"
    make_image(src / "alpha.png", mode="RGBA")
    Image.new("P", (20, 20)).save(src / "pal.png")
    report = import_source(conn, config, 1, src)
    assert report.added == 2 and report.corrupt == 0


def test_zip_import(conn, config, tmp_path):
    work = tmp_path / "work"
    make_image(work / "z1.png", color=(11, 0, 0))
    make_image(work / "dir" / "z2.png", color=(12, 0, 0))
    archive = tmp_path / "pics.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(work / "z1.png", "z1.png")
        zf.write(work / "dir" / "z2.png", "dir/z2.png")

    report = import_source(conn, config, 1, archive)

    assert report.added == 2
    assert not any((paths.data_dir(config) / "tmp").iterdir())  # scratch folder cleaned up


def test_zip_slip_member_is_skipped_and_reported(conn, config, tmp_path):
    work = make_image(tmp_path / "work" / "ok.png", color=(21, 0, 0))
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(work, "ok.png")
        zf.writestr("../escaped.png", work.read_bytes())

    report = import_source(conn, config, 1, archive)

    assert report.added == 1
    assert any("unsafe" in p["reason"] for p in report.problems)
    assert not (paths.data_dir(config).parent / "escaped.png").exists()
    assert not (tmp_path / "escaped.png").exists()


def test_zip_that_would_expand_too_much_is_refused(conn, config, tmp_path):
    archive = tmp_path / "big.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.png", b"x" * 2048)
    config["importing"]["max_zip_uncompressed_gb"] = 1e-9
    with pytest.raises(ImportFailed, match="expand"):
        import_source(conn, config, 1, archive)


def test_bad_sources_raise_clear_errors(conn, config, tmp_path):
    with pytest.raises(ImportFailed, match="not found"):
        import_source(conn, config, 1, tmp_path / "missing")
    with pytest.raises(ImportFailed, match="does not exist"):
        import_source(conn, config, 99, tmp_path)
    plain = tmp_path / "file.txt"
    plain.write_text("x", encoding="utf-8")
    with pytest.raises(ImportFailed, match="folder or a .zip"):
        import_source(conn, config, 1, plain)
    fake = tmp_path / "fake.zip"
    fake.write_bytes(b"not a zip")
    with pytest.raises(ImportFailed, match="zip"):
        import_source(conn, config, 1, fake)


def test_progress_callback_reports_final_total(conn, config, tmp_path):
    src = tmp_path / "src"
    for i in range(5):
        make_image(src / f"{i}.png", color=(i, 0, 0))
    config["importing"]["progress_every"] = 2
    calls = []
    import_source(conn, config, 1, src, progress=lambda done, total, r: calls.append((done, total)))
    assert calls[-1] == (5, 5)
    assert [c[0] for c in calls] == sorted(c[0] for c in calls)


def test_problem_list_is_capped_but_counts_stay_exact(conn, config, tmp_path):
    src = tmp_path / "src"
    for i in range(6):
        (src / f"bad{i}.jpg").parent.mkdir(parents=True, exist_ok=True)
        (src / f"bad{i}.jpg").write_bytes(b"junk" + bytes([i]))
    config["importing"]["max_problems_recorded"] = 2
    report = import_source(conn, config, 1, src)
    assert report.corrupt == 6
    assert len(report.problems) == 2 and report.problems_dropped == 4


def test_helpers(tmp_path):
    a = tmp_path / "a.bin"
    a.write_bytes(b"abc")
    assert sha256_of(a) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bin").write_bytes(b"x")
    files, skipped = list_candidate_files(tmp_path)
    assert [p.name for p in files] == ["a.bin", "b.bin"] and skipped == []
