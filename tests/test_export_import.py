"""Export a project as COCO / YOLO, import the zip into a fresh project, compare (Stage 3.1)."""

import io
import json
import zipfile

import pytest
from conftest import make_image, wait_for_job
from test_annotations_api import make_class, save

SKELETON = {"names": ["head", "neck", "tail"], "edges": [[0, 1], [1, 2]]}
BOX = {"x": 20, "y": 10, "w": 60, "h": 40}
POLY = {"points": [[10, 10], [110, 10], [60, 90]]}
POSE = {"points": [[40, 20, 2], [0, 0, 0], [100, 60, 1]]}


def build_project(client, tmp_path, name="Source", skeleton=True):
    """3 labelled images (box+polygon, pose, "no objects") and 1 unlabelled one."""
    folder = tmp_path / f"{name}_images"
    folder.mkdir()
    for i in range(4):
        make_image(folder / f"img{i}.jpg", (200, 100), (40 * i + 10, 30, 30))
    project = client.post("/api/projects", json={"name": name}).json()
    job = client.post(f"/api/projects/{project['id']}/imports", json={"path": str(folder)}).json()
    assert wait_for_job(client, job["job_id"])["state"] == "done"
    car = make_class(client, project["id"], "car").json()["id"]
    body = {"name": "cat", **({"skeleton": SKELETON} if skeleton else {})}
    cat = client.post(f"/api/projects/{project['id']}/classes", json=body).json()["id"]
    items = client.get(f"/api/projects/{project['id']}/images?limit=10").json()["items"]
    by_name = {i["original_name"]: i["id"] for i in items}
    save(
        client,
        by_name["img0.jpg"],
        0,
        [
            {"class_id": car, "kind": "box", "data": BOX},
            {"class_id": car, "kind": "polygon", "data": POLY},
        ],
    )
    save(client, by_name["img1.jpg"], 0, [{"class_id": cat, "kind": "keypoints", "data": POSE}])
    save(client, by_name["img2.jpg"], 0, [], empty=True)
    return project, by_name, car, cat


def fresh_project_with_same_images(client, tmp_path):
    n = len(list(tmp_path.glob("Target*_images")))
    folder = tmp_path / f"Target{n}_images"
    folder.mkdir()
    for i in range(4):
        make_image(folder / f"img{i}.jpg", (200, 100), (40 * i + 10, 30, 30))
    project = client.post("/api/projects", json={"name": f"Target{n}"}).json()
    job = client.post(f"/api/projects/{project['id']}/imports", json={"path": str(folder)}).json()
    assert wait_for_job(client, job["job_id"])["state"] == "done"
    items = client.get(f"/api/projects/{project['id']}/images?limit=10").json()["items"]
    return project, {i["original_name"]: i["id"] for i in items}


def stored(client, image_id):
    got = client.get(f"/api/images/{image_id}/annotations").json()
    return got["annotations"], got["marked_empty"]


def kinds_and_data(annotations):
    return sorted((a["kind"], json.dumps(a["data"], sort_keys=True)) for a in annotations)


def download(client, project_id, **params):
    response = client.get(f"/api/projects/{project_id}/export", params=params)
    assert response.status_code == 200, response.text
    return zipfile.ZipFile(io.BytesIO(response.content))


def approx(a, b, tolerance=0.02):
    return abs(a - b) <= tolerance


# ---- export contents ----


def test_coco_export_layout_and_report(client, tmp_path):
    project, names, car, cat = build_project(client, tmp_path)
    archive = download(client, project["id"], format="coco")
    members = set(archive.namelist())
    assert "annotations/instances_train.json" in members and "export_report.json" in members
    assert {"images/train/img0.jpg", "images/train/img1.jpg", "images/train/img2.jpg"} <= members
    assert "images/train/img3.jpg" not in members  # unlabelled images are not exported
    document = json.loads(archive.read("annotations/instances_train.json"))
    assert len(document["images"]) == 3 and len(document["annotations"]) == 3
    report = json.loads(archive.read("export_report.json"))
    assert report["excluded_unlabelled"] == 1 and report["splits"] == {"train": 3}


