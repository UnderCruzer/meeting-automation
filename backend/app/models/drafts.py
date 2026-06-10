from typing import Literal
from pydantic import BaseModel


class JiraIssueDraft(BaseModel):
    action: Literal["create", "comment"]  # create new issue or comment on existing
    existing_key: str = ""               # populated when action == "comment"
    summary: str
    description: str                     # Jira wiki markup / ADF text
    issue_type: str = "Task"
    priority: str = "Medium"
    assignee: str = ""
    labels: list[str] = []
    language: str = "ko"


class JiraDraftResult(BaseModel):
    meeting_id: str
    drafts: list[JiraIssueDraft]


class ConfluenceDraft(BaseModel):
    title: str
    body: str                            # Confluence storage format (HTML-like)
    space_key: str
    parent_page_id: str = ""
    language: str = "ko"


class SlackBriefDraft(BaseModel):
    text: str                            # Slack mrkdwn formatted message
    suggested_channel: str
    mentions: list[str] = []             # Slack user IDs or display names
    language: str = "ko"
