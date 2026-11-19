# ML-backend protocol (version 1)

How AI assist works in Local Vision Studio (Stage 4). Code: `studio/mlbackend/`. UI: `studio/web/js/assist.js`.

## Rules
1. **Local only.** A backend whose `info().local_only` is false is disabled unless `ml.allow_remote_backends: true`. Image bytes never leave the machine; the only network use is the one-time weight download the user starts.
2. **Nothing is saved without an accept.** `POST /api/images/{id}/suggest` returns suggestions and stores nothing. Accepting hands plain annotations to the annotator, which saves them through the normal path (undoable, one Undo per accepted batch).
3. **Backends are not trusted.** The service re-validates every result with the same rules as a saved annotation (bounds, minimum size, polygon area), clamps scores to 0..1, sorts, caps, and reports how many it dropped.
4. **Every backend has a fake** (`fake`, labelled "Demo backend (made-up results, not real AI)").
5. **Licence recorded before weights are added** (Development Rule 4).

## The interface (`studio/mlbackend/protocol.py`)
```python
class MLBackend(Protocol):
    def info(self) -> BackendInfo      # id, name, version, tasks, local_only, available, reason, licence, simulated
    def health(self) -> tuple[bool, str]
    def predict(self, request: PredictRequest) -> list[Suggestion]
```
Coordinates are pixels of the EXIF-oriented image, origin top-left (the annotation space).

| Task | Prompt fields | Result |
|------|---------------|--------|
| `segment_point` | `points` = (x, y, label) with label 1 inside / 0 outside; optional `box` (x, y, w, h) | `polygon` suggestions |
| `detect_text` | `text`, e.g. "pallet, forklift" | `box` suggestions, `label` = matched phrase |

A `Suggestion` is `{kind: box|polygon, data, score 0..1, label}`; `data` has the same shape as an annotation's data. A backend that cannot run raises `BackendError` with a message written for the user.

## HTTP
- `GET /api/ml/backends` → `{backends: [info + can_download], default_min_score}`
- `POST /api/ml/backends/{id}/download` → 202 `{job_id}` (a job of kind `download`; progress in `done`/`total` bytes)
- `POST /api/images/{id}/suggest` `{backend, task, points, box, text, max_results}` → `{suggestions, dropped, milliseconds, backend, task}`. 400 bad request (message says what), 404 unknown image/backend, 409 backend unavailable or failed.

## Built-in backends
| id | Tasks | Notes |
|----|-------|-------|
| `fake` | both | Deterministic, made-up. For tests, demos, and trying the UI. |
| `sam` | `segment_point` | Meta Segment Anything `vit_b`. **Licence: Apache-2.0** (the official repository page states "The model is licensed under the Apache 2.0 license"; checked 2026-11-19; it does not separately mention the checkpoint). Needs `pip install segment-anything==1.0` and a 375 MB weight file (`ml.sam.checkpoint_url`), downloaded on request into `<data_dir>/models`. The image embedding is cached per image so extra clicks are fast. The mask becomes a polygon with `studio/mlbackend/masks.py` (numpy only). |

Not built: zero-shot text detection (Grounding DINO / OWLv2 need a licence and VRAM check first, plan item 4.3), box prompts in the UI, negative-click refinement beyond Alt+click.

## Writing a new backend
Implement the three methods, register it in `service.build_backends` and `ml.backends`, and add it to `check_contract` in `tests/test_mlbackend.py`.

## Review UX (annotator)
Tool `M`. "Click an object" outlines what you click; "Describe objects" finds boxes for the phrases. Suggestions are dashed with their score; the slider hides low scores (default `ml.default_min_score`); each can be accepted or rejected, or all shown at once (Enter / Esc, or click a suggestion to accept it). A suggestion takes the project class with the same name as its label, else the active class.
