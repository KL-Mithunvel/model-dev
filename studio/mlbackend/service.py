"""The ML service: picks backends from ``config.yaml``, checks requests, cleans results.

Backends are untrusted code paths in the sense that they may return nonsense (an out-of-image box,
a NaN score, a polygon with two points). ``MLService.predict`` therefore re-validates every result
with the same rules the annotation save uses and counts what it had to drop. Nothing is stored.
"""

import logging
import math
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio import annotations
from studio.mlbackend.protocol import (
    TASK_DETECT_TEXT,
    TASK_SEGMENT_POINT,
    TASKS,
    BackendError,
    BackendInfo,
    MLBackend,
    PredictRequest,
    Suggestion,
)

logger = logging.getLogger(__name__)
BACKEND_CHOICES = ("fake", "sam")


@dataclass(frozen=True)
class PredictResult:
    suggestions: list[Suggestion]
    dropped: int  # results the backend returned that failed validation
    milliseconds: int

    def as_dict(self, backend: str, task: str) -> dict[str, Any]:
        return {
            "backend": backend,
            "task": task,
            "suggestions": [s.as_dict() for s in self.suggestions],
            "dropped": self.dropped,
            "milliseconds": self.milliseconds,
        }


def build_backends(config: dict[str, Any]) -> dict[str, MLBackend]:
    """The backends named in ``ml.backends``. Raises ValueError for an unknown name."""
    built: dict[str, MLBackend] = {}
    for name in config["ml"]["backends"]:
        if name == "fake":
            from studio.mlbackend.fake import FakeBackend

            built[name] = FakeBackend()
        elif name == "sam":
            from studio.mlbackend.sam import SamBackend

            built[name] = SamBackend(config)
        else:
            raise ValueError(
                f"ml.backends: unknown backend {name!r}; use one of {BACKEND_CHOICES}."
            )
    return built


class MLService:
    def __init__(
        self, config: dict[str, Any], backends: dict[str, MLBackend] | None = None
    ) -> None:
        self.config = config
        self.settings = config["ml"]
        self._backends = backends if backends is not None else build_backends(config)
        # One prediction at a time: models share one GPU, and two clicks racing would only slow both.
        self._lock = threading.Lock()

    # ---- discovery --------------------------------------------------------------------------
    def infos(self) -> list[BackendInfo]:
        """Every configured backend, with ``available`` forced off if it would leave the machine."""
        result = []
        for backend in self._backends.values():
            info = backend.info()
            if not info.local_only and not self.settings["allow_remote_backends"]:
                info = BackendInfo(
                    **{
                        **info.__dict__,
                        "available": False,
                        "reason": "This backend sends images off this computer, which "
                        "ml.allow_remote_backends does not allow.",
                    }
                )
            result.append(info)
        return result

    def backend(self, backend_id: str) -> MLBackend | None:
        return self._backends.get(backend_id)

    def info(self, backend_id: str) -> BackendInfo:
        for info in self.infos():
            if info.id == backend_id:
                return info
        raise LookupError(f"There is no backend called “{backend_id}”.")

    # ---- prediction -------------------------------------------------------------------------
    def check_request(self, request: PredictRequest) -> None:
        """Raise ValueError (message for the user) if the request itself is unusable."""
        limits = self.settings
        if request.task not in TASKS:
            raise ValueError(f"The task must be one of {list(TASKS)}.")
        if request.task == TASK_SEGMENT_POINT:
            if not request.points and request.box is None:
                raise ValueError("Click on the object first.")
            if len(request.points) > limits["max_prompt_points"]:
                raise ValueError(f"At most {limits['max_prompt_points']} clicks are used at once.")
            for x, y, label in request.points:
                self._check_finite((x, y), "A click")
                if label not in (0, 1):
                    raise ValueError("A click is either inside (1) or outside (0) the object.")
                if not (0 <= x <= request.width and 0 <= y <= request.height):
                    raise ValueError("A click is outside the image.")
            if request.box is not None:
                self._check_finite(request.box, "The box")
        if request.task == TASK_DETECT_TEXT:
            text = request.text.strip()
            if not text:
                raise ValueError("Describe what to find, for example “pallet, forklift”.")
            if len(text) > limits["max_text_length"]:
                raise ValueError(
                    f"The description is at most {limits['max_text_length']} characters."
                )

    @staticmethod
    def _check_finite(values: Sequence[float], what: str) -> None:
        if any(isinstance(v, bool) or not math.isfinite(v) for v in values):
            raise ValueError(f"{what} has a value that is not a finite number.")

    def predict(self, backend_id: str, request: PredictRequest) -> PredictResult:
        """Run a backend and return cleaned suggestions.

        Raises LookupError (unknown backend), ValueError (bad request) or BackendError (the backend
        is unavailable or failed; the message says why).
        """
        info = self.info(backend_id)
        if request.task not in info.tasks:
            raise ValueError(f"“{info.name}” cannot do “{request.task}”.")
        if not info.available:
            raise BackendError(info.reason or f"“{info.name}” is not available.")
        self.check_request(request)
        if not Path(request.image_path).is_file():
            raise BackendError("The image file is missing on disk.")
        backend = self._backends[backend_id]
        started = time.perf_counter()
        with self._lock:
            try:
                raw = backend.predict(request)
            except BackendError:
                raise
            except Exception as error:  # a model crash must not take the server down
                logger.exception("backend %s failed", backend_id)
                raise BackendError(
                    f"“{info.name}” failed ({type(error).__name__}). See the server log for details."
                ) from error
        cleaned, dropped = self.clean(raw, request)
        return PredictResult(cleaned, dropped, round((time.perf_counter() - started) * 1000))

    def clean(
        self, raw: Sequence[Suggestion], request: PredictRequest
    ) -> tuple[list[Suggestion], int]:
        """Validate every suggestion like a saved annotation; drop and count the rest."""
        kept: list[Suggestion] = []
        dropped = 0
        for index, suggestion in enumerate(raw, start=1):
            try:
                score = float(suggestion.score)
                if not math.isfinite(score):
                    raise annotations.AnnotationError("score is not finite")
                if suggestion.kind not in ("box", "polygon"):
                    raise annotations.AnnotationError("a suggestion is a box or a polygon")
                valid = annotations.validate_annotation(
                    {"kind": suggestion.kind, "data": suggestion.data},
                    index,
                    request.width,
                    request.height,
                    self.config["annotations"],
                )
            except (annotations.AnnotationError, TypeError, ValueError):
                dropped += 1
                continue
            label = suggestion.label.strip()[:80] if isinstance(suggestion.label, str) else None
            kept.append(
                Suggestion(valid["kind"], valid["data"], min(max(score, 0.0), 1.0), label or None)
            )
        kept.sort(key=lambda s: -s.score)
        cap = min(request.max_results, self.settings["max_suggestions"])
        dropped += max(0, len(kept) - cap)
        return kept[:cap], dropped
