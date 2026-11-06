-- v0.2: classes, annotations, per-image labelling state (docs/PLAN.md Stage 2).
-- Geometry is stored as JSON in PIXELS of the EXIF-oriented image, origin top-left:
--   box       {"x": n, "y": n, "w": n, "h": n}
--   polygon   {"points": [[x, y], ...]}
--   keypoints {"points": [[x, y, v], ...]}   v: 0 not labelled, 1 labelled but hidden, 2 visible

CREATE TABLE classes (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL COLLATE NOCASE,
    color       TEXT    NOT NULL,
    position    INTEGER NOT NULL,
    skeleton    TEXT,                          -- JSON {"names": [...], "edges": [[i, j], ...]}; v0.4
    created_at  TEXT    NOT NULL,
    UNIQUE (project_id, name)
);
CREATE INDEX idx_classes_project ON classes(project_id, position);

-- ON DELETE CASCADE (not RESTRICT) so deleting a project cannot fail on delete ordering.
-- The API refuses to delete a class that is in use unless the caller passes force.
CREATE TABLE annotations (
    id          INTEGER PRIMARY KEY,
    image_id    INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK (kind IN ('box', 'polygon', 'keypoints')),
    data        TEXT    NOT NULL,
    position    INTEGER NOT NULL,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX idx_annotations_image ON annotations(image_id, position);
CREATE INDEX idx_annotations_class ON annotations(class_id);

-- marked_empty: the user explicitly said "this image has no objects" (a deliberate negative).
-- label_class_id: single-label image classification.
-- annotations_rev: bumped on every save; clients send the revision they edited (optimistic lock).
ALTER TABLE images ADD COLUMN marked_empty INTEGER NOT NULL DEFAULT 0 CHECK (marked_empty IN (0, 1));
ALTER TABLE images ADD COLUMN label_class_id INTEGER REFERENCES classes(id) ON DELETE SET NULL;
ALTER TABLE images ADD COLUMN annotations_rev INTEGER NOT NULL DEFAULT 0;
