# FEATURES — clean-room notes on the reference platform (Gate G1)

Purpose: record *what* a hosted computer-vision platform (Roboflow) does, so we can design our own local equivalent. **Sources are public documentation only** (read 2026-11-06). Everything below is paraphrased; no code, assets or protected text was copied (Development Rule 5, `docs/REA.md`). "Our approach" is our own design decision and may differ.

Sources: docs home <https://docs.roboflow.com/> · data <https://docs.roboflow.com/datasets/create-and-upload/adding-data> · versions <https://docs.roboflow.com/datasets/dataset-versions> · models <https://docs.roboflow.com/models> · open-source `supervision` <https://supervision.roboflow.com/> (licence to be confirmed from its repo before any reuse).

## 1. Feature map
| Area | What the reference does (public docs) | Our approach | Stage |
|------|----------------------------------------|--------------|-------|
| Projects | A project is the container for data; types include image-based (video split into frames), action recognition (whole videos), classification | One project = one task type set (detection, classification, segmentation, keypoints). Images only in v1 | 1 |
| Adding data | Web upload (suggested for under ~1,000 images), CLI/SDK/HTTP API for large sets, cloud-bucket mirroring, camera capture | Folder/zip import in the UI plus a CLI import; no cloud mirroring (offline-first) | 1 |
| Image limits | JPG, PNG, WEBP, AVIF, BMP, HEIC/HEIF; 30 MB per file; 16,384 px per side; ~179 MP total | Support the same common formats; limits live in `config.yaml`; oversize files reported, not silently dropped | 1 |
| Batches | Each upload becomes a batch; shown on the annotate page; zip with labels creates an annotation job | Every import is a recorded batch with timestamp, source and counts; filterable | 1 |
| Duplicates | Images already in the project are skipped on upload; removing an image keeps its annotations so re-upload restores them | Content-hash duplicate detection; "removed" images are soft-deleted with their labels kept | 1 |
| Tags and metadata | Tags and metadata settable at upload via API | Tags and free metadata on images; searchable | 1 |
| Splits | train / valid / test, from folder names or chosen at upload | Split tool with stratification; recorded in dataset versions | 1, 3 |
| Class names | Names normalised on upload/import/export (whitespace trimmed; characters such as `/` and `#` replaced) | Same idea: one normalisation function, applied at every boundary, with a visible rename map | 1, 3 |
| Annotation formats import | 40+ formats, only together with their images | COCO, YOLO, CVAT, Label Studio first (`docs/FORMATS.md`) | 3 |
| Annotation | Box, polygon, keypoint and class labelling, review mode with approval, AI-assisted labelling | Own canvas annotator (`docs/UX.md`); review/approve status per image; ML-backend protocol for AI assist | 2, 4 |
| Dataset versions | Point-in-time snapshot of images and labels; preprocessing and augmentation chosen at creation; counts per split; export in training-ready formats; delete goes to trash | Immutable snapshot with manifest hash; preprocessing recorded; augmentation applied at train time or materialised (decide in Stage 3); trash with restore | 3 |
| Preprocessing | Examples named: resize (e.g. stretch), auto-orient, grayscale | Resize modes, EXIF auto-orient, grayscale, normalisation; stored in the version manifest | 3 |
| Augmentation | Examples named: rotate, brightness, noise, crop, flips, exposure, image multiplier | Same families via a library chosen later (licence check); train split only | 3, 6 |
| Training | Dashboard/API/SDK/CLI training; auto-train from first approved labels; architecture search; train from a published checkpoint | Local training from a dataset version; checkpoints; resume; (auto-train after N approved labels is an idea for Stage 7) | 6 |
| Evaluation | Metrics and graphs per job; mAP; confusion matrices; evaluation runs | mAP, per-class precision/recall, confusion matrix, worst-prediction browser | 7 |
| Deployment | Serverless API, dedicated deployments, self-hosted inference | Not needed: everything runs locally; export files instead | 7 |
| Workflows | Chain vision steps into a pipeline | Out of scope for v1 (revisit after v1.0) | — |
| Universe (public sharing) | Private projects hidden from the public registry | Out of scope; privacy by default | — |
| Agents/MCP | An MCP server lets agents upload and manage data | Possible later: expose our own API as MCP | post-1.0 |

## 2. Things the reference does not document publicly (do not guess)
- How splits are assigned automatically, and whether edits after a version is created affect it.
- Version count limits.
- Precision/recall presentation (docs only name mAP and confusion matrices).
- Exact preprocessing/augmentation semantics (parameter ranges).
Where we need these, we decide ourselves and record the decision in `docs/PLAN.md`.

## 3. What we deliberately do differently
- Fully offline after a one-time weight download; no accounts, credits or paywall.
- Local hardware monitoring during training (not described in the reference docs we read).
- Neutral open formats with import/export adapters instead of a proprietary dataset store.
- Remote training workers on the owner's own machines instead of a hosted cloud.

## 4. Open questions for the owner
- Do you want an "auto-train after N approved labels" feature (Stage 7)?
- Is review/approval per image wanted for a single user, or can that be skipped?
