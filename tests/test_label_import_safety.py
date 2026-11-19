"""Label import must never lose good labels to a bad file (Stage 3 review findings 1-8)."""

import json

import pytest
from test_export_import import build_project, fresh_project_with_same_images, kinds_and_data, stored

from studio.formats import cvat, labelstudio


def run_import(client, project_id, folder):
    response = client.post(f"/api/projects/{project_id}/label-imports", json={"path": str(folder)})
    assert response.status_code == 200 or response.status_code in (201, 202), response.text
    return response.json()


def coco_doc(*boxes, name="img0.jpg", size=(200, 100)):
    return {
        "images": [{"id": 1, "file_name": name, "width": size[0], "height": size[1]}],
        "categories": [{"id": 1, "name": "car"}],
        "annotations": [
            {"id": n, "image_id": 1, "category_id": 1, "bbox": list(b), "iscrowd": 0}
            for n, b in enumerate(boxes, 1)
        ],
    }


def yolo_folder(tmp_path, files, name="y"):
    root = tmp_path / name
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_yolo_file_with_only_invalid_rows_keeps_existing_labels(client, tmp_path):
    project, names, *_ = build_project(client, tmp_path)
    before = kinds_and_data(stored(client, names["img0.jpg"])[0])
    assert len(before) == 2
    root = yolo_folder(
        tmp_path,
        {"data.yaml": "names: [car]\n", "labels/img0.txt": "0 0.5 0.5 0 0\n0 abc\n"},
    )
    report = run_import(client, project["id"], root)
    assert report["matched_images"] == 0 and report["annotations_imported"] == 0
    assert "left as they are" in " ".join(report["skipped"])
    annotations, marked_empty = stored(client, names["img0.jpg"])
    assert kinds_and_data(annotations) == before and not marked_empty


def test_coco_box_that_clamps_to_nothing_keeps_existing_labels(client, tmp_path):
    project, names, *_ = build_project(client, tmp_path)
    before = kinds_and_data(stored(client, names["img0.jpg"])[0])
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "a.json").write_text(json.dumps(coco_doc([500, 500, 10, 10])))
    report = run_import(client, project["id"], folder)
    assert report["annotations_imported"] == 0
    assert kinds_and_data(stored(client, names["img0.jpg"])[0]) == before


def test_blank_yolo_file_still_means_no_objects(client, tmp_path):
    project, names, *_ = build_project(client, tmp_path)
    root = yolo_folder(tmp_path, {"data.yaml": "names: [car]\n", "labels/img0.txt": ""})
    report = run_import(client, project["id"], root)
    assert report["matched_images"] == 1
    annotations, marked_empty = stored(client, names["img0.jpg"])
    assert annotations == [] and marked_empty


def test_same_yolo_stem_in_two_splits_keeps_the_first_and_says_so(client, tmp_path):
    project, names = fresh_project_with_same_images(client, tmp_path)
    root = yolo_folder(
        tmp_path,
        {
            "data.yaml": "names: [car]\n",
            "labels/train/img3.txt": "0 0.5 0.5 0.2 0.2\n",
            "labels/val/img3.txt": "",
        },
    )
    report = run_import(client, project["id"], root)
    assert "also in" in " ".join(report["skipped"])
    annotations, marked_empty = stored(client, names["img3.jpg"])
    assert len(annotations) == 1 and not marked_empty


def test_image_in_two_coco_files_is_not_doubled(client, tmp_path):
    project, names = fresh_project_with_same_images(client, tmp_path)
    folder = tmp_path / "two"
    folder.mkdir()
    for name in ("a.json", "b.json"):
        (folder / name).write_text(json.dumps(coco_doc([20, 10, 60, 40], [10, 10, 30, 30])))
    report = run_import(client, project["id"], folder)
    assert len(stored(client, names["img0.jpg"])[0]) == 2
    assert report["annotations_imported"] == 2
    assert "also in a.json" in " ".join(report["skipped"])


def test_mixed_formats_in_one_source_report_what_was_ignored(client, tmp_path):
    project, names = fresh_project_with_same_images(client, tmp_path)
    root = yolo_folder(
        tmp_path,
        {"data.yaml": "names: [car]\n", "labels/img1.txt": "0 0.5 0.5 0.2 0.2\n"},
        name="mixed",
    )
    (root / "a.json").write_text(json.dumps(coco_doc([20, 10, 60, 40])))
    report = run_import(client, project["id"], root)
    assert report["format"] == "coco"
    assert "YOLO label file(s) were ignored" in " ".join(report["skipped"])
    assert stored(client, names["img1.jpg"])[0] == []


def test_odd_yaml_names_key_does_not_crash(client, tmp_path):
    project, names = fresh_project_with_same_images(client, tmp_path)
    root = yolo_folder(
        tmp_path,
        {"data.yaml": "names: {a: x}\n", "labels/img0.txt": "0 0.5 0.5 0.2 0.2\n"},
    )
    report = run_import(client, project["id"], root)
    assert report["annotations_imported"] == 1


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le"])
def test_cvat_refuses_entities_in_any_encoding(encoding):
    text = '<!DOCTYPE a [<!ENTITY x "y">]><annotations/>'
    raw = text.encode(encoding)
    if encoding == "utf-16-le":
        raw = b'<?xml version="1.0" encoding="utf-16"?>'.decode().encode(encoding) + raw
    with pytest.raises(cvat.CvatError, match="entities|valid XML"):
        cvat.parse(raw)


def test_cvat_plain_utf16_document_without_doctype_still_parses():
    xml = '<annotations><image id="0" name="a.jpg" width="5" height="5"/></annotations>'
    assert cvat.parse(xml.encode("utf-16"))["images"][0]["file_name"] == "a.jpg"


def test_labelstudio_picks_the_image_field_not_the_first_string():
    tasks = [
        {
            "data": {"text": "a caption", "image": "x.jpg"},
            "annotations": [{"result": []}],
        },
        {"data": {"note": "hello", "pic": "y.PNG?x=1"}, "annotations": [{"result": []}]},
    ]
    names = [i["file_name"] for i in labelstudio.parse(tasks)["images"]]
    assert names == ["x.jpg", "y.PNG?x=1"]
