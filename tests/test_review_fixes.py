"""Regression tests for the v0.2 independent review's backend findings."""

import json

import pytest
from conftest import seed_images


def make_class(client, project_id, name, color=None):
    body = {"name": name, **({"color": color} if color else {})}
    return client.post(f"/api/projects/{project_id}/classes", json=body)


def put(client, image_id, body):
    return client.put(
        f"/api/images/{image_id}/annotations",
        content=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )


def test_colour_with_trailing_newline_is_rejected(client, project):
    for bad in ("#ABCDEF\n", "#ABCDEF ", " #ABCDEF", "#ABCDEG", "#ABC", "ABCDEF"):
        assert (
            make_class(client, project["id"], f"c{len(bad)}{bad!r}", color=bad).status_code == 400
        )


def test_new_classes_keep_getting_different_colours_after_the_palette_is_used_up(
    client, project, config
):
    palette = [c.upper() for c in config["annotations"]["palette"]]
    colours = [
        make_class(client, project["id"], f"class {i}").json()["color"]
        for i in range(len(palette) + 4)
    ]
    assert colours[: len(palette)] == palette
    # beyond the palette they cycle by class count, so neighbours never share a colour
    assert len(set(colours[len(palette) :])) == 4
    assert colours[len(palette)] != colours[len(palette) + 1]


def test_huge_numbers_in_a_box_are_a_400_not_a_server_error(client, project):
    class_id = make_class(client, project["id"], "car").json()["id"]
    (image,) = seed_images(client, project["id"], 1)
    for huge in (10**400, -(10**400), 1e308 * 10):
        body = {
            "rev": 0,
            "annotations": [
                {"class_id": class_id, "kind": "box", "data": {"x": huge, "y": 1, "w": 5, "h": 5}}
            ],
            "marked_empty": False,
            "label_class_id": None,
        }
        response = put(client, image, body)
        assert response.status_code == 400, (huge, response.status_code)


HUGE_ID = 10**30


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", f"/api/images/{HUGE_ID}"),
        ("GET", f"/api/images/{HUGE_ID}/annotations"),
        ("GET", f"/api/images/{HUGE_ID}/neighbours"),
        ("GET", f"/api/images/{HUGE_ID}/thumb"),
        ("DELETE", f"/api/classes/{HUGE_ID}"),
        ("GET", f"/api/projects/{HUGE_ID}"),
        ("GET", f"/api/projects/{HUGE_ID}/classes"),
        ("GET", f"/api/projects/{HUGE_ID}/images"),
        ("GET", "/api/projects/1/images?class_id=" + str(HUGE_ID)),
        ("GET", "/api/projects/1/images?batch_id=" + str(HUGE_ID)),
        ("GET", "/api/projects/0"),
        ("GET", "/api/images/-5/annotations"),
    ],
)
def test_out_of_range_ids_are_422_never_500(client, project, method, path):
    assert client.request(method, path).status_code == 422


def test_class_patch_position_is_bounded(client, project):
    class_id = make_class(client, project["id"], "car").json()["id"]
    assert client.patch(f"/api/classes/{class_id}", json={"position": HUGE_ID}).status_code == 422
    assert client.patch(f"/api/classes/{class_id}", json={"position": -1}).status_code == 422
    assert client.patch(f"/api/classes/{class_id}", json={"position": 3}).status_code == 200


@pytest.mark.parametrize("bad_class_id", [True, 1.0, "1", None, 0, -3, 2**62 + 1], ids=repr)
def test_annotation_class_ids_must_be_real_positive_integers(client, project, bad_class_id):
    make_class(client, project["id"], "car")
    (image,) = seed_images(client, project["id"], 1)
    body = {
        "rev": 0,
        "annotations": [
            {"class_id": bad_class_id, "kind": "box", "data": {"x": 1, "y": 1, "w": 5, "h": 5}}
        ],
        "marked_empty": False,
        "label_class_id": None,
    }
    assert put(client, image, body).status_code == 422


@pytest.mark.parametrize("bad_rev", [True, "0", 0.0, None, -1], ids=repr)
def test_revision_must_be_a_real_non_negative_integer(client, project, bad_rev):
    (image,) = seed_images(client, project["id"], 1)
    body = {"rev": bad_rev, "annotations": [], "marked_empty": False, "label_class_id": None}
    assert put(client, image, body).status_code == 422


def test_label_class_id_is_strict_too(client, project):
    make_class(client, project["id"], "car")
    (image,) = seed_images(client, project["id"], 1)
    body = {"rev": 0, "annotations": [], "marked_empty": False, "label_class_id": True}
    assert put(client, image, body).status_code == 422
