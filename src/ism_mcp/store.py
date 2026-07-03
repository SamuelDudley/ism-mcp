"""SQLite-backed store for ISM controls across versions."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .models import ControlRecord

_FTS_WORD = re.compile(r"\w+", re.UNICODE)
_ID_DIGITS = re.compile(r"\d+")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    version       TEXT PRIMARY KEY,
    label         TEXT,
    published     TEXT,
    last_modified TEXT,
    oscal_version TEXT,
    git_tag       TEXT,
    git_commit    TEXT,
    ingested_at   TEXT,
    control_count INTEGER
);

CREATE TABLE IF NOT EXISTS controls (
    version          TEXT NOT NULL,
    identifier       TEXT NOT NULL,
    label            TEXT,
    title            TEXT,
    control_class    TEXT,
    guideline        TEXT NOT NULL,
    section          TEXT NOT NULL,
    topic            TEXT NOT NULL,
    description      TEXT NOT NULL,
    control_revision TEXT,
    updated          TEXT,
    sort_id          TEXT,
    applies_nc      INTEGER NOT NULL,
    applies_os      INTEGER NOT NULL,
    applies_p       INTEGER NOT NULL,
    applies_s       INTEGER NOT NULL,
    applies_ts      INTEGER NOT NULL,
    maturity_ml1    INTEGER NOT NULL,
    maturity_ml2    INTEGER NOT NULL,
    maturity_ml3    INTEGER NOT NULL,
    PRIMARY KEY (version, identifier)
);

CREATE INDEX IF NOT EXISTS controls_by_identifier ON controls(identifier);

CREATE VIRTUAL TABLE IF NOT EXISTS controls_fts USING fts5(
    identifier UNINDEXED,
    description,
    topic,
    section,
    guideline,
    content='controls',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS controls_ai AFTER INSERT ON controls BEGIN
    INSERT INTO controls_fts(rowid, identifier, description, topic, section, guideline)
    VALUES (new.rowid, new.identifier, new.description, new.topic, new.section, new.guideline);
END;

CREATE TRIGGER IF NOT EXISTS controls_ad AFTER DELETE ON controls BEGIN
    INSERT INTO controls_fts(controls_fts, rowid, identifier, description, topic, section, guideline)
    VALUES ('delete', old.rowid, old.identifier, old.description, old.topic, old.section, old.guideline);
END;

CREATE TABLE IF NOT EXISTS controls_embeddings (
    version    TEXT NOT NULL,
    identifier TEXT NOT NULL,
    embedding  BLOB NOT NULL,
    PRIMARY KEY (version, identifier)
);
"""

ACTIVE_VERSION_KEY = "active_version"

CLASSIFICATIONS = ("NC", "OS", "P", "S", "TS")
MATURITIES = ("ML1", "ML2", "ML3")


@dataclass(frozen=True)
class Control:
    version: str
    identifier: str
    label: str
    title: str
    control_class: str
    guideline: str
    section: str
    topic: str
    description: str
    control_revision: str | None
    updated: str | None
    sort_id: str | None
    applies: dict[str, bool]
    maturity: dict[str, bool]

    def as_dict(self) -> ControlRecord:
        return {
            "version": self.version,
            "identifier": self.identifier,
            "label": self.label,
            "title": self.title,
            "control_class": self.control_class,
            "guideline": self.guideline,
            "section": self.section,
            "topic": self.topic,
            "description": self.description,
            "control_revision": self.control_revision,
            "updated": self.updated,
            "sort_id": self.sort_id,
            "applies": dict(self.applies),  # type: ignore[typeddict-item]
            "maturity": dict(self.maturity),  # type: ignore[typeddict-item]
        }


class IncompatibleSchemaError(RuntimeError):
    pass


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _verify_schema(conn, path)
    return conn


def _verify_schema(conn: sqlite3.Connection, path: Path) -> None:
    """Reject a pre-existing database written by an older, incompatible schema.

    `CREATE TABLE IF NOT EXISTS` leaves an old-shaped `controls` table untouched, so a
    missing `version` column means the file predates the version-keyed schema.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(controls)")}
    if "version" not in cols:
        raise IncompatibleSchemaError(
            f"database at {path} uses an incompatible older schema. "
            "Re-ingest with --fresh to rebuild it, or delete the file."
        )


def reset(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS controls_embeddings;
        DROP TRIGGER IF EXISTS controls_ai;
        DROP TRIGGER IF EXISTS controls_ad;
        DROP TABLE IF EXISTS controls_fts;
        DROP TABLE IF EXISTS controls;
        DROP TABLE IF EXISTS versions;
        DROP TABLE IF EXISTS meta;
        """
    )
    conn.executescript(SCHEMA)


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def upsert_version(
    conn: sqlite3.Connection,
    *,
    version: str,
    label: str | None,
    published: str | None,
    last_modified: str | None,
    oscal_version: str | None,
    git_tag: str | None,
    git_commit: str | None,
    ingested_at: str,
    control_count: int,
) -> None:
    conn.execute(
        """
        INSERT INTO versions(
            version, label, published, last_modified, oscal_version,
            git_tag, git_commit, ingested_at, control_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(version) DO UPDATE SET
            label=excluded.label, published=excluded.published,
            last_modified=excluded.last_modified, oscal_version=excluded.oscal_version,
            git_tag=excluded.git_tag, git_commit=excluded.git_commit,
            ingested_at=excluded.ingested_at, control_count=excluded.control_count
        """,
        (
            version,
            label,
            published,
            last_modified,
            oscal_version,
            git_tag,
            git_commit,
            ingested_at,
            control_count,
        ),
    )
    conn.commit()


