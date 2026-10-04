from __future__ import annotations
import asyncio
import os
import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile

from app.models.meeting import MeetingMetadata, UploadResponse
from app.middleware.rate_limit import client_ip
from app.routers.auth import Uploader, upload_actor
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.storage.local import AudioSizeError
from app.services.workspace import Workspace
from app.services import atlassian_drafts
from app.services.due_dates import team_timezone
from app.services.guard import mask_transcript_segments, save_guard_report
from app.services.llm import LLMUnavailable
from app.services.name_guard import pseudonymise_segments, unmask_model
from app.services.orchestrator import analyse, save_analysis
from app.services.retrieval import retrieve_context
from app.services.stt import save_transcript, transcribe
from app.services.draft_confluence import generate_confluence_draft, save_confluence_draft
from app.services.draft_jira import generate_jira_drafts, save_jira_drafts
from app.services.draft_slack import generate_slack_draft, save_slack_draft
from app.services.summarizer import build_summary, save_summary
from app.services.review_sender import SendReviewRequest, send_review_message

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_FILE_BYTES = 500 * 1024 * 1024  # 500 MB


@router.post("/upload", response_model=UploadResponse)
async def upload_audio(
    request: Request,
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    metadata: str = Form(...),
    uploader: Uploader = Depends(upload_actor),
) -> UploadResponse:
    try:
        meta = MeetingMetadata.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if uploader.meeting_lock is not None and meta.meetingId != uploader.meeting_lock:
        raise HTTPException(status_code=403, detail="이 녹음 링크로는 해당 회의만 업로드할 수 있습니다.")

    storage = request.app.state.storage
    try:
        # Streamed to disk: a long meeting must not be held in memory (512 MB hosts).
        file_key = await storage.save_audio_stream(audio, meta.meetingId, MAX_FILE_BYTES)
    except AudioSizeError as exc:
        raise HTTPException(status_code=413 if exc.too_large else 422, detail=str(exc))
    await storage.save_metadata(file_key, meta.model_dump())

    job_id = file_key.split("/")[-1][:-4]
    username = uploader.username
    await asyncio.to_thread(request.app.state.workspace.create, job_id, meta.title, username)
    audit = getattr(request.app.state, "audit", None)
    if audit is not None:
        await asyncio.to_thread(audit.record, "upload", username, job_id=job_id, title=meta.title,
                                ip=client_ip(request))
    audio_path = storage.base_dir / file_key
    background_tasks.add_task(
        _run_stt_and_guard, audio_path, file_key, meta.meetingId, storage.base_dir, meta.participants
    )
    return UploadResponse(jobId=job_id, fileKey=file_key, meetingId=meta.meetingId)


async def _run_stt_and_guard(
    audio_path: Path, file_key: str, meeting_id: str, base_dir: Path,
    participants: list[str] | None = None,
) -> None:
    """Stage 1 (transcribe + mask) then stage 2 (analyse). A stage-2 failure stays retryable."""
    workspace = await asyncio.to_thread(Workspace, base_dir)
    job_id = file_key.split("/")[-1][:-4]
    stage = "stt"
    try:
        transcript = await transcribe(audio_path, meeting_id)

        # Mask PII in each segment
        masked_segments_raw, all_matches = mask_transcript_segments(
            [seg.model_dump() for seg in transcript.segments]
        )
        # Replace person names with [PERSON_n]; the token map never leaves this server
        masked_segments_raw, name_tokens = pseudonymise_segments(masked_segments_raw, participants)
        masked_full_text = " ".join(s["text"] for s in masked_segments_raw)
        masked_transcript = transcript.model_copy(update={
            "segments": [TranscriptSegment(**s) for s in masked_segments_raw],
            "full_text": masked_full_text,
        })

        # Original transcript contains raw PII — persisted only when explicitly retained
        if _retain_raw():
            await save_transcript(transcript, file_key, base_dir)

        # Persist guard report (masked text + match metadata)
        await save_guard_report(file_key, base_dir, all_matches, masked_full_text)

        if not masked_full_text.strip():
            raise NoSpeechError(meeting_id)

        # Only masked + pseudonymised text is kept, so "다시 분석" needs no raw data or re-upload.
        retry = {"file_key": file_key, "meeting_id": meeting_id, "pii_count": len(all_matches),
                 "name_tokens": name_tokens, "transcript": masked_transcript.model_dump()}
        await asyncio.to_thread(workspace.save_retry, job_id, retry)
        stage = "analysis"
        await _analyse_and_deliver(workspace, job_id, retry, base_dir)
    except Exception as exc:
        await asyncio.to_thread(workspace.fail, job_id, _error_code(stage, exc))
        logger.exception("[Pipeline] %s failed for %s", stage, meeting_id)
    finally:
        # Raw audio is no longer needed once transcribed (or failed — the user re-uploads).
        if not _retain_raw():
            audio_path.unlink(missing_ok=True)


