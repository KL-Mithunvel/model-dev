import sqlite3

import pytest

from studio import db, paths
from studio.config import load_config


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    db.migrate(connection)
    yield connection
    connection.close()


def test_migrate_creates_schema_and_is_idempotent():
    connection = db.connect(":memory:")
    first = db.migrate(connection)
    second = db.migrate(connection)
    assert first == second >= 1
    tables = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"projects", "batches", "images", "image_tags"} <= tables


def test_database_newer_than_code_is_refused():
    connection = db.connect(":memory:")
    connection.execute("PRAGMA user_version = 999")
    with pytest.raises(db.MigrationError, match="newer"):
        db.migrate(connection)


def test_bad_migration_name_is_refused(tmp_path):
    (tmp_path / "oops.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(db.MigrationError, match="Bad migration"):
        db.migrate(db.connect(":memory:"), tmp_path)


def test_migration_gap_is_refused(tmp_path):
    (tmp_path / "002_two.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(db.MigrationError, match="no gaps"):
        db.migrate(db.connect(":memory:"), tmp_path)


def test_failed_migration_rolls_back(tmp_path):
    (tmp_path / "001_ok.sql").write_text("CREATE TABLE a (x INTEGER);", encoding="utf-8")
    (tmp_path / "002_bad.sql").write_text(
        "CREATE TABLE b (x INTEGER); SELECT * FROM missing_table;", encoding="utf-8"
    )
    connection = db.connect(":memory:")
    with pytest.raises(sqlite3.Error):
        db.migrate(connection, tmp_path)
    assert db.schema_version(connection) == 1  # 002 did not partially apply
    names = {r["name"] for r in connection.execute("SELECT name FROM sqlite_master")}
    assert "b" not in names


def test_project_names_are_unique(conn):
    conn.execute("INSERT INTO projects (name, created_at) VALUES ('p', 'now')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO projects (name, created_at) VALUES ('p', 'now')")


def test_invalid_split_is_rejected(conn):
    conn.execute("INSERT INTO projects (id, name, created_at) VALUES (1, 'p', 'now')")
    conn.execute("INSERT INTO batches (id, project_id, source, created_at) VALUES (1, 1, 's', 'n')")
    insert = (
        "INSERT INTO images (project_id, batch_id, sha256, stored_name, original_name, width,"
        " height, bytes, split, created_at) VALUES (1, 1, ?, 'a.jpg', 'a.jpg', 1, 1, 1, ?, 'n')"
    )
    conn.execute(insert, ("aa", "train"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("bb", "validation"))


def test_duplicate_hash_in_same_project_is_rejected_but_not_across_projects(conn):
    for pid in (1, 2):
        conn.execute(
            "INSERT INTO projects (id, name, created_at) VALUES (?, ?, 'n')", (pid, f"p{pid}")
        )
        conn.execute(
            "INSERT INTO batches (id, project_id, source, created_at) VALUES (?, ?, 's', 'n')",
            (pid, pid),
        )
    insert = (
        "INSERT INTO images (project_id, batch_id, sha256, stored_name, original_name, width,"
        " height, bytes, created_at) VALUES (?, ?, 'same', 'a.jpg', 'a.jpg', 1, 1, 1, 'n')"
    )
    conn.execute(insert, (1, 1))
    conn.execute(insert, (2, 2))  # other project: fine
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, (1, 1))


def test_deleting_a_project_cascades(conn):
    conn.execute("INSERT INTO projects (id, name, created_at) VALUES (1, 'p', 'n')")
    conn.execute("INSERT INTO batches (id, project_id, source, created_at) VALUES (1, 1, 's', 'n')")
    conn.execute(
        "INSERT INTO images (id, project_id, batch_id, sha256, stored_name, original_name, width,"
        " height, bytes, created_at) VALUES (1, 1, 1, 'h', 'a.jpg', 'a.jpg', 1, 1, 1, 'n')"
    )
    conn.execute("INSERT INTO image_tags (image_id, tag) VALUES (1, 't')")
    conn.execute("DELETE FROM projects WHERE id = 1")
    for table in ("batches", "images", "image_tags"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_connect_creates_parent_folders(tmp_path):
    target = tmp_path / "deep" / "er" / "x.sqlite"
    db.connect(target).close()
    assert target.is_file()


def test_paths_follow_config_and_resolve_relative_to_repo():
    config = load_config()
    assert paths.data_dir(config) == paths.REPO_ROOT / "data"
    assert paths.images_dir(config, 7) == paths.REPO_ROOT / "data" / "projects" / "7" / "images"
    assert paths.thumbs_dir(config, 7).name == "thumbs"
    assert paths.db_path(config).name == config["database"]["filename"]


def test_absolute_data_dir_is_respected(tmp_path):
    config = {"app": {"data_dir": str(tmp_path)}, "database": {"filename": "x.sqlite"}}
    assert paths.data_dir(config) == tmp_path
    assert paths.db_path(config) == tmp_path / "x.sqlite"
