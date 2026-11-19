"""AI assist (Stage 4): mask tracing, the fake backend, the service's request checks and result
cleaning, and the API. No model is loaded anywhere (Development Rule 8)."""

import copy
import re

import numpy as np
import pytest
from conftest import make_image, seed_images

from studio.config import load_config
from studio.mlbackend import sam as sam_module
from studio.mlbackend.fake import FakeBackend, split_phrases
from studio.mlbackend.masks import mask_to_polygon, signed_area
from studio.mlbackend.protocol import (
    TASK_DETECT_TEXT,
    TASK_SEGMENT_POINT,
    BackendError,
    BackendInfo,
    PredictRequest,
    Suggestion,
)
from studio.mlbackend.service import MLService, build_backends


# ---- masks ---------------------------------------------------------------------------------------
def area(polygon):
    return abs(signed_area([tuple(p) for p in polygon]))


def test_rectangle_mask_becomes_exactly_that_rectangle():
    mask = np.zeros((20, 30), bool)
    mask[5:10, 4:14] = True
    polygon = mask_to_polygon(mask, (6, 6), epsilon=0)
    assert sorted(map(tuple, polygon)) == [(4, 5), (4, 10), (14, 5), (14, 10)]


def test_l_shape_keeps_its_corner():
    mask = np.zeros((10, 10), bool)
    mask[1:9, 1:4] = True
    mask[6:9, 1:8] = True
    polygon = mask_to_polygon(mask, (2, 2), epsilon=0)
    assert len(polygon) == 6 and area(polygon) == mask.sum()


def test_hole_is_ignored_and_a_seed_on_the_far_wall_still_gets_the_outer_outline():
    mask = np.zeros((20, 20), bool)
    mask[2:18, 2:18] = True
    mask[6:14, 6:14] = False
    for seed in [(10, 3), (16, 10), (3, 10)]:
        polygon = mask_to_polygon(mask, seed, epsilon=0)
        assert area(polygon) == 16 * 16, seed


def test_only_the_seed_blob_is_traced():
    mask = np.zeros((10, 20), bool)
    mask[2:5, 1:5] = True
    mask[2:5, 10:15] = True
    polygon = mask_to_polygon(mask, (12, 3), epsilon=0)
    assert area(polygon) == 15 and min(p[0] for p in polygon) == 10


def test_seed_off_the_mask_uses_the_nearest_pixel():
    mask = np.zeros((10, 10), bool)
    mask[4:6, 4:6] = True
    assert area(mask_to_polygon(mask, (0, 0), epsilon=0)) == 4


def test_disc_is_simplified_close_to_its_area():
    yy, xx = np.mgrid[:100, :100]
    disc = (xx - 50) ** 2 + (yy - 50) ** 2 < 30**2
    polygon = mask_to_polygon(disc, (50, 50), epsilon=1.5)
    assert 8 <= len(polygon) < 80
    assert abs(area(polygon) - disc.sum()) / disc.sum() < 0.05


def test_empty_and_single_pixel_masks():
    assert mask_to_polygon(np.zeros((5, 5), bool)) is None
    one = np.zeros((5, 5), bool)
    one[2, 2] = True
    assert area(mask_to_polygon(one, (2, 2), epsilon=0)) == 1


def test_mask_touching_the_image_border():
    mask = np.ones((6, 8), bool)
    polygon = mask_to_polygon(mask, (0, 0), epsilon=0)
    assert area(polygon) == 48


# ---- fake backend and the contract every backend must keep --------------------------------------
def request(task, tmp_path, **kwargs):
    path = tmp_path / "x.png"
    if not path.exists():
        make_image(path, (200, 100))
    return PredictRequest(task=task, image_path=path, width=200, height=100, **kwargs)


def check_contract(backend, tmp_path):
    """What every backend promises: info shape, health, predictions inside the image with a score."""
    info = backend.info()
    assert isinstance(info, BackendInfo) and info.id and info.tasks and info.protocol_version == 1
    ok, message = backend.health()
    assert isinstance(ok, bool) and message
    if not info.available:
        return
    if TASK_SEGMENT_POINT in info.tasks:
        found = backend.predict(request(TASK_SEGMENT_POINT, tmp_path, points=[(100, 50, 1)]))
        assert found and all(s.kind == "polygon" for s in found)
    if TASK_DETECT_TEXT in info.tasks:
        found = backend.predict(request(TASK_DETECT_TEXT, tmp_path, text="car"))
        assert found and all(s.kind == "box" for s in found)


