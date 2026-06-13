# CLAUDE.md — Meeting Automation Workflow

## 프로젝트 개요
22-component AI 회의 자동화 파이프라인. 3개 독립 서비스로 구성됨:
- `slack-bot/` — Node.js, Slack Bolt SDK Socket Mode
- `recording-page/` — Next.js 14 App Router, TypeScript
- `backend/` — Python FastAPI, uvicorn

## 개발 워크플로우
1. `git checkout -b feat/issue-N-description`
2. 구현 → atomic commit (`type(scope): subject`)
3. `/code-review` 스킬로 diff 리뷰
4. critical 버그만 수정 후 PR 생성 (`gh pr create --base main`)
5. `gh pr merge --merge --delete-branch`
6. `gh issue close N`

커밋 타입: `feat` `fix` `refactor` `chore` `docs`

## 실행 방법

```bash
# Backend (port 8000)
cd backend && uvicorn app.main:app --reload --port 8000

# Recording Page (port 3001)
cd recording-page && npm run dev

# Slack Bot
cd slack-bot && npm start
```

## 절대 규칙

### 파일 키 접미사
```python
# ✅ 항상 이 패턴
job_id = file_key.split("/")[-1][:-4]
save_path = file_key[:-4] + ".analysis.json"

# ❌ 절대 금지
job_id = file_key.split("/")[-1].replace(".wav", "")
```
이유: meeting_id에 `.wav`가 포함되면 substring replace가 wrong part를 치환함.

### PII 마스킹 guard
```python
# ✅ None 체크 필수
text = masked_text if masked_text is not None else transcript.full_text

# ❌ falsy check 금지
text = masked_text or transcript.full_text  # 빈 문자열(전체 마스킹)이면 원본 노출
```

### 환경변수
```python
# ✅ 함수 내부에서 읽기 (hot reload 지원)
def transcribe():
    backend = os.getenv("STT_BACKEND", "whisper-api")

# ❌ 모듈 레벨 금지
_BACKEND = os.getenv("STT_BACKEND")  # 프로세스 시작 시 freeze됨
```

### Python 3.9 타입 힌트
```python
# ✅ X | None 사용 파일 최상단에 필수
from __future__ import annotations

# 없으면 런타임 TypeError 발생
```

### async 파일 I/O
백엔드 모든 파일 읽기/쓰기는 `aiofiles` 사용. `open()` 직접 호출 금지 (audit log 제외).

### approval_store 동시성
`all_resolved()` / `approved_artifacts()` 포함 모든 `_store` 접근은 `with _lock:` 필수.

## 파일 저장 구조
```
data/recordings/
  {_safe_name(meeting_id)}/   ← 특수문자 → _ 치환
    {job_id}.wav
    {job_id}.transcript.json
    {job_id}.guard.json
    {job_id}.analysis.json
    {job_id}.summary.json
    {job_id}.jira_drafts.json
    {job_id}.confluence_draft.json
    {job_id}.slack_draft.json
    audit.jsonl
  feedback.jsonl
  sent_alerts.json            ← Slack Bot DM 중복 방지
```
경로 조회 시 항상 `_safe_name(meeting_id)` 적용 (`review.py:_load_draft` 참고).

## 서비스별 주요 파일

### Backend (`backend/app/`)
| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI app, lifespan (write_queue worker 시작) |
| `routers/upload.py` | POST /upload → BackgroundTask 파이프라인 |
| `routers/review.py` | 검토/승인 API |
| `routers/digest.py` | Morning Brief / Daily / Weekly 트리거 |
| `routers/followup.py` | 리마인더, Jira webhook |
| `routers/monitor.py` | 메트릭, 피드백, 이상 탐지 |
| `services/stt.py` | Whisper API / local 전사 |
| `services/guard.py` | PII 패턴 마스킹 (RRN, 카드, 전화, 이메일) |
| `services/orchestrator.py` | Claude tool_use 분석 |
| `services/summarizer.py` | 인용 매칭 + 품질 검증 |
| `services/retrieval.py` | Jira JQL / Confluence CQL / Slack 병렬 검색 |
| `services/draft_*.py` | 초안 생성 (Jira/Confluence/Slack) |
| `services/approval_store.py` | in-memory 승인 상태 (threading.Lock) |
| `services/write_queue.py` | asyncio.Queue 워커, 3회 재시도 |
| `services/timezone_scheduler.py` | 근무시간 기반 즉시/예약 분기 |
| `services/regional_delivery.py` | NA/EU/APAC 채널 라우팅, KR/EN 언어 선택 |
| `services/digest.py` | Morning Brief / Daily / Weekly 생성 |
| `services/followup.py` | 액션 리마인더, Jira 상태 감지 |
| `services/monitoring.py` | 메트릭 집계, 피드백 저장, 이상 탐지 |

### Slack Bot (`slack-bot/src/`)
| 파일 | 역할 |
|------|------|
| `services/scheduler.js` | cron 기반 회의 알림 (`alertStore` 사용) |
| `services/alertStore.js` | DM 중복 방지 JSON persistent store (TTL 1h) |
| `services/timezone.js` | IANA tz 변환, getUserTimezone (warn on fallback) |
| `services/sessionStore.js` | 승인/거절 세션 상태 |
| `handlers/actions.js` | Slack Block Kit 버튼 핸들러 |

### Recording Page (`recording-page/src/`)
| 파일 | 역할 |
|------|------|
| `app/record/page.tsx` | 메인 녹음 UI (Suspense 래핑 필수) |
| `hooks/useRecorder.ts` | MediaRecorder + WAV 인코딩 |
| `hooks/useWaveform.ts` | AnalyserNode 실시간 파형 |
| `hooks/useCountdown.ts` | 회의 시작 카운트다운 |
| `lib/audioEncoder.ts` | OfflineAudioContext → 16kHz mono WAV |

## 알려진 MVP 한계 (Phase 3에서 개선 예정)
- `approval_store`: in-memory → 재시작 시 승인 상태 소실 (Redis로 교체 예정)
- `alertStore.js`: JSON 파일 → 다중 인스턴스 불가 (Redis로 교체 시 이 파일만 교체)
- Write Queue: 단일 asyncio 워커 → 고부하 시 Redis + BullMQ 전환
- 스토리지: 로컬 파일 → S3/Azure Blob 전환
