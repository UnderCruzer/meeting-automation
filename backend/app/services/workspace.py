"""단일 팀 회의 검토 상태와 승인 결과를 SQLite에 보관한다."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path

from app.services.due_dates import local_date, parse_due

class Workspace:
    def __init__(self, base_dir):
        self.path = Path(base_dir) / "workspace.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL, summary TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            # Added with accounts: who uploaded and who decided (older databases are migrated in place).
            existing = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            for column in ("uploaded_by", "decided_by", "decided_at",
                           # Slack publishing (#73): none|queued|scheduled|sent|failed
                           "publish_status", "publish_at", "published_at", "publish_channel", "publish_error",
                           # Failure reason code and the masked transcript kept for "다시 분석" (#75)
                           "error_code", "retry_payload"):
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
            db.execute("UPDATE jobs SET status='review',summary=?,error_code=NULL,retry_payload=NULL"
                       " WHERE id=? AND status='processing'", (json.dumps(summary,ensure_ascii=False),job_id))

    def fail(self, job_id, code="FAILED"):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='failed', error_code=? WHERE id=? AND status='processing'", (code, job_id))

    def save_retry(self, job_id, payload):
        """Keep the masked transcript so analysis can be retried without re-upload."""
        with self.connect() as db:
            db.execute("UPDATE jobs SET retry_payload=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), job_id))

    def start_retry(self, job_id):
        """Atomically move a retryable failed job back to processing; returns its payload or None."""
        with self.connect() as db:
            row = db.execute("SELECT retry_payload FROM jobs WHERE id=? AND status='failed' AND retry_payload IS NOT NULL",
                             (job_id,)).fetchone()
            if row is None:
                return None
            changed = db.execute("UPDATE jobs SET status='processing', error_code=NULL WHERE id=? AND status='failed'",
                                 (job_id,)).rowcount
        return json.loads(row["retry_payload"]) if changed else None

    def recover(self):
        # 실행 중 재시작된 작업은 무한 대기 대신 실패로 표시한다.
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='failed', error_code='RESTARTED' WHERE status='processing'")
            # Queued/scheduled Slack posts lived in memory and are gone after a restart.
            db.execute("UPDATE jobs SET publish_status='failed', publish_error='서버 재시작으로 게시 예약이 취소되었습니다.'"
                       " WHERE publish_status IN ('queued','scheduled')")

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT 100").fetchall()
        return [self._public(row) for row in rows]

    @staticmethod
    def _public(row):
        job = {**dict(row), "summary": json.loads(row["summary"]) if row["summary"] else None}
        job["can_retry"] = job.pop("retry_payload", None) is not None and job["status"] == "failed"
        # Resolved due date (free text → calendar date, relative to the meeting day) for UI and briefings.
        meeting_day = local_date(job.get("created_at"))
        for item in (job["summary"] or {}).get("action_items", []):
            due = parse_due(item.get("due_date"), meeting_day) if meeting_day else None
            item["due"] = due.isoformat() if due else None
        return job

    def decide(self, job_id, status, decided_by=None):
        if status not in ("approved", "rejected"):
            raise ValueError("Invalid decision")
        with self.connect() as db:
            changed = db.execute(
                "UPDATE jobs SET status=?, decided_by=?, decided_at=CURRENT_TIMESTAMP WHERE id=? AND status='review'",
                (status, decided_by, job_id),
            ).rowcount
        return bool(changed)

    def set_item_done(self, job_id, index, done, by=None):
        """Mark one action item of an approved meeting done/open. Returns False if not applicable."""
        with self.connect() as db:
            row = db.execute("SELECT summary FROM jobs WHERE id=? AND status='approved'", (job_id,)).fetchone()
            if row is None or not row["summary"]:
                return False
            summary = json.loads(row["summary"])
            items = summary.get("action_items", [])
            if not 0 <= index < len(items):
                return False
            items[index].update(done=bool(done), done_by=by if done else None,
                                done_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if done else None)
            db.execute("UPDATE jobs SET summary=? WHERE id=?", (json.dumps(summary, ensure_ascii=False), job_id))
        return True

    def update_action_items(self, job_id, items):
        """Replace the action items of a job still under review. Returns False otherwise."""
        with self.connect() as db:
            row = db.execute("SELECT summary FROM jobs WHERE id=? AND status='review'", (job_id,)).fetchone()
            if row is None or not row["summary"]:
                return False
            summary = json.loads(row["summary"])
            summary["action_items"] = items
            changed = db.execute("UPDATE jobs SET summary=? WHERE id=? AND status='review'",
                                 (json.dumps(summary, ensure_ascii=False), job_id)).rowcount
        return bool(changed)

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._public(row)

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
