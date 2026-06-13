# Backend — FastAPI (Python 3.9)

## 주요 파일

| 파일 | 역할 |
|------|------|
| `app/main.py` | FastAPI app, lifespan (write_queue worker 시작) |
| `app/routers/upload.py` | POST /upload → BackgroundTask 파이프라인 |
| `app/routers/review.py` | 검토/승인 API |
| `app/routers/digest.py` | Morning Brief / Daily / Weekly 트리거 |
| `app/routers/followup.py` | 리마인더, Jira webhook |
| `app/routers/monitor.py` | 메트릭, 피드백, 이상 탐지 |
| `app/services/stt.py` | Whisper API / local 전사 |
| `app/services/guard.py` | PII 패턴 마스킹 (RRN, 카드, 전화, 이메일) |
| `app/services/orchestrator.py` | Claude tool_use 분석 |
| `app/services/summarizer.py` | 인용 매칭 + 품질 검증 |
| `app/services/retrieval.py` | Jira JQL / Confluence CQL / Slack 병렬 검색 |
| `app/services/draft_*.py` | 초안 생성 (Jira/Confluence/Slack) |
| `app/services/approval_store.py` | in-memory 승인 상태 (threading.Lock) |
| `app/services/write_queue.py` | asyncio.Queue 워커, 3회 재시도 |
| `app/services/timezone_scheduler.py` | 근무시간 기반 즉시/예약 분기 |
| `app/services/regional_delivery.py` | NA/EU/APAC 채널 라우팅, KR/EN 언어 선택 |
| `app/services/pdf_report.py` | fpdf2 기반 회의록 PDF 생성 |
| `app/services/digest.py` | Morning Brief / Daily / Weekly 생성 |
| `app/services/followup.py` | 액션 리마인더, Jira 상태 감지 |
| `app/services/monitoring.py` | 메트릭 집계, 피드백 저장, 이상 탐지 |

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
    report.pdf
    audit.jsonl
  feedback.jsonl
  sent_alerts.json
```

경로 조회 시 항상 `_safe_name(meeting_id)` 적용 (`routers/review.py:_load_draft` 참고).

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
```

### async 파일 I/O
모든 파일 읽기/쓰기는 `aiofiles` 사용. `open()` 직접 호출 금지 (audit log 제외).

### approval_store 동시성
`all_resolved()` / `approved_artifacts()` 포함 모든 `_store` 접근은 `with _lock:` 필수.

## 알려진 한계
- `approval_store`: in-memory → 재시작 시 승인 상태 소실 (Redis로 교체 예정)
- Write Queue: 단일 asyncio 워커 → 고부하 시 Redis + BullMQ 전환
- 스토리지: 로컬 파일 → S3/Azure Blob 전환
