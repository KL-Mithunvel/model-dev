-- v0.5 (Stage 3.3): immutable dataset versions.
-- A version is a frozen copy of the LABELLED images of a project: their split, size, labels and
-- the class table, plus a recorded preprocessing description. Image bytes are not copied: they are
-- stored by sha256 and never change, so a version only records the hashes (a version is removed
-- with its project, which also removes the files).
-- Classes are referenced BY NAME inside a version (live class ids can change or be deleted).

ALTER TABLE projects ADD COLUMN next_version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE dataset_versions (
    id               INTEGER PRIMARY KEY,
    project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    number           INTEGER NOT NULL,                -- 1, 2, 3 ... never reused after a delete
    name             TEXT    NOT NULL DEFAULT '',
    created_at       TEXT    NOT NULL,
    content_hash     TEXT    NOT NULL,                -- sha256 of the canonical content (versions.py)
    manifest         TEXT    NOT NULL,                -- JSON: classes (with colours), preprocessing, counts
    image_count      INTEGER NOT NULL,
    annotation_count INTEGER NOT NULL,
    UNIQUE (project_id, number),
    UNIQUE (project_id, content_hash)
);

CREATE TABLE version_images (
    version_id     INTEGER NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE,
    sha256         TEXT    NOT NULL,
    original_name  TEXT    NOT NULL,
    stored_name    TEXT    NOT NULL,
    width          INTEGER NOT NULL,
    height         INTEGER NOT NULL,
    split          TEXT    CHECK (split IN ('train', 'val', 'test')),
    marked_empty   INTEGER NOT NULL CHECK (marked_empty IN (0, 1)),
    label_class    TEXT,                               -- single-label classification, by class name
    annotations    TEXT    NOT NULL,                   -- JSON [{"class": name, "kind", "data"}]
    PRIMARY KEY (version_id, sha256)
);