def test_fake_backend_keeps_the_contract(tmp_path):
    check_contract(FakeBackend(), tmp_path)
    assert FakeBackend().info().simulated


def test_fake_results_are_deterministic_and_change_with_the_text(tmp_path):
    fake = FakeBackend()
    one = fake.predict(request(TASK_DETECT_TEXT, tmp_path, text="pallet"))
    again = fake.predict(request(TASK_DETECT_TEXT, tmp_path, text="pallet"))
    other = fake.predict(request(TASK_DETECT_TEXT, tmp_path, text="forklift"))
    assert one == again and one != other
    assert [round(s.score, 2) for s in one] == [0.95, 0.7, 0.4]


def test_split_phrases():
    assert split_phrases("pallet, forklift and box; crate") == [
        "pallet",
        "forklift",
        "box",
        "crate",
    ]
    assert split_phrases(" , ") == []


def test_fake_needs_a_click_or_a_description(tmp_path):
    with pytest.raises(BackendError):
        FakeBackend().predict(request(TASK_SEGMENT_POINT, tmp_path))
    with pytest.raises(BackendError):
        FakeBackend().predict(request(TASK_DETECT_TEXT, tmp_path, text=" , "))


# ---- service -------------------------------------------------------------------------------------
@pytest.fixture
def cfg():
    config = copy.deepcopy(load_config())
    config["ml"]["backends"] = ["fake"]
    return config


class Garbage:
    """A misbehaving backend: out-of-image box, NaN score, two-point polygon, one good box."""

    id = "garbage"

    def info(self):
        return BackendInfo("garbage", "Garbage", "0", (TASK_DETECT_TEXT,), True, True)

    def health(self):
        return True, "ok"

    def predict(self, req):
        nan = float("nan")
        return [
            Suggestion("box", {"x": 500, "y": 500, "w": 10, "h": 10}, 0.9),
            Suggestion("box", {"x": 1, "y": 1, "w": 10, "h": 10}, nan),
            Suggestion("polygon", {"points": [[1, 1], [5, 5]]}, 0.9),
            Suggestion("circle", {"r": 3}, 0.9),
            Suggestion("box", {"x": 10.123, "y": 10, "w": 20, "h": 20}, 7.0, "  car  "),
            Suggestion("box", {"x": 30, "y": 30, "w": 20, "h": 20}, 0.2),
        ]


def test_results_are_validated_clamped_sorted_and_counted(cfg, tmp_path):
    service = MLService(cfg, {"garbage": Garbage()})
    result = service.predict("garbage", request(TASK_DETECT_TEXT, tmp_path, text="x"))
    assert result.dropped == 4
    assert [s.score for s in result.suggestions] == [1.0, 0.2]  # 7.0 clamped to 1
    assert result.suggestions[0].label == "car" and result.suggestions[0].data["x"] == 10.12


def test_max_results_caps_and_counts_the_overflow(cfg, tmp_path):
    service = MLService(cfg, {"garbage": Garbage()})
    result = service.predict(
        "garbage", request(TASK_DETECT_TEXT, tmp_path, text="x", max_results=1)
    )
    assert len(result.suggestions) == 1 and result.dropped == 5


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"task": TASK_SEGMENT_POINT}, "Click on the object"),
        ({"task": TASK_SEGMENT_POINT, "points": [(300, 5, 1)]}, "outside the image"),
        ({"task": TASK_SEGMENT_POINT, "points": [(5, 5, 7)]}, "inside (1) or outside (0)"),
        ({"task": TASK_SEGMENT_POINT, "points": [(float("inf"), 5, 1)]}, "finite"),
        ({"task": TASK_SEGMENT_POINT, "points": [(1, 1, 1)] * 21}, "At most 20"),
        ({"task": TASK_DETECT_TEXT, "text": "   "}, "Describe"),
        ({"task": TASK_DETECT_TEXT, "text": "x" * 201}, "at most 200"),
        ({"task": "dance"}, "task must be"),
    ],
)
def test_bad_requests_are_refused_with_a_reason(cfg, tmp_path, kwargs, message):
    service = MLService(cfg)
    with pytest.raises(ValueError, match=re.escape(message)):
        service.check_request(request(tmp_path=tmp_path, **kwargs))


def test_unknown_backend_and_wrong_task(cfg, tmp_path):
    service = MLService(cfg)
    with pytest.raises(LookupError):
        service.predict("nope", request(TASK_DETECT_TEXT, tmp_path, text="x"))
    service = MLService(cfg, {"garbage": Garbage()})
    with pytest.raises(ValueError, match="cannot do"):
        service.predict("garbage", request(TASK_SEGMENT_POINT, tmp_path, points=[(1, 1, 1)]))


