"""CVAT and Label Studio adapters (Stage 3.2): pure converters and export -> import round trips."""

import io
import json
import zipfile

import pytest
from test_export_import import (
    BOX,
    POLY,
    POSE,
    approx,
    build_project,
    download,
    fresh_project_with_same_images,
    kinds_and_data,
    stored,
)

from studio.formats import cvat, labelstudio


def import_zip(client, tmp_path, project_id, archive):
    path = tmp_path / "labels_in.zip"
    path.write_bytes(archive_bytes(archive))
    response = client.post(f"/api/projects/{project_id}/label-imports", json={"path": str(path)})
    assert response.status_code in (200, 201, 202), response.text
    return response.json()


def archive_bytes(archive: zipfile.ZipFile) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        for name in archive.namelist():
            out.writestr(name, archive.read(name))
    return buffer.getvalue()


# ---- pure CVAT ----


def test_cvat_build_and_parse_round_trip():
    images = [
        {
            "file_name": "a.jpg",
            "width": 200,
            "height": 100,
            "annotations": [
                {"class_id": 1, "kind": "box", "data": BOX},
                {"class_id": 1, "kind": "polygon", "data": POLY},
                {"class_id": 2, "kind": "keypoints", "data": POSE},
            ],
        }
    ]
    classes = [{"id": 1, "name": "car & <co>", "color": "#112233"}, {"id": 2, "name": "cat"}]
    xml, skipped = cvat.build(images, classes)
    assert skipped == 1  # the keypoint set
    parsed = cvat.parse(xml)
    got = parsed["images"][0]["annotations"]
    assert [(a["label"], a["kind"]) for a in got] == [
        ("car & <co>", "box"),
        ("car & <co>", "polygon"),
    ]
    assert got[0]["data"] == {"x": 20.0, "y": 10.0, "w": 60.0, "h": 40.0}
    assert got[1]["data"]["points"] == [[10.0, 10.0], [110.0, 10.0], [60.0, 90.0]]


def test_cvat_parse_lists_what_it_cannot_read_and_refuses_entities():
    xml = (
        '<annotations><version>1.1</version><image id="0" name="a.jpg" width="10" height="10">'
        '<box label="x" xtl="0" ytl="0" xbr="5" ybr="5" rotation="30"/>'
        '<points label="x" points="1,1"/><polyline label="x" points="1,1;2,2"/>'
        '<polygon label="x" points="1,1;2,2"/></image></annotations>'
    )
    parsed = cvat.parse(xml)
    assert parsed["images"][0]["annotations"] == []
    text = " ".join(parsed["skipped"])
    assert "rotated" in text and "<points>" in text and "<polyline>" in text and "3 x,y" in text
    with pytest.raises(cvat.CvatError, match="entities"):
        cvat.parse('<!DOCTYPE a [<!ENTITY x "y">]><annotations/>')
    with pytest.raises(cvat.CvatError, match="root"):
        cvat.parse("<other/>")
    with pytest.raises(cvat.CvatError, match="valid XML"):
        cvat.parse("<annotations>")


# ---- pure Label Studio ----


def _ls_images():
    return [
        {
            "file_name": "a.jpg",
            "width": 200,
            "height": 100,
            "annotations": [
                {"class_id": 1, "kind": "box", "data": BOX},
                {"class_id": 1, "kind": "polygon", "data": POLY},
                {"class_id": 2, "kind": "keypoints", "data": POSE},
            ],
        }
    ]


CLASSES = [
    {"id": 1, "name": "car"},
    {"id": 2, "name": "cat", "skeleton": {"names": ["head", "neck", "tail"], "edges": []}},
]


