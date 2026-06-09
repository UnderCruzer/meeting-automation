from pydantic import BaseModel, field_validator
from datetime import datetime


class MeetingMetadata(BaseModel):
    meetingId: str
    title: str
    startTime: str
    endTime: str
    location: str = ""

    @field_validator("meetingId")
    @classmethod
    def meeting_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("meetingId must not be empty")
        return v

    @field_validator("startTime", "endTime")
    @classmethod
    def valid_iso(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.rstrip("Z"))
        except ValueError:
            raise ValueError(f"Invalid ISO datetime: {v}")
        return v


class UploadResponse(BaseModel):
    jobId: str
    fileKey: str
    meetingId: str
    status: str = "uploaded"
