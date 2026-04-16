---
name: harness
description: 기능 요청을 받아 Clarify -> Context -> Plan -> Generate -> Evaluate 5단계로 구현하는 워크플로우. 결정적 상태 관리는 CLI(harness.py)에 위임하고, 창의적 판단은 Claude가 Agent 호출로 수행.
argument-hint: "<기능 요청 설명>"
allowed-tools: Bash Read Write Edit Glob Grep Agent AskUserQuestion
---

# Harness Workflow

사용자의 기능 요청 `$ARGUMENTS`를 5단계 파이프라인으로 처리한다.
각 단계는 **창의적 판단**(Claude)과 **결정적 상태 관리**(harness CLI)로 분리된다.

## 두 레인 모델

| 레인 | 누가 | 무엇을 |
|---|---|---|
| 창의 | Claude (Agent 호출 포함) | 요구사항 분석, 코드베이스 해석, 계획 수립, 구현, 품질 판단, 실패 원인 해석, 사용자 대화 |
| 결정적 | `harness.py` CLI | 슬러그 생성·충돌 처리, 상태 스캔, 다음 task 결정, 사이드카 쓰기, 산출물 검증, 병렬 충돌 감지, summary 집계, 승인 기록, 계획 아카이브 |

**원칙:** Claude는 task 사이드카(`.harness/{slug}/04-generate/task-*.json`)를 손으로 읽거나 쓰지 않는다. 항상 CLI를 통한다. CLI는 절대 LLM을 호출하지 않는다.

## 사전 요건

- Python 3.9+
- PyYAML (`pip install pyyaml`)

## CLI 호출 관례

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" <subcommand> [args...]
```

- exit 0: stdout이 JSON. 파싱해서 판단에 사용.
- exit ≠ 0: stderr 메시지를 사용자에게 그대로 보이고, **파이프라인 진행을 멈춤**.
- 환경변수:
  - `HARNESS_MAX_ATTEMPTS` (기본 1): task 재시도 예산.

> **표기 규약**: 아래 본문에서 인라인 코드로 적힌 `harness <subcommand> ...`는 모두 위 전체 경로(`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" <subcommand> ...`)의 축약 표기다. Bash로 실행할 때는 항상 전체 경로를 써야 한다.

각 subcommand의 상세 계약은 `scripts/README.md` 참조.

---

## Step 0: 진입 / Resume 판정

사용자 요청이 들어오면 **반드시 이 단계부터** 시작한다.

### 0-1. 슬러그 결정

요청 `$ARGUMENTS`를 요약해 영어 kebab-case 슬러그를 제안한다 (예: "로그인 기능 추가" → `add-login-feature`).

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" slug \
  --request "$ARGUMENTS" \
  --suggested "add-login-feature"
```

### 0-2. 반환 JSON의 `status`에 따라 분기

**`status: "created"`**: 신규 파이프라인. Step 1로 진행.

**`status: "exists"`**: 동일 요청이 이미 있음. `scan`으로 재개 지점 판정:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" scan <slug>
```
반환의 `resume_point.reason`을 읽어:
- `pipeline_complete` → 사용자에게 "이미 완료됨" 보고. 끝.
- `steps_incomplete` (carries `step`) → 해당 Step으로 점프.
- `waiting_for_approval` (carries `step`) → 그 Step의 아티팩트를 사용자에게 다시 보여주고 승인 받기 → `harness approve`.
- `not_started` / `failed_within_budget` / `in_progress` (carries `task_id`) → Step 4 실행 루프로 진입.
- `blocked` (carries `blocked_tasks`) → 사용자에게 차단된 task와 원인 보고, 재시도/건너뛰기/중단 선택.

**`status: "collision"`**: 같은 슬러그지만 요청 내용이 다름. 사용자에게 "기존 `<slug>`와 내용이 달라요. 새 요청이면 `<suggested_slug>`로 진행할까요?" 확인. 승인 시 `--suggested <suggested_slug>`로 다시 `slug` 호출.

### 0-3. 사용자 재시작 요청

"처음부터 다시"를 원하면 백업 후 재생성:
```bash
mv .harness/<slug> ".harness/<slug>.backup-$(date -u +%Y-%m-%dT%H-%M-%SZ)"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" slug --request "$ARGUMENTS" --suggested "<slug>"
```

---

## Step 1: Clarify (Sub-Agent)

**Agent 호출 설정:**
- `subagent_type`: `general-purpose`
- `description`: `Clarify requirements`

