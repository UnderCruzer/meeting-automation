## 독립형 회의 워크스페이스 (단일 팀 파일럿)

Slack 계정 없이 **녹음 업로드 → 전사·분석 → 근거 확인 → 승인/거절 → 승인한 업무 목록**을 사용할 수 있습니다. 기존 Slack 기반 흐름도 유지됩니다.

### 실행

1. `backend/.env`에 분석용 `GEMINI_API_KEY`와 전사용 `GROQ_API_KEY` 또는 `OPENAI_API_KEY`를 설정합니다. Claude를 쓰려면 `LLM_PROVIDER=anthropic`과 `ANTHROPIC_API_KEY`를 설정합니다. 실제 업로드 시 사용 중인 공급자 요금이 발생할 수 있습니다.
   - Gemini **무료 등급은 입력 내용이 Google 제품 개선에 사용될 수 있습니다.** 실제 회의 자료는 결제를 연결한 유료 등급 키를 사용하세요. PII는 마스킹 후 전송되지만 회의 내용 자체는 전송됩니다.
2. 루트 `.env`에 임의의 긴 값으로 `BACKEND_API_KEY`와, 최초 관리자 비밀번호 `ADMIN_PASSWORD`(10자 이상)를 설정합니다. 관리자 이름은 `ADMIN_USERNAME`(기본 `admin`)입니다. 관리자 계정은 사용자가 한 명도 없을 때만 만들어집니다.
3. `docker compose -f compose.standalone.yml up --build -d`를 실행합니다.
4. `http://localhost:3001`에 접속해 관리자 계정으로 로그인합니다. **사용자 관리**에서 팀원 계정을 만들고 초기 비밀번호를 전달합니다(첫 로그인 후 변경 안내).
5. 참석자 동의를 받은 녹음을 올리고, 분석 완료 후 근거와 품질 경고를 확인하여 승인합니다.

Jira/Confluence로는 발송하지 않으며, `SLACK_BOT_TOKEN`을 설정하면 승인한 회의를 Slack 채널에 게시합니다(아래 "Slack 채널 게시"). 녹음과 회의 결과, 승인 상태는 `meeting-data` 볼륨에 저장됩니다. 같은 서버에서 재배포해도 볼륨을 유지하면 보존됩니다. 백업 대상에 포함하고 `down -v`는 사용하지 마세요.

### Render 무료 배포 (체험용)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/UnderCruzer/meeting-automation)

1. 위 버튼 → Render 로그인(GitHub 연동) → Blueprint(`render.yaml`) 확인
2. `GEMINI_API_KEY`, `GROQ_API_KEY`만 입력합니다. `BACKEND_API_KEY`와 관리자 비밀번호 `ADMIN_PASSWORD`는 Render가 임의 값으로 생성합니다.
3. 배포 완료 후 서비스 **Environment** 탭에서 `ADMIN_PASSWORD`를 확인하고, `https://<서비스 이름>.onrender.com`에 사용자 이름 `admin`으로 로그인합니다. 로그인 후 비밀번호를 바꾸고 팀원 계정을 만드세요. (무료 플랜은 재시작 시 데이터가 초기화되어 계정도 다시 `ADMIN_PASSWORD`로 만들어집니다.)

- 프런트엔드와 백엔드를 하나의 컨테이너(`deploy/container/Dockerfile`)에서 실행하며, 백엔드는 외부에 노출되지 않습니다. `/api/healthz`만 인증 없이 응답합니다(상태만 반환).
- main에 머지하면 자동 재배포됩니다.
- `onrender.com`은 Cloudflare를 거치므로 Blueprint가 `CLIENT_IP_HEADER=cf-connecting-ip`를 설정합니다. 로그인 실패 제한·업로드 제한·감사 기록이 실제 접속자 IP 기준으로 동작합니다.
- **무료 인스턴스는 15분 미사용 시 잠들고(첫 접속 약 1분), 재시작·재배포·잠들기 시 회의와 녹음이 초기화됩니다.** 보존이 필요하면 유료 플랜 + Persistent Disk(`/app/data`)나 위 Compose 구성을 사용합니다.
- 업로드와 전사는 스트리밍으로 처리해 녹음 길이와 관계없이 메모리가 일정합니다(512MB 제한에서 150분 녹음 확인). 한 번에 올릴 수 있는 녹음은 500MB(약 4시간)까지입니다. 브라우저가 녹음을 WAV로 변환하므로 매우 긴 파일은 사용자 기기 메모리를 많이 씁니다.

