---
name: harness
description: 기능 요청을 받아 Clarify -> Context Gather -> Plan -> Generate -> Evaluate 5단계로 구현하는 워크플로우. 프로젝트 생성 및 기능 구현에 사용.
argument-hint: "<기능 요청 설명>"
allowed-tools: Bash Read Write Edit Glob Grep Agent AskUserQuestion
---

# Harness Workflow

사용자의 기능 요청 `$ARGUMENTS`를 아래 5단계 파이프라인으로 처리한다.
각 단계는 **독립된 sub-agent**로 실행되며, 결과를 **artifact 파일**로 생성하여 다음 단계에 전달한다.

## Artifact 디렉토리 구조

```
artifacts/
├── 01-clarify.md        # Step 1 결과: 분석된 요구사항 + 논의 결과
├── 02-context.md        # Step 2 결과: 코드베이스 컨텍스트 요약
├── 03-plan/             # Step 3 결과: Phase/Task YAML 파일들
│   ├── phase-1-*.yaml
│   └── phase-2-*.yaml
├── 04-generate.md       # Step 4 결과: 생성/실행 결과 리포트
└── 05-evaluate.md       # Step 5 결과: 품질 검증 리포트
```

## 실행 흐름

### 사전 준비

1. `artifacts/` 디렉토리를 생성한다 (이미 있으면 기존 artifact를 정리할지 사용자에게 확인).
2. 사용자의 요청 `$ARGUMENTS`를 `artifacts/00-request.md`에 원문 그대로 저장한다.

---

### Step 1: Clarify (Sub-Agent)

Agent 도구를 사용하여 Clarify 에이전트를 호출한다.

**Agent 호출 설정:**
- `subagent_type`: `general-purpose`
- `description`: `Clarify requirements`

**Agent Prompt:**
```
당신은 소프트웨어 요구사항 분석가입니다.

## 입력
아래 파일을 읽어 사용자의 기능 요청을 파악하세요:
- artifacts/00-request.md

## 작업
요청을 분석하고 다음 관점에서 **논의점**을 정리하세요:

- **구현가능성**: 기술적 제약, 필요한 라이브러리/서비스, 예상되는 난이도
- **UX**: 사용자 플로우, 화면 구성, 인터랙션 방식
- **데이터베이스**: 필요한 테이블/컬렉션, 관계, 인덱스
- **API 설계**: 엔드포인트, 요청/응답 형태
- **보안**: 인증/인가, 입력 검증
- **기타**: 성능, 확장성, 외부 의존성

해당되지 않는 관점은 생략하세요.

## 출력
분석 결과를 `artifacts/01-clarify.md` 파일에 아래 형식으로 작성하세요:

```markdown
# 요구사항 분석

## 요청 요약
(요청을 1-2문장으로 요약)

## 논의점
### 1. (논의 주제)
- 질문/제안 내용
- 대안이 있다면 제시

### 2. ...

## 초기 기술 판단
- 예상 기술 스택: ...
- 예상 복잡도: 낮음/중간/높음
- 핵심 리스크: ...
```

파일 작성 후 논의점 요약을 텍스트로 반환하세요.
```

**Agent 결과 처리:**
1. Agent가 반환한 논의점 요약을 사용자에게 표시한다.
2. 사용자에게 확인/수정/추가 의견을 요청한다.
3. 사용자의 피드백을 `artifacts/01-clarify.md`에 `## 사용자 피드백` 섹션으로 추가한다.

> **중요**: 사용자가 응답할 때까지 다음 단계로 진행하지 않는다.

---

### Step 2: Context Gather (Sub-Agent)

Agent 도구를 사용하여 Context Gather 에이전트를 호출한다.

**Agent 호출 설정:**
- `subagent_type`: `Explore`
- `description`: `Gather codebase context`

**Agent Prompt:**
```
당신은 코드베이스 분석가입니다.

## 입력
아래 파일을 읽어 구현할 기능을 파악하세요:
- artifacts/00-request.md (원래 요청)
- artifacts/01-clarify.md (요구사항 분석 및 사용자 피드백)

## 작업
프로젝트 루트에서 기존 코드베이스를 탐색하고 다음을 파악하세요:

1. **프로젝트 구조**: 디렉토리 레이아웃, 주요 파일
2. **기술 스택**: 프레임워크, 언어, 빌드 도구, 패키지 매니저
3. **코드 컨벤션**: 네이밍, 디렉토리 규칙, 패턴 (MVC, 레이어드 등)
4. **관련 기존 코드**: 새 기능과 연관된 모듈, 파일, 함수
5. **설정 파일**: tsconfig, package.json, .env.example 등
6. **데이터베이스**: 기존 스키마, 마이그레이션, ORM 설정

코드베이스가 비어있으면(프로젝트 신규 생성) 그 사실을 명시하세요.

## 출력
분석 결과를 `artifacts/02-context.md` 파일에 아래 형식으로 작성하세요:

```markdown
# 코드베이스 컨텍스트

