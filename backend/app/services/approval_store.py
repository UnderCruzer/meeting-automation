"""
In-memory approval store for human review/approval gate.

State per job:
  pending   → awaiting human review
  approved  → all selected artifacts approved
  partial   → some artifacts approved, others still pending
  rejected  → at least one artifact rejected
"""
import threading
from dataclasses import dataclass, field
from typing import Literal

ArtifactType = Literal["jira", "confluence", "slack"]
ArtifactStatus = Literal["pending", "approved", "rejected"]


@dataclass
class ArtifactApproval:
    artifact: ArtifactType
    status: ArtifactStatus = "pending"
    approved_by: str = ""
    schedule_time: str = ""   # ISO datetime for deferred publishing


@dataclass
class JobApproval:
    job_id: str
    meeting_id: str
    artifacts: dict[str, ArtifactApproval] = field(default_factory=dict)
    slack_review_ts: str = ""   # Slack message timestamp for update


_store: dict[str, JobApproval] = {}
_lock = threading.Lock()


def register_job(job_id: str, meeting_id: str, artifact_types: list[str]) -> JobApproval:
    with _lock:
        job = JobApproval(
            job_id=job_id,
            meeting_id=meeting_id,
            artifacts={t: ArtifactApproval(artifact=t) for t in artifact_types},  # type: ignore[arg-type]
        )
        _store[job_id] = job
        return job


def get_job(job_id: str) -> JobApproval | None:
    return _store.get(job_id)


def approve_artifact(job_id: str, artifact: str, approved_by: str = "", schedule_time: str = "") -> bool:
    """Mark one artifact as approved. Returns True if job_id found."""
    with _lock:
        job = _store.get(job_id)
        if not job or artifact not in job.artifacts:
            return False
        job.artifacts[artifact].status = "approved"
        job.artifacts[artifact].approved_by = approved_by
        job.artifacts[artifact].schedule_time = schedule_time
        return True


def reject_artifact(job_id: str, artifact: str) -> bool:
    with _lock:
        job = _store.get(job_id)
        if not job or artifact not in job.artifacts:
            return False
        job.artifacts[artifact].status = "rejected"
        return True


def all_resolved(job_id: str) -> bool:
    """True if every artifact is approved or rejected (no pending left)."""
    with _lock:                                          # fix: was lock-free → race with approve/reject
        job = _store.get(job_id)
        if not job:
            return False
        return all(a.status != "pending" for a in job.artifacts.values())


def approved_artifacts(job_id: str) -> list[ArtifactApproval]:
    with _lock:
        job = _store.get(job_id)
        if not job:
            return []
        return [a for a in job.artifacts.values() if a.status == "approved"]
