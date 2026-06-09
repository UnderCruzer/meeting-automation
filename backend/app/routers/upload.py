import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile

from app.models.meeting import MeetingMetadata, UploadResponse
from app.services.guard import mask_transcript_segments, save_guard_report
from app.services.stt import save_transcript, transcribe

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

    job_id = file_key.split("/")[-1].replace(".wav", "")
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

        logger.info(
            "[STT+Guard] %s — %d segments, %d PII masked, lang=%s",
            meeting_id, len(transcript.segments), len(all_matches), transcript.language,
        )
    except Exception:
        logger.exception("[STT+Guard] Failed for %s", meeting_id)