def list_versions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM versions ORDER BY version DESC").fetchall()
    return [dict(r) for r in rows]


def get_version(conn: sqlite3.Connection, version: str) -> dict | None:
    row = conn.execute("SELECT * FROM versions WHERE version = ?", (version,)).fetchone()
    return dict(row) if row else None


def delete_version(conn: sqlite3.Connection, version: str) -> None:
    conn.execute("DELETE FROM controls_embeddings WHERE version = ?", (version,))
    conn.execute("DELETE FROM controls WHERE version = ?", (version,))
    conn.execute("DELETE FROM versions WHERE version = ?", (version,))
    conn.commit()


def set_active_version(conn: sqlite3.Connection, version: str) -> None:
    set_meta(conn, ACTIVE_VERSION_KEY, version)


def get_active_version(conn: sqlite3.Connection) -> str | None:
    return get_meta(conn, ACTIVE_VERSION_KEY)


def _resolve_version(conn: sqlite3.Connection, version: str | None) -> str | None:
    return version if version is not None else get_active_version(conn)


def normalise_identifier(
    conn: sqlite3.Connection, raw: str, version: str | None = None
) -> str | None:
    """Resolve a user identifier (ism-1001, ISM-1001, 1001, or a label) to a canonical id."""
    version = _resolve_version(conn, version)
    if version is None:
        return None
    low = raw.strip().lower()
    row = conn.execute(
        "SELECT identifier FROM controls WHERE version = ? AND lower(identifier) = ?",
        (version, low),
    ).fetchone()
    if row:
        return row["identifier"]
    digits = "".join(_ID_DIGITS.findall(low))
    if digits and ("ism" in low or low == digits):
        cand = f"ism-{int(digits):04d}"
        row = conn.execute(
            "SELECT identifier FROM controls WHERE version = ? AND identifier = ?",
            (version, cand),
        ).fetchone()
        if row:
            return row["identifier"]
    row = conn.execute(
        "SELECT identifier FROM controls WHERE version = ? AND upper(label) = ?",
        (version, raw.strip().upper()),
    ).fetchone()
    return row["identifier"] if row else None


