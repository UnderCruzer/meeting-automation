from typing import Literal
from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    description: str
    assignee: str = ""
    due_date: str = ""
    priority: Literal["high", "medium", "low"] = "medium"


class OrchestratorOutput(BaseModel):
    meeting_id: str
    topics: list[str] = Field(description="주요 논의 주제 목록")
    decisions: list[str] = Field(description="회의에서 결정된 사항 목록")
    action_items: list[ActionItem] = Field(description="후속 조치 항목")
    participants_mentioned: list[str] = Field(description="transcript에서 언급된 참석자/담당자")
    summary_ko: str = Field(description="한국어 요약 (3-5문장)")
    summary_en: str = Field(description="영어 요약 (3-5 sentences)")
    confidence: float = Field(ge=0.0, le=1.0, description="분석 신뢰도 0-1")
    routing: list[Literal["jira", "confluence", "slack"]] = Field(
        description="후속 단계 자동 결정 — 생성할 artifact 종류"
    )