## 프로젝트 개요
- 타입: (신규 / 기존 프로젝트)
- 기술 스택: ...
- 패키지 매니저: ...

## 디렉토리 구조
(주요 디렉토리/파일 트리)

## 코드 컨벤션
- 네이밍: ...
- 패턴: ...
- 스타일: ...

## 관련 기존 코드
(새 기능과 관련된 파일/모듈 목록 + 간단한 설명)

## 설정 및 환경
(주요 설정 파일 내용 요약)

## 의존성
(관련 패키지/라이브러리 목록)
```

파일 작성 후 핵심 발견사항을 간단히 반환하세요.
```

**Agent 결과 처리:**
1. Agent가 반환한 컨텍스트 요약을 사용자에게 간단히 표시한다.
2. 바로 다음 단계로 진행한다.

---

### Step 3: Plan (Sub-Agent)

Agent 도구를 사용하여 Plan 에이전트를 호출한다.

**Agent 호출 설정:**
- `subagent_type`: `Plan`
- `description`: `Create implementation plan`

**Agent Prompt:**
```
당신은 소프트웨어 아키텍트입니다.

## 입력
아래 artifact 파일들을 읽어 전체 컨텍스트를 파악하세요:
- artifacts/00-request.md (원래 요청)
- artifacts/01-clarify.md (요구사항 분석 + 사용자 피드백)
- artifacts/02-context.md (코드베이스 컨텍스트)

## 작업
작업을 Phase와 Task로 구조화하여 `artifacts/03-plan/` 디렉토리에 YAML 파일로 생성하세요.

### 파일 형식

`artifacts/03-plan/phase-{N}-{name}.yaml`:

```yaml
phase: 1
name: "Phase 이름"
description: "Phase 설명"
tasks:
  - id: "1.1"
    name: "Task 이름"
    description: "Task 설명"
    artifacts:
      inputs: ["artifacts/02-context.md"]
      outputs: ["src/path/to/file.ts"]
    prompt: |
      구체적인 구현 지시사항.
      어떤 파일을 만들고, 어떤 코드를 작성해야 하는지 상세히 기술.

      ## 참고 컨텍스트
      - artifacts/02-context.md 를 읽어 프로젝트 컨벤션을 따르세요.

      ## 구현 내용
      1. (구체적 단계)
      2. ...

      ## 완료 조건
      - (검증 가능한 조건)
    depends_on: []
  - id: "1.2"
    name: "다음 Task"
    description: "설명"
    artifacts:
      inputs: ["src/path/from/1.1.ts"]
      outputs: ["src/path/to/new-file.ts"]
    prompt: |
      구현 지시사항.
    depends_on: ["1.1"]
```

### 규칙

- Phase는 논리적 단위로 나눈다 (예: 프로젝트 설정, DB 스키마, API, 프론트엔드)
- 각 Task의 `prompt`는 Claude가 독립적으로 실행할 수 있을 만큼 구체적으로 작성
- `prompt`에는 파일 경로, 함수명, 구체적 구현 내용을 포함
- `prompt`에 필요한 artifact 파일 읽기 지시를 포함 (컨텍스트 전달)
- `artifacts.inputs`/`artifacts.outputs`로 Task 간 데이터 흐름을 명시
- Task 간 의존 관계를 `depends_on`으로 명시
- 의존 관계가 없는 Task는 병렬 실행 가능함을 고려

## 출력
1. `artifacts/03-plan/` 디렉토리에 Phase YAML 파일들을 생성
2. 전체 계획 요약을 텍스트로 반환 (Phase 수, Task 수, 핵심 흐름)
```

**Agent 결과 처리:**
1. Agent가 반환한 계획 요약을 사용자에게 표시한다.
2. 사용자에게 계획 확인/수정을 요청한다.
3. 수정이 필요하면 Plan 에이전트를 다시 호출하거나 직접 YAML을 수정한다.

