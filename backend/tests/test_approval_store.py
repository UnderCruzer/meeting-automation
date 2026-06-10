"""Unit tests for in-memory approval store (approval_store.py)."""
import threading
import pytest
from app.services import approval_store as store


@pytest.fixture(autouse=True)
def clear_store():
    """Reset global state between tests."""
    store._store.clear()
    yield
    store._store.clear()


class TestRegisterAndGet:
    def test_register_creates_pending_artifacts(self):
        job = store.register_job("job1", "mtg1", ["jira", "slack"])
        assert job.job_id == "job1"
        assert job.meeting_id == "mtg1"
        assert set(job.artifacts) == {"jira", "slack"}
        assert all(a.status == "pending" for a in job.artifacts.values())

    def test_get_job_returns_registered(self):
        store.register_job("job2", "mtg2", ["confluence"])
        job = store.get_job("job2")
        assert job is not None
        assert job.job_id == "job2"

    def test_get_job_missing_returns_none(self):
        assert store.get_job("nonexistent") is None

    def test_register_overwrites_existing(self):
        store.register_job("job3", "mtg3", ["jira"])
        store.register_job("job3", "mtg3", ["slack"])
        job = store.get_job("job3")
        assert "slack" in job.artifacts
        assert "jira" not in job.artifacts


class TestApproveAndReject:
    def test_approve_sets_status(self):
        store.register_job("job4", "mtg4", ["jira"])
        ok = store.approve_artifact("job4", "jira", approved_by="alice")
        assert ok is True
        assert store.get_job("job4").artifacts["jira"].status == "approved"
        assert store.get_job("job4").artifacts["jira"].approved_by == "alice"

    def test_approve_stores_schedule_time(self):
        store.register_job("job5", "mtg5", ["slack"])
        store.approve_artifact("job5", "slack", schedule_time="2026-01-01T09:00:00Z")
        assert store.get_job("job5").artifacts["slack"].schedule_time == "2026-01-01T09:00:00Z"

    def test_reject_sets_status(self):
        store.register_job("job6", "mtg6", ["confluence"])
        ok = store.reject_artifact("job6", "confluence")
        assert ok is True
        assert store.get_job("job6").artifacts["confluence"].status == "rejected"

    def test_approve_missing_job_returns_false(self):
        assert store.approve_artifact("no-job", "jira") is False

    def test_approve_missing_artifact_returns_false(self):
        store.register_job("job7", "mtg7", ["jira"])
        assert store.approve_artifact("job7", "confluence") is False

    def test_reject_missing_returns_false(self):
        assert store.reject_artifact("no-job", "slack") is False


class TestAllResolved:
    def test_all_pending_not_resolved(self):
        store.register_job("job8", "mtg8", ["jira", "slack"])
        assert store.all_resolved("job8") is False

    def test_partial_approval_not_resolved(self):
        store.register_job("job9", "mtg9", ["jira", "slack"])
        store.approve_artifact("job9", "jira")
        assert store.all_resolved("job9") is False

    def test_all_approved_resolved(self):
        store.register_job("job10", "mtg10", ["jira", "slack"])
        store.approve_artifact("job10", "jira")
        store.approve_artifact("job10", "slack")
        assert store.all_resolved("job10") is True

    def test_mix_approved_rejected_resolved(self):
        store.register_job("job11", "mtg11", ["jira", "slack", "confluence"])
        store.approve_artifact("job11", "jira")
        store.reject_artifact("job11", "slack")
        store.reject_artifact("job11", "confluence")
        assert store.all_resolved("job11") is True

    def test_missing_job_not_resolved(self):
        assert store.all_resolved("no-job") is False


class TestApprovedArtifacts:
    def test_returns_only_approved(self):
        store.register_job("job12", "mtg12", ["jira", "slack", "confluence"])
        store.approve_artifact("job12", "jira")
        store.reject_artifact("job12", "slack")
        approved = store.approved_artifacts("job12")
        assert len(approved) == 1
        assert approved[0].artifact == "jira"

    def test_empty_when_all_rejected(self):
        store.register_job("job13", "mtg13", ["jira"])
        store.reject_artifact("job13", "jira")
        assert store.approved_artifacts("job13") == []


class TestConcurrency:
    def test_concurrent_approvals_no_race(self):
        store.register_job("job14", "mtg14", ["jira", "slack", "confluence"])
        errors = []

        def approve(artifact):
            try:
                store.approve_artifact("job14", artifact)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=approve, args=(a,)) for a in ["jira", "slack", "confluence"]]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert store.all_resolved("job14") is True
        assert len(store.approved_artifacts("job14")) == 3
