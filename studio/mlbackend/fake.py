"""A deterministic fake backend (Development Rule 8): runs anywhere, needs no model or GPU.

Its results are MADE UP: a small octagon where you click, and a few boxes whose positions come from
a hash of the prompt text. It exists so the protocol, the review UI and the tests work on any
machine, and it says so in its ``info()`` (``simulated=True``) so nobody mistakes it for real AI.
"""

import hashlib
import math
import re

from studio.mlbackend.protocol import (
    TASK_DETECT_TEXT,
    TASK_SEGMENT_POINT,
    BackendError,
    BackendInfo,
    PredictRequest,
    Suggestion,
)

FAKE_SCORES = (
    0.95,
    0.70,
    0.40,
)  # one box per score, so a confidence filter has something to filter
OCTAGON_SIDES = 8
CLICK_RADIUS_FRACTION = 0.08  # of the shorter image side
MIN_CLICK_RADIUS_PX = 6.0


def split_phrases(text: str) -> list[str]:
    """'pallet, forklift and box' -> ['pallet', 'forklift', 'box']."""
    parts = re.split(r",|;|\band\b", text, flags=re.IGNORECASE)
    return [part.strip() for part in parts if part.strip()]


def _unit(seed: str, index: int) -> float:
    """A repeatable number in [0, 1) from text."""
    digest = hashlib.sha256(f"{seed}:{index}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


class FakeBackend:
    id = "fake"

    def info(self) -> BackendInfo:
        return BackendInfo(
            id=self.id,
            name="Demo backend (made-up results, not real AI)",
            version="1",
            tasks=(TASK_SEGMENT_POINT, TASK_DETECT_TEXT),
            local_only=True,
            available=True,
            licence="none (no model)",
            simulated=True,
        )

    def health(self) -> tuple[bool, str]:
        return True, "ok"

    def predict(self, request: PredictRequest) -> list[Suggestion]:
        if request.task == TASK_SEGMENT_POINT:
            return self._segment(request)
        if request.task == TASK_DETECT_TEXT:
            return self._detect(request)
        raise BackendError(f"The demo backend cannot do “{request.task}”.")

    def _segment(self, request: PredictRequest) -> list[Suggestion]:
        positives = [(x, y) for x, y, label in request.points if label == 1]
        if positives:
            cx, cy = positives[0]
        elif request.box is not None:
            x, y, w, h = request.box
            cx, cy = x + w / 2, y + h / 2
        else:
            raise BackendError("Click on the object first.")
        radius = max(
            MIN_CLICK_RADIUS_PX, CLICK_RADIUS_FRACTION * min(request.width, request.height)
        )
        points = [
            [
                min(max(cx + radius * math.cos(2 * math.pi * i / OCTAGON_SIDES), 0), request.width),
                min(
                    max(cy + radius * math.sin(2 * math.pi * i / OCTAGON_SIDES), 0), request.height
                ),
            ]
            for i in range(OCTAGON_SIDES)
        ]
        return [Suggestion("polygon", {"points": points}, 0.9)]

    def _detect(self, request: PredictRequest) -> list[Suggestion]:
        phrases = split_phrases(request.text)
        if not phrases:
            raise BackendError("Describe what to find, for example “pallet, forklift”.")
        found = []
        for phrase in phrases:
            for index, score in enumerate(FAKE_SCORES):
                width = request.width * (0.12 + 0.12 * _unit(phrase, index * 4 + 2))
                height = request.height * (0.12 + 0.12 * _unit(phrase, index * 4 + 3))
                x = (request.width - width) * _unit(phrase, index * 4)
                y = (request.height - height) * _unit(phrase, index * 4 + 1)
                found.append(
                    Suggestion("box", {"x": x, "y": y, "w": width, "h": height}, score, phrase)
                )
        return found
