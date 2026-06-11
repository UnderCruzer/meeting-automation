# Contributing Guide

## Branch Strategy

```
main
└── develop
    ├── feat/issue-02-slack-dm-alert
    ├── feat/issue-04-recording-page
    └── fix/issue-08-guard-masking
```

- `main` → 배포 가능한 상태만
- `develop` → 통합 브랜치
- `feat/issue-{번호}-{short-desc}` → 기능 개발
- `fix/issue-{번호}-{short-desc}` → 버그 수정
- `chore/` → 설정, 빌드, 문서

## Commit Convention

```
<type>(<scope>): <subject>

[body]

[footer]
```

### Type

| Type | 설명 |
|------|------|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `refactor` | 리팩토링 (기능 변경 없음) |
| `test` | 테스트 추가/수정 |
| `chore` | 빌드, 패키지, 설정 변경 |
| `docs` | 문서만 변경 |
| `style` | 포맷, 세미콜론 등 (로직 변경 없음) |

### Scope (선택)

컴포넌트 번호 또는 모듈명: `slack`, `recording`, `stt`, `ai`, `jira`, `confluence`

### Rules

- subject: 영어, 소문자 시작, 동사 원형, 마침표 없음
- 한 커밋 = 한 논리 단위 (원자 단위)
- 50자 이내 subject
- body: 무엇을, 왜 변경했는지 (how는 코드로)

### Examples

```
feat(slack): add DM alert with recording approval buttons

fix(stt): handle empty audio file edge case

refactor(ai): extract prompt templates to separate module

chore: add eslint and prettier config

docs: update README with architecture diagram
```

## PR Convention

- 제목: `feat(scope): 간단한 설명 (#이슈번호)` — 커밋 컨벤션과 동일한 형식 사용
- 본문: PR 템플릿([`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)) 자동 적용
- 관련 이슈는 본문에 `closes #번호` 로 연결
- 리뷰어 지정 후 머지 (Merge commit 사용, 원자 커밋 유지)

## Code Review

- `/code-review` 스킬로 리뷰 진행
- Critical 이슈만 수정 후 재커밋
- Non-critical은 follow-up 이슈로 등록
