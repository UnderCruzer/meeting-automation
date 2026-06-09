from typing import Literal
from pydantic import BaseModel


class RetrievalItem(BaseModel):
    source: Literal["jira", "confluence", "slack"]
    id: str
    title: str
    url: str
    snippet: str          # short excerpt or description
    relevance: float = 1.0


class RetrievalContext(BaseModel):
    meeting_id: str
    items: list[RetrievalItem]
    sources_searched: list[str]
