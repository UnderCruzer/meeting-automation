# Review Guide — Recording Page

이 파일은 GitHub PR에서 코드 리뷰어가 recording-page 변경을 검토할 때 참고하도록 저장소에 커밋된 공개 리뷰 체크리스트다. 비밀값, 로컬 운영 정보, 현재 진행률은 넣지 않는다.

## Review guidelines

리뷰 코멘트는 한국어로 작성한다.  
실제 버그, 녹음 데이터 유실 가능성, 업로드 실패 처리 누락, 접근성 문제를 우선 지적한다.  
단순 스타일 취향이나 nit는 실제 결함 가능성이 있을 때만 지적한다.  
`useSearchParams`를 사용하는 컴포넌트는 `Suspense`로 래핑되었는지 확인한다.  
`useCountdown.ts`에서 `let id`가 `tick()` 정의 위에 선언되었는지 확인한다 — TDZ 오류 방지.  
`next.config.js`가 `.ts`가 아닌 `.js`(CommonJS)인지 확인한다 — Next.js 14.2.35 미지원.  
API 키가 브라우저에 노출되지 않는지 확인한다 — 업로드는 서버사이드 프록시(`/api/upload`)를 통해서만.  
녹음 중 페이지 이탈 시 MediaRecorder가 정상 종료되는지 확인한다.

## Clean code checklist

오디오 처리 로직은 `hooks/`와 `lib/`에 분리한다 — 페이지 컴포넌트에 직접 구현 금지.  
업로드 실패 시 사용자에게 이해 가능한 메시지가 표시되는지 확인한다.  
카운트다운 종료, 녹음 완료, 업로드 성공/실패 각 상태가 UI에 명확히 반영되는지 확인한다.

## Project-specific focus

`/record` 페이지 진입은 Slack DM 링크를 통해서만 허용 — `startTime`, `endTime` 파라미터가 없으면 접근 차단.  
URL 파라미터는 `startTime=`, `endTime=` 형식만 인식 — `start=` 파라미터는 동작하지 않는다.  
오디오는 `OfflineAudioContext`로 16kHz mono WAV로 변환 후 업로드 — 원본 포맷 그대로 업로드 금지.
