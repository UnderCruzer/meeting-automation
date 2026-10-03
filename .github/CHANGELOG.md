# Changelog

## [Unreleased]

## [2.0.0] — 2026-10-03

배포·보안·워크플로 연결. 단일 컨테이너로 Render에 배포하고 22단계 워크플로를 끝까지 이었습니다.

### 배포
- 단일 컨테이너(웹·백엔드·Slack 봇)와 Render Blueprint, 절전 방지 핑(선택) (#55)
- 의존성 업그레이드: Next 16, React 19, Node 24, Starlette (#57)
- LLM 공급자 선택: Gemini(기본)·Claude

### 보안·개인정보
- CSRF 차단, CSP·HSTS 등 보안 헤더, 로그인·업로드 요청 제한 (#58)
- Cloudflare 뒤 실제 접속자 IP 식별 (#71)
- 원본 녹음 자동 삭제, 회의 삭제, 근거 인용문 마스킹 (#63)
- LLM 전송 전 사람 이름 가명 처리, 화면에서는 복원 (#65)
- 개인 계정 로그인(scrypt, 세션 해시 저장)과 승인자 감사 기록 (#66, #67)

### 워크플로
- [1~3] 배포 환경에서 캘린더(ICS) 감지 → Slack DM → 녹음 준비 (#79)
- [4~6] 서명된 회의 전용 녹음 링크, 로그인 없이 그 회의만 업로드 (#80)
- [15~16] 할 일 수정(담당·기한·우선순위), 산출물별 게시 선택 (#81)
- [16~19] 승인 → Write Queue → 시간대 판단 → 지역 채널 게시 (#73)
- [20~21] Morning Brief·Weekly Digest, 기한 해석, 할 일 완료 추적 (#83)
- [22] 요약 피드백, 품질 지표 화면, 이상 경고, 주간 품질 리포트 (#84)

### 화면
- 회의·할 일·관리 화면 개편, 라이트/다크 (#89)
- 도구형 디자인으로 정리 (#93)

### 수정
- 긴 녹음 업로드 OOM — 업로드·전사 스트리밍 (#61)
- Gemini 503 시 재시도·예비 모델·다시 분석·실패 단계 표시 (#75)
- Slack 게시 실패 원인 표시, INFO 로그 출력, 성공 후 중복 게시 방지 (#77)

### 문서
- 포트폴리오 README, 아키텍처·운영 문서, 화면 캡처 (#97)

## [1.1.0]

### Added
- `CHANGELOG.md` 추가
- `docker-compose.override.yml` 로컬 개발용 핫리로드 설정
- **#23 PDF Report** — `pdf_report.py`: fpdf2 기반 회의록 PDF 자동 생성 (회의 ID·참석자·요약·결정사항·액션 아이템, KR/EN 분기)
- `write_queue.py`: `pdf` artifact 타입 추가, Slack `files.uploadV2`로 PDF 파일 첨부 발송 (토큰 없을 시 로컬 저장 fallback)
- `test_pdf_report.py`: 25개 유닛 테스트 추가 (총 131개)

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