async def retry_analysis(base_dir: Path, job_id: str, retry: dict) -> None:
    """Re-run stage 2 from the stored masked transcript (no STT, no raw data)."""
    workspace = await asyncio.to_thread(Workspace, base_dir)
    try:
        await _analyse_and_deliver(workspace, job_id, retry, base_dir)
    except Exception as exc:
        await asyncio.to_thread(workspace.fail, job_id, _error_code("analysis", exc))
        logger.exception("[Pipeline] analysis retry failed for %s", retry.get("meeting_id"))


class NoSpeechError(ValueError):
    """Transcription produced no text."""


def _error_code(stage: str, exc: Exception) -> str:
    if isinstance(exc, NoSpeechError):
        return "NO_SPEECH"
    if stage == "stt":
        return "STT_FAILED"
    if isinstance(exc, LLMUnavailable):
        return "LLM_BUSY"
    return "ANALYSIS_FAILED"


async def _analyse_and_deliver(workspace: Workspace, job_id: str, retry: dict, base_dir: Path) -> None:
    file_key, meeting_id = retry["file_key"], retry["meeting_id"]
    name_tokens: dict[str, str] = retry["name_tokens"]
    masked_transcript = TranscriptResult.model_validate(retry["transcript"])

    # AI analysis — only masked, pseudonymised text reaches the LLM
    analysis = await analyse(masked_transcript, masked_text=masked_transcript.full_text)
    await save_analysis(analysis, file_key, base_dir)

    # Enrich with citations + quality validation — citations quote the masked text.
    # Names are restored only in the summary shown to signed-in users.
    masked_summary = build_summary(analysis, masked_transcript)
    summary = unmask_model(masked_summary, name_tokens)
    await save_summary(summary, file_key, base_dir)

    if os.getenv("WORKSPACE_MODE") == "standalone":
        # Workflow 10·12·13: search the configured Jira project / Confluence space and draft
        # issues + minutes for review. Nothing is created until a reviewer approves.
        drafts = None
        if summary.quality_ok:
            title = await asyncio.to_thread(workspace.title, job_id) or ""
            drafts = await atlassian_drafts.prepare(analysis, masked_summary, name_tokens, title,
                                                    datetime.now(team_timezone()).date())
        await asyncio.to_thread(workspace.finish, job_id, summary.model_dump(), analysis.confidence, drafts)
        return
    await asyncio.to_thread(workspace.finish, job_id, summary.model_dump(), analysis.confidence)

    # Bounded retrieval — fetch related Jira/Confluence/Slack context
    context = await retrieve_context(analysis)

    # Generate drafts — only for routing targets, skip if quality_ok is False
    if summary.quality_ok:
        if "jira" in analysis.routing:
            # LLM call: send the pseudonymised summary, restore names in the drafts
            jira_result = unmask_model(
                await generate_jira_drafts(masked_summary, analysis, context), name_tokens
            )
            await save_jira_drafts(jira_result, file_key, base_dir)

        if "confluence" in analysis.routing:
            conf_draft = generate_confluence_draft(summary)
            await save_confluence_draft(conf_draft, file_key, base_dir)

        if "slack" in analysis.routing:
            slack_draft = generate_slack_draft(summary)
            await save_slack_draft(slack_draft, file_key, base_dir)
    else:
        logger.warning("[Pipeline] %s — quality_ok=False, skipping draft generation", meeting_id)

    # Send Slack review message (fire-and-forget, non-blocking)
    review_req = SendReviewRequest(
        job_id=job_id,
        meeting_id=meeting_id,
        file_key=file_key,
        routing=analysis.routing if summary.quality_ok else [],
        has_pii=retry["pii_count"] > 0,
        summary_ko=summary.summary_ko,
        quality_ok=summary.quality_ok,
    )
    await send_review_message(review_req)

    logger.info(
        "[Pipeline] %s — %d segments, %d PII masked, routing=%s, confidence=%.2f, "
        "quality_ok=%s, retrieved=%d items from %s",
        meeting_id, len(masked_transcript.segments), retry["pii_count"],
        analysis.routing, analysis.confidence,
        summary.quality_ok, len(context.items), context.sources_searched,
    )


def _retain_raw() -> bool:
    return os.getenv("RETAIN_RAW_RECORDINGS", "").lower() in ("1", "true", "yes")
