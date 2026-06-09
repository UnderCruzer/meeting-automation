import json
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.models.meeting import MeetingMetadata, UploadResponse

router = APIRouter()

MAX_FILE_BYTES = 500 * 1024 * 1024  # 500 MB


@router.post("/upload", response_model=UploadResponse)
async def upload_audio(
    request: Request,
    audio: UploadFile = File(...),
    metadata: str = Form(...),
) -> UploadResponse:
    # Parse and validate metadata
    try:
        meta = MeetingMetadata.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Read audio — enforce size limit without loading everything into memory first
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

    job_id = file_key.split("/")[-1].replace(".wav", "")
    return UploadResponse(jobId=job_id, fileKey=file_key, meetingId=meta.meetingId)
