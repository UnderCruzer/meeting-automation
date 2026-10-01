"""Workflow 20–21: Morning Brief, Weekly Digest and due-date follow-ups for the team channel.

Built only from **approved** meetings (the human approval gate, workflow 16) with a fixed
template — no LLM call, so no extra cost, no pseudonym tokens and no provider errors in Slack.
Sent through the Write Queue and scheduled in the team's timezone, once per day.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from datetime import date, datetime, time, timedelta

from app.services.due_dates import local_date, team_timezone
from app.services.quality import run_quality_checks
from app.services.slack_publish import slack_enabled
from app.services.write_queue import WriteTask, enqueue

logger = logging.getLogger(__name__)

_CHECK_SECONDS = 60
_MAX_LINES = 15


# ── Data ───────────────────────────────────────────────────────────────────────

def _approved(jobs: list[dict]) -> list[dict]:
    return [j for j in jobs if j.get("status") == "approved" and j.get("summary")]


def _tasks(jobs: list[dict]) -> list[dict]:
    tasks = []
    for job in _approved(jobs):
        for index, item in enumerate(job["summary"].get("action_items", [])):
            due = date.fromisoformat(item["due"]) if item.get("due") else None
            tasks.append({**item, "index": index, "job": job, "due_date_parsed": due})
    return tasks


def previous_workday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def next_workday(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


# ── Formatting ─────────────────────────────────────────────────────────────────

def _user_map() -> dict[str, str]:
    """SLACK_USER_MAP="김민수=U0123,박지은=U0456" → mention people by Slack ID."""
    pairs = (p.split("=", 1) for p in os.getenv("SLACK_USER_MAP", "").split(",") if "=" in p)
    return {name.strip(): uid.strip() for name, uid in pairs if name.strip() and uid.strip()}


def _who(name: str, users: dict[str, str]) -> str:
    if not name:
        return "담당자 미정"
    return f"<@{users[name]}>" if name in users else name


def _link(job: dict) -> str:
    base = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    title = job["title"].replace("<", "‹").replace(">", "›").replace("|", "¦")
    return f"<{base}/?meeting={job['id']}|{title}>" if base else title


def _task_line(task: dict, users: dict[str, str], today: date) -> str:
    due = task["due_date_parsed"]
    when = ""
    if due:
        delta = (due - today).days
        when = f" · {due.month}/{due.day}" + (f" ({-delta}일 지남)" if delta < 0 else "")
    return f"• {task['description']} — {_who(task.get('assignee', ''), users)}{when} _({_link(task['job'])})_"


def _section(title: str, lines: list[str]) -> list[str]:
    if not lines:
        return []
    extra = len(lines) - _MAX_LINES
    return [f"*{title}* ({len(lines)})", *lines[:_MAX_LINES], *([f"…외 {extra}건"] if extra > 0 else []), ""]


def build_morning_brief(jobs: list[dict], today: date) -> str | None:
    """Overdue / due today / due next workday, plus meetings approved since the last workday."""
    users = _user_map()
    open_tasks = [t for t in _tasks(jobs) if not t.get("done")]
    dated = [t for t in open_tasks if t["due_date_parsed"]]
    dated.sort(key=lambda t: t["due_date_parsed"])
    upcoming = next_workday(today)
    overdue = [_task_line(t, users, today) for t in dated if t["due_date_parsed"] < today]
    due_today = [_task_line(t, users, today) for t in dated if t["due_date_parsed"] == today]
    due_next = [_task_line(t, users, today) for t in dated if today < t["due_date_parsed"] <= upcoming]

    since = previous_workday(today)
    recent = [j for j in _approved(jobs) if (d := local_date(j.get("decided_at"))) and since <= d < today]
    meetings = [f"• {_link(j)} — 결정 {len(j['summary'].get('decisions', []))} · 할 일 {len(j['summary'].get('action_items', []))}"
                for j in recent]

    body = [*_section("⚠️ 기한 지남", overdue), *_section("🔴 오늘 마감", due_today),
            *_section(f"🟡 {'다음 근무일' if upcoming != today + timedelta(days=1) else '내일'} 마감", due_next),
            *_section("📝 새로 승인된 회의", meetings)]
    if not body:
        return None
    return "\n".join([f"☀️ *Morning Brief* · {today.month}월 {today.day}일", "", *body]).rstrip()


def build_weekly_digest(jobs: list[dict], today: date) -> str | None:
    """Last 7 days: meetings, decisions, tasks created/done/open, open tasks per owner."""
    users = _user_map()
    start = today - timedelta(days=7)
    week = [j for j in _approved(jobs) if (d := local_date(j.get("decided_at"))) and start <= d < today]
    all_tasks = _tasks(jobs)
    week_ids = {j["id"] for j in week}
    created = [t for t in all_tasks if t["job"]["id"] in week_ids]
    done = [t for t in all_tasks if t.get("done") and (d := local_date(t.get("done_at"))) and start <= d < today]
    open_tasks = [t for t in all_tasks if not t.get("done")]
    overdue = sorted((t for t in open_tasks if t["due_date_parsed"] and t["due_date_parsed"] < today),
                     key=lambda t: t["due_date_parsed"])
    if not week and not done and not open_tasks:
        return None

    decisions = [f"• {d['text']} _({_link(j)})_" for j in week for d in j["summary"].get("decisions", [])]
    owners = Counter(t.get("assignee") or "담당자 미정" for t in open_tasks)
    lines = [
        f"📊 *Weekly Digest* · {start.month}/{start.day} ~ {(today - timedelta(days=1)).month}/{(today - timedelta(days=1)).day}",
        "",
        f"회의 {len(week)}건 승인 · 할 일 {len(created)}건 생성 · {len(done)}건 완료 · 미완료 {len(open_tasks)}건",
        "",
        *_section("✅ 이번 주 결정", decisions),
        *_section("⚠️ 기한 지난 할 일", [_task_line(t, users, today) for t in overdue]),
        *_section("👥 담당자별 미완료", [f"• {_who(name if name != '담당자 미정' else '', users)} {count}건"
                                     for name, count in owners.most_common()]),
    ]
    return "\n".join(lines).rstrip()


# ── Delivery & schedule ────────────────────────────────────────────────────────

def _channel() -> str:
    return os.getenv("DIGEST_CHANNEL") or os.getenv("SLACK_BRIEF_CHANNEL", "")


async def send_briefing(kind: str, workspace, audit, storage, today: date | None = None) -> bool:
    """Build and queue one briefing ("morning" | "weekly"). Returns False when there is nothing to send."""
    today = today or datetime.now(team_timezone()).date()
    jobs = await asyncio.to_thread(workspace.list_all)
    text = (build_weekly_digest if kind == "weekly" else build_morning_brief)(jobs, today)
    if not text:
        logger.info("[Briefing] %s %s — nothing to report", kind, today)
        return False

    async def on_result(ok: bool, detail) -> None:
        code = "" if ok else f": {(detail or {}).get('error', '')}"[:80]
        await asyncio.to_thread(audit.record, "briefing", "system", detail=f"{kind} {'sent' if ok else 'failed'}{code}")

    await enqueue(WriteTask(job_id=f"briefing-{kind}-{today}", meeting_id="briefings", artifact="slack",
                            payload={"text": text, "suggested_channel": _channel()},
                            base_dir=storage.base_dir, on_result=on_result))
    return True


def briefing_time() -> time:
    try:
        hour, minute = (int(x) for x in os.getenv("BRIEFING_TIME", "09:00").split(":"))
        return time(hour, minute)
    except ValueError:
        return time(9, 0)


def due_briefings(now: datetime) -> list[str]:
    """Which briefings should go out at local time `now` (weekdays, from BRIEFING_TIME until noon)."""
    start = briefing_time()
    catch_up_until = max(time(12, 0), start)
    if now.weekday() >= 5 or not (start <= now.time() < catch_up_until):
        return []
    return ["morning", "weekly"] if now.weekday() == 0 else ["morning"]


def briefing_enabled() -> bool:
    return slack_enabled() and os.getenv("BRIEFING_ENABLED", "true").lower() not in ("0", "false", "no")


_QUALITY_CHECK_SECONDS = 60 * 60


async def run_briefing_loop(workspace, audit, storage) -> None:
    """Check every minute; each briefing goes out once per day even with several restarts/instances.
    If the server slept through BRIEFING_TIME (free hosting), it catches up until noon.
    Quality anomaly checks (workflow 22) run hourly; the weekly quality report rides on Monday's slot."""
    last_quality_check = 0.0
    loop = asyncio.get_running_loop()
    while True:
        try:
            if slack_enabled():
                now = datetime.now(team_timezone())
                due = due_briefings(now)
                if briefing_enabled():
                    for kind in due:
                        if await asyncio.to_thread(workspace.claim_briefing, kind, now.date().isoformat()):
                            await send_briefing(kind, workspace, audit, storage, now.date())
                if loop.time() - last_quality_check >= _QUALITY_CHECK_SECONDS or "weekly" in due:
                    last_quality_check = loop.time()
                    await run_quality_checks(workspace, audit, storage, now.date(), weekly="weekly" in due)
        except Exception:
            logger.exception("[Briefing] Scheduler tick failed")
        await asyncio.sleep(_CHECK_SECONDS)
