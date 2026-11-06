"""Classes, annotations, stats, filters and navigation through the API and the data layer."""

import threading

import pytest
from conftest import seed_images

from studio import db, repo
from studio import repo_annotations as ra


def box(x=10, y=10, w=50, h=30, class_id=1):
    return {"class_id": class_id, "kind": "box", "data": {"x": x, "y": y, "w": w, "h": h}}


def make_class(client, project_id, name, color=None):
    body = {"name": name, **({"color": color} if color else {})}
    return client.post(f"/api/projects/{project_id}/classes", json=body)


def save(client, image_id, rev, items=(), empty=False, label=None):
    return client.put(
        f"/api/images/{image_id}/annotations",
        json={
            "rev": rev,
            "annotations": list(items),
            "marked_empty": empty,
            "label_class_id": label,
        },
    )


# ---- classes ------------------------------------------------------------------------------------


def test_classes_get_distinct_palette_colours_and_positions(client, project, config):
    pid = project["id"]
    made = [make_class(client, pid, n).json() for n in ("car", "bus", "bike")]
    palette = config["annotations"]["palette"]
    assert [c["color"] for c in made] == [p.upper() for p in palette[:3]]
    assert [c["position"] for c in made] == [0, 1, 2]
    assert [c["name"] for c in client.get(f"/api/projects/{pid}/classes").json()] == [
        "car",
        "bus",
        "bike",
    ]


def test_class_name_and_colour_validation(client, project):
    pid = project["id"]
    assert make_class(client, pid, "Car").status_code == 201
    duplicate = make_class(client, pid, "  car ")  # case-insensitive, whitespace-insensitive
    assert duplicate.status_code == 409 and "already exists" in duplicate.json()["detail"]
    assert make_class(client, pid, "   ").status_code == 400
    assert make_class(client, pid, "x" * 81).status_code == 400
    assert make_class(client, pid, "ok", color="red").status_code == 400
    assert make_class(client, pid, "ok2", color="#abc123").json()["color"] == "#ABC123"
    assert make_class(client, 999, "z").status_code == 404


def test_class_rename_recolour_and_conflicts(client, project):
    pid = project["id"]
    a, b = (make_class(client, pid, n).json() for n in ("a", "b"))
    changed = client.patch(f"/api/classes/{a['id']}", json={"name": "alpha", "color": "#112233"})
    assert changed.json()["name"] == "alpha" and changed.json()["color"] == "#112233"
    assert client.patch(f"/api/classes/{a['id']}", json={"name": "B"}).status_code == 409
    assert client.patch(f"/api/classes/{b['id']}", json={"color": "nope"}).status_code == 400
    assert client.patch("/api/classes/9999", json={"name": "x"}).status_code == 404


def test_deleting_a_used_class_needs_force_and_cleans_up(client, project):
    pid = project["id"]
    cls = make_class(client, pid, "car").json()
    other = make_class(client, pid, "bus").json()
    img1, img2 = seed_images(client, pid, 2)
    assert (
        save(client, img1, 0, [box(class_id=cls["id"]), box(class_id=other["id"])]).status_code
        == 200
    )
    assert save(client, img2, 0, label=cls["id"], empty=False).status_code == 200

    refused = client.delete(f"/api/classes/{cls['id']}")
    assert refused.status_code == 409
    assert refused.json()["in_use"] == {"annotations": 1, "images": 1, "labels": 1}

    assert client.delete(f"/api/classes/{cls['id']}?force=true").status_code == 204
    after = client.get(f"/api/images/{img1}/annotations").json()
    assert [a["class_id"] for a in after["annotations"]] == [other["id"]]
    assert after["rev"] == 2  # bumped so an open editor notices
    assert client.get(f"/api/images/{img2}/annotations").json()["label_class_id"] is None
    assert client.delete(f"/api/classes/{cls['id']}").status_code == 404


def test_unused_class_deletes_without_force(client, project):
    cls = make_class(client, project["id"], "tmp").json()
    assert client.delete(f"/api/classes/{cls['id']}").status_code == 204


# ---- saving annotations -------------------------------------------------------------------------


def test_save_replace_all_and_revisions(client, project):
    pid = project["id"]
    cls = make_class(client, pid, "car").json()["id"]
    (image,) = seed_images(client, pid, 1)
    assert client.get(f"/api/images/{image}/annotations").json() == {
        "rev": 0,
        "marked_empty": False,
        "label_class_id": None,
        "annotations": [],
    }

    first = save(client, image, 0, [box(class_id=cls), box(x=60, class_id=cls)])
    assert first.status_code == 200 and first.json() == {"rev": 1}
    second = save(client, image, 1, [box(x=5, class_id=cls)])
    assert second.json() == {"rev": 2}
    stored = client.get(f"/api/images/{image}/annotations").json()
    assert stored["rev"] == 2 and len(stored["annotations"]) == 1  # replaced, not appended
    assert stored["annotations"][0]["data"]["x"] == 5