**Agent Prompt:**
```
당신은 소프트웨어 요구사항 분석가입니다.

## 입력
아래 파일을 읽어 사용자의 기능 요청을 파악하세요:
- {BASE}00-request.md

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
분석 결과를 `{BASE}01-clarify.md` 파일에 아래 형식으로 작성하세요:

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

> `{BASE}`는 `.harness/<slug>/`로 치환해 전달한다.

### Step 1 사후 처리

1. Agent의 논의점 요약을 사용자에게 표시.
2. 사용자 피드백 받기 (AskUserQuestion 또는 자연스러운 대화).
3. 피드백을 `{BASE}01-clarify.md`에 `## 사용자 피드백` 섹션으로 **Edit 도구**로 추가 (사람용 산문 편집이므로 CLI 개입 없음).
4. **승인 기록** (게이트 통과):
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" approve <slug> \
  --step 1 \
  --feedback "<사용자 코멘트 요약 또는 생략>"
```

승인 기록 없이는 `scan`이 `waiting_for_approval`을 반환해 Step 2 진행이 막힌다.

---

## Step 2: Context Gather (Sub-Agent)

**Agent 호출 설정:**
- `subagent_type`: `Explore`
- `description`: `Gather codebase context`

**Agent Prompt:**
```
당신은 코드베이스 분석가입니다.

## 입력
아래 파일을 읽어 구현할 기능을 파악하세요:
- {BASE}00-request.md (원래 요청)
- {BASE}01-clarify.md (요구사항 분석 및 사용자 피드백)

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
분석 결과를 `{BASE}02-context.md` 파일에 아래 형식으로 작성하세요:

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

### Step 2 사후 처리

1. 핵심 발견사항을 사용자에게 한 단락으로 요약.
2. **게이트 없음** — 바로 Step 3.

---

## Step 3: Plan (Sub-Agent)

### 재계획 판정 (Plan Agent 호출 전)

이전에 Step 4가 실행된 적이 있는지 확인:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" scan <slug>
```

반환의 `phases[].tasks[]`에 `status != "not_started"`인 task가 하나라도 있으면 **기존 계획을 아카이브해야 한다**:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" archive-plan <slug>
```

이 명령은 현재 `03-plan/`을 `03-plan.v{N}/`으로 이동하고 빈 `03-plan/`을 만든다. 기존 사이드카(`04-generate/task-*.json`)는 건드리지 않는다 — 다음 `scan` 호출 시 `stale[]`로 표시되어 Claude가 영향을 받는 task를 재실행할지 판단한다.

### Agent 호출 설정

- `subagent_type`: `Plan`
- `description`: `Create implementation plan`

**Agent Prompt:**
```
당신은 소프트웨어 아키텍트입니다.

## 입력
아래 artifact 파일들을 읽어 전체 컨텍스트를 파악하세요:
- {BASE}00-request.md (원래 요청)
- {BASE}01-clarify.md (요구사항 분석 + 사용자 피드백)
- {BASE}02-context.md (코드베이스 컨텍스트)

## 작업
작업을 Phase와 Task로 구조화하여 `{BASE}03-plan/` 디렉토리에 YAML 파일로 생성하세요.

### 파일 형식

`{BASE}03-plan/phase-{N}-{name}.yaml`:

```yaml
phase: 1
name: "Phase 이름"
description: "Phase 설명"
tasks:
  - id: "1.1"
    name: "Task 이름"
    description: "Task 설명"
    artifacts:
      inputs: ["{BASE}02-context.md"]
      outputs: ["src/path/to/file.ts"]
    prompt: |
      구체적인 구현 지시사항.

      ## 참고 컨텍스트
      - {BASE}02-context.md 를 읽어 프로젝트 컨벤션을 따르세요.

      ## 구현 내용
      1. (구체적 단계)

      ## 완료 조건
      - (검증 가능한 조건)
    depends_on: []
```

### 규칙

- Phase는 논리적 단위로 나눈다 (프로젝트 설정, DB 스키마, API, 프론트엔드 등)
- 각 Task의 `prompt`는 Claude가 독립적으로 실행 가능할 만큼 구체적
- `artifacts.inputs`/`artifacts.outputs`로 Task 간 데이터 흐름 명시
- `depends_on`으로 의존 관계 명시 (없는 Task는 병렬 실행 후보)
- Task id 형식: `{phase}.{seq}` (예: "1.1", "2.3")
- **같은 파일을 출력하는 병렬 후보 Task를 만들지 말 것** — harness CLI가 conflicts로 감지하지만 애초에 계획 단계에서 피하는 게 안전

## 출력
1. `{BASE}03-plan/` 디렉토리에 Phase YAML 파일들을 생성
2. 전체 계획 요약을 텍스트로 반환 (Phase 수, Task 수, 핵심 흐름)
```

### Step 3 사후 처리

1. Agent의 계획 요약을 사용자에게 표시 (Phase/Task 수, 핵심 흐름).
2. 사용자가 수정 요구 시:
   - 소규모: 직접 YAML Edit.
   - 전면 재계획: 만약 Step 4가 이미 실행된 상태면 `archive-plan` 먼저, 그 다음 Plan Agent 재호출.
