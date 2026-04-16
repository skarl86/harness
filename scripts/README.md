# harness CLI contract

Deterministic state-management CLI for the harness pipeline.

`SKILL.md` (Claude-facing workflow prose) orchestrates the creative phases —
Clarify, Context, Plan, Generate, Evaluate — by calling Agent sub-agents.
This CLI handles everything else: slug generation, resume detection,
output verification, conflict checking, summary reporting.

**Design rule:** the CLI and the skill have a hard boundary.
The CLI never calls an LLM. The skill never parses task sidecars by hand.

---

## Boundaries

This CLI **does**:

- Create and manipulate `.harness/{slug}/` trees
- Read plan YAML (`03-plan/phase-*.yaml`) and task state JSON sidecars
- Compute derived views (resume point, phase rollup, output conflicts)
- Verify that declared output files exist and are non-empty
- Write atomic, schema-versioned state files
- Archive plans on re-generation
- Emit machine-readable JSON on stdout, human-readable diagnostics on stderr

This CLI **does not**:

- Call LLMs, Agents, or any external API
- Prompt the user for input
- Execute project build tools, tests, or user code
- Modify files outside `.harness/{slug}/` (exception: summary files the user asked for, always under that tree)
- Interpret task prompts or make creative decisions about what to do next

---

## Requirements