def test_a_crashing_backend_becomes_a_readable_error(cfg, tmp_path):
    class Crash(Garbage):
        def predict(self, req):
            raise RuntimeError("CUDA out of memory")

    with pytest.raises(BackendError, match="failed"):
        MLService(cfg, {"garbage": Crash()}).predict(
            "garbage", request(TASK_DETECT_TEXT, tmp_path, text="x")
        )


def test_a_missing_image_file_is_reported(cfg, tmp_path):
    req = PredictRequest(TASK_DETECT_TEXT, tmp_path / "gone.png", 200, 100, text="x")
    with pytest.raises(BackendError, match="missing"):
        MLService(cfg).predict("fake", req)


def test_remote_backends_are_disabled_unless_allowed(cfg, tmp_path):
    class Remote(Garbage):
        id = "remote"

        def info(self):
            return BackendInfo("remote", "Remote", "0", (TASK_DETECT_TEXT,), False, True)

    service = MLService(cfg, {"remote": Remote()})
    [info] = service.infos()
    assert not info.available and "off this computer" in info.reason
    with pytest.raises(BackendError):
        service.predict("remote", request(TASK_DETECT_TEXT, tmp_path, text="x"))
    cfg["ml"]["allow_remote_backends"] = True
    assert MLService(cfg, {"remote": Remote()}).infos()[0].available


def test_unknown_backend_name_in_config_is_an_error(cfg):
    cfg["ml"]["backends"] = ["magic"]
    with pytest.raises(ValueError, match="unknown backend"):
        build_backends(cfg)


# ---- SAM without its pieces ----------------------------------------------------------------------
def test_sam_says_what_is_missing(cfg, tmp_path, monkeypatch):
    cfg["app"]["data_dir"] = str(tmp_path)
    cfg["ml"]["backends"] = ["sam"]
    backend = sam_module.SamBackend(cfg)
    monkeypatch.setattr(sam_module, "sam_model_registry", None)
    assert "segment-anything package" in backend.info().reason and not backend.can_download()
    monkeypatch.setattr(sam_module, "sam_model_registry", {"vit_b": object()})
    monkeypatch.setattr(sam_module, "torch", object())
    assert "not downloaded" in backend.info().reason and backend.can_download()
    weights = backend.weights_path()
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"short")
    assert "incomplete" in backend.info().reason
    weights.write_bytes(b"x" * cfg["ml"]["sam"]["checkpoint_bytes"])
    assert backend.info().available and not backend.can_download()


def test_sam_download_checks_the_size_and_cleans_up(cfg, tmp_path, monkeypatch):
    cfg["app"]["data_dir"] = str(tmp_path)
    cfg["ml"]["sam"]["checkpoint_bytes"] = 10
    backend = sam_module.SamBackend(cfg)
    served = {"data": b"0123456789"}

    class Response:
        def __init__(self):
            self.data = served["data"]

        def read(self, n):
            chunk, self.data = self.data[:n], self.data[n:]
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(sam_module.urllib.request, "urlopen", lambda *a, **k: Response())
    seen = []
    backend.download_weights(lambda p: seen.append(p["done"]))
    assert backend.weights_path().read_bytes() == b"0123456789" and seen == [10]
    backend.weights_path().unlink()
    served["data"] = b"012"
    with pytest.raises(BackendError, match="wrong size"):
        backend.download_weights()
    assert not backend.weights_path().exists()
    assert not list(backend.weights_path().parent.glob("*.part"))
    served["data"] = b"0123456789"
    with pytest.raises(BackendError, match="cancelled"):
        backend.download_weights(cancelled=lambda: True)
    assert not backend.weights_path().exists()


# ---- API -----------------------------------------------------------------------------------------
@pytest.fixture
def image_id(client, project, tmp_path):
    folder = tmp_path / "imgs"
    make_image(folder / "a.png", (200, 100))
    job = client.post(f"/api/projects/{project['id']}/imports", json={"path": str(folder)}).json()
    from conftest import wait_for_job

    wait_for_job(client, job["job_id"])
    return client.get(f"/api/projects/{project['id']}/images").json()["items"][0]["id"]


def test_backends_endpoint_lists_the_fake_and_the_default_score(client):
    body = client.get("/api/ml/backends").json()
    [fake] = body["backends"]
    assert (
        fake["id"] == "fake"
        and fake["simulated"]
        and fake["available"]
        and not fake["can_download"]
    )
    assert body["default_min_score"] == 0.5


