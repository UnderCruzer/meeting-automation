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

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, job_id, title):
        with self.connect() as db:
            db.execute("INSERT INTO jobs(id,title,status) VALUES (?,?,'processing')", (job_id,title))

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

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT 100").fetchall()
        return [{**dict(row), "summary": json.loads(row["summary"]) if row["summary"] else None} for row in rows]

    def decide(self, job_id, status):
        if status not in ("approved", "rejected"):
            raise ValueError("Invalid decision")
        with self.connect() as db:
            changed = db.execute("UPDATE jobs SET status=? WHERE id=? AND status='review'", (status,job_id)).rowcount
        return bool(changed)