def test_annotation_order_is_preserved(client, project):
    cls = make_class(client, project["id"], "car").json()["id"]
    (image,) = seed_images(client, project["id"], 1)
    items = [box(x=i * 10, w=5, class_id=cls) for i in range(8)]
    save(client, image, 0, items)
    got = client.get(f"/api/images/{image}/annotations").json()["annotations"]
    assert [a["data"]["x"] for a in got] == [i * 10 for i in range(8)]


def test_stale_revision_is_a_conflict_and_changes_nothing(client, project):
    cls = make_class(client, project["id"], "car").json()["id"]
    (image,) = seed_images(client, project["id"], 1)
    save(client, image, 0, [box(class_id=cls)])
    conflict = save(client, image, 0, [box(x=99, class_id=cls)])
    assert conflict.status_code == 409 and conflict.json()["current_rev"] == 1
    assert (
        client.get(f"/api/images/{image}/annotations").json()["annotations"][0]["data"]["x"] == 10
    )


def test_invalid_content_is_rejected_atomically(client, project):
    pid = project["id"]
    cls = make_class(client, pid, "car").json()["id"]
    (image,) = seed_images(client, pid, 1, width=200, height=100)
    save(client, image, 0, [box(class_id=cls)])
    bad = save(client, image, 1, [box(class_id=cls), box(x=500, class_id=cls)])
    assert bad.status_code == 400 and "Annotation 2" in bad.json()["detail"]
    kept = client.get(f"/api/images/{image}/annotations").json()
    assert (
        kept["rev"] == 1 and len(kept["annotations"]) == 1
    )  # the good first box was not half-saved


def test_class_must_belong_to_the_same_project(client, project):
    other_project = client.post("/api/projects", json={"name": "Other"}).json()
    foreign = make_class(client, other_project["id"], "foreign").json()["id"]
    (image,) = seed_images(client, project["id"], 1)
    assert save(client, image, 0, [box(class_id=foreign)]).status_code == 400
    assert save(client, image, 0, [], label=foreign).status_code == 400
    assert save(client, image, 0, [box(class_id=999)]).status_code == 400


def test_marked_empty_rules_and_label(client, project):
    pid = project["id"]
    cls = make_class(client, pid, "car").json()["id"]
    (image,) = seed_images(client, pid, 1)
    assert save(client, image, 0, [box(class_id=cls)], empty=True).status_code == 400
    assert save(client, image, 0, [], empty=True, label=cls).json() == {"rev": 1}
    state = client.get(f"/api/images/{image}/annotations").json()
    assert state["marked_empty"] is True and state["label_class_id"] == cls
    assert client.get(f"/api/images/{image}").json()["marked_empty"] is True


def test_too_many_annotations_and_unknown_image(client, project, config):
    cls = make_class(client, project["id"], "car").json()["id"]
    (image,) = seed_images(client, project["id"], 1)
    config["annotations"]["max_per_image"] = 3
    assert save(client, image, 0, [box(class_id=cls)] * 4).status_code == 400
    assert save(client, 99999, 0, []).status_code == 404
    assert client.get("/api/images/99999/annotations").status_code == 404


def test_malformed_requests_are_422(client, project):
    (image,) = seed_images(client, project["id"], 1)
    assert (
        client.put(f"/api/images/{image}/annotations", json={"annotations": []}).status_code == 422
    )
    assert (
        client.put(
            f"/api/images/{image}/annotations", json={"rev": 0, "annotations": [{"class_id": "x"}]}
        ).status_code
        == 422
    )


