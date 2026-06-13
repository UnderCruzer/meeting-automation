# Review Guide

이 파일은 GitHub PR에서 코드 리뷰어가 전체 프로젝트 변경을 검토할 때 참고하도록 저장소에 커밋된 공개 리뷰 체크리스트다. 비밀값, 로컬 운영 정보, 현재 진행률은 넣지 않는다.

## Review guidelines

리뷰 코멘트는 한국어로 작성한다.  
실제 버그, 보안 취약점, 데이터 유실 가능성, 테스트 누락을 우선 지적한다.  
단순 스타일 취향이나 nit는 실제 결함 가능성이 있을 때만 지적한다.  
환경변수가 브라우저에 노출되지 않는지 확인한다 (API 키는 서버사이드 프록시를 통해서만 사용).  
새 서비스 추가 시 대응하는 유닛 테스트가 함께 포함되었는지 확인한다.  
GitHub 이슈 없이 기능이 추가되지 않았는지 확인한다 (PR 본문에 `closes #N` 필수).  
커밋 메시지가 `type(scope): subject` 컨벤션을 따르는지 확인한다.

## 개발 워크플로우

1. GitHub 이슈 먼저 생성 — 라벨: `bug`/`feature` + `P0~P3`
2. `git checkout -b feat/issue-N-short-desc`
3. 구현 → atomic commit (`type(scope): subject`)
4. PR 제목: `feat: Name — description (#N)` 형식, 본문에 `closes #N`
5. PR에는 라벨 붙이지 않는다 (이슈에만 붙임)
6. `gh pr merge --merge`

커밋 타입: `feat` `fix` `refactor` `chore` `docs`

## Project-specific focus

3개 독립 서비스로 구성된 AI 회의 자동화 파이프라인이다.  
각 서비스 상세 리뷰 가이드는 해당 폴더의 `AGENTS.md`를 참고한다.  
PII(개인정보)는 반드시 마스킹 후 Claude API로 전송해야 한다 — 원본 텍스트 외부 미노출.  
회의록 PDF, Slack 메시지 등 AI 생성 아티팩트는 인간 승인 게이트를 거쳐야 한다.
