---
title: Meeting Automation
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Meeting Automation

녹음 업로드 → 전사·분석 → 회의록과 근거 검토 → 승인 → 내부 업무 목록.

단일 팀 체험용입니다. 직접 앱 URL을 열어 관리자가 만들어 준 계정으로 로그인합니다.
무료 Space의 로컬 저장소는 재시작·재배포 시 초기화됩니다. 보존할 회의 자료를 올리지 마세요.
분석은 Gemini(또는 Claude), 전사는 Groq Whisper를 사용하며 공급자 사용량 제한과 요금이 적용될 수 있습니다.

소스와 실행 안내: https://github.com/UnderCruzer/meeting-automation

## Space Secrets

`GEMINI_API_KEY`(Claude 사용 시 `ANTHROPIC_API_KEY`), `GROQ_API_KEY`, `BACKEND_API_KEY`, `ADMIN_PASSWORD`(최초 관리자, 10자 이상)를 Settings → Secrets에 설정합니다.
키와 비밀번호, 녹음 데이터는 저장소에 업로드하지 않습니다. 백엔드는 컨테이너 내부에서만 접근 가능합니다.
