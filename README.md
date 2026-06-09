# Meeting Automation Workflow

> 회의에서 인사이트를 추출하고, Action으로 연결해 전 세계 팀이 빠르게 실행할 수 있도록 돕는 지능형 워크플로우

## Architecture

### Layer 1: Capture & Input
`01` Calendar 감지 → `02` Slack DM 알림 → `03` 사용자 승인 → `04` Recording Web Page → `05` 오디오 캡처 → `06` 업로드

### Layer 2: Processing & Intelligence
`07` STT → `08` Ingestion/Guard → `09` AI Orchestrator → `10` Bounded Retrieval → `11` 회의분석 & 요약
→ `12` Jira Draft → `13` Confluence Draft → `14` Slack Brief → `15` Review Queue → `16` Approval Gate

### Layer 3: Outputs & Integration
`17` Write Queue → `18` Timezone Scheduler → `19` Regional Slack Delivery → `20` Digest 자동화 → `21` Follow-up → `22` Monitoring

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Slack Bot | Node.js + Bolt SDK |
| Recording Page | Next.js |
| Backend Pipeline | Python + FastAPI |
| STT | OpenAI Whisper |
| AI Processing | Claude API |
| Calendar | Microsoft Graph / Google Calendar API |
| Storage | S3 / Azure Blob |
| Queue | Redis + BullMQ |

## MVP Roadmap

- [ ] Phase 1: Local MVP (Socket Mode Bot + Recording Page)
- [ ] Phase 2: KRAFTON Slack 승인
- [ ] Phase 3: KP/AIT Backend 이관
- [ ] Phase 4: Production 운영 전환
- [ ] Phase 5: 지속적 개선 Loop
