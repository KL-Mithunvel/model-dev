"""Click-to-segment with Meta's Segment Anything (SAM, vit_b by default). Licence: Apache-2.0.

Optional at run time: without the ``segment-anything`` package, torch, or the downloaded weights,
``info()`` says what is missing and ``predict`` is refused by the service. Weights are downloaded once
(on request, never silently) into ``<data_dir>/models`` and then used offline. Images never leave the
machine: only the weight file is fetched.
"""

import logging
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from studio import paths
from studio.mlbackend.masks import mask_to_polygon
from studio.mlbackend.protocol import (
    TASK_SEGMENT_POINT,
    BackendError,
    BackendInfo,
    PredictRequest,
    Suggestion,
)

try:
    import torch
except ImportError:
    torch = None
try:
    from segment_anything import SamPredictor, sam_model_registry
except ImportError:
    SamPredictor = sam_model_registry = None

logger = logging.getLogger(__name__)
DOWNLOAD_CHUNK = 1 << 20
SAM_VERSION = "1.0"


class SamBackend:
    id = "sam"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.settings = config["ml"]["sam"]
        self._predictor = None
        self._embedded: tuple[str, int, int] | None = (
            None  # (path, mtime_ns, size) of the image set
        )
        self._load_lock = threading.Lock()
        self._download_lock = threading.Lock()  # one download at a time: they share one .part file

    # ---- state ------------------------------------------------------------------------------
    def weights_path(self) -> Path:
        return paths.models_dir(self.config) / self.settings["checkpoint_filename"]

    def _problem(self) -> str:
        if torch is None:
            return "PyTorch is not installed."
        if sam_model_registry is None:
            return (
                "The segment-anything package is not installed (pip install segment-anything==1.0)."
            )
        path = self.weights_path()
        if not path.is_file():
            size_mb = self.settings["checkpoint_bytes"] // 1_000_000
            return f"The model weights ({size_mb} MB) are not downloaded yet. Use “Download model”."
        if path.stat().st_size != self.settings["checkpoint_bytes"]:
            return "The model file is incomplete or damaged. Download it again."
        return ""

    def info(self) -> BackendInfo:
        reason = self._problem()
        return BackendInfo(
            id=self.id,
            name="Segment Anything (click to outline)",
            version=SAM_VERSION,
            tasks=(TASK_SEGMENT_POINT,),
            local_only=True,
            available=not reason,
            reason=reason,
            licence="Apache-2.0 (code and weights; checked 2026-11-19 on the official repository page)",
        )

    def can_download(self) -> bool:
        """True when the only thing missing is the weight file."""
        return (
            torch is not None
            and sam_model_registry is not None
            and not self.info().available
            and not self._download_lock.locked()
        )

    def health(self) -> tuple[bool, str]:
        reason = self._problem()
        return (not reason), reason or "ok"

    # ---- weights ----------------------------------------------------------------------------
    def download_weights(
        self,
        progress: Callable[[dict[str, Any]], None] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        """Fetch the checkpoint to a temp file, check its size, then move it into place."""
        if not self._download_lock.acquire(blocking=False):
            raise BackendError("The model is already being downloaded.")
        try:
            self._download(progress, cancelled)
        finally:
            self._download_lock.release()

    def _download(self, progress, cancelled) -> None:
        url, expected = self.settings["checkpoint_url"], self.settings["checkpoint_bytes"]
        target = self.weights_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(target.suffix + ".part")
        try:
            with (
                urllib.request.urlopen(
                    url, timeout=self.settings["download_timeout_s"]
                ) as response,
                part.open("wb") as out,
            ):
                done = 0
                while chunk := response.read(DOWNLOAD_CHUNK):
                    if cancelled():
                        raise BackendError("The download was cancelled.")
                    out.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress({"done": done, "total": expected})
            if part.stat().st_size != expected:
                raise BackendError("The downloaded file has the wrong size. Try again.")
            part.replace(target)
        except BackendError:
            raise
        except OSError as error:
            raise BackendError(f"The download failed: {error}") from error
        finally:
            part.unlink(missing_ok=True)

    # ---- prediction -------------------------------------------------------------------------
    def _device(self) -> str:
        wanted = self.config["hardware"]["device"]
        if wanted == "cpu" or not torch.cuda.is_available():
            return "cpu"
        return "cuda"

    def _load(self):
        with self._load_lock:
            if self._predictor is None:
                model = sam_model_registry[self.settings["model_type"]](
                    checkpoint=str(self.weights_path())
                )
                model.to(self._device())
                self._predictor = SamPredictor(model)
            return self._predictor

    def predict(self, request: PredictRequest) -> list[Suggestion]:
        if request.task != TASK_SEGMENT_POINT:
            raise BackendError("Segment Anything only outlines objects you click.")
        from PIL import Image, ImageOps

        predictor = self._load()
        stat = request.image_path.stat()
        key = (str(request.image_path), stat.st_mtime_ns, stat.st_size)
        if self._embedded != key:  # the image embedding is the slow part; reuse it for more clicks
            with Image.open(request.image_path) as raw:
                rgb = np.asarray(ImageOps.exif_transpose(raw).convert("RGB"))
            if rgb.shape[1] != request.width or rgb.shape[0] != request.height:
                raise BackendError("The image on disk does not match its recorded size.")
            predictor.set_image(rgb)
            self._embedded = key
        coords = (
            np.array([[x, y] for x, y, _ in request.points], dtype=np.float32)
            if request.points
            else None
        )
        labels = (
            np.array([label for _, _, label in request.points], dtype=np.int32)
            if request.points
            else None
        )
        box = None
        if request.box is not None:
            x, y, w, h = request.box
            box = np.array([x, y, x + w, y + h], dtype=np.float32)
        with torch.inference_mode():
            masks, scores, _ = predictor.predict(
                point_coords=coords, point_labels=labels, box=box, multimask_output=True
            )
        seed = next(((x, y) for x, y, label in request.points if label == 1), None)
        suggestions = []
        for index in np.argsort(-scores)[: request.max_results]:
            polygon = mask_to_polygon(masks[index], seed, self.settings["polygon_epsilon_px"])
            if polygon:
                suggestions.append(Suggestion("polygon", {"points": polygon}, float(scores[index])))
        return suggestions
