import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile

from app.models.meeting import MeetingMetadata, UploadResponse
from app.services.guard import mask_transcript_segments, save_guard_report
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
) -> UploadResponse:
    try:
        meta = MeetingMetadata.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    chunks: list[bytes] = []
    total = 0
    async for chunk in audio:
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="Audio file exceeds 500 MB limit")
        chunks.append(chunk)
    audio_bytes = b"".join(chunks)

    if len(audio_bytes) < 44:
        raise HTTPException(status_code=422, detail="Audio file too small to be valid WAV")

    storage = request.app.state.storage
    file_key = await storage.save_audio(audio_bytes, meta.meetingId)
    await storage.save_metadata(file_key, meta.model_dump())

    audio_path = storage.base_dir / file_key
    background_tasks.add_task(_run_stt_and_guard, audio_path, file_key, meta.meetingId, storage.base_dir)

    job_id = file_key.split("/")[-1][:-4]  # safe suffix strip
    return UploadResponse(jobId=job_id, fileKey=file_key, meetingId=meta.meetingId)


async def _run_stt_and_guard(
    audio_path: Path, file_key: str, meeting_id: str, base_dir: Path
) -> None:
    try:
        transcript = await transcribe(audio_path, meeting_id)

        # Mask PII in each segment
        masked_segments_raw, all_matches = mask_transcript_segments(
            [seg.model_dump() for seg in transcript.segments]
        )
        masked_full_text = " ".join(s["text"] for s in masked_segments_raw)

        # Persist original transcript (contains raw text — treat as sensitive)
        await save_transcript(transcript, file_key, base_dir)

        # Persist guard report (masked text + match metadata)
        await save_guard_report(file_key, base_dir, all_matches, masked_full_text)

        # AI analysis — pass masked text so PII never reaches Claude API
        analysis = await analyse(transcript, masked_text=masked_full_text)
        await save_analysis(analysis, file_key, base_dir)

        # Enrich with citations + quality validation
        summary = build_summary(analysis, transcript)
        await save_summary(summary, file_key, base_dir)

        # Bounded retrieval — fetch related Jira/Confluence/Slack context
        context = await retrieve_context(analysis)

        # Generate drafts — only for routing targets, skip if quality_ok is False
        if summary.quality_ok:
            if "jira" in analysis.routing:
                jira_result = await generate_jira_drafts(summary, analysis, context)
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
        job_id = file_key.split("/")[-1][:-4]  # fix: safe suffix strip, was .replace(".wav","")
        review_req = SendReviewRequest(
            job_id=job_id,
            meeting_id=meeting_id,
            file_key=file_key,
            routing=analysis.routing if summary.quality_ok else [],
            has_pii=len(all_matches) > 0,
            summary_ko=summary.summary_ko,
            quality_ok=summary.quality_ok,
        )
        await send_review_message(review_req)

        logger.info(
            "[Pipeline] %s — %d segments, %d PII masked, routing=%s, confidence=%.2f, "
            "quality_ok=%s, retrieved=%d items from %s",
            meeting_id, len(transcript.segments), len(all_matches),
            analysis.routing, analysis.confidence,
            summary.quality_ok, len(context.items), context.sources_searched,
        )
    except Exception:
        logger.exception("[STT+Guard] Failed for %s", meeting_id)
