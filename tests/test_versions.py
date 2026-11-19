"""Immutable dataset versions (Stage 3.3): snapshots, hash stability, isolation from live edits."""

import io
import json
import random
import sqlite3
import zipfile

import pytest
from test_annotations_api import save
from test_export_import import BOX, build_project, download

from studio import db, paths, versions


def create(client, project_id, **body):
    return client.post(f"/api/projects/{project_id}/versions", json=body)


def db_connection(config):
    connection = sqlite3.connect(paths.db_path(config))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def coco_rows(archive):
    """A COCO export reduced to comparable facts (ids differ between live and frozen data)."""
    document = json.loads(archive.read("annotations/instances_train.json"))
    names = {c["id"]: c["name"] for c in document["categories"]}
    files = {i["id"]: i["file_name"] for i in document["images"]}
    rows = sorted(
        json.dumps(
            [
                files[a["image_id"]],
                names[a["category_id"]],
                a["bbox"],
                a["segmentation"],
                a.get("keypoints"),
            ],
            sort_keys=True,
        )
        for a in document["annotations"]
    )
    return rows, sorted(c["name"] for c in document["categories"])


# ---- creating ----


def test_create_version_freezes_the_labelled_images(client, tmp_path):
    project, names, car, cat = build_project(client, tmp_path)
    response = create(client, project["id"], name="  first   cut ")
    assert response.status_code == 201, response.text
    version = response.json()
    assert version["number"] == 1 and version["name"] == "first cut"
    assert version["image_count"] == 3 and version["annotation_count"] == 3
    assert len(version["content_hash"]) == 64 and version["intact"] is True
    manifest = version["manifest"]
    assert manifest["excluded_unlabelled"] == 1  # img3 has no labels
    assert [c["name"] for c in manifest["classes"]] == ["car", "cat"]
    assert manifest["classes"][1]["skeleton"]["names"] == ["head", "neck", "tail"]
    listed = client.get(f"/api/projects/{project['id']}/versions").json()
    assert [v["number"] for v in listed] == [1] and "manifest" not in listed[0]


