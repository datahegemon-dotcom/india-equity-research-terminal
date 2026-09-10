"""Local storage.

A single SQLite file on the analyst's machine. It holds working reports, which
are private, and a record of what has been published, which is not.

The whole working report is stored as JSON in one column. For a single-user
research tool this is the right trade: the shape of a report changes as the
frameworks evolve, and a rigid schema would fight that.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(__file__).resolve().parent.parent / "terminal.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL,
    company_name  TEXT,
    slug          TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'draft',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    published_at  TEXT,
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_ticker ON reports(ticker);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, always close.

    sqlite3's own connection context manager commits but does not close, and a
    write is invisible to any other connection until that commit lands. Reading
    a row back inside the writing block therefore fails.
    """
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)


def slugify(ticker: str, when: dt.date | None = None) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", ticker.lower()).strip("-")
    stamp = (when or dt.date.today()).isoformat()
    return f"{stem}-{stamp}"


def _unique_slug(connection: sqlite3.Connection, base: str) -> str:
    slug, suffix = base, 2
    while connection.execute("SELECT 1 FROM reports WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def create_report(ticker: str, company_name: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with connect() as connection:
        slug = _unique_slug(connection, slugify(ticker))
        cursor = connection.execute(
            "INSERT INTO reports (ticker, company_name, slug, status, created_at, updated_at, payload)"
            " VALUES (?, ?, ?, 'draft', ?, ?, ?)",
            (ticker.upper(), company_name, slug, now, now, json.dumps(payload)),
        )
        new_id = cursor.lastrowid
    return get_report(new_id)  # type: ignore[arg-type]


def update_payload(report_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with connect() as connection:
        connection.execute(
            "UPDATE reports SET payload = ?, updated_at = ? WHERE id = ?",
            (json.dumps(payload), now, report_id),
        )
    return get_report(report_id)


def mark_published(report_id: int) -> dict[str, Any]:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with connect() as connection:
        connection.execute(
            "UPDATE reports SET status = 'published', published_at = ?, updated_at = ? WHERE id = ?",
            (now, now, report_id),
        )
    return get_report(report_id)


def unpublish(report_id: int) -> dict[str, Any]:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with connect() as connection:
        connection.execute(
            "UPDATE reports SET status = 'draft', published_at = NULL, updated_at = ? WHERE id = ?",
            (now, report_id),
        )
    return get_report(report_id)


def delete_report(report_id: int) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM reports WHERE id = ?", (report_id,))


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    record["payload"] = json.loads(record["payload"])
    return record


def get_report(report_id: int) -> dict[str, Any]:
    with connect() as connection:
        row = connection.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if row is None:
        raise KeyError(f"No report with id {report_id}.")
    return _row_to_dict(row)


def get_by_slug(slug: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM reports WHERE slug = ?", (slug,)).fetchone()
    return _row_to_dict(row) if row else None


def list_reports(status: str | None = None) -> list[dict[str, Any]]:
    query = (
        "SELECT id, ticker, company_name, slug, status, created_at, updated_at, published_at FROM reports"
    )
    params: tuple = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY updated_at DESC"
    with connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(r) for r in rows]