def test_export_without_images_and_preview(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    archive = download(client, project["id"], format="coco", images="false")
    assert not [n for n in archive.namelist() if n.startswith("images/")]
    preview = client.get(
        f"/api/projects/{project['id']}/export/preview", params={"format": "yolo", "task": "detect"}
    )
    assert preview.status_code == 200
    assert (
        preview.json()["skipped_annotations"] == 2
    )  # the polygon and the pose are not detect rows


def test_yolo_export_layout(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    archive = download(client, project["id"], format="yolo", task="segment")
    members = set(archive.namelist())
    assert {"data.yaml", "labels/train/img0.txt", "images/train/img0.jpg"} <= members
    assert archive.read("labels/train/img2.txt") == b""  # "no objects" -> empty label file
    assert len(archive.read("labels/train/img0.txt").decode().splitlines()) == 2  # polygon + box


def test_yolo_pose_needs_one_point_count_and_errors_are_readable(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    ok = client.get(
        f"/api/projects/{project['id']}/export", params={"format": "yolo", "task": "pose"}
    )
    assert ok.status_code == 200
    client.post(
        f"/api/projects/{project['id']}/classes",
        json={"name": "dog", "skeleton": {"names": ["a", "b"], "edges": []}},
    )
    bad = client.get(
        f"/api/projects/{project['id']}/export", params={"format": "yolo", "task": "pose"}
    )
    assert bad.status_code == 400 and "same number of points" in bad.json()["detail"]
    assert (
        client.get(f"/api/projects/{project['id']}/export", params={"format": "nope"}).status_code
        == 400
    )
    assert (
        client.get(
            f"/api/projects/{project['id']}/export", params={"format": "yolo", "task": "x"}
        ).status_code
        == 400
    )


def test_splits_are_respected_and_unassigned_are_reported(client, tmp_path):
    project, names, *_ = build_project(client, tmp_path)
    from studio import db, repo

    conn = db.connect(client.app.state.db_path)
    try:
        repo.set_split(conn, project["id"], [names["img0.jpg"]], "val")
        repo.set_split(conn, project["id"], [names["img1.jpg"]], "train")
    finally:
        conn.close()
    archive = download(client, project["id"], format="coco")
    members = set(archive.namelist())
    assert (
        "annotations/instances_val.json" in members
        and "annotations/instances_train.json" in members
    )
    report = json.loads(archive.read("export_report.json"))
    assert report["excluded_unassigned"] == 1  # img2 is labelled ("no objects") but has no split


# ---- round trips ----


def unpack(archive, tmp_path, name):
    target = tmp_path / name
    archive.extractall(target)
    return target


def test_coco_round_trip(client, tmp_path):
    source, names, *_ = build_project(client, tmp_path)
    folder = unpack(download(client, source["id"], format="coco"), tmp_path, "coco_out")
    target, tnames = fresh_project_with_same_images(client, tmp_path)
    response = client.post(
        f"/api/projects/{target['id']}/label-imports", json={"path": str(folder)}
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["format"] == "coco" and report["annotations_imported"] == 3
    assert sorted(report["classes_created"]) == ["car", "cat"] and report["unmatched_images"] == []
    for name in ("img0.jpg", "img1.jpg"):
        assert kinds_and_data(stored(client, tnames[name])[0]) == kinds_and_data(
            stored(client, names[name])[0]
        )
    classes = {c["name"]: c for c in client.get(f"/api/projects/{target['id']}/classes").json()}
    assert classes["cat"]["skeleton"] == SKELETON  # names and edges survive the trip
    assert stored(client, tnames["img3.jpg"]) == ([], False)


def test_yolo_round_trip_segment_and_pose(client, tmp_path):
    source, names, *_ = build_project(client, tmp_path)
    for task, image, kind in (
        ("segment", "img0.jpg", "polygon"),
        ("pose", "img1.jpg", "keypoints"),
    ):
        folder = unpack(
            download(client, source["id"], format="yolo", task=task), tmp_path, f"yolo_{task}"
        )
        target, tnames = fresh_project_with_same_images(client, tmp_path)
        response = client.post(
            f"/api/projects/{target['id']}/label-imports", json={"path": str(folder)}
        )
        assert response.status_code == 200, response.text
        got = [a for a in stored(client, tnames[image])[0] if a["kind"] == kind]
        want = [a for a in stored(client, names[image])[0] if a["kind"] == kind]
        assert len(want) == 1
        if task == "segment":
            assert (
                len(got) == 2
            )  # the polygon, plus the box which YOLO segment writes as a rectangle
        else:
            assert len(got) == 1
        match = min(
            got,
            key=lambda g: sum(
                abs(a[0] - b[0]) + abs(a[1] - b[1])
                for a, b in zip(g["data"]["points"], want[0]["data"]["points"], strict=False)
            ),
        )
        for g, w in zip(match["data"]["points"], want[0]["data"]["points"], strict=True):
            assert g[2:] == w[2:] and approx(g[0], w[0]) and approx(g[1], w[1])
        if task == "segment":
            assert stored(client, tnames["img2.jpg"])[1] is True  # empty label file -> "no objects"


def test_yolo_detect_round_trip_boxes(client, tmp_path):
    source, names, *_ = build_project(client, tmp_path)
    folder = unpack(
        download(client, source["id"], format="yolo", task="detect"), tmp_path, "yolo_det"
    )
    target, tnames = fresh_project_with_same_images(client, tmp_path)
    client.post(f"/api/projects/{target['id']}/label-imports", json={"path": str(folder)})
    (box,) = stored(client, tnames["img0.jpg"])[0]
    assert box["kind"] == "box" and all(approx(box["data"][k], BOX[k]) for k in "xywh")


def test_import_from_a_zip_and_a_second_import_replaces_not_duplicates(client, tmp_path):
    source, names, *_ = build_project(client, tmp_path)
    response = client.get(f"/api/projects/{source['id']}/export", params={"format": "coco"})
    archive = tmp_path / "labels.zip"
    archive.write_bytes(response.content)
    target, tnames = fresh_project_with_same_images(client, tmp_path)
    for _ in range(2):
        out = client.post(
            f"/api/projects/{target['id']}/label-imports", json={"path": str(archive)}
        )
        assert out.status_code == 200, out.text
    assert len(stored(client, tnames["img0.jpg"])[0]) == 2  # still 2, not 4


# ---- bad input is explained ----


def test_unmatched_images_bad_sizes_and_empty_sources_are_reported(client, tmp_path):
    target, tnames = fresh_project_with_same_images(client, tmp_path)
    folder = tmp_path / "hand_made"
    folder.mkdir()
    document = {
        "images": [
            {"id": 1, "file_name": "img0.jpg", "width": 999, "height": 100},
            {"id": 2, "file_name": "ghost.jpg", "width": 200, "height": 100},
            {"id": 3, "file_name": "img1.jpg", "width": 200, "height": 100},
        ],
        "categories": [{"id": 1, "name": "thing"}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10]},
            {"id": 2, "image_id": 3, "category_id": 1, "bbox": [-5, 5, 400, 50]},
            {"id": 3, "image_id": 3, "category_id": 9, "bbox": [0, 0, 10, 10]},
        ],
    }
    (folder / "labels.json").write_text(json.dumps(document))
    report = client.post(
        f"/api/projects/{target['id']}/label-imports", json={"path": str(folder)}
    ).json()
    assert report["unmatched_images"] == ["ghost.jpg"]
    assert any("999x100" in s for s in report["skipped"])
    assert any("unknown category 9" in s for s in report["skipped"])
    (box,) = stored(client, tnames["img1.jpg"])[0]
    assert box["data"] == {"x": 0, "y": 5, "w": 200, "h": 50}  # overshoot pulled back to the image
    assert stored(client, tnames["img0.jpg"]) == ([], False)  # wrong size: left alone

    empty = tmp_path / "nothing"
    empty.mkdir()
    refused = client.post(f"/api/projects/{target['id']}/label-imports", json={"path": str(empty)})
    assert refused.status_code == 400 and "Found no COCO" in refused.json()["detail"]
    missing = client.post(
        f"/api/projects/{target['id']}/label-imports", json={"path": str(tmp_path / "zz")}
    )
    assert missing.status_code == 400


def test_export_of_a_project_without_labels_or_classes(client, tmp_path):
    project = client.post("/api/projects", json={"name": "Blank"}).json()
    response = client.get(f"/api/projects/{project['id']}/export", params={"format": "coco"})
    assert response.status_code == 400 and "no classes" in response.json()["detail"]
    make_class(client, project["id"], "car")
    response = client.get(f"/api/projects/{project['id']}/export", params={"format": "coco"})
    assert response.status_code == 400 and "No labelled images" in response.json()["detail"]


@pytest.mark.parametrize("fmt", ["coco", "yolo"])
def test_no_temp_files_are_left_behind(client, tmp_path, fmt):
    project, *_ = build_project(client, tmp_path, name=f"Tidy{fmt}")
    download(client, project["id"], format=fmt)
    leftovers = list((tmp_path / "data" / "tmp").glob("export_*.zip"))
    assert leftovers == []
