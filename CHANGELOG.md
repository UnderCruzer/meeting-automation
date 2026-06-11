# Changelog

## [Unreleased]

### Added
- `CHANGELOG.md` 추가
- `docker-compose.override.yml` 로컬 개발용 핫리로드 설정

---

## [1.0.0] — 2026-06-12

22-component AI 회의 자동화 파이프라인 초기 릴리스.

### Features

#### Layer 1: Capture & Input
- **#01 Calendar Detection** — Microsoft Graph API로 Slack Bot이 캘린더 폴링, 회의 감지
- **#02 Slack DM Alert** — 회의 시작 전 Block Kit DM 알림, 중복 방지(alertStore TTL 1h)
- **#03 Recording Approval** — Slack 버튼으로 녹음 승인/스킵 처리
- **#04 Recording Web Page** — Next.js 14 브라우저 녹음 앱, 카운트다운 자동 시작
- **#05 Audio Capture** — MediaRecorder + OfflineAudioContext → 16kHz mono WAV 인코딩
- **#06 Upload API** — FastAPI multipart 업로드, 서버사이드 프록시(API 키 브라우저 미노출)

#### Layer 2: Processing & Intelligence
- **#07 STT** — OpenAI Whisper API (primary) + 로컬 Whisper fallback
- **#08 Ingestion Guard** — 주민등록번호·카드번호·전화·이메일·비밀번호 PII 정규식 마스킹
- **#09 AI Orchestrator** — Claude `claude-sonnet-4-6` tool_use 강제 구조화 출력
- **#10 Bounded Retrieval** — Jira JQL / Confluence CQL / Slack 병렬 컨텍스트 검색
- **#11 Meeting Summary** — 인용 매칭(키워드 오버랩) + 품질 검증(신뢰도·길이·세그먼트)

#### Layer 3: Outputs & Integration
- **#12 Jira Draft** — 액션 아이템 → Jira 이슈 초안 자동 생성
- **#13 Confluence Draft** — 회의 요약 → Confluence 페이지 초안
- **#14 Slack Brief Draft** — Slack 채널용 요약 메시지 초안
- **#15 Human Review Queue** — Slack Block Kit 검토 메시지 발송
- **#16 Human Approval Gate** — 아티팩트별 승인/거절, 전체 완료 감지
- **#17 Write Queue** — asyncio.Queue 워커, 3회 지수 백오프 재시도, JSONL 감사 로그
- **#18 Timezone Scheduler** — 지역 근무시간 기반 즉시/예약 발송 분기, 주말 스킵
- **#19 Regional Slack Delivery** — NA/EU/APAC 채널 라우팅, KR/EN 언어 자동 선택
- **#20 Brief/Digest** — Morning Brief / Daily Digest / Weekly Digest (Claude 생성)

#### Layer 4: Operation & Governance
- **#21 Follow-up Automation** — D-1/D-day 액션 리마인더, 기한 초과 알림
- **#22 Monitoring & Feedback** — 품질 메트릭 집계, 이상 탐지, 주간 리포트, 피드백 수집

### Security
- API Key 미들웨어 (`X-API-Key` 헤더 검증)
- Jira Webhook HMAC-SHA256 서명 검증
- 업로드 Rate Limit: IP당 슬라이딩 윈도우 (기본 10회/60초)
- PII 마스킹 후 Claude API 전송 — 원본 텍스트 외부 미노출

### Infrastructure
- Docker Compose (3서비스: backend / recording-page / slack-bot, 헬스체크 포함)
- GitHub Actions CI (backend pytest, recording-page tsc, slack-bot syntax check)
- 이슈 템플릿 (bug / feature), PR 템플릿
- `.env.example` 전체 환경변수 문서화

### Tests
- 총 **106개** 유닛 테스트
  - `test_guard.py` — PII 마스킹 (13개)
  - `test_approval_store.py` — 승인 스토어 (18개)
  - `test_write_queue.py` — Write Queue (8개)
  - `test_rate_limit.py` — Rate Limit 미들웨어 (5개)
  - `test_retrieval.py` — 컨텍스트 검색 (10개)
  - `test_summarizer.py` — 요약 및 인용 (23개)
  - `test_timezone_scheduler.py` — 타임존 스케줄러 (14개)
  - `test_regional_delivery.py` — 지역 발송 (15개)

### Bug Fixes
- `local.py`: `.replace(".wav", "")` → `file_key[:-4]` (meeting_id에 .wav 포함 시 오작동 방지)
- `guard.py`: `\b` 워드 경계 한국어 유니코드 실패 → lookaround로 교체
- `summarizer.py`: `re` import 모듈 레벨로 이동
- `slack-bot`: `socketMode: true` + `ExpressReceiver` 충돌 → 분리
- `recording-page`: `useCountdown` TDZ 버그 (`const id` 선언 전 참조)
- `recording-page`: `next.config.ts` → `next.config.js` (Next.js 14 미지원)
