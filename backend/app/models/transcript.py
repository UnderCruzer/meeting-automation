from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    start: float      # seconds
    end: float        # seconds
    text: str
    speaker: str = "SPEAKER_00"  # placeholder until diarization is wired


class TranscriptResult(BaseModel):
    meetingId: str
    language: str
    duration: float
    segments: list[TranscriptSegment]
    full_text: str
    backend: str      # "whisper-api" | "whisper-local"
