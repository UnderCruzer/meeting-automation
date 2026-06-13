# Meeting Automation — Project Overview

22-component AI 회의 자동화 파이프라인. 3개 독립 서비스로 구성됨:
- `slack-bot/` — Node.js, Slack Bolt SDK Socket Mode
- `recording-page/` — Next.js 14 App Router, TypeScript
- `backend/` — Python FastAPI, uvicorn

각 서비스 상세 내용은 해당 폴더의 `AGENT.md` 참고.

## 개발 워크플로우

1. GitHub 이슈 먼저 생성 (`gh issue create`) — 라벨: `bug`/`feature` + `P0~P3`
2. `git checkout -b feat/issue-N-short-desc`
3. 구현 → atomic commit (`type(scope): subject`)
4. PR 생성: `feat: Name — description (#N)` 형식, 본문에 `closes #N`
5. `gh pr merge --merge`

커밋 타입: `feat` `fix` `refactor` `chore` `docs`

## 실행 방법

```bash
# Backend (port 8000)
cd backend && uvicorn app.main:app --reload --port 8000

# Recording Page (port 3001)
cd recording-page && npm run dev

# Slack Bot
cd slack-bot && npm start

# 전체 (Docker)
docker-compose up --build
```