- Python 3.9+
- [PyYAML](https://pypi.org/project/PyYAML/) for plan file parsing
  - Install: `pip install pyyaml` (or `pipx install pyyaml` / `uv pip install pyyaml`)
  - On import failure, every subcommand exits with code 2 and a stderr install hint

---

## Invocation

From `SKILL.md`, always invoke via Bash with the plugin root:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" <subcommand> [args...]
```

`CLAUDE_PLUGIN_ROOT` is substituted by Claude Code at runtime when the plugin
is installed. The CLI itself never needs to know where it lives.

---

## Conventions

### stdout

On exit code `0`, stdout contains **exactly one** UTF-8 JSON value
(object or array), pretty-printed with 2-space indent, trailing newline.
No log lines, no banners.

Parse with `jq` or `json.loads` without preprocessing.

### stderr

Human-readable text. Used for progress hints, warnings, and error
messages. Never machine-parsed. Emojis allowed in emphasis only.

### Exit codes

| Code | Meaning |
|------|---------|
| 0    | Success. stdout is valid JSON. |
| 1    | Usage error (bad arguments, unknown subcommand). |
| 2    | Missing runtime dependency (PyYAML absent). |
| 3    | State error (slug not found, task id absent from plan, plan missing, approval already exists, etc.). |
| 4    | I/O error (permission denied, disk full, path outside project). |
| 5    | Schema validation error (corrupted sidecar, plan doesn't conform). |

On any non-zero exit, stdout SHOULD be empty; all detail goes to stderr.

### Atomic writes

Every file write uses `tmpfile + os.replace()` (POSIX atomic). A crash
mid-write leaves either the old file or no file, never a partial one.

### Schema versioning

Every persisted JSON carries `schema_version`. The CLI rejects unknown
versions with exit `5`. Schema bumps are never silent.

### Time

All timestamps are ISO-8601 UTC with `Z` suffix (`2026-04-17T10:12:03Z`).
The CLI reads and writes timestamps only in this form.

### Paths

All paths the CLI emits are POSIX-style, relative to the project root
(the directory that contains `.harness/`).

---

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `HARNESS_MAX_ATTEMPTS` | `1` | Retry budget per task before `status=blocked`. Integer >= 0. |
| `HARNESS_BASE_DIR` | `.harness` | Root directory for artifact trees (relative to project root). |
| `CLAUDE_PLUGIN_ROOT` | (set by Claude Code) | Used only for invocation path; CLI does not read it. |

Unrecognized `HARNESS_*` variables are ignored silently.

### Resolution priority (max_attempts)

`HARNESS_MAX_ATTEMPTS` env var  >  `.harness/{slug}/config.json` max_attempts  >  built-in default (1)

Use `harness config <slug> --max-attempts N` to persist a non-default budget per slug without needing to export the env var on every Bash call.

---

## Data model

| File | Schema | Purpose |
|------|--------|---------|
| `.harness/{slug}/04-generate/task-{id}.json` | [task-state](./schemas/task-state.schema.json) | Per-task machine state |
| `.harness/{slug}/03-plan/phase-{N}-*.yaml`   | [plan](./schemas/plan.schema.json) | Phase+tasks definition |
| `.harness/{slug}/.approvals/step-{N}.json`   | [approval](./schemas/approval.schema.json) | User gate approvals |
| `.harness/{slug}/config.json`                | [config](./schemas/config.schema.json) | Per-slug overrides (currently `max_attempts`) |

Other files (`00-request.md`, `01-clarify.md`, `02-context.md`,
`04-generate/task-*.md`, `04-generate/summary.md`, `05-evaluate.md`)
are human-readable prose. The CLI touches them only when explicitly
requested (e.g., `harness slug` writes `00-request.md`,
`harness summary` writes `04-generate/summary.md`).

---

## Directory layout

```
.harness/{slug}/
├── 00-request.md              # user's raw request (written by `slug`)
├── 01-clarify.md              # Clarify Agent output + user feedback
├── 02-context.md              # Context Agent output
├── 03-plan/                   # current (latest) plan
│   ├── phase-1-setup.yaml
│   └── phase-2-api.yaml
├── 03-plan.v1/                # archived prior plans (by `archive-plan`)
├── 04-generate/
│   ├── task-1.1.md            # human report (written by skill/Claude)
│   ├── task-1.1.json          # machine state sidecar (written by CLI)
│   ├── task-1.2.md
│   ├── task-1.2.json
│   └── summary.md             # written by `summary`
├── 05-evaluate.md
└── .approvals/
    ├── step-1.json
    └── step-3.json
```

---

## Subcommands

Each subcommand below lists its synopsis, stdout shape, exit codes it may
produce beyond `0`, and a short example.

### `slug`

Compute a kebab-case slug from a request string, create
`.harness/{slug}/`, and write `00-request.md`.

**Synopsis**

```
harness.py slug --request <text> [--suggested <slug>]
```

**Arguments**

- `--request <text>` (required): raw request string.
- `--suggested <slug>` (optional): candidate slug to try first. If absent,
  CLI derives one from the request. The Agent or Claude typically supplies
  the suggestion since slug-from-request is a creative task.

**Behavior**

- If the target directory does not exist, creates it and writes `00-request.md`.
- If it exists **and the request text matches** (checksum equal), returns
  `status: "exists"` and does nothing else.
- If it exists **and the request text differs**, returns
  `status: "collision"` with an unused `-vN` suggestion. Caller decides.

**stdout**

```json
{
  "slug": "add-login-feature",
  "path": ".harness/add-login-feature/",
  "status": "created",
  "request_checksum": "sha256:..."
}
```

`status` is one of `created`, `exists`, `collision`. On `collision`, the
object also carries `suggested_slug: "add-login-feature-v2"`.

**Exit codes:** `0`, `1`, `4`.

---

### `scan`

Compute the full resume state for a slug by reading the plan and all task
sidecars. Does not modify any file.

**Synopsis**

```
harness.py scan <slug>
```

**stdout**

```json
{
  "slug": "add-login-feature",
  "base_path": ".harness/add-login-feature/",
  "pipeline_status": "in_progress",
  "current_step": 4,
  "steps": {
    "1_clarify":  {"status": "approved",    "artifact": "01-clarify.md", "approved_at": "2026-04-17T10:05:00Z"},
    "2_context":  {"status": "completed",   "artifact": "02-context.md"},
    "3_plan":     {"status": "approved",    "plan_version": 2, "archived": ["03-plan.v1"]},
    "4_generate": {"status": "in_progress"},
    "5_evaluate": {"status": "not_started"}
  },
  "phases": [
    {
      "phase": 1,
      "name": "Setup",
      "status": "completed",
      "tasks": [
        {"id": "1.1", "status": "success", "attempts": 1},
        {"id": "1.2", "status": "success", "attempts": 1}
      ]
    },
    {
      "phase": 2,
      "name": "API",
      "status": "blocked",
      "tasks": [
        {"id": "2.1", "status": "success", "attempts": 1},
        {"id": "2.2", "status": "failed",  "attempts": 1, "last_error": "TypeError in login.ts:42"},
        {"id": "2.3", "status": "not_started"}
      ]
    }
  ],
  "resume_point": {
    "phase": 2,
    "task_id": "2.2",
    "reason": "failed_within_budget"
  },
  "orphans": [],
  "stale": []
}
```

**Field definitions**

- `pipeline_status`: `not_started | in_progress | blocked | completed`.
- `steps.{N}.status`: `not_started | completed | approved | in_progress | blocked`.
  (`approved` implies `completed` + user gate passed.)
- `phases[].status`: `not_started | in_progress | completed | blocked`.
  - `blocked` means at least one task is `failed` with `attempts >= HARNESS_MAX_ATTEMPTS`.
- `resume_point.reason`: one of
  - `not_started` — runnable task that has never been attempted (carries `task_id`, `phase`)
  - `in_progress` — task whose last recorded status is `running` (carries `task_id`, `phase`)
  - `failed_within_budget` — task is `failed` and `attempts < HARNESS_MAX_ATTEMPTS` (carries `task_id`, `phase`)
  - `waiting_for_approval` — Step 1 or Step 3 artifact exists but no approval recorded (carries `step: 1 | 3`)
  - `steps_incomplete` — an earlier step's artifact is missing (carries `step: N`)
  - `blocked` — every remaining candidate task either exceeded its retry budget or depends on a blocked predecessor (carries `blocked_tasks`)
  - `pipeline_complete` — Step 5 artifact exists and all prior steps are done
- `orphans`: task ids that have sidecars but no matching entry in current plan.
- `stale`: task ids whose `plan_checksum` disagrees with the current plan's
  canonicalized hash for that task.

**Exit codes:** `0`, `3` (slug not found), `5` (corrupted sidecar or plan).

---

### `next`

Thin wrapper over `scan` returning only the next runnable task plus its
full plan definition. Callers use this to avoid re-deriving the resume
point themselves.

**Synopsis**

```
harness.py next <slug>
```

**stdout (runnable)**

```json
{
  "task_id": "2.2",
  "phase": 2,
  "reason": "failed_within_budget",
  "task": {
    "id": "2.2",
    "name": "Implement login endpoint",
    "description": "...",
    "prompt": "...",
    "artifacts": {
      "inputs": ["src/auth/types.ts"],
      "outputs": ["src/auth/login.ts"]
    },
    "depends_on": ["1.2", "2.1"]
  },
  "previous_attempts": 1
}
```

**stdout (no runnable task)**

```json
{
  "task_id": null,
  "reason": "pipeline_complete"
}
```

`reason` in the no-task case is one of: `pipeline_complete`,
`waiting_for_approval` (carries `step: N`), `steps_incomplete`
(carries `step: N`), or `blocked` (carries `blocked_tasks: [...]`).
Same vocabulary as `scan`'s `resume_point.reason`.

**Exit codes:** `0`, `3`.

---

### `log`

Create or update a task sidecar. The only way the CLI writes task state.
Multiple invocations are idempotent; last write wins.

**Synopsis**

```
harness.py log <slug> <task_id>
  --status <state>            [required]
  [--attempt-start]           # increments attempts, sets started=now, clears last_error
  [--outputs <json-array>]    # JSON array of {path} objects, replaces existing
  [--last-error <text>]       # stored verbatim; null out with empty string
```

**Behavior**

- If the sidecar doesn't exist, creates it populated from the plan
  (phase, depends_on, plan_checksum).
- If it exists, merges the requested changes.
- On `--attempt-start`, also bumps `attempts` by 1, stamps `started`, clears
  both `last_error` and `completed`, and refreshes `plan_checksum` +
  `depends_on` from the current plan.
- `completed` is auto-stamped when status transitions to a terminal state
  (`success`, `failed`, `blocked`, `skipped`).
- `last_updated` is always stamped to now.

**stdout**

The written sidecar content (see task-state schema).

**Exit codes:** `0`, `1` (bad status value), `3` (slug or task not found), `5` (plan corrupted).

---

### `verify`

Check that a task's declared outputs exist and are non-empty. Updates
the sidecar's `outputs` field with observed sizes. Optionally runs a
language-based syntax check with `--syntax`.

**Synopsis**

```
harness.py verify <slug> <task_id> [--syntax]
```

**Flags**

- `--syntax`: for each existing non-empty output, parse it based on file
  extension. `.py` via `py_compile`, `.json` via `json.load`, `.yaml`/`.yml`
  via `yaml.safe_load`. Unknown extensions keep the structural-only result.
  On syntax failure, `issue` becomes `"syntax_error: ..."` and `ok` becomes
  `false`. External toolchains (tsc, gofmt, etc.) are deliberately out of
  scope — run them from the skill or in Step 5 Evaluate.

**stdout**

```json
{
  "task_id": "2.2",
  "ok": false,
  "outputs": [
    {"path": "src/auth/login.ts", "exists": true,  "size": 0,    "issue": "empty"},
    {"path": "src/auth/types.ts", "exists": false, "size": null, "issue": "missing"}
  ],
  "issues_count": 2
}
```

`ok` is `true` iff every declared output exists and has `size > 0`.

**Note:** `verify` does not parse content or run syntax checks — file
validity beyond "exists and non-empty" is the skill's concern. This keeps
the CLI independent of project language.

**Exit codes:** `0` (regardless of `ok` value), `3`.

---

### `conflicts`

Given a set of task ids intended for parallel execution, check whether
their declared `artifacts.outputs` overlap.

**Synopsis**

```
harness.py conflicts <slug> --tasks <id1,id2,id3>
```

**stdout**

```json
{
  "safe": false,
  "conflicts": [
    {
      "path": "src/routes/index.ts",
      "task_ids": ["2.1", "2.3"]
    }
  ]
}
```

If `safe: true`, `conflicts` is an empty array.

**Decision rule:** declaration-based only. The CLI does not inspect
actual file writes; it compares declared outputs verbatim after resolving
placeholders supplied by the caller (none, at this phase — placeholders
are resolved by the orchestrator before invoking tasks).

**Exit codes:** `0`, `1` (unknown task id in list), `3`.

---

### `archive-plan`

Archive the current `03-plan/` directory to `03-plan.v{N}/`, where `N`
is one above the highest existing archive. Required before the Plan Agent
regenerates a plan when any task has been executed on the current version.

**Synopsis**

```
harness.py archive-plan <slug>
```

**Behavior**

- Finds the highest existing `03-plan.v{N}/`.
- Moves current `03-plan/` to `03-plan.v{N+1}/`.
- Creates an empty `03-plan/`.
- Does NOT touch `04-generate/` — task sidecars remain, and their
  `plan_checksum` fields will drive `stale` detection after the new plan lands.

**stdout**

```json
{
  "archived_to": "03-plan.v1/",
  "new_version": 2
}
```

If no prior archives exist and current `03-plan/` is empty, exits with `3`
(nothing to archive).

**Exit codes:** `0`, `3`, `4`.

---

### `classify-failure`

Suggest a failure class for a task currently in `status=failed` by
pattern-matching the last error, output-verification result, and any
drift between declared outputs and actual files.

**Synopsis**

```
harness.py classify-failure <slug> <task_id>
```

**Classes**

- `A` — Auto-recoverable: missing import, syntax error in generated file,
  output file path drift (agent wrote to neighbor path).
- `B` — Needs user judgment: output content semantically wrong but
  structurally valid; agent claimed unrelated files.
- `C` — Escalate: no outputs produced, agent returned apparent hallucination,
  pattern unrecognized.

**stdout**

```json
{
  "task_id": "2.2",
  "suggested_class": "A",
  "confidence": "high",
  "reasons": [
    "declared output src/auth/login.ts exists but is empty",
    "sibling file src/auth/login.tsx found; likely extension mismatch"
  ]
}
```

`confidence` is `high | medium | low`. The skill makes the final call;
this is a heuristic.

**Exit codes:** `0`, `3`.

---

### `approve`

Record user approval of a gated step (Clarify=1, Plan=3). Writes
`.approvals/step-{N}.json`.

**Synopsis**

```
harness.py approve <slug> --step <N> [--feedback <text>]
```

**Behavior**

- Fails with exit `3` if approval file already exists (re-approval requires
  explicit deletion or `--force`).
- Stamps `approved_at` and current artifact checksum for later stale detection.

**stdout**

The written approval (see approval schema).

**Exit codes:** `0`, `1` (invalid step), `3` (already approved), `4`.

---

### `stale`

Detect drift:

- Task sidecars whose `plan_checksum` does not match the current plan's hash.
- Step approvals whose `artifact_checksum` does not match the current artifact.

**Synopsis**

```
harness.py stale <slug>
```

**stdout**

```json
{
  "stale_tasks": [
    {"task_id": "1.2", "recorded": "sha256:...", "current": "sha256:..."}
  ],
  "stale_approvals": [
    {"step": 1, "recorded": "sha256:...", "current": "sha256:..."}
  ]
}
```

**Exit codes:** `0`, `3`, `5`.

---

### `summary`

Write `04-generate/summary.md` by aggregating all task sidecars in the
current plan version. Human-readable report.

**Synopsis**

```
harness.py summary <slug>
```

**stdout**

```json
{
  "summary_path": ".harness/add-login-feature/04-generate/summary.md",
  "totals": {"phases": 2, "tasks": 5, "success": 4, "failed": 1, "skipped": 0}
}
```

**Exit codes:** `0`, `3`, `4`.

---

### `cleanup`

Remove a slug's artifact tree. Always backs up by default.

**Synopsis**

```
harness.py cleanup <slug> [--purge]
```

**Behavior**

- Default: rename `.harness/{slug}/` to `.harness/{slug}.backup-{ts}/`.
- `--purge`: delete the tree recursively. No prompt from the CLI;
  the skill is responsible for confirming with the user.

**stdout**

```json
{
  "slug": "add-login-feature",
  "action": "backed_up",
  "backup_path": ".harness/add-login-feature.backup-2026-04-17T10-30-00Z/"
}
```

On `--purge`, `action` is `"purged"` and `backup_path` is `null`.

**Exit codes:** `0`, `3`, `4`.

---

### `config`

View or update per-slug `config.json`. Without setter flags, prints the
current contents (or just `{"schema_version": 1}` if the file does not
exist yet). With setter flags, updates and writes atomically.

**Synopsis**

```
harness.py config <slug> [--max-attempts N]
```

**stdout**

The effective config after any update:

```json
{
  "schema_version": 1,
  "max_attempts": 3
}
```

**Exit codes:** `0`, `1` (invalid value, e.g., negative `--max-attempts`), `3`, `5`.

---

### `list`

Enumerate all slugs under `.harness/`.

**Synopsis**

```
harness.py list
```

**stdout**

```json
{
  "slugs": [
    {
      "slug": "add-login-feature",
      "path": ".harness/add-login-feature/",
      "pipeline_status": "in_progress",
      "created_at": "2026-04-17T10:00:00Z"
    }
  ]
}
```

**Exit codes:** `0`, `4`.

---

## Not-in-CLI (by design)

The following are intentionally the skill's responsibility, not the CLI's:

- Deciding **when** to run which subcommand (that's workflow logic in `SKILL.md`).
- Prompting the user for feedback or approval (the skill collects, then calls `approve`).
- Running project tools (typecheck, lint, tests) — these belong in the Evaluate Agent.
- Generating slugs semantically from natural language (the skill proposes via `--suggested`, CLI only canonicalizes).
- Interpreting task prompts or diagnosing novel failures (those stay with Claude).

---

## Testing

Unit tests live under `scripts/tests/` with synthetic `.harness/` fixtures
in `scripts/tests/fixtures/`. Each fixture is a full directory tree plus
an `expected/` sibling containing the expected stdout JSON for each subcommand.

Run (once implementation lands):

```
python3 -m unittest discover scripts/tests
```
