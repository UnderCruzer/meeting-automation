from pydantic import BaseModel


class CitedActionItem(BaseModel):
    description: str
    assignee: str = ""
    due_date: str = ""
    priority: str = "medium"
    citation_start: float = 0.0   # transcript segment start (seconds)
    citation_end: float = 0.0     # transcript segment end (seconds)
    citation_text: str = ""       # matched transcript excerpt


class CitedDecision(BaseModel):
    text: str
    citation_start: float = 0.0
    citation_end: float = 0.0
    citation_text: str = ""


class QualityFlag(BaseModel):
    code: str         # e.g. "LOW_CONFIDENCE", "SHORT_TRANSCRIPT", "NO_ACTION_ITEMS"
    message: str


class MeetingSummary(BaseModel):
    meeting_id: str
    summary_ko: str
    summary_en: str
    decisions: list[CitedDecision]
    action_items: list[CitedActionItem]
    quality_flags: list[QualityFlag]
    quality_ok: bool              # False if any blocking flag is present
