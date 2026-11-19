"""The ML-backend protocol (Stage 4.1): images in, suggestions out. Pure data, no I/O.

A backend is anything with ``info()``, ``health()`` and ``predict()``. The app never saves a
suggestion by itself: it returns them to the browser, and only an explicit accept in the annotator
turns one into a real annotation (so nothing a model guesses can reach a dataset unreviewed).

Protocol version 1. Tasks:

* ``segment_point`` — "what object is at this point?" Prompt: ``points`` (x, y, label) with label
  1 = inside the object, 0 = not the object; optional ``box`` [x, y, w, h]. Result: polygons.
* ``detect_text`` — "find these objects". Prompt: ``text`` (for example "pallet, forklift").
  Result: boxes, each with the matched phrase as ``label``.

Coordinates are pixels of the EXIF-oriented image, origin top-left (the same space as annotations).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

PROTOCOL_VERSION = 1
TASK_SEGMENT_POINT = "segment_point"
TASK_DETECT_TEXT = "detect_text"
TASKS = (TASK_SEGMENT_POINT, TASK_DETECT_TEXT)


@dataclass(frozen=True)
class BackendInfo:
    """What a backend is and whether it can run right now."""

    id: str  # stable short name used in the API and config, such as "sam"
    name: str  # human name
    version: str
    tasks: tuple[str, ...]
    local_only: bool  # True: images never leave this computer
    available: bool  # can it predict right now?
    reason: str = ""  # when not available: what is missing and what to do about it
    licence: str = ""  # code and weights, recorded before a weight is added (Development Rule 4)
    protocol_version: int = PROTOCOL_VERSION
    simulated: bool = False  # True for fakes: results are made up, never from a real model

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "tasks": list(self.tasks),
            "local_only": self.local_only,
            "available": self.available,
            "reason": self.reason,
            "licence": self.licence,
            "protocol_version": self.protocol_version,
            "simulated": self.simulated,
        }


@dataclass(frozen=True)
class PredictRequest:
    task: str
    image_path: Path
    width: int  # oriented size, from the database
    height: int
    points: Sequence[tuple[float, float, int]] = ()
    box: tuple[float, float, float, float] | None = None
    text: str = ""
    max_results: int = 20


@dataclass(frozen=True)
class Suggestion:
    kind: str  # "box" | "polygon"
    data: dict[str, Any]  # same shape as an annotation's data
    score: float  # 0..1; how sure the backend is
    label: str | None = None  # a class name the backend thinks this is (may match a project class)
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "data": self.data,
            "score": round(self.score, 4),
            "label": self.label,
        }


class BackendError(Exception):
    """A backend could not do what was asked. The message is shown to the user, so write it for them."""


class MLBackend(Protocol):
    def info(self) -> BackendInfo: ...

    def health(self) -> tuple[bool, str]:
        """(ok, message). Cheap: no model loading unless it is already loaded."""
        ...

    def predict(self, request: PredictRequest) -> list[Suggestion]: ...
