"""Append-only audit trail of who did what. Survives meeting deletion (stores titles, not content)."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

ACTIONS = {
    "login", "login_failed", "logout", "password_change", "user_create", "user_update",
    "upload", "approve", "reject", "delete", "purge", "publish_request", "publish",
}


class AuditLog:
    def __init__(self, base_dir):
        self.path = Path(base_dir) / "workspace.sqlite3"
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY,"
                " at TEXT DEFAULT CURRENT_TIMESTAMP, username TEXT, action TEXT NOT NULL,"
                " job_id TEXT, title TEXT, detail TEXT, ip TEXT)"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, action: str, username: str | None = None, *, job_id: str | None = None,
               title: str | None = None, detail: str | None = None, ip: str | None = None) -> None:
        if action not in ACTIONS:
            raise ValueError(f"Unknown audit action: {action}")
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO audit_events(username,action,job_id,title,detail,ip) VALUES (?,?,?,?,?,?)",
                    (username, action, job_id, title, detail, ip),
                )
        except sqlite3.Error:
            # Never fail the user's action because the audit write failed — but make it visible.
            logger.exception("[Audit] Failed to record %s by %s", action, username)

    def recent(self, limit: int = 200) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (min(limit, 1000),)).fetchall()
        return [dict(r) for r in rows]
