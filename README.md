## 독립형 회의 워크스페이스 (단일 팀 파일럿)

Slack 계정 없이 **녹음 업로드 → 전사·분석 → 근거 확인 → 승인/거절 → 승인한 업무 목록**을 사용할 수 있습니다. 기존 Slack 기반 흐름도 유지됩니다.

### 실행

1. `backend/.env`에 분석용 `GEMINI_API_KEY`와 전사용 `GROQ_API_KEY` 또는 `OPENAI_API_KEY`를 설정합니다. Claude를 쓰려면 `LLM_PROVIDER=anthropic`과 `ANTHROPIC_API_KEY`를 설정합니다. 실제 업로드 시 사용 중인 공급자 요금이 발생할 수 있습니다.
   - Gemini **무료 등급은 입력 내용이 Google 제품 개선에 사용될 수 있습니다.** 실제 회의 자료는 결제를 연결한 유료 등급 키를 사용하세요. PII는 마스킹 후 전송되지만 회의 내용 자체는 전송됩니다.
2. 루트 `.env`에 서로 다른 임의의 긴 값으로 `BACKEND_API_KEY`와 `WORKSPACE_PASSWORD`를 설정합니다. 비밀번호는 ASCII 문자를 사용합니다.
3. `docker compose -f compose.standalone.yml up --build -d`를 실행합니다.
4. `http://localhost:3001`에 접속합니다. 사용자 이름은 `workspace`, 비밀번호는 설정한 값입니다.
5. 참석자 동의를 받은 녹음을 올리고, 분석 완료 후 근거와 품질 경고를 확인하여 승인합니다.

이 구성은 Slack/Jira/Confluence로 발송하지 않습니다. 녹음과 회의 결과, 승인 상태는 `meeting-data` 볼륨에 저장됩니다. 같은 서버에서 재배포해도 볼륨을 유지하면 보존됩니다. 백업 대상에 포함하고 `down -v`는 사용하지 마세요.

### Render 무료 배포 (체험용)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/UnderCruzer/meeting-automation)

1. 위 버튼 → Render 로그인(GitHub 연동) → Blueprint(`render.yaml`) 확인
2. `GEMINI_API_KEY`, `GROQ_API_KEY`만 입력합니다. `BACKEND_API_KEY`와 `WORKSPACE_PASSWORD`는 Render가 임의 값으로 생성합니다.
3. 배포 완료 후 서비스 **Environment** 탭에서 `WORKSPACE_PASSWORD`를 확인하고, `https://<서비스 이름>.onrender.com`에 사용자 이름 `workspace`로 접속합니다.

- 프런트엔드와 백엔드를 하나의 컨테이너(`deploy/container/Dockerfile`)에서 실행하며, 백엔드는 외부에 노출되지 않습니다. `/api/healthz`만 인증 없이 응답합니다(상태만 반환).
- main에 머지하면 자동 재배포됩니다.
- **무료 인스턴스는 15분 미사용 시 잠들고(첫 접속 약 1분), 재시작·재배포·잠들기 시 회의와 녹음이 초기화됩니다.** 보존이 필요하면 유료 플랜 + Persistent Disk(`/app/data`)나 위 Compose 구성을 사용합니다.
- 무료 인스턴스 메모리가 작아 매우 긴 녹음(1시간 이상)은 실패할 수 있습니다.

### Hugging Face 배포

Docker Space는 현재 PRO 구독이 필요합니다. 사용할 경우 `deploy/container/Dockerfile`을 업로드 루트의 `Dockerfile`로, `deploy/huggingface/README.md`를 Space 루트 README로 사용하고 위와 같은 값을 Space Secrets에 등록합니다. 영구 저장소는 없습니다.

### 보안 설정

- **인증:** 공유 비밀번호(Basic 인증). 같은 IP에서 15분 내 `AUTH_MAX_FAILURES`(기본 20)회 틀리면 429로 잠시 차단됩니다.
- **CSRF:** Basic 인증 정보는 다른 사이트의 요청에도 자동 첨부되므로, 상태를 바꾸는 요청은 `Sec-Fetch-Site`/`Origin`이 같은 출처일 때만 허용합니다.
- **보안 헤더:** CSP(`frame-ancestors 'none'`), `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`(마이크만 허용), HSTS. `X-Powered-By`와 이미지 최적화 엔드포인트는 끕니다.
- **요청 제한:** 업로드는 실제 클라이언트 IP 기준으로 제한합니다. 백엔드는 API 키가 맞는 내부 요청의 `X-Client-IP`만 신뢰합니다.
- **의존성:** CI가 `pip-audit`, `npm audit --audit-level=high`로 알려진 취약점을 검사합니다.
- **외부 전송:** 녹음 원본은 전사 공급자(Groq/OpenAI)로 그대로 전송되고, 개인정보 패턴을 가린 전사문이 LLM으로 전송됩니다. 각 공급자의 데이터 보관 정책을 확인하세요.

### 배포 범위와 다음 단계

Docker를 지원하는 서버에서 동일한 구성으로 실행하고, 3001 포트 앞에 **HTTPS와 접근 제한**을 설정합니다. 백엔드 포트는 호스트에 노출하지 않습니다. 여러 인스턴스 대신 백엔드 한 개로 실행합니다.

- 공유 비밀번호를 사용하는 단일 팀 파일럿입니다. 사용자 가입·팀별 권한 분리·개별 감사 이력은 아직 없습니다.
- 처리 중 서버가 재시작되면 해당 작업은 실패로 표시되며 다시 업로드해야 합니다. 재개 가능한 작업 큐는 후속 범위입니다.
- 승인 결과는 내부 목록에 보관됩니다. 담당자 알림, 완료 상태 변경, 삭제/보존 정책 UI, 초안 수정은 후속 범위입니다.
- 근거 연결은 키워드 유사도 기반 후보이며 사실 검증을 보장하지 않습니다.
- 목록에는 최근 100개 회의가 표시됩니다. 사용자별 데이터 분리 이전에 불특정 다수에게 공개하지 않습니다.

---

# Meeting Automation Workflow

> 회의에서 인사이트를 추출하고 Action으로 연결해 전 세계 팀이 빠르게 실행할 수 있도록 돕는 22-component AI 워크플로우

## 전체 파이프라인

```
캘린더 감지 → Slack DM → 사용자 승인 → 브라우저 녹음
    → 오디오 업로드 → STT → PII 마스킹 → LLM 분석(Gemini/Claude)
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
- `GEMINI_API_KEY` — Gemini API 키 (기본 분석 모델 `GEMINI_MODEL`, 기본값 `gemini-3.8-flash`)
- `ANTHROPIC_API_KEY` — `LLM_PROVIDER=anthropic`일 때 Claude API 키
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

### AI 분석 (`backend/app/services/orchestrator.py`, `llm.py`)
- 공급자 선택: Gemini(`generateContent` + `responseSchema` JSON 출력) 또는 Claude(`tool_use` 강제 구조화 출력)
- PII 마스킹(`guard.py`) 후 LLM API 호출 — 원본 텍스트 외부 미노출
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
| AI | `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `ANTHROPIC_API_KEY` |
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
