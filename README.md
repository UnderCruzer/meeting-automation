# Meeting Automation Workflow

> 회의에서 인사이트를 추출하고 Action으로 연결해 전 세계 팀이 빠르게 실행할 수 있도록 돕는 22-component AI 워크플로우

## 전체 파이프라인

```
캘린더 감지 → Slack DM → 사용자 승인 → 브라우저 녹음
    → 오디오 업로드 → STT → PII 마스킹 → Claude 분석
    → 인용 요약 + 품질 검증 → 컨텍스트 검색
    → 초안 생성(Jira/Confluence/Slack) → Slack 검토 메시지
    → 인간 승인 게이트 → Write Queue → 실제 배포
    → 타임존 스케줄러 → 지역별 Slack 전달
    → Morning Brief / Daily / Weekly Digest
    → 액션 아이템 리마인더 → Jira 상태 감지
    → 품질 모니터링 & 피드백 수집
```

## 서비스 구조

| 서비스 | 위치 | 포트 | 설명 |
|--------|------|------|------|
| **Slack Bot** | `slack-bot/` | Socket Mode | 캘린더 폴링, DM 알림, 사용자 승인 |
| **Recording Page** | `recording-page/` | 3001 | Next.js 14 브라우저 녹음 앱 |
| **Backend API** | `backend/` | 8000 | FastAPI AI 처리 파이프라인 |

## 빠른 시작

### 1. 환경변수 설정

```bash
cp .env.example backend/.env
cp .env.example slack-bot/.env
cp .env.example recording-page/.env.local
```

필수 항목:
- `ANTHROPIC_API_KEY` — Claude API 키
- `OPENAI_API_KEY` — Whisper STT (또는 `STT_BACKEND=local`로 로컬 Whisper 사용)
- `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` — Slack Bot Socket Mode
- `JIRA_*` / `CONFLUENCE_*` — Atlassian API 키 (초안 배포 필요 시)

> 전체 환경변수 목록 및 설명은 [`.env.example`](.env.example) 참고

### 2a. Docker로 실행 (권장)

```bash
docker-compose up --build
```

- Backend: http://localhost:8000
- Recording Page: http://localhost:3001

### 2b. 로컬 직접 실행

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Recording Page
cd recording-page && npm install
npm run dev   # → http://localhost:3001

# Slack Bot
cd slack-bot && npm install
npm start
```

## Backend API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/upload` | 오디오 업로드 → AI 파이프라인 트리거 |
| `POST` | `/review/send` | Slack 검토 메시지 발송 |
| `POST` | `/review/approve` | 아티팩트 승인/거절 |
| `GET`  | `/review/{job_id}` | 승인 상태 조회 |
| `POST` | `/digest/morning` | Morning Brief 즉시 발송 |
| `POST` | `/digest/daily` | Daily Digest 즉시 발송 |
| `POST` | `/digest/weekly` | Weekly Digest 즉시 발송 |
| `POST` | `/followup/reminders` | D-1/D-day 액션 리마인더 |
| `POST` | `/followup/overdue` | 기한 초과 알림 |
| `POST` | `/followup/jira` | Jira webhook 수신 |
| `GET`  | `/monitor/metrics` | 품질 메트릭 조회 |
| `POST` | `/monitor/feedback` | 사용자 피드백 저장 |
| `POST` | `/monitor/check` | 이상 탐지 실행 |
| `POST` | `/monitor/weekly-report` | 주간 리포트 발송 |
| `GET`  | `/health` | 헬스체크 |

## 핵심 설계 결정

### AI 분석 (`backend/app/services/orchestrator.py`)
- Claude `claude-sonnet-4-6` + `tool_use` 강제 구조화 출력
- PII 마스킹(`guard.py`) 후 Claude API 호출 — 원본 텍스트 외부 미노출
- `masked_text if masked_text is not None else transcript.full_text` — 빈 문자열 falsy 방지

### 파일 저장 패턴
```
data/recordings/
  {safe_meeting_id}/        ← _safe_name() 적용
    {job_id}.wav            ← 원본 오디오
    {job_id}.transcript.json
    {job_id}.guard.json     ← PII 마스킹 리포트
    {job_id}.analysis.json
    {job_id}.summary.json
    {job_id}.jira_drafts.json
    {job_id}.confluence_draft.json
    {job_id}.slack_draft.json
    audit.jsonl             ← Write Queue 감사 로그
  feedback.jsonl            ← 사용자 피드백
  sent_alerts.json          ← DM 중복 방지 persistent store
```
파일 키 접미사 분리: 항상 `file_key[:-4] + ".ext"` 패턴 사용 (`.replace(".wav", "")` 금지)

### 동시성
- FastAPI BackgroundTasks로 업로드 응답 즉시 반환, 파이프라인은 백그라운드 실행
- `asyncio.gather`로 Jira/Confluence/Slack 컨텍스트 병렬 조회
- Write Queue: `asyncio.Queue` 단일 워커 + 3회 지수 백오프 재시도
- `approval_store`: `threading.Lock` 보호 (FastAPI 멀티스레드 환경)

### Python 3.9 호환
- 모든 `X | None` 타입 힌트 사용 파일에 `from __future__ import annotations` 추가

## 환경변수 전체 목록

`backend/.env.example` 참고. 주요 그룹:

| 그룹 | 변수 |
|------|------|
| STT | `STT_BACKEND`, `OPENAI_API_KEY`, `WHISPER_LOCAL_MODEL` |
| AI | `ANTHROPIC_API_KEY` |
| Jira | `JIRA_BASE_URL`, `JIRA_PROJECT_KEY`, `JIRA_EMAIL`, `JIRA_API_TOKEN` |
| Confluence | `CONFLUENCE_BASE_URL`, `CONFLUENCE_SPACE_KEY`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN` |
| Slack | `SLACK_BOT_TOKEN`, `SLACK_REVIEW_CHANNEL`, `SLACK_BRIEF_CHANNEL` |
| 지역 채널 | `SLACK_CHANNEL_APAC/EU/NA` |
| 다이제스트 | `DIGEST_CHANNEL`, `DIGEST_SUBSCRIBERS` |
| 모니터링 | `MONITOR_ALERT_CHANNEL`, `ALERT_FAILURE_RATE`, `ALERT_MIN_CONFIDENCE` |
| Slack Bot | `DEFAULT_TIMEZONE`, `ALERT_STORE_PATH` |

## 로드맵

- [x] Phase 1: Local MVP — 22-component 파이프라인 구현 완료
- [ ] Phase 2: Redis Write Queue, 프로덕션 스토리지(S3/Azure Blob) 전환
- [ ] Phase 3: 다중 인스턴스 지원, 승인 store → Redis
- [ ] Phase 4: 모델/프롬프트 A/B 테스트, 피드백 루프 자동화
