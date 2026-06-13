# Review Guide — Slack Bot

이 파일은 GitHub PR에서 코드 리뷰어가 slack-bot 변경을 검토할 때 참고하도록 저장소에 커밋된 공개 리뷰 체크리스트다. 비밀값, 로컬 운영 정보, 현재 진행률은 넣지 않는다.

## Review guidelines

리뷰 코멘트는 한국어로 작성한다.  
실제 버그, DM 중복 발송 가능성, 인증 오류, 테스트 누락을 우선 지적한다.  
단순 스타일 취향이나 nit는 실제 결함 가능성이 있을 때만 지적한다.  
`socketMode: true`와 `ExpressReceiver`를 동시에 사용하지 않았는지 확인한다 — 충돌 발생.  
`alertStore`를 통한 중복 DM 방지 로직이 새 알림 경로에도 적용되었는지 확인한다.  
`getUserTimezone` 반환값이 없을 때 fallback 처리와 warn 로그가 있는지 확인한다.  
Slack Block Kit 버튼 핸들러에서 `ack()`가 3초 이내에 호출되는지 확인한다.  
환경변수 `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`이 없을 때 명확한 에러 메시지가 출력되는지 확인한다.

## Clean code checklist

비즈니스 로직은 `services/`에, Slack 이벤트 핸들링은 `handlers/`에 분리한다.  
`alertStore.js`는 단일 인스턴스 전용 — 다중 인스턴스 환경에서 사용하려면 Redis로 교체가 필요하다.  
cron 스케줄 변경 시 타임존 처리가 올바른지 확인한다.

## Project-specific focus

DM 알림은 `alertStore` TTL(1h) 내 중복 발송이 없어야 한다.  
회의 녹음 승인/거절 버튼은 세션 만료 후 재클릭 시 적절한 오류 메시지를 반환해야 한다.  
`alertStore.js`는 JSON 파일 기반 — 서버 재시작 후에도 TTL 내 중복 방지가 유지되는지 확인한다.
