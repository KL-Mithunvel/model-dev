"""Pure validation of annotations (no database)."""

import math

import pytest

from studio.annotations import AnnotationError, validate_annotation, validate_set

W, H = 200, 100
LIMITS = {
    "max_per_image": 5,
    "max_points": 6,
    "min_box_px": 1,
    "min_polygon_area_px": 1,
    "coord_tolerance_px": 0.5,
}


def box(**data):
    return {"kind": "box", "data": {"x": 10, "y": 20, "w": 30, "h": 40, **data}}


def check(item, skeleton=None):
    return validate_annotation(item, 1, W, H, LIMITS, skeleton)


def test_valid_box_is_rounded_to_two_decimals():
    result = check(box(x=10.123456, w=30.987654))
    assert result == {"kind": "box", "data": {"x": 10.12, "y": 20.0, "w": 30.99, "h": 40.0}}


def test_box_may_touch_the_image_edges():
    assert check(box(x=0, y=0, w=W, h=H))["data"] == {"x": 0, "y": 0, "w": W, "h": H}


def test_tiny_overshoot_is_clamped_but_a_real_overshoot_is_rejected():
    clamped = check(box(x=-0.3, w=W + 0.6))["data"]
    assert clamped["x"] == 0 and clamped["x"] + clamped["w"] == W
    with pytest.raises(AnnotationError, match="outside the image"):
        check(box(x=-5))
    with pytest.raises(AnnotationError, match="right edge"):
        check(box(x=180, w=30))


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, True, "5", None])
def test_non_finite_or_non_numeric_values_are_rejected(bad):
    with pytest.raises(AnnotationError, match="finite number"):
        check(box(x=bad))


def test_box_too_small_and_wrong_fields():
    with pytest.raises(AnnotationError, match="at least 1 px"):
        check(box(w=0.5))
    with pytest.raises(AnnotationError, match="unexpected field"):
        check(box(extra=1))
    with pytest.raises(AnnotationError, match="missing field"):
        check({"kind": "box", "data": {"x": 1, "y": 1, "w": 5}})


def test_unknown_kind_and_non_object_data():
    with pytest.raises(AnnotationError, match="kind must be one of"):
        check({"kind": "circle", "data": {}})
    with pytest.raises(AnnotationError, match="data must be an object"):
        check({"kind": "box", "data": [1, 2]})


def test_polygon_rules():
    ok = {"kind": "polygon", "data": {"points": [[10, 10], [60, 10], [60, 50]]}}
    assert check(ok)["data"]["points"] == [[10, 10], [60, 10], [60, 50]]
    with pytest.raises(AnnotationError, match="at least 3"):
        check({"kind": "polygon", "data": {"points": [[1, 1], [5, 5]]}})
    with pytest.raises(AnnotationError, match="flat"):
        check({"kind": "polygon", "data": {"points": [[10, 10], [20, 10], [30, 10]]}})
    with pytest.raises(AnnotationError, match="outside the image"):
        check({"kind": "polygon", "data": {"points": [[10, 10], [300, 10], [60, 50]]}})
    with pytest.raises(AnnotationError, match="more than 6 points"):
        check({"kind": "polygon", "data": {"points": [[i, i % 5 + 1] for i in range(7)]}})
    with pytest.raises(AnnotationError, match="2 numbers"):
        check({"kind": "polygon", "data": {"points": [[1, 1, 1], [5, 5, 1], [9, 1, 1]]}})


def test_keypoint_rules():
    ok = {"kind": "keypoints", "data": {"points": [[10, 10, 2], [20, 20, 1], [5, 5, 0]]}}
    cleaned = check(ok)["data"]["points"]
    assert cleaned == [[10, 10, 2], [20, 20, 1], [0.0, 0.0, 0]]  # unlabelled position is zeroed
    with pytest.raises(AnnotationError, match="visibility"):
        check({"kind": "keypoints", "data": {"points": [[1, 1, 3]]}})
    with pytest.raises(AnnotationError, match="at least one keypoint must be labelled"):
        check({"kind": "keypoints", "data": {"points": [[1, 1, 0], [2, 2, 0]]}})
    with pytest.raises(AnnotationError, match="at least one point"):
        check({"kind": "keypoints", "data": {"points": []}})
    with pytest.raises(AnnotationError, match="outside the image"):
        check({"kind": "keypoints", "data": {"points": [[999, 1, 2]]}})


def test_keypoint_count_must_match_the_class_skeleton():
    skeleton = {"names": ["a", "b", "c"], "edges": []}
    with pytest.raises(AnnotationError, match="has 3 keypoints but 2"):
        check({"kind": "keypoints", "data": {"points": [[1, 1, 2], [2, 2, 2]]}}, skeleton)
    good = {"kind": "keypoints", "data": {"points": [[1, 1, 2], [2, 2, 2], [3, 3, 0]]}}
    assert len(check(good, skeleton)["data"]["points"]) == 3


def test_messages_name_the_annotation_number():
    with pytest.raises(AnnotationError, match="Annotation 7:"):
        validate_annotation(box(x=-50), 7, W, H, LIMITS)


def test_set_rules():
    validate_set([box()] * 5, False, LIMITS)
    with pytest.raises(AnnotationError, match="at most 5"):
        validate_set([box()] * 6, False, LIMITS)
    with pytest.raises(AnnotationError, match="no objects"):
        validate_set([box()], True, LIMITS)
    validate_set([], True, LIMITS)  # an explicit empty image is fine