def test_labelstudio_build_uses_percentages_and_parent_ids():
    tasks, notes = labelstudio.build(_ls_images(), CLASSES)
    result = tasks[0]["annotations"][0]["result"]
    box = result[0]["value"]
    assert (box["x"], box["y"], box["width"], box["height"]) == (10.0, 10.0, 30.0, 40.0)
    assert result[0]["original_width"] == 200 and result[0]["original_height"] == 100
    poly = result[1]["value"]["points"]
    assert poly[1] == [55.0, 10.0]
    rect = result[2]
    kids = result[3:]
    assert len(kids) == 2 and all(k["parentID"] == rect["id"] for k in kids)  # v=0 point left out
    assert [k["value"]["keypointlabels"][0] for k in kids] == ["head", "tail"]
    assert any("hidden" in n for n in notes)  # the v=1 point is a known loss
    assert 'KeyPointLabels name="keypoint"' in labelstudio.labeling_config(CLASSES)


def test_labelstudio_parse_round_trip_and_unsupported():
    tasks, _ = labelstudio.build(_ls_images(), CLASSES)
    parsed = labelstudio.parse(tasks)
    got = parsed["images"][0]["annotations"]
    assert [a["kind"] for a in got] == ["box", "polygon", "named_keypoints"]
    assert got[0]["data"] == pytest.approx({"x": 20, "y": 10, "w": 60, "h": 40})
    assert got[2]["data"]["points"][0] == pytest.approx(["head", 40, 20])
    odd = [
        {
            "data": {"image": "a.jpg"},
            "annotations": [
                {
                    "result": [
                        {
                            "id": "1",
                            "type": "rectanglelabels",
                            "original_width": 100,
                            "original_height": 100,
                            "value": {
                                "x": 0,
                                "y": 0,
                                "width": 10,
                                "height": 10,
                                "rotation": 45,
                                "rectanglelabels": ["a"],
                            },
                        },
                        {"id": "2", "type": "brushlabels", "value": {}},
                        {
                            "id": "3",
                            "type": "keypointlabels",
                            "parentID": "zzz",
                            "value": {"x": 1, "y": 1, "width": 1, "keypointlabels": ["p"]},
                        },
                    ]
                }
            ],
        },
        {"data": {"image": "b.jpg"}, "annotations": [{"was_cancelled": True, "result": []}]},
    ]
    parsed = labelstudio.parse(odd)
    text = " ".join(parsed["skipped"])
    assert "rotated" in text and "brushlabels" in text and "without a parent" in text
    assert len(parsed["images"]) == 1  # the cancelled one is ignored
    with pytest.raises(labelstudio.LabelStudioError):
        labelstudio.parse({"not": "a list"})


def test_labelstudio_missing_size_uses_fallback():
    task = [
        {
            "data": {"image": "a.jpg"},
            "annotations": [
                {
                    "result": [
                        {
                            "id": "1",
                            "type": "polygonlabels",
                            "value": {
                                "points": [[0, 0], [50, 0], [50, 50]],
                                "polygonlabels": ["a"],
                            },
                        }
                    ]
                }
            ],
        }
    ]
    assert "percentages" in " ".join(labelstudio.parse(task)["skipped"])
    got = labelstudio.parse(task, lambda name: (200, 100))["images"][0]["annotations"][0]
    assert got["data"]["points"] == [[0, 0], [100, 0], [100, 50]]


# ---- export -> import through the API ----


def test_cvat_round_trip(client, tmp_path):
    project, names, car, cat = build_project(client, tmp_path)
    archive = download(client, project["id"], format="cvat")
    assert {"annotations.xml", "images/img0.jpg", "export_report.json"} <= set(archive.namelist())
    report = json.loads(archive.read("export_report.json"))
    assert report["skipped_annotations"] == 1 and report["annotations"] == 2  # pose not carried
    target, tnames = fresh_project_with_same_images(client, tmp_path)
    result = import_zip(client, tmp_path, target["id"], archive)
    assert result["format"] == "cvat" and result["annotations_imported"] == 2
    src, _ = stored(client, names["img0.jpg"])
    dst, _ = stored(client, tnames["img0.jpg"])
    assert [a["kind"] for a in src] == [a["kind"] for a in dst] == ["box", "polygon"]
    assert kinds_and_data(src) == kinds_and_data(dst)
    assert stored(client, tnames["img1.jpg"])[0] == []  # the pose never travelled


