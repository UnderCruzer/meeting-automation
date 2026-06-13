# Recording Page — Next.js 14 App Router, TypeScript

## 주요 파일

| 파일 | 역할 |
|------|------|
| `src/app/page.tsx` | 메인 랜딩 (Slack DM 링크로 진입 안내) |
| `src/app/record/page.tsx` | 메인 녹음 UI — Suspense 래핑 필수 (`useSearchParams` 사용) |
| `src/hooks/useRecorder.ts` | MediaRecorder + WAV 인코딩, 업로드 |
| `src/hooks/useWaveform.ts` | AnalyserNode 실시간 파형 시각화 |
| `src/hooks/useCountdown.ts` | 회의 시작 카운트다운 타이머 |
| `src/lib/audioEncoder.ts` | OfflineAudioContext → 16kHz mono WAV 변환 |

## URL 파라미터
`/record` 페이지는 `startTime`과 `endTime` 쿼리 파라미터 필수:
```
/record?meetingId=xxx&title=xxx&startTime=1234567890&endTime=1234571490
```
`start=` 파라미터는 인식 안 됨 — 반드시 `startTime=` 사용.

## 주의사항
- `next.config.js` 사용 (`.ts` 불가 — Next.js 14.2.35 미지원)
- `useCountdown.ts`: `let id` 를 `tick()` 정의 위에 호이스팅 필수 (TDZ 방지)
- `useSearchParams` 사용 컴포넌트는 반드시 `Suspense`로 래핑
