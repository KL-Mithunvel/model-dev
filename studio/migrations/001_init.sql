-- v0.1 schema. Annotations arrive in Stage 2 (see docs/PLAN.md).
-- Image width/height are the EXIF-ORIENTED dimensions (what a browser displays).

CREATE TABLE projects (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL
);

-- One row per import run: provenance for every image and a record of what was skipped.
CREATE TABLE batches (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    added       INTEGER NOT NULL DEFAULT 0,
    duplicates  INTEGER NOT NULL DEFAULT 0,
    corrupt     INTEGER NOT NULL DEFAULT 0,
    oversize    INTEGER NOT NULL DEFAULT 0,
    unsupported INTEGER NOT NULL DEFAULT 0,
    problems    TEXT    NOT NULL DEFAULT '[]'   -- JSON list of {"path", "reason"}
);

CREATE TABLE images (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_id      INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    sha256        TEXT    NOT NULL,
    stored_name   TEXT    NOT NULL,             -- <sha256><ext>, inside the project images folder
    original_name TEXT    NOT NULL,
    width         INTEGER NOT NULL,
    height        INTEGER NOT NULL,
    bytes         INTEGER NOT NULL,
    split         TEXT    CHECK (split IN ('train', 'val', 'test')),
    created_at    TEXT    NOT NULL,
    UNIQUE (project_id, sha256)
);
CREATE INDEX idx_images_project_split ON images(project_id, split);
CREATE INDEX idx_images_batch ON images(batch_id);

CREATE TABLE image_tags (
    image_id  INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    tag       TEXT    NOT NULL,
    PRIMARY KEY (image_id, tag)
);
CREATE INDEX idx_image_tags_tag ON image_tags(tag);
