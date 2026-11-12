"""COCO and YOLO conversion: golden values and round trips (pure functions, no files)."""

import pytest

from studio.formats import coco, yolo

W, H = 200, 100
BOX = {"kind": "box", "class_id": 1, "data": {"x": 20, "y": 10, "w": 60, "h": 40}}
POLY = {"kind": "polygon", "class_id": 1, "data": {"points": [[10, 10], [110, 10], [60, 90]]}}
POSE = {"kind": "keypoints", "class_id": 2,
        "data": {"points": [[40, 20, 2], [0, 0, 0], [100, 60, 1]]}}
CLASSES = [
    {"id": 1, "name": "car", "skeleton": None},
    {"id": 2, "name": "cat",
     "skeleton": {"names": ["head", "neck", "tail"], "edges": [[0, 1], [1, 2]]}},
]


def doc(*items):
    return coco.build([{"id": 7, "file_name": "a.jpg", "width": W, "height": H,
                        "annotations": list(items)}], CLASSES)


# ---- COCO ----------------------------------------------------------------------------------------


def test_coco_golden_box():
    out = doc(BOX)
    ann = out["annotations"][0]
    assert ann["bbox"] == [20, 10, 60, 40] and ann["area"] == 2400 and ann["iscrowd"] == 0
    assert ann["category_id"] == 1 and ann["image_id"] == 7 and ann["segmentation"] == []
    assert out["images"] == [{"id": 7, "file_name": "a.jpg", "width": W, "height": H}]


def test_coco_golden_polygon_and_keypoints():
    out = doc(POLY, POSE)
    poly, pose = out["annotations"]
    assert poly["segmentation"] == [[10, 10, 110, 10, 60, 90]]
    assert poly["bbox"] == [10, 10, 100, 80] and poly["area"] == 4000
    assert pose["keypoints"] == [40, 20, 2, 0, 0, 0, 100, 60, 1] and pose["num_keypoints"] == 2
    assert pose["bbox"] == [40, 20, 60, 40]
    cat = out["categories"][1]
    assert cat["keypoints"] == ["head", "neck", "tail"]
    assert cat["skeleton"] == [[1, 2], [2, 3]]  # COCO edges are 1-based
    assert "keypoints" not in out["categories"][0]


def test_coco_round_trip_is_lossless_for_every_kind():
    parsed = coco.parse(doc(BOX, POLY, POSE))
    got = parsed["images"][0]["annotations"]
    assert [a["kind"] for a in got] == ["box", "polygon", "keypoints"]
    assert got[0]["data"] == BOX["data"]
    assert got[1]["data"] == POLY["data"]
    assert got[2]["data"] == POSE["data"]
    assert parsed["categories"][2] == {"name": "cat", "skeleton": CLASSES[1]["skeleton"]}
    assert parsed["skipped"] == []


def test_coco_multipart_polygons_become_separate_polygons_and_rle_is_reported():
    document = {
        "images": [{"id": 1, "file_name": "x.jpg", "width": 10, "height": 10}],
        "categories": [{"id": 5, "name": "thing"}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 5, "iscrowd": 0,
             "segmentation": [[0, 0, 4, 0, 4, 4], [5, 5, 9, 5, 9, 9]]},
            {"id": 2, "image_id": 1, "category_id": 5, "iscrowd": 1,
             "segmentation": {"counts": [1, 2], "size": [10, 10]}},
            {"id": 3, "image_id": 99, "category_id": 5, "bbox": [0, 0, 1, 1]},
            {"id": 4, "image_id": 1, "category_id": 5},
        ],
    }
    parsed = coco.parse(document)
    assert [a["kind"] for a in parsed["images"][0]["annotations"]] == ["polygon", "polygon"]
    assert len(parsed["skipped"]) == 3
    assert any("RLE" in s for s in parsed["skipped"])


def test_coco_rejects_files_that_are_not_coco():
    with pytest.raises(ValueError, match="no 'images' list"):
        coco.parse({"annotations": []})


# ---- YOLO ----------------------------------------------------------------------------------------

INDEX = {1: 0, 2: 1}


def test_yolo_detect_golden():
    lines, skipped = yolo.export_lines("detect", [BOX, POLY], INDEX, W, H)
    assert lines == ["0 0.25 0.3 0.3 0.4"] and skipped == 1  # the polygon cannot be a detect row


def test_yolo_segment_golden_includes_boxes_as_rectangles():
    lines, skipped = yolo.export_lines("segment", [POLY, BOX], INDEX, W, H)
    assert lines[0] == "0 0.05 0.1 0.55 0.1 0.3 0.9"
    assert lines[1] == "0 0.1 0.1 0.4 0.1 0.4 0.5 0.1 0.5" and skipped == 0


def test_yolo_pose_golden():
    lines, _ = yolo.export_lines("pose", [POSE], INDEX, W, H)
    assert lines == ["1 0.35 0.4 0.3 0.4 0.2 0.2 2 0 0 0 0.5 0.6 1"]


def test_yolo_unknown_class_and_task():
    lines, skipped = yolo.export_lines("detect", [{**BOX, "class_id": 99}], INDEX, W, H)
    assert lines == [] and skipped == 1
    with pytest.raises(ValueError, match="Unknown YOLO task"):
        yolo.export_lines("obb", [BOX], INDEX, W, H)


def close(a, b, tolerance=1e-3):
    return abs(a - b) <= tolerance


@pytest.mark.parametrize("task, item, kpt", [
    ("detect", BOX, None), ("segment", POLY, None), ("pose", POSE, (3, 3)),
])
def test_yolo_round_trip(task, item, kpt):
    lines, _ = yolo.export_lines(task, [item], INDEX, W, H)
    got, problems = yolo.parse_label_text("\n".join(lines), W, H, kpt)
    assert problems == [] and len(got) == 1 and got[0]["kind"] == item["kind"]
    if item["kind"] == "box":
        assert all(close(got[0]["data"][k], item["data"][k], 0.01) for k in "xywh")
    else:
        for a, b in zip(got[0]["data"]["points"], item["data"]["points"], strict=True):
            assert a[2:] == b[2:]
            assert all(close(x, y, 0.01) for x, y in zip(a[:2], b[:2], strict=True))


def test_yolo_parse_reports_bad_lines_and_keeps_good_ones():
    text = "0 0.5 0.5 0.2 0.2\nhello\n-1 0.1 0.1 0.1 0.1\n0 0.1 0.2 0.3\n\n"
    got, problems = yolo.parse_label_text(text, W, H)
    assert len(got) == 1 and len(problems) == 3


def test_yolo_dataset_yaml():
    text = yolo.dataset_yaml(["car", "cat"], ["train", "val"], (3, 3))
    assert "train: images/train" in text and "val: images/val" in text
    assert "kpt_shape:" in text and "0: car" in text and "1: cat" in text
    only_train = yolo.dataset_yaml(["car"], ["train"])
    assert "val: images/train" in only_train and "test" not in only_train
