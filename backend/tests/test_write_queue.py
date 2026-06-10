"""Unit tests for write queue dispatch logic (write_queue.py)."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.services.write_queue import WriteTask, _dispatch, _queue


def make_task(artifact="jira", schedule_time="", tmp_path=None):
    return WriteTask(
        job_id="testjob",
        meeting_id="mtg_test",
        artifact=artifact,
        payload={"drafts": []},
        base_dir=tmp_path or Path("/tmp/test"),
        schedule_time=schedule_time,
    )


class TestDispatchCancelled:
    @pytest.mark.asyncio
    async def test_cancelled_task_skipped(self, tmp_path):
        task = make_task(schedule_time="cancelled", tmp_path=tmp_path)
        with patch("app.services.write_queue._write_audit", new_callable=AsyncMock) as mock_audit:
            await _dispatch(task)
            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args
            assert call_kwargs[1]["success"] is False or call_kwargs[0][1] is False


class TestDispatchRouting:
    @pytest.mark.asyncio
    async def test_jira_artifact_calls_publish_jira(self, tmp_path):
        task = make_task(artifact="jira", tmp_path=tmp_path)
        with patch("app.services.write_queue._publish_jira", new_callable=AsyncMock, return_value={"results": []}) as mock_jira, \
             patch("app.services.write_queue._write_audit", new_callable=AsyncMock):
            await _dispatch(task)
            mock_jira.assert_called_once_with(task.payload)

    @pytest.mark.asyncio
    async def test_confluence_artifact_calls_publish_confluence(self, tmp_path):
        task = make_task(artifact="confluence", tmp_path=tmp_path)
        task.payload = {"title": "T", "space_key": "SP", "body": "<p/>"}
        with patch("app.services.write_queue._publish_confluence", new_callable=AsyncMock, return_value={}) as mock_conf, \
             patch("app.services.write_queue._write_audit", new_callable=AsyncMock):
            await _dispatch(task)
            mock_conf.assert_called_once()

    @pytest.mark.asyncio
    async def test_slack_artifact_calls_publish_slack(self, tmp_path):
        task = make_task(artifact="slack", tmp_path=tmp_path)
        task.payload = {"text": "hello", "suggested_channel": "general"}
        with patch("app.services.write_queue._publish_slack", new_callable=AsyncMock, return_value={}) as mock_slack, \
             patch("app.services.write_queue._write_audit", new_callable=AsyncMock):
            await _dispatch(task)
            mock_slack.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_artifact_skipped_gracefully(self, tmp_path):
        task = make_task(artifact="unknown", tmp_path=tmp_path)
        with patch("app.services.write_queue._write_audit", new_callable=AsyncMock):
            await _dispatch(task)  # should not raise


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self, tmp_path):
        task = make_task(artifact="jira", tmp_path=tmp_path)
        call_count = 0

        async def flaky(_payload):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient error")
            return {"results": []}

        with patch("app.services.write_queue._publish_jira", side_effect=flaky), \
             patch("app.services.write_queue._write_audit", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await _dispatch(task)

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries_writes_failure_audit(self, tmp_path):
        task = make_task(artifact="jira", tmp_path=tmp_path)

        async def always_fail(_payload):
            raise RuntimeError("always fails")

        with patch("app.services.write_queue._publish_jira", side_effect=always_fail), \
             patch("app.services.write_queue._write_audit", new_callable=AsyncMock) as mock_audit, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await _dispatch(task)

        # Last audit call should be failure
        last_call = mock_audit.call_args_list[-1]
        assert last_call[1].get("success") is False or last_call[0][1] is False


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_audit_log_written_to_meeting_subdir(self, tmp_path):
        from app.services.write_queue import _write_audit
        task = make_task(tmp_path=tmp_path)
        await _write_audit(task, success=True, detail={"key": "TEST-1"})

        audit_file = tmp_path / "mtg_test" / "audit.jsonl"
        assert audit_file.exists()
        import json
        entry = json.loads(audit_file.read_text())
        assert entry["job_id"] == "testjob"
        assert entry["success"] is True
        assert entry["artifact"] == "jira"
