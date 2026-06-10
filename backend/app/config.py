"""
Startup environment variable validation.

Called once from lifespan. Logs a clear warning for each missing variable
so operators know exactly what to set before the first request fails silently.
"""
import logging
import os

logger = logging.getLogger(__name__)

_REQUIRED = {
    "ANTHROPIC_API_KEY": "Claude AI 분석 (orchestrator)",
    "SLACK_BOT_TOKEN": "Slack 메시지 발송 (review, digest, followup)",
}

_OPTIONAL_WARN = {
    "OPENAI_API_KEY": "Whisper STT API (STT_BACKEND=whisper-api 시 필요)",
    "JIRA_BASE_URL": "Jira 초안 배포",
    "CONFLUENCE_BASE_URL": "Confluence 초안 배포",
    "BACKEND_API_KEY": "API 인증 (미설정 시 모든 엔드포인트 공개)",
}


def validate_env() -> None:
    missing_required = [k for k in _REQUIRED if not os.getenv(k)]
    missing_optional = [k for k in _OPTIONAL_WARN if not os.getenv(k)]

    if missing_required:
        for key in missing_required:
            logger.error(
                "[Config] 필수 환경변수 누락: %s — %s", key, _REQUIRED[key]
            )
        raise RuntimeError(
            f"필수 환경변수가 설정되지 않았습니다: {', '.join(missing_required)}"
        )

    if missing_optional:
        for key in missing_optional:
            logger.warning(
                "[Config] 선택 환경변수 미설정: %s — %s", key, _OPTIONAL_WARN[key]
            )
