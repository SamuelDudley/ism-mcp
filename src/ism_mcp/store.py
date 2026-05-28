"""SQLite-backed store for ISM controls."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS controls (
    identifier      TEXT PRIMARY KEY,
    guideline       TEXT NOT NULL,
    section         TEXT NOT NULL,
    topic           TEXT NOT NULL,
    revision        TEXT,
    updated         TEXT,
    description     TEXT NOT NULL,
    applies_nc      INTEGER NOT NULL,
    applies_os      INTEGER NOT NULL,
    applies_p       INTEGER NOT NULL,
    applies_s       INTEGER NOT NULL,
    applies_ts      INTEGER NOT NULL,
    maturity_ml1    INTEGER NOT NULL,
    maturity_ml2    INTEGER NOT NULL,
    maturity_ml3    INTEGER NOT NULL,
    pdf_excerpt     TEXT,
    pdf_page        INTEGER
);

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

CREATE TABLE IF NOT EXISTS controls_embeddings (
    rowid     INTEGER PRIMARY KEY REFERENCES controls(rowid) ON DELETE CASCADE,
    embedding BLOB NOT NULL
);
"""


CLASSIFICATIONS = ("NC", "OS", "P", "S", "TS")
MATURITIES = ("ML1", "ML2", "ML3")


@dataclass(frozen=True)
class Control:
    identifier: str
    guideline: str
    section: str
    topic: str
    revision: str | None
    updated: str | None
    description: str
    applies: dict[str, bool]
    maturity: dict[str, bool]
    pdf_excerpt: str | None = None
    pdf_page: int | None = None

    def as_dict(self) -> dict:
        return {
            "identifier": self.identifier,
            "guideline": self.guideline,
            "section": self.section,
            "topic": self.topic,
            "revision": self.revision,
            "updated": self.updated,
            "description": self.description,
            "applies": dict(self.applies),
            "maturity": dict(self.maturity),
            "pdf_excerpt": self.pdf_excerpt,
            "pdf_page": self.pdf_page,
        }


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def reset(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS controls_embeddings;
        DROP TABLE IF EXISTS controls_fts;
        DROP TABLE IF EXISTS controls;
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


def insert_controls(conn: sqlite3.Connection, controls: Iterable[Control]) -> int:
    count = 0
    for c in controls:
        conn.execute(
            """
            INSERT INTO controls(
                identifier, guideline, section, topic, revision, updated, description,
                applies_nc, applies_os, applies_p, applies_s, applies_ts,
                maturity_ml1, maturity_ml2, maturity_ml3,
                pdf_excerpt, pdf_page
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c.identifier,
                c.guideline,
                c.section,
                c.topic,
                c.revision,
                c.updated,
                c.description,
                int(c.applies["NC"]),
                int(c.applies["OS"]),
                int(c.applies["P"]),
                int(c.applies["S"]),
                int(c.applies["TS"]),
                int(c.maturity["ML1"]),
                int(c.maturity["ML2"]),
                int(c.maturity["ML3"]),
                c.pdf_excerpt,
                c.pdf_page,
            ),
        )
        count += 1
    conn.commit()
    return count


def _row_to_control(row: sqlite3.Row) -> Control:
    return Control(
        identifier=row["identifier"],
        guideline=row["guideline"],
        section=row["section"],
        topic=row["topic"],
        revision=row["revision"],
        updated=row["updated"],
        description=row["description"],
        applies={c: bool(row[f"applies_{c.lower()}"]) for c in CLASSIFICATIONS},
        maturity={m: bool(row[f"maturity_{m.lower()}"]) for m in MATURITIES},
        pdf_excerpt=row["pdf_excerpt"],
        pdf_page=row["pdf_page"],
    )


def get_control(conn: sqlite3.Connection, identifier: str) -> Control | None:
    row = conn.execute("SELECT * FROM controls WHERE identifier = ?", (identifier,)).fetchone()
    return _row_to_control(row) if row else None


def search(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[Control]:
    rows = conn.execute(
        """
        SELECT c.* FROM controls c
        JOIN controls_fts ON controls_fts.rowid = c.rowid
        WHERE controls_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def list_by_classification(conn: sqlite3.Connection, classification: str) -> list[Control]:
    cls = classification.upper()
    if cls not in CLASSIFICATIONS:
        raise ValueError(
            f"unknown classification {classification!r}, expected one of {CLASSIFICATIONS}"
        )
    rows = conn.execute(
        f"SELECT * FROM controls WHERE applies_{cls.lower()} = 1 ORDER BY identifier"
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def list_by_topic(conn: sqlite3.Connection, topic: str) -> list[Control]:
    rows = conn.execute(
        "SELECT * FROM controls WHERE topic = ? ORDER BY identifier",
        (topic,),
    ).fetchall()
    return [_row_to_control(r) for r in rows]


def list_topics(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT topic FROM controls ORDER BY topic").fetchall()
    return [r["topic"] for r in rows]


def list_sections(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT section FROM controls ORDER BY section").fetchall()
    return [r["section"] for r in rows]


def count_controls(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM controls").fetchone()["n"]


def insert_embeddings(conn: sqlite3.Connection, rows: list[tuple[int, bytes]]) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO controls_embeddings(rowid, embedding) VALUES (?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def load_embedding_matrix(conn: sqlite3.Connection, dim: int) -> tuple[np.ndarray, list[int]]:
    rows = conn.execute(
        "SELECT rowid, embedding FROM controls_embeddings ORDER BY rowid"
    ).fetchall()
    if not rows:
        return np.empty((0, dim), dtype=np.float32), []
    ids = [r["rowid"] for r in rows]
    matrix = np.frombuffer(b"".join(r["embedding"] for r in rows), dtype=np.float32)
    matrix = matrix.reshape(len(rows), dim)
    return matrix.copy(), ids
