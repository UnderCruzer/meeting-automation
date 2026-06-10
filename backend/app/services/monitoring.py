"""
Monitoring & Feedback — Issue #22

- STT/AI 품질 메트릭 수집 (audit JSONL 기반)
- 사용자 피드백 수신 (Slack 버튼 → POST /monitor/feedback)
- 이상 탐지 알림 (실패율, 지연 임계치 초과)
- 주간 정확도 리포트
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./data/recordings"))

# 이상 탐지 임계치
_FAILURE_RATE_THRESHOLD = float(os.getenv("ALERT_FAILURE_RATE", "0.3"))   # 30%
_MIN_CONFIDENCE_THRESHOLD = float(os.getenv("ALERT_MIN_CONFIDENCE", "0.5"))


# ── Audit log 수집 ────────────────────────────────────────────────────────────

def _load_audit_entries(since: datetime) -> list[dict]:
    """STORAGE_DIR 하위 모든 audit.jsonl에서 since 이후 항목 수집."""
    entries = []
    for path in _STORAGE_DIR.rglob("audit.jsonl"):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry.get("ts", "1970-01-01T00:00:00+00:00"))
                if ts >= since:
                    entries.append(entry)
        except Exception as exc:
            logger.warning("[Monitor] Failed to parse %s: %s", path, exc)
    return entries


def _load_analysis_entries(since: datetime) -> list[dict]:
    """분석 결과 JSON 수집 (confidence, quality_ok 지표용)."""
    entries = []
    for path in _STORAGE_DIR.rglob("*.analysis.json"):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < since:
                continue
            entries.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            logger.warning("[Monitor] Failed to load analysis %s: %s", path, exc)
    return entries


# ── 메트릭 계산 ───────────────────────────────────────────────────────────────

def compute_metrics(since: datetime) -> dict:
    """
    기간 내 품질/정확도 메트릭 계산.
    Returns dict with: total, success, failed, failure_rate,
                       avg_confidence, low_quality_count, feedback_count
    """
    audit = _load_audit_entries(since)
    analyses = _load_analysis_entries(since)

    total = len(audit)
    success = sum(1 for e in audit if e.get("success"))
    failed = total - success
    failure_rate = failed / total if total else 0.0

    confidences = [a.get("confidence", 0) for a in analyses if isinstance(a.get("confidence"), (int, float))]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    low_quality = sum(1 for a in analyses if not a.get("quality_ok", True))

    # 피드백은 feedback.jsonl에서 읽기
    feedback_count = _count_feedback(since)

    return {
        "period_start": since.isoformat(),
        "total_jobs": total,
        "success": success,
        "failed": failed,
        "failure_rate": round(failure_rate, 4),
        "avg_confidence": round(avg_confidence, 4),
        "low_quality_count": low_quality,
        "feedback_count": feedback_count,
    }


# ── 피드백 저장 ───────────────────────────────────────────────────────────────

_FEEDBACK_PATH = _STORAGE_DIR / "feedback.jsonl"


def save_feedback(job_id: str, user_id: str, rating: str, comment: str = "") -> None:
    """Slack 버튼에서 수신한 피드백을 JSONL에 저장."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "user_id": user_id,
        "rating": rating,      # "good" | "bad" | "partial"
        "comment": comment,
    }
    try:
        _FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_FEEDBACK_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("[Monitor] Feedback saved: job=%s user=%s rating=%s", job_id, user_id, rating)
    except Exception as exc:
        logger.error("[Monitor] Failed to save feedback: %s", exc)


def _count_feedback(since: datetime) -> int:
    count = 0
    if not _FEEDBACK_PATH.exists():
        return 0
    try:
        for line in _FEEDBACK_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry.get("ts", "1970-01-01T00:00:00+00:00"))
            if ts >= since:
                count += 1
    except Exception:
        pass
    return count


# ── 이상 탐지 알림 ────────────────────────────────────────────────────────────

async def _post_alert(text: str) -> None:
    token = os.getenv("SLACK_BOT_TOKEN", "")
    channel = os.getenv("MONITOR_ALERT_CHANNEL", os.getenv("SLACK_BRIEF_CHANNEL", "general"))
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                json={"channel": f"#{channel}", "text": text, "mrkdwn": True},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("error"))
    except Exception as exc:
        logger.warning("[Monitor] Alert post failed: %s", exc)


async def check_anomalies(since_hours: int = 1) -> dict:
    """
    최근 N시간 메트릭을 체크해 임계치 초과 시 Slack 알림 발송.
    Returns: {"alerts_sent": int, "metrics": dict}
    """
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    metrics = compute_metrics(since)
    alerts_sent = 0

    if metrics["total_jobs"] == 0:
        return {"alerts_sent": 0, "metrics": metrics}

    if metrics["failure_rate"] >= _FAILURE_RATE_THRESHOLD:
        await _post_alert(
            f"🚨 *[모니터링 이상]* 실패율 임계치 초과\n"
            f"최근 {since_hours}h 실패율: *{metrics['failure_rate']*100:.1f}%* "
            f"(임계치: {_FAILURE_RATE_THRESHOLD*100:.0f}%)\n"
            f"실패 건수: {metrics['failed']} / {metrics['total_jobs']}"
        )
        alerts_sent += 1

    if metrics["avg_confidence"] > 0 and metrics["avg_confidence"] < _MIN_CONFIDENCE_THRESHOLD:
        await _post_alert(
            f"⚠️ *[모니터링 이상]* AI 신뢰도 낮음\n"
            f"최근 {since_hours}h 평균 신뢰도: *{metrics['avg_confidence']:.2f}* "
            f"(임계치: {_MIN_CONFIDENCE_THRESHOLD:.2f})"
        )
        alerts_sent += 1

    return {"alerts_sent": alerts_sent, "metrics": metrics}


# ── 주간 리포트 ───────────────────────────────────────────────────────────────

async def send_weekly_report() -> None:
    """주간 정확도 리포트를 Slack으로 발송."""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    metrics = compute_metrics(since)

    report = (
        f"📊 *주간 AI 품질 리포트*\n\n"
        f"• 총 처리 건수: *{metrics['total_jobs']}*\n"
        f"• 성공률: *{(1 - metrics['failure_rate'])*100:.1f}%*\n"
        f"• 평균 AI 신뢰도: *{metrics['avg_confidence']:.2f}*\n"
        f"• 품질 경고 건수: *{metrics['low_quality_count']}*\n"
        f"• 사용자 피드백 수: *{metrics['feedback_count']}*\n"
        f"\n_기간: {since.strftime('%Y-%m-%d')} ~ {datetime.now(timezone.utc).strftime('%Y-%m-%d')}_"
    )
    await _post_alert(report)
    logger.info("[Monitor] Weekly report sent: %s", metrics)
