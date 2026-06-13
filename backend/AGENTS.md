# Review Guide — Backend

이 파일은 GitHub PR에서 코드 리뷰어가 backend 변경을 검토할 때 참고하도록 저장소에 커밋된 공개 리뷰 체크리스트다. 비밀값, 로컬 운영 정보, 현재 진행률은 넣지 않는다.

## Review guidelines

리뷰 코멘트는 한국어로 작성한다.  
실제 버그, 보안 취약점, 데이터 유실 가능성, 테스트 누락을 우선 지적한다.  
단순 스타일 취향이나 nit는 실제 결함 가능성이 있을 때만 지적한다.  
환경변수는 함수 내부에서 읽어야 한다 — 모듈 레벨 전역 변수로 고정하면 hot reload 시 갱신 안 됨.  
`masked_text or transcript.full_text` 패턴은 금지 — 전체 마스킹 시 빈 문자열이 원본을 노출시킴.  
파일 키 접미사 제거는 `[:-4]` 슬라이싱만 사용 — `.replace(".wav", "")` 금지.  
`approval_store` 접근은 반드시 `with _lock:` 블록 안에서만 수행한다.  
새 서비스 추가 시 `tests/` 폴더에 대응하는 유닛 테스트가 함께 포함되었는지 확인한다.  
Python 3.9 호환 — `X | None` 타입 힌트 사용 시 파일 최상단에 `from __future__ import annotations` 필수.  
모든 파일 I/O는 `aiofiles` 사용 (`open()` 직접 호출 금지, audit log 제외).

## Clean code checklist

새 라우터 추가 시 `app/main.py`에 `include_router`가 등록되었는지 확인한다.  
서비스 함수는 HTTP 관련 코드를 포함하지 않는다 — 라우터와 서비스 계층을 분리한다.  
Claude API 호출은 `orchestrator.py`를 통해서만 한다 — 라우터에서 직접 호출 금지.  
Write Queue에 새 artifact 타입 추가 시 `_dispatch()`의 분기와 audit log가 함께 업데이트되었는지 확인한다.

## Project-specific focus

파일 저장 경로는 `_safe_name(meeting_id)` 적용 필수 — 특수문자가 경로에 그대로 들어가면 파일 조회 실패.  
PII 마스킹(`guard.py`)은 Claude API 전송 전에 반드시 적용되어야 한다.  
`approval_store`는 in-memory 구조 — 서버 재시작 시 승인 상태 소실됨을 인지하고 설계한다.  
`write_queue.py`의 재시도는 최대 3회 지수 백오프 — 무한 재시도 로직 추가 금지.