def insert_controls(conn: sqlite3.Connection, controls: Iterable[Control]) -> int:
    count = 0
    for c in controls:
        conn.execute(
            """
            INSERT INTO controls(
                version, identifier, label, title, control_class,
                guideline, section, topic, description, control_revision, updated, sort_id,
                applies_nc, applies_os, applies_p, applies_s, applies_ts,
                maturity_ml1, maturity_ml2, maturity_ml3
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c.version,
                c.identifier,
                c.label,
                c.title,
                c.control_class,
                c.guideline,
                c.section,
                c.topic,
                c.description,
                c.control_revision,
                c.updated,
                c.sort_id,
                int(c.applies["NC"]),
                int(c.applies["OS"]),
                int(c.applies["P"]),
                int(c.applies["S"]),
                int(c.applies["TS"]),
                int(c.maturity["ML1"]),
                int(c.maturity["ML2"]),
                int(c.maturity["ML3"]),
            ),
        )
        count += 1
    conn.commit()
    return count


def _row_to_control(row: sqlite3.Row) -> Control:
    return Control(
        version=row["version"],
        identifier=row["identifier"],
        label=row["label"],
        title=row["title"],
        control_class=row["control_class"],
        guideline=row["guideline"],
        section=row["section"],
        topic=row["topic"],
        description=row["description"],
        control_revision=row["control_revision"],
        updated=row["updated"],
        sort_id=row["sort_id"],
        applies={c: bool(row[f"applies_{c.lower()}"]) for c in CLASSIFICATIONS},
        maturity={m: bool(row[f"maturity_{m.lower()}"]) for m in MATURITIES},
    )


def get_control(
    conn: sqlite3.Connection, identifier: str, version: str | None = None
) -> Control | None:
    version = _resolve_version(conn, version)
    if version is None:
        return None
    row = conn.execute(
        "SELECT * FROM controls WHERE version = ? AND identifier = ?", (version, identifier)
    ).fetchone()
    if row is None:
        canon = normalise_identifier(conn, identifier, version)
        if canon is not None:
            row = conn.execute(
                "SELECT * FROM controls WHERE version = ? AND identifier = ?", (version, canon)
            ).fetchone()
    return _row_to_control(row) if row else None


def sanitise_fts_query(query: str) -> str:
    """Quote each run of word characters as an FTS5 phrase.

    Free-text input may contain FTS5 operators or punctuation that would
    otherwise raise a syntax or unknown-column error. Quoting neutralises them
    and treats every token as a literal term.
    """
    return " ".join(f'"{word}"' for word in _FTS_WORD.findall(query))


def search(
    conn: sqlite3.Connection, query: str, limit: int = 10, version: str | None = None
) -> list[Control]:
    version = _resolve_version(conn, version)
    match = sanitise_fts_query(query)
    if not match or version is None:
        return []
    rows = conn.execute(
        """
        SELECT c.* FROM controls c
        JOIN controls_fts ON controls_fts.rowid = c.rowid
        WHERE controls_fts MATCH ? AND c.version = ?
        ORDER BY rank
        LIMIT ?
        """,
        (match, version, limit),
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def list_by_classification(
    conn: sqlite3.Connection, classification: str, version: str | None = None
) -> list[Control]:
    cls = classification.upper()
    if cls not in CLASSIFICATIONS:
        raise ValueError(
            f"unknown classification {classification!r}, expected one of {CLASSIFICATIONS}"
        )
    version = _resolve_version(conn, version)
    rows = conn.execute(
        f"SELECT * FROM controls WHERE version = ? AND applies_{cls.lower()} = 1 "
        "ORDER BY identifier",
        (version,),
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def list_in_scope(
    conn: sqlite3.Connection,
    classification: str | None,
    maturity: str | None,
    sections: list[str] | None,
    version: str | None = None,
) -> list[Control]:
    """Controls matching all supplied filters within one version. Each filter is optional."""
    version = _resolve_version(conn, version)
    where: list[str] = ["version = ?"]
    params: list = [version]
    if classification is not None:
        cls = classification.upper()
        if cls not in CLASSIFICATIONS:
            raise ValueError(
                f"unknown classification {classification!r}, expected one of {CLASSIFICATIONS}"
            )
        where.append(f"applies_{cls.lower()} = 1")
    if maturity is not None:
        ml = maturity.upper()
        if ml not in MATURITIES:
            raise ValueError(f"unknown maturity {maturity!r}, expected one of {MATURITIES}")
        where.append(f"maturity_{ml.lower()} = 1")
    if sections:
        placeholders = ",".join(["?"] * len(sections))
        where.append(f"section IN ({placeholders})")
        params.extend(sections)
    clause = "WHERE " + " AND ".join(where)
    rows = conn.execute(
        f"SELECT * FROM controls {clause} ORDER BY identifier",
        params,
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def list_by_topic(
    conn: sqlite3.Connection, topic: str, version: str | None = None
) -> list[Control]:
    version = _resolve_version(conn, version)
    rows = conn.execute(
        "SELECT * FROM controls WHERE version = ? AND topic = ? ORDER BY identifier",
        (version, topic),
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def list_topics(conn: sqlite3.Connection, version: str | None = None) -> list[str]:
    version = _resolve_version(conn, version)
    rows = conn.execute(
        "SELECT DISTINCT topic FROM controls WHERE version = ? ORDER BY topic", (version,)
    ).fetchall()
    return [r["topic"] for r in rows]


def list_sections(conn: sqlite3.Connection, version: str | None = None) -> list[str]:
    version = _resolve_version(conn, version)
    rows = conn.execute(
        "SELECT DISTINCT section FROM controls WHERE version = ? ORDER BY section", (version,)
    ).fetchall()
    return [r["section"] for r in rows]


def list_controls(conn: sqlite3.Connection, version: str | None = None) -> list[Control]:
    """All controls for a version, ordered by sort_id then identifier. Used by diff."""
    version = _resolve_version(conn, version)
    rows = conn.execute(
        "SELECT * FROM controls WHERE version = ? ORDER BY sort_id, identifier", (version,)
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def count_controls(conn: sqlite3.Connection, version: str | None = None) -> int:
    version = _resolve_version(conn, version)
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM controls WHERE version = ?", (version,)
    ).fetchone()
    return int(row["n"])


def insert_embeddings(conn: sqlite3.Connection, rows: list[tuple[str, str, bytes]]) -> int:
    """rows are (version, identifier, embedding_bytes)."""
    conn.executemany(
        "INSERT OR REPLACE INTO controls_embeddings(version, identifier, embedding) "
        "VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def load_embedding_matrix(
    conn: sqlite3.Connection, dim: int, version: str | None = None
) -> tuple[np.ndarray, list[str]]:
    version = _resolve_version(conn, version)
    rows = conn.execute(
        "SELECT identifier, embedding FROM controls_embeddings WHERE version = ? "
        "ORDER BY identifier",
        (version,),
    ).fetchall()
    if not rows:
        return np.empty((0, dim), dtype=np.float32), []
    ids = [r["identifier"] for r in rows]
    matrix = np.frombuffer(b"".join(r["embedding"] for r in rows), dtype=np.float32)
    matrix = matrix.reshape(len(rows), dim)
    return matrix.copy(), ids