### Hugging Face 배포

Docker Space는 현재 PRO 구독이 필요합니다. 사용할 경우 `deploy/container/Dockerfile`을 업로드 루트의 `Dockerfile`로, `deploy/huggingface/README.md`를 Space 루트 README로 사용하고 위와 같은 값을 Space Secrets에 등록합니다. 영구 저장소는 없습니다.

### 캘린더 감지 → Slack DM → 녹음 준비 (워크플로 1~3)

회의 5분 전에 참석자에게 Slack DM(참석자 현지 시간 표시)으로 "녹음 세션을 준비할까요?"를 보내고, **녹음 준비**를 누르면 녹음 페이지 링크를 보냅니다. 배포 컨테이너는 `SLACK_BOT_TOKEN`과 `SLACK_APP_TOKEN`이 모두 있을 때 Slack 봇을 함께 실행합니다(Socket Mode라 공개 URL 불필요).

1. **캘린더 구독 주소**(OAuth 불필요): Google 캘린더 → 설정 → 해당 캘린더 → **"iCal 형식의 비공개 주소"** 복사 / Outlook → 설정 → 일정 → 공유 일정 → **캘린더 게시**의 ICS 링크. 여러 개면 쉼표로 구분해 `CALENDAR_ICS_URLS`에 넣습니다. 이 주소는 비밀번호와 같으니 공유하지 마세요.
2. **Slack 앱 수준 토큰**: Slack 앱 → **Basic Information → App-Level Tokens → Generate**, 범위 `connections:write` → `xapp-…`를 `SLACK_APP_TOKEN`에 넣습니다. (앱 매니페스트에 Socket Mode·Interactivity·`users:read.email`이 켜져 있어야 합니다.)
3. 참석자 이메일이 Slack 계정 이메일과 같아야 DM이 갑니다. 장소가 있는 회의만 대상이며, 온라인 회의도 포함하려면 `CALENDAR_INCLUDE_ONLINE=true`.
4. **무료 플랜 절전 방지**: Render 무료 인스턴스는 15분간 요청이 없으면 잠들어 캘린더 감지가 멈춥니다. GitHub 저장소 **Settings → Secrets and variables → Actions → Variables**에 `KEEPALIVE_URL`(배포 주소)을 추가하면 `.github/workflows/keepalive.yml`이 10분마다 깨웁니다(한 서비스 상시 실행 ≈ 월 744시간, 무료 750시간 이내).

**녹음 링크(워크플로 4~6)**: DM의 녹음 링크는 회의·Slack 사용자·만료 시각(회의 종료 2시간 후)을 `RECORDING_LINK_SECRET`으로 서명한 링크입니다. 웹 로그인 없이 **그 회의의 녹음 페이지와 업로드만** 허용하고, 다른 회의로 바꾸거나 위조·만료된 링크는 거부합니다. 업로드한 사람은 `slack:<사용자ID>`로 회의 목록과 감사 기록에 남습니다. 회의 시작 시각이 되면 자동으로 녹음을 시작하고 종료 시각에 멈춘 뒤 업로드합니다.

Microsoft 365 계정은 기존 Graph 연동(`AZURE_*`)도 계속 지원하지만 로그인 콜백이 내부 포트라 배포 환경에서는 ICS 방식을 권장합니다.

### Slack 채널 게시 (워크플로 16→17→18→19)

승인하면 **Write Queue**가 **Timezone Scheduler** 결과에 따라 근무시간에는 바로, 근무시간 외에는 다음 근무 시작 시각(주말 제외)에 **지역 채널**로 게시합니다. 메시지는 Slack Brief 형식(요약·결정·할 일·담당자)이고, APAC은 한국어, EU/NA는 영어입니다. 승인할 때 "지금 바로 게시"를 고를 수 있고, 실패하거나 서버 재시작으로 예약이 취소되면 회의 화면에서 다시 게시할 수 있습니다.

1. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From scratch**, 내 워크스페이스 선택 (무료 워크스페이스로 충분합니다)
2. **OAuth & Permissions → Bot Token Scopes**에 `chat:write` 추가 → **Install to Workspace** → `xoxb-…` 토큰 복사
3. 게시할 채널에서 `/invite @앱이름`으로 봇 초대, 채널 정보 하단의 **채널 ID**(`C0…`) 복사
4. 환경변수: `SLACK_BOT_TOKEN`, `SLACK_BRIEF_CHANNEL`(채널 ID). 지역별로 나누려면 `SLACK_CHANNEL_APAC`/`SLACK_CHANNEL_EU`/`SLACK_CHANNEL_NA`. 팀 시간대는 `WORKSPACE_TIMEZONES`(기본 `Asia/Seoul`, 쉼표로 여러 개 → 다수결로 지역 결정)

예약 게시는 서버 메모리에 있어 재시작하면 취소되고 "실패"로 표시됩니다. Slack 채널에는 가명이 아닌 실명이 게시됩니다.

### 아침 브리핑·주간 다이제스트 (워크플로 20~21)

Slack 게시가 설정되어 있으면 백엔드가 팀 시간대(`WORKSPACE_TIMEZONES` 첫 값) 기준으로 **평일 `BRIEFING_TIME`(기본 09:00)**에 채널(`DIGEST_CHANNEL`, 없으면 `SLACK_BRIEF_CHANNEL`)로 보냅니다.

- **Morning Brief**: 기한 지남 / 오늘 마감 / 내일(금요일엔 다음 근무일) 마감 할 일, 지난 근무일 이후 승인된 회의. 보낼 내용이 없으면 보내지 않습니다.
- **Weekly Digest**(월요일): 지난 7일 승인 회의·결정, 할 일 생성/완료/미완료, 기한 지난 할 일, 담당자별 미완료
- **승인된 회의만** 사용하고 고정 템플릿으로 만듭니다(LLM 미사용). 할 일을 **완료 체크**하면 기한 알림에서 빠집니다.
- 기한은 "2026-10-10", "10/10", "10월 10일", "내일", "다음 주 금요일" 등을 회의 날짜 기준으로 해석하고, 해석할 수 없는 문구는 알림 대상에서 제외합니다.
- 하루 한 번만 보내며, 무료 호스팅이 잠들어 있었다면 깨어난 뒤 정오까지 보충 발송합니다(절전 방지 설정 권장).
- 담당자 멘션: `SLACK_USER_MAP="김민수=U0123,박지은=U0456"`. 끄려면 `BRIEFING_ENABLED=false`. 관리자 화면 **브리핑** 탭에서 미리 보고 바로 보낼 수 있습니다.

### 보안 설정

- **인증:** 개인 계정 + 세션 로그인. 비밀번호는 scrypt 해시, 세션 토큰은 HttpOnly·SameSite=Lax 쿠키(HTTPS에서 Secure)로만 전달되고 서버에는 해시만 저장됩니다(기본 12시간, `SESSION_TTL_HOURS`). 관리자는 사용자 추가·비활성화·역할 변경·비밀번호 재설정을 할 수 있고, 비활성화·재설정 시 해당 사용자의 세션이 즉시 끊깁니다. 로그인 실패는 IP당 15분 내 `AUTH_MAX_FAILURES`(기본 20)회, 사용자 이름당 5회로 제한합니다. 이전 `WORKSPACE_PASSWORD`만 설정된 배포는 첫 실행 때 `workspace` 관리자 계정으로 옮겨집니다.
- **감사 기록:** 로그인·로그인 실패·로그아웃·비밀번호 변경·사용자 추가/변경·업로드·승인·거절·삭제·보존 기간 만료 삭제를 시각·사용자·IP와 함께 남깁니다. 관리자 **사용자 관리** 화면에서 최근 기록을 볼 수 있고, 회의를 삭제해도 기록(제목만)은 남습니다. 회의 상세에는 업로드한 사람과 승인·거절한 사람이 표시됩니다.
- **CSRF:** 세션 쿠키는 SameSite=Lax이고, 추가로 상태를 바꾸는 요청은 `Sec-Fetch-Site`/`Origin`이 같은 출처일 때만 허용합니다.
- **보안 헤더:** CSP(`frame-ancestors 'none'`), `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`(마이크만 허용), HSTS. `X-Powered-By`와 이미지 최적화 엔드포인트는 끕니다.
- **요청 제한:** 업로드는 실제 클라이언트 IP 기준으로 제한합니다. 백엔드는 API 키가 맞는 내부 요청의 `X-Client-IP`만 신뢰합니다.
- **의존성:** CI가 `pip-audit`, `npm audit --audit-level=high`로 알려진 취약점을 검사합니다.
- **실패 처리:** Gemini가 혼잡(503)·한도 초과(429)·일시 오류를 내면 간격을 늘려가며 재시도하고(`GEMINI_MAX_ATTEMPTS`), 그래도 안 되면 `GEMINI_FALLBACK_MODELS`로 시도합니다. 분석 단계에서 실패한 회의는 가려진 전사문만 보관해 두었다가 화면의 **다시 분석**으로 재시도할 수 있습니다(재업로드·재전사 없음). 실패 화면에는 단계별 이유(전사 실패, AI 혼잡, 분석 실패, 음성 없음, 서버 재시작)가 표시됩니다.
- **데이터 보존:** 처리가 끝나면(실패 포함) 원본 녹음을 삭제하고 원문 전사는 저장하지 않습니다(`RETAIN_RAW_RECORDINGS=true`일 때만 보관). 검토 화면의 근거 인용문도 개인정보 패턴을 가린 전사에서 가져옵니다. 회의는 화면에서 삭제할 수 있고(분석 중 제외), `MEETING_RETENTION_DAYS`를 설정하면 기간이 지난 회의가 자동 삭제됩니다.

