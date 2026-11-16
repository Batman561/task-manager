from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).with_name("tasks.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    title           TEXT    NOT NULL,
    next_at         TEXT,
    repeat_count    INTEGER NOT NULL,
    repeat_interval INTEGER NOT NULL,
    sent_count      INTEGER NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'active',
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks (status, next_at);
"""

ACTIVE = "active"
DONE = "done"


@dataclass(slots=True)
class Task:
    id: int
    chat_id: int
    user_id: int
    title: str
    next_at: str | None
    repeat_count: int
    repeat_interval: int
    sent_count: int
    status: str
    created_at: str

    @property
    def remaining(self) -> int:
        return max(self.repeat_count - self.sent_count, 0)


def _path(path: str | Path | None = None) -> str | Path:
    return path or os.getenv("DB_PATH") or DEFAULT_DB_PATH


def _connect(path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(_path(path), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _as_task(row: sqlite3.Row) -> Task:
    return Task(**dict(row))


def init_db(path: str | Path | None = None) -> None:
    with closing(_connect(path)) as conn, conn:
        conn.executescript(SCHEMA)


def add_task(
    *,
    chat_id: int,
    user_id: int,
    title: str,
    next_at: str,
    repeat_count: int,
    repeat_interval: int,
    created_at: str,
    path: str | Path | None = None,
) -> Task:
    with closing(_connect(path)) as conn, conn:
        cursor = conn.execute(
            """
            INSERT INTO tasks
                (chat_id, user_id, title, next_at, repeat_count, repeat_interval, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, user_id, title, next_at, repeat_count, repeat_interval, created_at),
        )
        task_id = cursor.lastrowid
    task = get_task(task_id, path=path)
    assert task is not None
    return task


def get_task(task_id: int, path: str | Path | None = None) -> Task | None:
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _as_task(row) if row else None


def due_tasks(now_iso: str, path: str | Path | None = None) -> list[Task]:
    with closing(_connect(path)) as conn:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = ? AND next_at IS NOT NULL AND next_at <= ?
            ORDER BY next_at ASC
            """,
            (ACTIVE, now_iso),
        ).fetchall()
    return [_as_task(row) for row in rows]


def list_tasks(chat_id: int, limit: int = 20, path: str | Path | None = None) -> list[Task]:
    with closing(_connect(path)) as conn:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE chat_id = ?
            ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id ASC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()
    return [_as_task(row) for row in rows]


def record_reminder(
    task_id: int,
    next_at: str | None,
    sent_count: int,
    path: str | Path | None = None,
) -> None:
    with closing(_connect(path)) as conn, conn:
        conn.execute(
            "UPDATE tasks SET next_at = ?, sent_count = ? WHERE id = ?",
            (next_at, sent_count, task_id),
        )


def snooze(task_id: int, next_at: str, path: str | Path | None = None) -> None:
    with closing(_connect(path)) as conn, conn:
        conn.execute(
            "UPDATE tasks SET next_at = ?, repeat_count = repeat_count + 1 WHERE id = ?",
            (next_at, task_id),
        )


def stop_reminders(task_id: int, path: str | Path | None = None) -> None:
    with closing(_connect(path)) as conn, conn:
        conn.execute("UPDATE tasks SET next_at = NULL WHERE id = ?", (task_id,))


def set_status(task_id: int, status: str, path: str | Path | None = None) -> None:
    with closing(_connect(path)) as conn, conn:
        conn.execute(
            "UPDATE tasks SET status = ?, next_at = NULL WHERE id = ?",
            (status, task_id),
        )


def delete_task(task_id: int, path: str | Path | None = None) -> None:
    with closing(_connect(path)) as conn, conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