def test_identical_state_is_refused_even_with_another_name(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    assert create(client, project["id"], name="a").status_code == 201
    again = create(client, project["id"], name="b")
    assert again.status_code == 409 and again.json()["existing"] == 1
    assert "unchanged since version 1" in again.json()["detail"]
    assert len(client.get(f"/api/projects/{project['id']}/versions").json()) == 1


def test_hash_does_not_depend_on_ids_or_project(client, tmp_path):
    first, *_ = build_project(client, tmp_path, name="A")
    second, *_ = build_project(client, tmp_path, name="B")  # other ids, same images and labels
    a = create(client, first["id"]).json()
    b = create(client, second["id"]).json()
    assert first["id"] != second["id"] and a["id"] != b["id"]
    assert a["content_hash"] == b["content_hash"]


def test_no_labelled_images_and_unknown_project(client, tmp_path):
    empty = client.post("/api/projects", json={"name": "Empty"}).json()
    response = create(client, empty["id"])
    assert response.status_code == 400 and "no labelled images" in response.json()["detail"]
    assert create(client, 9999).status_code == 404


def test_preprocessing_is_recorded_validated_and_hashed(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    plain = create(client, project["id"]).json()
    resized = create(client, project["id"], preprocessing={"resize": 640, "mode": "fit"})
    assert resized.status_code == 201, resized.text
    assert resized.json()["manifest"]["preprocessing"] == {"mode": "fit", "resize": 640}
    assert resized.json()["content_hash"] != plain["content_hash"]
    for bad in ([1, 2], {"x": "y" * 5000}):
        refused = create(client, project["id"], preprocessing=bad)
        assert refused.status_code in (400, 422)
    assert create(client, project["id"], name="n" * 200).status_code == 400


def test_version_limit_comes_from_config(client, config, tmp_path):
    config["versions"]["max_per_project"] = 1
    project, names, car, cat = build_project(client, tmp_path)
    assert create(client, project["id"]).status_code == 201
    save(client, names["img3.jpg"], 0, [{"class_id": car, "kind": "box", "data": BOX}])
    refused = create(client, project["id"])
    assert refused.status_code == 400 and "at most 1" in refused.json()["detail"]


# ---- immutability ----


def test_live_edits_never_change_an_existing_version(client, tmp_path):
    project, names, car, cat = build_project(client, tmp_path)
    live_before = coco_rows(download(client, project["id"], format="coco"))
    v1 = create(client, project["id"]).json()
    # edit everything a user can edit
    save(client, names["img3.jpg"], 0, [{"class_id": car, "kind": "box", "data": BOX}])
    save(client, names["img0.jpg"], 1, [], empty=True)
    client.patch(f"/api/classes/{car}", json={"name": "vehicle"})
    client.delete(f"/api/classes/{cat}", params={"force": "true"})
    live_after = coco_rows(download(client, project["id"], format="coco"))
    assert live_after != live_before
    frozen = client.get(f"/api/versions/{v1['id']}/export", params={"format": "coco"})
    assert frozen.status_code == 200, frozen.text
    assert coco_rows(zipfile.ZipFile(io.BytesIO(frozen.content))) == live_before
    again = client.get(f"/api/versions/{v1['id']}").json()
    assert again["content_hash"] == v1["content_hash"] and again["intact"] is True
    v2 = create(client, project["id"])
    assert v2.status_code == 201 and v2.json()["number"] == 2
    assert v2.json()["content_hash"] != v1["content_hash"]


def test_split_change_makes_a_new_version(client, tmp_path):
    project, names, *_ = build_project(client, tmp_path)
    v1 = create(client, project["id"]).json()
    moved = client.put(
        f"/api/projects/{project['id']}/split",
        json={"image_ids": [names["img0.jpg"]], "split": "val"},
    )
    assert moved.status_code == 200, moved.text
    v2 = create(client, project["id"])
    assert v2.status_code == 201 and v2.json()["content_hash"] != v1["content_hash"]
    assert v2.json()["manifest"]["splits"] == {"val": 1, "unassigned": 2}
    assert v1["manifest"]["splits"] == {"unassigned": 3}


def test_tampering_with_stored_rows_is_detected(client, config, tmp_path):
    project, *_ = build_project(client, tmp_path)
    version = create(client, project["id"]).json()
    with db_connection(config) as connection:
        connection.execute("UPDATE version_images SET width = width + 1 WHERE rowid = 1")
    assert client.get(f"/api/versions/{version['id']}").json()["intact"] is False


def test_version_export_covers_every_format_and_reports_errors(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    version = create(client, project["id"]).json()
    for fmt, task in (
        ("coco", "detect"),
        ("yolo", "segment"),
        ("cvat", "detect"),
        ("labelstudio", "detect"),
    ):
        response = client.get(
            f"/api/versions/{version['id']}/export",
            params={"format": fmt, "task": task, "images": "false"},
        )
        assert response.status_code == 200, (fmt, response.text)
        assert "-v1-" in response.headers["content-disposition"]
        assert zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    preview = client.get(
        f"/api/versions/{version['id']}/export/preview", params={"format": "yolo", "task": "detect"}
    )
    assert preview.status_code == 200 and preview.json()["images"] == 3
    bad = client.get(f"/api/versions/{version['id']}/export", params={"format": "nope"})
    assert bad.status_code == 400
    assert client.get("/api/versions/9999/export").status_code == 404


def test_version_export_includes_the_image_files(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    version = create(client, project["id"]).json()
    response = client.get(f"/api/versions/{version['id']}/export", params={"format": "coco"})
    members = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert {"images/train/img0.jpg", "images/train/img1.jpg", "images/train/img2.jpg"} <= set(
        members
    )


# ---- lifecycle ----


def test_delete_never_reuses_numbers_and_project_delete_removes_versions(client, config, tmp_path):
    project, names, car, cat = build_project(client, tmp_path)
    v1 = create(client, project["id"]).json()
    assert client.delete(f"/api/versions/{v1['id']}").status_code == 204
    assert client.delete(f"/api/versions/{v1['id']}").status_code == 404
    assert client.get(f"/api/versions/{v1['id']}").status_code == 404
    v2 = create(client, project["id"]).json()  # same content as the deleted one: allowed again
    assert v2["number"] == 2  # number 1 is not reused
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    with db_connection(config) as connection:
        assert connection.execute("SELECT COUNT(*) FROM dataset_versions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM version_images").fetchone()[0] == 0


def test_migration_adds_the_version_tables():
    connection = db.connect(":memory:")
    db.migrate(connection)
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"dataset_versions", "version_images"} <= tables
    assert connection.execute("PRAGMA user_version").fetchone()[0] >= 3
    connection.close()


# ---- pure hashing ----


def _sample():
    classes = [{"name": "car", "skeleton": None}, {"name": "cat", "skeleton": None}]
    images = [
        {
            "sha256": f"{n:064x}",
            "original_name": f"{n}.jpg",
            "width": 100,
            "height": 50,
            "split": "train",
            "marked_empty": False,
            "label_class": None,
            "annotations": [
                {"class": "car", "kind": "box", "data": {"x": n, "y": 1, "w": 5, "h": 5}},
                {"class": "cat", "kind": "box", "data": {"x": 2, "y": n, "w": 6, "h": 6}},
            ],
        }
        for n in range(1, 6)
    ]
    return classes, images


def test_hash_ignores_order_but_not_content():
    classes, images = _sample()
    base = versions.content_hash(versions.build_payload(classes, images, {}))
    shuffled = [
        dict(i, annotations=random.Random(n).sample(i["annotations"], 2))
        for n, i in enumerate(images)
    ]
    random.Random(3).shuffle(shuffled)
    assert versions.content_hash(versions.build_payload(classes, shuffled, {})) == base
    moved = json.loads(json.dumps(images))
    moved[2]["annotations"][0]["data"]["x"] += 0.01
    assert versions.content_hash(versions.build_payload(classes, moved, {})) != base
    relabelled = json.loads(json.dumps(images))
    relabelled[0]["split"] = "val"
    assert versions.content_hash(versions.build_payload(classes, relabelled, {})) != base
    reordered = list(reversed(classes))  # class ORDER is content (it fixes YOLO class indices)
    assert versions.content_hash(versions.build_payload(reordered, images, {})) != base


def test_preprocessing_checks():
    assert versions.check_preprocessing(None, 100) == {}
    with pytest.raises(versions.VersionError):
        versions.check_preprocessing({"a": float("nan")}, 100)
    with pytest.raises(versions.VersionError):
        versions.check_preprocessing("resize", 100)