### 외부 공급자 데이터 정책 (2026-10 기준, 사용 전 원문 확인)

| 공급자 | 전송 데이터 | 정책 요약 | 권장 설정 |
|---|---|---|---|
| Groq (전사) | **원본 녹음** (음성은 마스킹 불가) | 기본적으로 추론 데이터 비보관. 오류·남용 조사 시 최대 30일 로그 | 콘솔에서 **Zero Data Retention** 켜기 |
| Gemini (분석) | 개인정보 패턴을 가린 전사문 | **무료 등급: 학습·제품 개선에 사용, 사람이 검토할 수 있음.** 유료 등급: 학습 미사용, 정책 위반 탐지용으로만 제한 기간 보관 | API 키 프로젝트에 **Cloud Billing 연결**(연결하면 유료 등급으로 처리) |
| Claude (선택) | 개인정보 패턴을 가린 전사문 | 상용 API 약관 적용 | — |
| Slack (선택) | 승인한 회의의 요약·결정·할 일(실명) | 내 워크스페이스 정책 적용 | 게시 채널 멤버 확인 |

마스킹은 정규식 기반(주민번호·카드·전화·이메일·비밀번호)이며, **사람 이름은 가명(`[PERSON_n]`)으로 바꿔 전송**합니다. 가명 대상은 업로드 시 입력한 참석자 이름, "김민수 팀장"·"박지은님"처럼 호칭·직함이 붙은 한국어 이름, "Mr. Kim" 같은 영문 이름입니다. 가명과 실명의 대응표는 서버에만 저장되고, 검토 화면에서는 원래 이름으로 복원해 보여줍니다. 호칭 없이 부른 이름(참석자 목록에 없을 때), 주소, 사내 기밀은 가려지지 않습니다. 실제 회의 자료는 위 권장 설정을 마친 뒤 올리세요.

### 배포 범위와 다음 단계

Docker를 지원하는 서버에서 동일한 구성으로 실행하고, 3001 포트 앞에 **HTTPS와 접근 제한**을 설정합니다. 백엔드 포트는 호스트에 노출하지 않습니다. 여러 인스턴스 대신 백엔드 한 개로 실행합니다.

- 공유 비밀번호를 사용하는 단일 팀 파일럿입니다. 사용자 가입·팀별 권한 분리·개별 감사 이력은 아직 없습니다.
- 처리 중 서버가 재시작되면 해당 작업은 실패로 표시되며 다시 업로드해야 합니다. 재개 가능한 작업 큐는 후속 범위입니다.
- 승인 결과는 내부 목록에 보관됩니다. 담당자 알림, 완료 상태 변경, 삭제/보존 정책 UI, 초안 수정은 후속 범위입니다.
- 근거 연결은 키워드 유사도 기반 후보이며 사실 검증을 보장하지 않습니다.
- 목록에는 최근 100개 회의가 표시됩니다. 사용자별 데이터 분리 이전에 불특정 다수에게 공개하지 않습니다.
