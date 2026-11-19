"""Read our exports with code we did not write (Stage 3 verification, FORMATS.md §7).

COCO is read by ``pycocotools`` (the reference loader); YOLO by a few lines that follow the
Ultralytics docs and share nothing with ``studio.formats.yolo``. Skips when pycocotools is absent.
"""


import pytest
import yaml
from test_export_import import build_project, download

pycocotools = pytest.importorskip("pycocotools.coco")


def _coco(tmp_path, archive, name="instances_train.json"):
    path = tmp_path / name
    path.write_bytes(archive.read(f"annotations/{name}"))
    return pycocotools.COCO(str(path))


def test_pycocotools_reads_our_coco_export(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    coco = _coco(tmp_path, download(client, project["id"], format="coco"))
    assert sorted(c["name"] for c in coco.loadCats(coco.getCatIds())) == ["car", "cat"]
    assert len(coco.getImgIds()) == 3
    polys = [
        a
        for a in coco.dataset["annotations"]
        if isinstance(a["segmentation"], list) and a["segmentation"]
    ]
    assert polys, "expected a polygon annotation"
    mask = coco.annToMask(polys[0])  # reference rasteriser must accept our polygon
    assert mask.shape == (100, 200) and mask.sum() > 0
    # polygon (110-10)*(90-10)/2 = 4000 px
    assert abs(float(mask.sum()) - 4000) < 150
    keypoint_anns = [a for a in coco.dataset["annotations"] if a.get("keypoints")]
    assert len(keypoint_anns) == 1
    kp = keypoint_anns[0]["keypoints"]
    assert len(kp) == 9 and kp[2] == 2 and kp[5] == 0 and kp[8] == 1
    cat = coco.loadCats(keypoint_anns[0]["category_id"])[0]
    assert cat["keypoints"] == ["head", "neck", "tail"] and cat["skeleton"] == [[1, 2], [2, 3]]
    for a in coco.dataset["annotations"]:
        x, y, w, h = a["bbox"]
        assert w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= 200.01 and y + h <= 100.01


def test_coco_bbox_area_matches_reference_for_box(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    coco = _coco(tmp_path, download(client, project["id"], format="coco"))
    boxes = [a for a in coco.dataset["annotations"] if a["bbox"] == [20, 10, 60, 40]]
    assert boxes and abs(boxes[0]["area"] - 2400) < 1


def _parse_yolo_rows(text):
    return [[float(v) for v in line.split()] for line in text.splitlines() if line.strip()]


def test_yolo_detect_export_matches_ultralytics_docs(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    archive = download(client, project["id"], format="yolo", task="detect")
    cfg = yaml.safe_load(archive.read("data.yaml"))
    assert cfg["names"] and "train" in cfg
    rows = _parse_yolo_rows(archive.read("labels/train/img0.txt").decode())
    assert len(rows) == 1 and len(rows[0]) == 5
    cls, xc, yc, w, h = rows[0]
    assert cls == 0 and all(0 <= v <= 1 for v in (xc, yc, w, h))
    assert (xc * 200, yc * 100, w * 200, h * 100) == pytest.approx((50, 30, 60, 40), abs=0.1)


def test_yolo_segment_and_pose_rows(client, tmp_path):
    project, *_ = build_project(client, tmp_path)
    seg = download(client, project["id"], format="yolo", task="segment")
    for row in _parse_yolo_rows(seg.read("labels/train/img0.txt").decode()):
        assert (len(row) - 1) % 2 == 0 and (len(row) - 1) // 2 >= 3
        assert all(0 <= v <= 1 for v in row[1:])
    pose = download(client, project["id"], format="yolo", task="pose")
    cfg = yaml.safe_load(pose.read("data.yaml"))
    n, dims = cfg["kpt_shape"]
    assert (n, dims) == (3, 3)
    row = _parse_yolo_rows(pose.read("labels/train/img1.txt").decode())[0]
    assert len(row) == 1 + 4 + n * dims
    coords = [v for i, v in enumerate(row[5:]) if i % 3 != 2]  # x, y of each point (drop v)
    assert all(0 <= v <= 1 for v in row[1:5] + coords)
    assert [row[5 + 3 * k + 2] for k in range(n)] == [2, 0, 1]


# ---- golden samples (hand-written, third-party shaped) are read by our importer ----

GOLDEN = __import__("pathlib").Path(__file__).parent / "data" / "formats"


def _project_with_images(client, tmp_path):
    from test_export_import import fresh_project_with_same_images

    return fresh_project_with_same_images(client, tmp_path)


def _import(client, project_id, path):
    response = client.post(f"/api/projects/{project_id}/label-imports", json={"path": str(path)})
    assert response.status_code in (200, 201, 202), response.text
    return response.json()


def test_golden_coco_sample_is_imported(client, tmp_path):
    project, names = _project_with_images(client, tmp_path)
    _import(client, project["id"], GOLDEN / "coco")
    got = client.get(f"/api/images/{names['img0.jpg']}/annotations").json()["annotations"]
    kinds = sorted(a["kind"] for a in got)
    assert kinds == ["box", "keypoints", "polygon"]
    pose = next(a for a in got if a["kind"] == "keypoints")
    assert pose["data"]["points"] == [[40, 20, 2], [0, 0, 0], [100, 60, 1]]
    classes = client.get(f"/api/projects/{project['id']}/classes").json()
    cat = next(
        c
        for c in (classes["classes"] if isinstance(classes, dict) else classes)
        if c["name"] == "cat"
    )
    assert cat["skeleton"]["names"] == ["head", "neck", "tail"] and cat["skeleton"]["edges"] == [
        [0, 1],
        [1, 2],
    ]


def test_golden_yolo_sample_is_imported(client, tmp_path):
    project, names = _project_with_images(client, tmp_path)
    _import(client, project["id"], GOLDEN / "yolo")
    got = client.get(f"/api/images/{names['img0.jpg']}/annotations").json()["annotations"]
    assert len(got) == 2 and all(a["kind"] == "box" for a in got)
    first = min(got, key=lambda a: a["data"]["x"])
    assert (
        first["data"]["x"],
        first["data"]["y"],
        first["data"]["w"],
        first["data"]["h"],
    ) == pytest.approx((20, 10, 60, 40), abs=0.05)
