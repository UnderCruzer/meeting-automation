# Slack Bot — Node.js, Bolt SDK Socket Mode

## 주요 파일

| 파일 | 역할 |
|------|------|
| `src/app.js` | Bolt 앱 진입점, Socket Mode 연결 |
| `src/services/scheduler.js` | cron 기반 회의 감지 및 DM 알림 (`alertStore` 사용) |
| `src/services/alertStore.js` | DM 중복 방지 JSON persistent store (TTL 1h) |
| `src/services/timezone.js` | IANA tz 변환, `getUserTimezone` (fallback 시 warn) |
| `src/services/sessionStore.js` | 승인/거절 세션 상태 관리 |
| `src/handlers/actions.js` | Slack Block Kit 버튼 핸들러 |

## 주의사항
- `socketMode: true`와 `ExpressReceiver`는 동시에 사용 불가 — 분리해서 설정
- `alertStore.js`: JSON 파일 기반 → 다중 인스턴스 환경 불가 (Redis 전환 시 이 파일만 교체)
- 환경변수 `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` 필수

## 알려진 한계
- `alertStore.js`: 단일 인스턴스 전용, 다중 인스턴스 시 Redis로 교체 필요