3. **승인 기록**:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" approve <slug> \
  --step 3 \
  --feedback "<사용자 코멘트>"
```

---

## Step 4: Generate (적응적 실행 루프)

### 4-1. 실행 루프

매 반복마다 다음 순서:

**1. 다음 실행할 task 조회**
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" next <slug>
```

**2. 반환 JSON 분기**

`task_id`가 `null`이면:
- `reason: pipeline_complete` → Step 5로 이동.
- `reason: blocked` → `blocked_tasks` 목록을 사용자에게 보여주고, 각 task의 `last_error` 확인. 사용자에게 선택지:
  - **retry**: 해당 task의 `prompt` 수정 필요하면 plan YAML 편집 후 `harness log <slug> <task_id> --status not_started`로 상태만 리셋하고 루프 재진입. `attempts`는 누적으로 유지되며, 다음 루프의 4-1.4 단계에서 `--attempt-start`가 정상적으로 +1 한다.
  - **skip**: `harness log <slug> <task_id> --status skipped`.
  - **abort**: 사용자에게 최종 상태 요약 후 파이프라인 중단.
- `reason: waiting_for_approval` 또는 `steps_incomplete` → 해당 Step으로 되돌아감 (업스트림 게이트 미통과, 비정상).

`task_id`가 있으면 3부터 진행.

**3. 병렬 그룹 구성 (선택)**

여러 독립 task를 같은 메시지에서 병렬 Agent 호출할지 판단. 조건:
- 같은 Phase 내 (현재 그룹 형성은 Claude 재량).
- 서로 간 `depends_on` 없음.
- `conflicts` 체크 통과:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" conflicts <slug> \
  --tasks 2.1,2.2,2.3
```
`safe: true`면 병렬 진행, `false`면 충돌 task들은 순차 실행.

단일 task라면 이 단계 생략.

**4. Task 실행 시작 로깅**
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" log <slug> <task_id> \
  --status running \
  --attempt-start
```

`--attempt-start`는 `attempts`를 +1, `started` 타임스탬프, `plan_checksum` 갱신, `last_error`를 null로 초기화.

**5. Agent 호출**

`next`의 반환에서 `task.prompt`를 읽는다. `{BASE}` 치환 후 다음 템플릿으로 Agent 호출:

- `subagent_type`: `general-purpose`
- `description`: `Task <task_id>: <task.name>`

```
<task.prompt — {BASE} 치환 완료>

## 추가 지시사항
- 작업 완료 후 아래 형식으로 결과를 반환하세요:
  - 변경된 파일 목록 (생성/수정/삭제 구분)
  - 핵심 변경 내용 요약
  - 계획 대비 달라진 점 (파일명/함수명/구조 변경 등)이 있으면 명시
- 오류가 발생하면 오류 내용과 시도한 해결 방법을 반환하세요.
```

**6. 결과 처리**

Agent 반환 내용을 Claude가 해석해:

a. **사람용 보고서 작성** — `{BASE}04-generate/task-<id>.md`에 Write 도구로:
```markdown
# Task <id>: <name>

## 변경 파일
- [created] src/path/to/file.ts
- [modified] src/other/file.ts

## 실행 요약
(Agent 반환 요약)

## 계획 대비 변경점
(파일명/함수명/구조 차이. 없으면 "없음")

## 오류 (실패 시)
(오류 내용 + 시도)
```

b. **기계 상태 기록** — 성공으로 보이면:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" log <slug> <task_id> \
  --status success \
  --outputs '[{"path":"src/path/to/file.ts"}]'
```

c. **산출물 검증**:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" verify <slug> <task_id>
```

반환의 `ok: false`면 실제로는 실패 — 4-2로 이동.

실패(Agent 에러 반환) 또는 verify 실패면 4-2로.

### 4-2. 실패 분류 결정트리

`classify-failure` subcommand가 아직 구현되지 않았으므로 Claude가 다음 규칙으로 분류한다.

**Class A — 자동 복구 (예산 내 재시도)**
조건 중 하나:
- `verify` 결과 `issue: "missing"` (선언된 output 파일이 없음)
- `verify` 결과 `issue: "empty"` (파일은 있으나 비어있음)
- Agent 반환문에 명확한 transient 에러 (syntax error, import 누락, 타입 오류 등)

그리고 `attempts < HARNESS_MAX_ATTEMPTS`.

**조치**:
1. `prompt` 조정이 도움이 되면 plan YAML의 해당 task `prompt`를 Edit (선택).
2. `log --status failed --last-error "<요약>"` 로 실패 기록 후,
3. 다음 루프에서 `next`가 다시 이 task를 `failed_within_budget`으로 돌려줌 → 4-1.4부터 반복 (`--attempt-start`가 attempts를 +1).

