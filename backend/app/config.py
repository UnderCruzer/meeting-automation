"""
Startup environment variable validation.

Called once from lifespan. Logs a clear warning for each missing variable
so operators know exactly what to set before the first request fails silently.
"""
import logging
import os

from app.services import llm

logger = logging.getLogger(__name__)

_LLM_KEYS = {
    "GEMINI_API_KEY": "Gemini AI 분석 (orchestrator)",
    "ANTHROPIC_API_KEY": "Claude AI 분석 (orchestrator)",
}

_REQUIRED = {
    "SLACK_BOT_TOKEN": "Slack 메시지 발송 (review, digest, followup)",
}

_OPTIONAL_WARN = {
    "OPENAI_API_KEY": "Whisper STT API (STT_BACKEND=whisper-api 시 필요)",
    "BACKEND_API_KEY": "API 인증 (미설정 시 모든 엔드포인트 공개)",
}


def validate_env() -> None:
    llm_key = llm.api_key_env()  # raises on unsupported LLM_PROVIDER
    required = {llm_key: _LLM_KEYS[llm_key], **_REQUIRED}
    if os.getenv("WORKSPACE_MODE") == "standalone":
        required.pop("SLACK_BOT_TOKEN")
    missing_required = [k for k in required if not os.getenv(k)]
    missing_optional = [k for k in _OPTIONAL_WARN if not os.getenv(k)]

    if missing_required:
        for key in missing_required:
            logger.error(
                "[Config] 필수 환경변수 누락: %s — %s", key, required[key]
            )
        raise RuntimeError(
            f"필수 환경변수가 설정되지 않았습니다: {', '.join(missing_required)}"
        )

    if missing_optional:
        for key in missing_optional:
            logger.warning(
                "[Config] 선택 환경변수 미설정: %s — %s", key, _OPTIONAL_WARN[key]
            )

    # Atlassian is enabled per product only when site, e-mail, token and project/space are all set (#82).
    from app.services import atlassian
    jira, confluence = atlassian.jira_site(), atlassian.confluence_site()
    logger.info("[Config] Jira: %s · Confluence: %s",
                f"프로젝트 {jira.scope}" if jira else "미연결", f"스페이스 {confluence.scope}" if confluence else "미연결")
