"""Skeletons on classes and keypoint annotations (v0.4)."""

import pytest
from conftest import seed_images
from test_annotations_api import make_class, save

from studio.annotations import AnnotationError, validate_skeleton

SKELETON = {"names": ["head", "neck", "tail"], "edges": [[0, 1], [1, 2]]}


def clean(raw):
    return validate_skeleton(raw, 64, 40)


def test_skeleton_is_cleaned():
    got = clean({"names": ["  head ", "neck"], "edges": [[1, 0], [0, 1]]})
    assert got == {"names": ["head", "neck"], "edges": [[0, 1]]}  # trimmed, sorted, de-duplicated


@pytest.mark.parametrize(
    "raw",
    [
        {"names": []},
        {"names": ["a", "A"]},  # duplicate ignoring case
        {"names": ["a", " "]},
        {"names": ["a", 3]},
        {"names": ["a", "b"], "edges": [[0, 0]]},
        {"names": ["a", "b"], "edges": [[0, 2]]},
        {"names": ["a", "b"], "edges": [[-1, 1]]},
        {"names": ["a", "b"], "edges": [[0, True]]},
        {"names": ["a", "b"], "edges": [[0]]},
        {"names": ["a" * 41]},
        {"names": [str(i) for i in range(65)]},
        {"names": ["a"], "extra": 1},
        [],
    ],
)
def test_bad_skeletons_are_refused(raw):
    with pytest.raises(AnnotationError):
        clean(raw)


def test_class_with_skeleton_round_trips(client, project):
    pid = project["id"]
    created = client.post(
        f"/api/projects/{pid}/classes", json={"name": "cat", "skeleton": SKELETON}
    )
    assert created.status_code == 201
    assert created.json()["skeleton"] == SKELETON
    assert client.get(f"/api/projects/{pid}/classes").json()[0]["skeleton"] == SKELETON


def test_bad_skeleton_gives_400(client, project):
    pid = project["id"]
    response = client.post(
        f"/api/projects/{pid}/classes", json={"name": "cat", "skeleton": {"names": []}}
    )
    assert response.status_code == 400
    assert "at least one point" in response.json()["detail"]


def test_patch_sets_keeps_and_removes_skeleton(client, project):
    pid = project["id"]
    cid = make_class(client, pid, "cat").json()["id"]
    assert client.patch(f"/api/classes/{cid}", json={"name": "kitten"}).json()["skeleton"] is None
    got = client.patch(f"/api/classes/{cid}", json={"skeleton": SKELETON}).json()
    assert got["skeleton"] == SKELETON
    assert client.patch(f"/api/classes/{cid}", json={"color": "#112233"}).json()["skeleton"] == (
        SKELETON
    )  # leaving the field out keeps it
    assert client.patch(f"/api/classes/{cid}", json={"skeleton": None}).json()["skeleton"] is None


def test_keypoints_save_and_must_match_the_skeleton(client, project):
    pid = project["id"]
    cid = client.post(
        f"/api/projects/{pid}/classes", json={"name": "cat", "skeleton": SKELETON}
    ).json()["id"]
    (image,) = seed_images(client, pid, 1)
    good = {"class_id": cid, "kind": "keypoints",
            "data": {"points": [[10, 10, 2], [20, 20, 1], [0, 0, 0]]}}
    assert save(client, image, 0, [good]).status_code == 200
    stored = client.get(f"/api/images/{image}/annotations").json()["annotations"][0]
    assert stored["data"]["points"] == [[10, 10, 2], [20, 20, 1], [0, 0, 0]]
    short = {**good, "data": {"points": [[10, 10, 2], [20, 20, 2]]}}
    response = save(client, image, 1, [short])
    assert response.status_code == 400
    assert "3 keypoints" in response.json()["detail"]


def test_point_count_is_locked_once_keypoints_exist(client, project):
    pid = project["id"]
    cid = client.post(
        f"/api/projects/{pid}/classes", json={"name": "cat", "skeleton": SKELETON}
    ).json()["id"]
    (image,) = seed_images(client, pid, 1)
    item = {"class_id": cid, "kind": "keypoints",
            "data": {"points": [[10, 10, 2], [20, 20, 2], [30, 30, 2]]}}
    assert save(client, image, 0, [item]).status_code == 200
    longer = {"names": ["a", "b", "c", "d"], "edges": []}
    assert client.patch(f"/api/classes/{cid}", json={"skeleton": longer}).status_code == 400
    assert client.patch(f"/api/classes/{cid}", json={"skeleton": None}).status_code == 400
    renamed = {"names": ["a", "b", "c"], "edges": [[0, 2]]}
    assert client.patch(f"/api/classes/{cid}", json={"skeleton": renamed}).status_code == 200


def test_limits_expose_skeleton_bounds(client):
    got = client.get("/api/limits").json()
    assert got["max_keypoints"] == 64
    assert got["skeleton_name_max"] == 40
