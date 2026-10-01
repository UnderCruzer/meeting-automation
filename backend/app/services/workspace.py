"""단일 팀 회의 검토 상태와 승인 결과를 SQLite에 보관한다."""
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path

class Workspace:
    def __init__(self, base_dir):
        self.path = Path(base_dir) / "workspace.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL, summary TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            # Added with accounts: who uploaded and who decided (older databases are migrated in place).
            existing = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            for column in ("uploaded_by", "decided_by", "decided_at",
                           # Slack publishing (#73): none|queued|scheduled|sent|failed
                           "publish_status", "publish_at", "published_at", "publish_channel", "publish_error"):
                if column not in existing:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, job_id, title, uploaded_by=None):
        with self.connect() as db:
            db.execute("INSERT INTO jobs(id,title,status,uploaded_by) VALUES (?,?,'processing',?)", (job_id,title,uploaded_by))

    def finish(self, job_id, summary):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='review',summary=? WHERE id=? AND status='processing'", (json.dumps(summary,ensure_ascii=False),job_id))

    def fail(self, job_id):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='failed' WHERE id=? AND status='processing'", (job_id,))

    def recover(self):
        # 실행 중 재시작된 작업은 무한 대기 대신 실패로 표시한다.
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='failed' WHERE status='processing'")
            # Queued/scheduled Slack posts lived in memory and are gone after a restart.
            db.execute("UPDATE jobs SET publish_status='failed', publish_error='서버 재시작으로 게시 예약이 취소되었습니다.'"
                       " WHERE publish_status IN ('queued','scheduled')")

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT 100").fetchall()
        return [{**dict(row), "summary": json.loads(row["summary"]) if row["summary"] else None} for row in rows]

    def decide(self, job_id, status, decided_by=None):
        if status not in ("approved", "rejected"):
            raise ValueError("Invalid decision")
        with self.connect() as db:
            changed = db.execute(
                "UPDATE jobs SET status=?, decided_by=?, decided_at=CURRENT_TIMESTAMP WHERE id=? AND status='review'",
                (status, decided_by, job_id),
            ).rowcount
        return bool(changed)

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return {**dict(row), "summary": json.loads(row["summary"]) if row["summary"] else None}

    def set_publish(self, job_id, status, *, at=None, channel=None, error=None):
        if status not in ("queued", "scheduled", "sent", "failed"):
            raise ValueError("Invalid publish status")
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET publish_status=?, publish_at=COALESCE(?, publish_at),"
                " published_at=CASE WHEN ?='sent' THEN CURRENT_TIMESTAMP ELSE published_at END,"
                " publish_channel=COALESCE(?, publish_channel), publish_error=? WHERE id=?",
                (status, at, status, channel, error, job_id),
            )

    def title(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT title FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row["title"] if row else None

    def delete(self, job_id):
        """Delete a finished job row. Returns False if missing, raises if still processing."""
        with self.connect() as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return False
            if row["status"] == "processing":
                raise JobBusyError(job_id)
            db.execute("DELETE FROM jobs WHERE id=? AND status!='processing'", (job_id,))
        return True

    def expired(self, days):
        """IDs of non-processing jobs created more than `days` days ago."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT id FROM jobs WHERE status!='processing' AND created_at < datetime('now', ?)",
                (f"-{int(days)} days",),
            ).fetchall()
        return [row["id"] for row in rows]


class JobBusyError(Exception):
    """The job is still being processed and cannot be deleted yet."""
