"""SQLite access and forward-only migrations.

The schema version is stored in ``PRAGMA user_version``. Migration files live in
``studio/migrations`` and are named ``NNN_description.sql``; ``NNN`` is the version they bring
the database to. Migrations are applied in order, each inside one transaction.
"""

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{3})_[\w-]+\.sql$")


class MigrationError(Exception):
    """Raised when migration files are malformed or the database is newer than the code."""


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enforced.

    ``path`` may be ``":memory:"``. Parent folders of a file path are created.
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _migration_files(directory: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for file in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.match(file.name)
        if not match:
            raise MigrationError(f"Bad migration file name: {file.name} (expected NNN_name.sql)")
        found.append((int(match.group(1)), file))
    versions = [version for version, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"Migration numbers must be 1..N with no gaps, got {versions}")
    return found


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the database's current schema version."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> int:
    """Apply every pending migration and return the resulting schema version.

    Raises:
        MigrationError: bad migration names, or the database is newer than the code.
    """
    migrations = _migration_files(directory)
    current = schema_version(conn)
    latest = len(migrations)
    if current > latest:
        raise MigrationError(
            f"Database schema version {current} is newer than this code knows ({latest})."
        )
    for version, file in migrations:
        if version <= current:
            continue
        script = file.read_text(encoding="utf-8")
        # executescript() commits first, so wrap the script and the version bump in one script.
        try:
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error:
            # A failing statement leaves the BEGIN open; undo everything this migration did.
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return schema_version(conn)