def test_suggest_returns_polygons_for_a_click_and_stores_nothing(client, image_id):
    reply = client.post(
        f"/api/images/{image_id}/suggest",
        json={
            "backend": "fake",
            "task": "segment_point",
            "points": [[100, 50, 1]],
            "max_results": 1,
        },
    )
    assert reply.status_code == 200
    body = reply.json()
    assert body["suggestions"][0]["kind"] == "polygon" and body["dropped"] == 0
    assert client.get(f"/api/images/{image_id}/annotations").json()["annotations"] == []


def test_suggest_boxes_from_text(client, image_id):
    body = client.post(
        f"/api/images/{image_id}/suggest",
        json={"backend": "fake", "task": "detect_text", "text": "pallet, forklift"},
    ).json()
    assert len(body["suggestions"]) == 6
    assert {s["label"] for s in body["suggestions"]} == {"pallet", "forklift"}
    scores = [s["score"] for s in body["suggestions"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize(
    "payload, status",
    [
        ({"backend": "nope", "task": "detect_text", "text": "x"}, 404),
        ({"backend": "fake", "task": "detect_text", "text": ""}, 400),
        ({"backend": "fake", "task": "segment_point", "points": [[999, 5, 1]]}, 400),
        ({"backend": "fake", "task": "segment_point", "points": [[1, 5]]}, 422),
        ({"backend": "fake", "task": "detect_text", "text": "x", "max_results": 0}, 422),
        ({"backend": "fake", "task": "detect_text", "text": "x", "max_results": 101}, 422),
    ],
)
def test_suggest_rejects_bad_input(client, image_id, payload, status):
    assert client.post(f"/api/images/{image_id}/suggest", json=payload).status_code == status


def test_suggest_unknown_image_and_bad_ids(client):
    ok = {"backend": "fake", "task": "detect_text", "text": "x"}
    assert client.post("/api/images/999/suggest", json=ok).status_code == 404
    assert client.post("/api/images/abc/suggest", json=ok).status_code == 422


def test_download_endpoint_refuses_what_has_nothing_to_download(client):
    assert client.post("/api/ml/backends/fake/download").status_code == 404
    assert client.post("/api/ml/backends/nope/download").status_code == 404


def test_suggest_in_a_project_without_the_file_is_a_clear_error(client, project):
    [image] = seed_images(client, project["id"], 1)
    reply = client.post(
        f"/api/images/{image}/suggest", json={"backend": "fake", "task": "detect_text", "text": "x"}
    )
    assert reply.status_code == 409 and "missing" in reply.json()["detail"]


# ---- review fixes --------------------------------------------------------------------------------
@pytest.mark.parametrize("box, message", [
    ((10, 10, 0, 5), "above zero"),
    ((10, 10, -5, 5), "above zero"),
    ((-1, 10, 5, 5), "outside the image"),
    ((190, 10, 20, 5), "outside the image"),
    ((float("nan"), 1, 5, 5), "finite"),
])
def test_prompt_boxes_are_checked(cfg, tmp_path, box, message):
    with pytest.raises(ValueError, match=message):
        MLService(cfg).check_request(request(TASK_SEGMENT_POINT, tmp_path, box=box))


def test_a_good_box_alone_is_a_valid_prompt(cfg, tmp_path):
    MLService(cfg).check_request(request(TASK_SEGMENT_POINT, tmp_path, box=(10, 10, 50, 40)))


def test_huge_prompts_are_refused_before_they_are_processed(client, image_id):
    url = f"/api/images/{image_id}/suggest"
    assert client.post(url, json={"backend": "fake", "task": "detect_text", "text": "x" * 5001}).status_code == 422
    many = [[1, 1, 1]] * 201
    assert client.post(url, json={"backend": "fake", "task": "segment_point", "points": many}).status_code == 422


def test_only_one_sam_download_runs_at_a_time(cfg, tmp_path, monkeypatch):
    import threading

    cfg["app"]["data_dir"] = str(tmp_path)
    backend = sam_module.SamBackend(cfg)
    monkeypatch.setattr(sam_module, "sam_model_registry", {"vit_b": object()})
    monkeypatch.setattr(sam_module, "torch", object())
    started, release = threading.Event(), threading.Event()

    def slow(progress, cancelled):
        started.set()
        release.wait(5)

    monkeypatch.setattr(backend, "_download", slow)
    first = threading.Thread(target=backend.download_weights)
    first.start()
    assert started.wait(5)
    assert not backend.can_download()
    with pytest.raises(BackendError, match="already being downloaded"):
        backend.download_weights()
    release.set()
    first.join()
    assert backend.can_download()