def test_labelstudio_round_trip(client, tmp_path):
    project, names, car, cat = build_project(client, tmp_path)
    archive = download(client, project["id"], format="labelstudio")
    assert {"labelstudio.json", "labeling_config.xml", "images/img1.jpg"} <= set(archive.namelist())
    report = json.loads(archive.read("export_report.json"))
    assert report["annotations"] == 3 and any("hidden" in n for n in report["notes"])
    target, tnames = fresh_project_with_same_images(client, tmp_path)
    result = import_zip(client, tmp_path, target["id"], archive)
    assert result["format"] == "labelstudio" and result["annotations_imported"] == 3
    assert not result["skipped"], result["skipped"]
    src0, _ = stored(client, names["img0.jpg"])
    dst0, _ = stored(client, tnames["img0.jpg"])
    assert kinds_and_data(src0) == kinds_and_data(dst0)
    src1 = stored(client, names["img1.jpg"])[0][0]
    dst1 = stored(client, tnames["img1.jpg"])[0][0]
    assert src1["kind"] == dst1["kind"] == "keypoints"
    placed = [p for p in src1["data"]["points"] if p[2]]  # only labelled points travel
    assert len(dst1["data"]["points"]) == len(placed) == 2
    for a, b in zip(placed, dst1["data"]["points"], strict=True):
        assert approx(a[0], b[0]) and approx(a[1], b[1])
        assert b[2] == 2  # hidden (1) comes back visible (2): documented loss
    classes = client.get(f"/api/projects/{target['id']}/classes").json()
    classes = classes["classes"] if isinstance(classes, dict) else classes
    cat_class = next(c for c in classes if c["name"] == "cat")
    assert cat_class["skeleton"]["names"] == ["head", "tail"]  # only the labelled points travel


def test_labelstudio_upload_prefix_matches_image(client, tmp_path):
    project, names = fresh_project_with_same_images(client, tmp_path)
    task = [
        {
            "data": {"image": "/data/upload/1/1a2b3c4d-img2.jpg"},
            "annotations": [
                {
                    "result": [
                        {
                            "id": "1",
                            "type": "rectanglelabels",
                            "original_width": 200,
                            "original_height": 100,
                            "value": {
                                "x": 10,
                                "y": 10,
                                "width": 50,
                                "height": 50,
                                "rotation": 0,
                                "rectanglelabels": ["thing"],
                            },
                        }
                    ]
                }
            ],
        }
    ]
    folder = tmp_path / "ls"
    folder.mkdir()
    (folder / "export.json").write_text(json.dumps(task))
    response = client.post(
        f"/api/projects/{project['id']}/label-imports", json={"path": str(folder)}
    )
    assert response.status_code in (200, 201, 202), response.text
    assert response.json()["annotations_imported"] == 1
    box = stored(client, names["img2.jpg"])[0][0]
    assert box["data"] == {"x": 20.0, "y": 10.0, "w": 100.0, "h": 50.0}


def test_cvat_size_mismatch_is_skipped(client, tmp_path):
    project, names = fresh_project_with_same_images(client, tmp_path)
    xml = (
        '<annotations><version>1.1</version><image id="0" name="img0.jpg" width="999" height="10">'
        '<box label="x" xtl="0" ytl="0" xbr="5" ybr="5"/></image></annotations>'
    )
    folder = tmp_path / "cv"
    folder.mkdir()
    (folder / "annotations.xml").write_text(xml)
    response = client.post(
        f"/api/projects/{project['id']}/label-imports", json={"path": str(folder)}
    )
    body = response.json()
    assert body["annotations_imported"] == 0 and "size 999x10" in " ".join(body["skipped"])