**Class B — 사용자 판단 필요**
조건 중 하나:
- Output이 존재하고 비어있지 않지만 내용이 요구사항과 명백히 다름
- Agent가 선언 외 파일을 만들었거나 엉뚱한 일을 함
- Class A로 시도했으나 `attempts >= HARNESS_MAX_ATTEMPTS`에 도달

**조치**:
1. `log --status failed --last-error "<요약>"`.
2. 사용자에게 diff/상황 요약 + 선택지 제시 (계획 수정 후 재시도 / 이 task 건너뛰기 / 중단).

**Class C — 에스컬레이션**
조건 중 하나:
- Agent가 아무 output도 반환하지 않거나 정책상 거부
- Agent 반환이 hallucination으로 보임 (declared output과 주장한 파일이 완전 불일치)
- 원인 분류 자체가 모호

**조치**:
1. `log --status blocked --last-error "<원인>"`.
2. 해당 병렬 그룹의 나머지는 유지, 이 task만 차단.
3. 사용자에게 raw 에러 + 컨텍스트 보고, 수동 개입 요청.

### 4-3. 병렬 그룹 실패 처리

병렬로 호출한 Agent 중 일부만 실패하면:
- 성공한 task들은 `log --status success` + `verify`로 개별 처리.
- 실패한 task들만 4-2 분류 적용.
- 그룹 전체를 롤백하지 않음 (성공은 성공).

---

## Step 5: Evaluate (Sub-Agent)

### 5-1. 사전 요약 생성

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" summary <slug>
```

`{BASE}04-generate/summary.md`가 생성되며, Evaluate Agent의 입력으로 사용된다.

### 5-2. Agent 호출

- `subagent_type`: `general-purpose`
- `description`: `Evaluate implementation quality`

**Agent Prompt:**
```
당신은 소프트웨어 품질 엔지니어입니다.

## 입력
아래 artifact 파일들을 읽어 전체 맥락을 파악하세요:
- {BASE}00-request.md (원래 요청)
- {BASE}01-clarify.md (요구사항)
- {BASE}04-generate/summary.md (생성 결과 리포트)
- {BASE}04-generate/task-*.md (개별 Task 실행 로그 — 필요시 참조)

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
발견된 오류는 직접 수정하세요. 단, 수정 범위가 Phase 1~4의 Task 경계를 벗어나는 큰 변경이면 **수정 대신 리포트에 기록**하고 사용자 판단을 요청하세요.

## 출력
검증 결과를 `{BASE}05-evaluate.md` 파일에 아래 형식으로 작성하세요:

```markdown
# 품질 검증 리포트

## 자동 검증 결과
| 도구 | 상태 | 비고 |
|------|------|------|
| TypeCheck | Pass / Fail / Skip | ... |
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

### 5-3. 사후 처리

1. 최종 판정을 사용자에게 표시.
2. Evaluate Agent가 수정한 파일이 있으면 그 파일들을 명시적으로 언급 (이 수정은 특정 Task 사이드카에 기록되지 않는다 — 의도적으로 Evaluate 단계의 독립 수정으로 분류).
3. 판정이 `Fail`이면 사용자에게 추가 조치 선택지 제시 (특정 Task로 되돌아가 재실행 / 새 요청으로 재시작 / 현 상태 수용).

---

## 완료 보고

`harness scan <slug>` 한 번 더 호출해 최종 상태 집계:

1. **파이프라인 요약**: 각 단계 상태, Step 4 task별 결과.
2. **Artifact 위치**: `.harness/<slug>/`의 파일 목록.
3. **다음 단계 제안**: 테스트 실행, 커밋, PR 작성, 추가 기능 등.

---

## 에러 처리 (전역 규칙)

- `harness` 호출이 exit ≠ 0이면 **사용자에게 stderr 그대로 전달** + 원인 진단 (PyYAML 누락? 사이드카 손상? 권한?). 무시하고 진행하지 않는다.
- exit 2 (PyYAML 누락): 사용자에게 `pip install pyyaml` 안내.
- exit 3 (state 오류: slug 없음, 이미 승인됨 등): 사용자에게 원인 확인 요청.
- exit 5 (schema 오류: 사이드카 손상, plan YAML 파싱 실패): 사용자에게 해당 파일 점검 요청.

## 되풀이되는 실수 방지

- **사이드카를 직접 수정하지 말 것** — 모든 task 상태 변화는 `harness log`로만.
- **`scan`/`next`의 결과를 추측하지 말 것** — 매번 호출해 최신 상태로 판단.
- **승인 없이 다음 Step으로 넘어가지 말 것** — `approve` 호출이 없으면 `scan`이 게이트에서 막는다.
- **같은 파일을 출력하는 병렬 Task를 만들지 말 것** — 만들게 되면 `conflicts`가 감지해 순차 실행해야 함.