def test_two_writers_with_the_same_revision_only_one_wins(tmp_path, config):
    """Real concurrency: both pass the first revision check; the write lock decides."""
    path = tmp_path / "race.sqlite"
    setup = db.connect(path)
    db.migrate(setup)
    setup.execute("INSERT INTO projects (id, name, created_at) VALUES (1, 'p', 'n')")
    setup.execute(
        "INSERT INTO batches (id, project_id, source, created_at) VALUES (1, 1, 's', 'n')"
    )
    setup.execute(
        "INSERT INTO images (id, project_id, batch_id, sha256, stored_name, original_name, width,"
        " height, bytes, created_at) VALUES (1, 1, 1, 'h', 'a', 'a', 200, 100, 1, 'n')"
    )
    setup.execute(
        "INSERT INTO classes (id, project_id, name, color, position, created_at)"
        " VALUES (1, 1, 'c', '#000000', 0, 'n')"
    )
    setup.commit()
    outcomes = []
    barrier = threading.Barrier(6)

    def writer(x):
        conn = db.connect(path)
        try:
            barrier.wait()
            ra.save_annotations(conn, 1, 0, [box(x=x)], False, None, config["annotations"])
            outcomes.append("ok")
        except ra.RevisionConflict:
            outcomes.append("conflict")
        finally:
            conn.close()

    threads = [threading.Thread(target=writer, args=(i * 5,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["conflict"] * 5 + ["ok"]
    assert (
        ra.get_annotations(setup, 1)["rev"] == 1
        and len(ra.get_annotations(setup, 1)["annotations"]) == 1
    )


# ---- stats, filters, navigation -----------------------------------------------------------------


def test_stats_filters_and_counts(client, project):
    pid = project["id"]
    car = make_class(client, pid, "car").json()["id"]
    bus = make_class(client, pid, "bus").json()["id"]
    ids = seed_images(client, pid, 5)
    save(client, ids[0], 0, [box(class_id=car), box(x=70, class_id=car)])
    save(client, ids[1], 0, [box(class_id=bus)])
    save(client, ids[2], 0, [], empty=True)
    save(client, ids[3], 0, [], label=bus)
    # ids[4] stays unlabelled

    stats = client.get(f"/api/projects/{pid}/annotation-stats").json()
    assert (stats["images"], stats["labelled"], stats["unlabelled"]) == (5, 4, 1)
    assert (stats["marked_empty"], stats["with_annotations"], stats["with_label"]) == (1, 2, 1)
    by_name = {c["name"]: c for c in stats["per_class"]}
    assert by_name["car"]["boxes"] == 2 and by_name["car"]["images"] == 1
    assert by_name["bus"]["boxes"] == 1 and by_name["bus"]["labels"] == 1

    url = f"/api/projects/{pid}/images"
    assert client.get(url, params={"labelled": True}).json()["total"] == 4
    unlabelled = client.get(url, params={"labelled": False}).json()
    assert [i["id"] for i in unlabelled["items"]] == [ids[4]]
    assert client.get(url, params={"class_id": bus}).json()["total"] == 2  # a box and a label
    first = client.get(url).json()["items"][0]
    assert first["annotation_count"] == 2 and first["marked_empty"] is False


def test_neighbours_and_next_unlabelled_wraps(client, project):
    pid = project["id"]
    cls = make_class(client, pid, "c").json()["id"]
    ids = seed_images(client, pid, 4)
    save(client, ids[1], 0, [box(class_id=cls)])
    save(client, ids[3], 0, [], empty=True)

    middle = client.get(f"/api/images/{ids[1]}/neighbours").json()
    assert middle == {
        "previous": ids[0],
        "next": ids[2],
        "next_unlabelled": ids[2],
        "index": 2,
        "total": 4,
    }
    last = client.get(f"/api/images/{ids[3]}/neighbours").json()
    assert last["next"] is None and last["next_unlabelled"] == ids[0]  # wraps around
    save(client, ids[0], 0, [], empty=True)
    save(client, ids[2], 0, [], empty=True)
    assert client.get(f"/api/images/{ids[0]}/neighbours").json()["next_unlabelled"] is None
    assert client.get("/api/images/99999/neighbours").status_code == 404


def test_deleting_a_project_removes_classes_and_annotations(client, project):
    pid = project["id"]
    cls = make_class(client, pid, "car").json()["id"]
    (image,) = seed_images(client, pid, 1)
    save(client, image, 0, [box(class_id=cls)])
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    conn = db.connect(client.app.state.db_path)
    for table in ("classes", "annotations", "images"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    conn.close()


def test_limits_endpoint_includes_annotation_settings(client, config):
    limits = client.get("/api/limits").json()
    assert limits["palette"] == config["annotations"]["palette"]
    assert limits["undo_limit"] == config["annotations"]["undo_limit"]


@pytest.mark.parametrize("name", ["Car", "CAR", " car "])
def test_class_names_are_unique_ignoring_case(client, project, name):
    make_class(client, project["id"], "car")
    assert make_class(client, project["id"], name).status_code == 409


def test_repo_import_is_used_for_labelled_sql():
    assert "marked_empty" in repo.LABELLED_SQL