> **중요**: 사용자가 확인할 때까지 다음 단계로 진행하지 않는다.

---

### Step 4: Generate (Sub-Agent)

`artifacts/03-plan/` 의 Phase YAML 파일들을 읽고, 각 Task를 sub-agent로 실행한다.

**실행 방식:**

1. Phase YAML 파일들을 Phase 번호 순으로 로드한다.
2. 각 Phase 내 Task를 `depends_on` 기반으로 위상 정렬한다.
3. **의존관계가 없는 Task들은 병렬로** Agent를 호출한다 (동일 메시지에 여러 Agent 호출).
4. **의존관계가 있는 Task는 선행 Task 완료 후** 순차 실행한다.

**각 Task의 Agent 호출 설정:**
- `subagent_type`: `general-purpose`
- `description`: `Task {task_id}: {task_name}`

**각 Task의 Agent Prompt:**
```
{task.prompt 내용을 그대로 전달}

## 추가 지시사항
- 작업 완료 후 변경된 파일 목록과 핵심 변경 내용을 텍스트로 반환하세요.
- 오류가 발생하면 오류 내용과 시도한 해결 방법을 반환하세요.
```

**결과 수집:**
- 각 Task Agent의 반환 결과를 수집한다.
- 모든 Task 완료 후, 전체 결과를 `artifacts/04-generate.md`에 아래 형식으로 작성한다:

```markdown
# 생성 결과 리포트

## 실행 요약
- 총 Phase: N개
- 총 Task: N개
- 성공: N개
- 실패: N개

## Task별 결과

### Task 1.1: {name}
- 상태: 성공/실패
- 변경 파일: ...
- 요약: ...

### Task 1.2: {name}
...
```

- 실패한 Task가 있으면 사용자에게 보고하고, 재시도 여부를 확인한다.

---

### Step 5: Evaluate (Sub-Agent)

Agent 도구를 사용하여 Evaluate 에이전트를 호출한다.

**Agent 호출 설정:**
- `subagent_type`: `general-purpose`
- `description`: `Evaluate implementation quality`

**Agent Prompt:**
```
당신은 소프트웨어 품질 엔지니어입니다.

## 입력
아래 artifact 파일들을 읽어 전체 맥락을 파악하세요:
- artifacts/00-request.md (원래 요청)
- artifacts/01-clarify.md (요구사항)
- artifacts/04-generate.md (생성 결과 리포트)

## 작업
생성된 코드의 품질을 검증하세요.

### 1. 자동 검증 (프로젝트에 해당 도구가 있을 때만)
- **Type Check**: tsc --noEmit, mypy, pyright 등
- **Lint**: eslint, ruff, flake8 등
- **Build**: npm run build, cargo build 등
- **Test**: npm test, pytest 등

package.json, pyproject.toml 등을 확인하여 사용 가능한 도구를 판별하세요.
설정이 없는 도구는 건너뛰세요.

### 2. 수동 검증
- 요구사항 대비 구현 완성도 체크
- 명백한 버그나 누락된 부분 확인
- 보안 취약점 확인

### 3. 오류 수정
발견된 오류는 직접 수정하세요.

## 출력
검증 결과를 `artifacts/05-evaluate.md` 파일에 아래 형식으로 작성하세요:

```markdown
# 품질 검증 리포트

## 자동 검증 결과
| 도구 | 상태 | 비고 |
|------|------|------|
| TypeCheck | ✅ Pass / ❌ Fail / ⏭ Skip | ... |
| Lint | ... | ... |
| Build | ... | ... |
| Test | ... | ... |

## 수동 검증 결과
### 요구사항 충족도
- [ ] (요구사항 1) - 충족/미충족
- [ ] (요구사항 2) - ...

### 발견된 이슈
1. (이슈 설명 + 수정 여부)

## 수정 사항
- (수정한 파일과 내용)

## 최종 판정
(Pass / Conditional Pass / Fail)
```

파일 작성 후 최종 판정과 요약을 반환하세요.
```

**Agent 결과 처리:**
1. Agent가 반환한 최종 판정을 사용자에게 표시한다.
2. 필요시 `artifacts/05-evaluate.md`의 상세 내용을 안내한다.

---

## 완료

모든 단계가 끝나면 사용자에게 다음을 보고한다:

1. **파이프라인 완료 요약**: 각 단계별 상태
2. **Artifact 위치**: `artifacts/` 디렉토리 내 파일 목록
3. **다음 단계 제안**: 테스트, 배포, 추가 기능 등
