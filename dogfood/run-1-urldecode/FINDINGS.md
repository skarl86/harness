# Dogfood run 1 — url-decode-cli

**Date**: 2026-04-17
**Harness version**: main @ Phase 3 merge (4 PRs deep; 13/13 CLI subcommands shipped)
**Request**: "Create urldecode.py — a Python CLI that reads URL-encoded strings from stdin, prints decoded strings line by line. Flag --json makes each line a {input, decoded} object."
**Outcome**: Pipeline completed. 4/4 tasks success, 1 simulated failure with successful retry, 5 unit tests passing.

## What got built

- `urldecode.py` (702 bytes) — single-file CLI, stdlib only
- `test_urldecode.py` (1.3 KB) — unittest suite, 5 tests covering `decode_line` + both output modes + blank-line skipping

Full artifact tree under `.harness/url-decode-cli/`:

```
00-request.md        (138 B)   user request verbatim
01-clarify.md        (1.6 KB)  requirements + user feedback section
02-context.md        (555 B)   empty-codebase context summary
03-plan/
  phase-1-implementation.yaml  3 tasks (scaffold → decoder → --json mode)
  phase-2-tests.yaml           1 task (unittest suite)
04-generate/
  task-1.1.json .. task-2.1.json  machine state (sidecars)
  summary.md                   aggregated report
05-evaluate.md       (680 B)   quality report, Pass verdict
.approvals/
  step-1.json  step-3.json     gate approvals with artifact_checksum
```

## Pipeline timeline

Every state transition was observed via `harness scan`:

| Moment | scan.pipeline_status | scan.resume_point.reason |
|---|---|---|
| After `slug --request ...` | `not_started` | `steps_incomplete` step=1 |
| After writing `01-clarify.md` | `not_started` | `waiting_for_approval` step=1 |
| After `approve --step 1` | `not_started` | `steps_incomplete` step=2 |
| After writing `02-context.md` | `not_started` | `steps_incomplete` step=3 |
| After writing `03-plan/*.yaml` | `not_started` | `waiting_for_approval` step=3 |
| After `approve --step 3` | `not_started` | `not_started` task=1.1 |
| After task 1.1 success | `in_progress` | `not_started` task=1.2 |
| After task 1.2 failed (simulated SyntaxError) | `in_progress` | `failed_within_budget` task=1.2 |
| After 1.2 retry success | `in_progress` | `not_started` task=1.3 |
| After all 4 tasks success | `in_progress` | `steps_incomplete` step=5 |
| After writing `05-evaluate.md` | `completed` | `pipeline_complete` |

Not a single misfire on state transitions. The resume semantics lock in cleanly.

## Frictions observed

### F1 — env var persistence across Bash tool calls (medium)

Claude Code's Bash tool spawns a fresh shell per call. `export HARNESS_MAX_ATTEMPTS=2` in one call does not persist to the next. In this run, my first `classify-failure` invocation forgot to re-export and the CLI saw budget=1 (default), which triggered an immediate A→B escalation even though I intended a higher budget.

**Evidence**:
```
# First classify-failure, no HARNESS_MAX_ATTEMPTS exported in the same shell:
"suggested_class": "B",
"confidence": "high",
"reasons": [
  "outputs present but transient error: SyntaxError: ...",
  "attempts (1) >= HARNESS_MAX_ATTEMPTS (1); escalating A -> B"
]
```

**Impact**: A plausible retry scenario was suppressed. In a real run, Claude would have escalated to the user unnecessarily.

**Mitigation options**:
1. **Prose fix** (low effort): SKILL.md's 호출 관례 section should explicitly instruct Claude to pass `HARNESS_MAX_ATTEMPTS` inline on every invocation if a non-default budget is in effect.
2. **CLI fix** (medium effort): read a `.harness/{slug}/config.json` (e.g., `{"max_attempts": 2}`) as a fallback before the env var. Config sits with the artifact tree; env becomes optional.
3. **Combo**: both — make config the recommended path, env as override.

**Applied in this PR**: option 1 (SKILL.md note). Option 2 is a P5 CLI enhancement.

### F2 — `verify` is structural only (low, but easy to forget)

`harness verify` checks that declared outputs exist and are non-empty. It does NOT run syntax checks, tests, or semantic validation. In this run, the simulated SyntaxError in `urldecode.py` was not caught by `verify` — I (Claude) had to separately call `python3 -c "import py_compile; py_compile.compile(...)"` to detect it.

**Impact**: A task could appear "verify ok" but contain a syntax error. Without Claude's independent sanity check, the pipeline would carry on and the failure would surface only at downstream task or Evaluate time, costing more tokens.

**Mitigation**: SKILL.md's Step 4-1.6 (사후 처리) should explicitly instruct Claude to run a project-appropriate sanity check (py_compile for .py, tsc --noEmit for .ts, etc.) after `log --status success` but before treating the task as done. This is already implicit in Step 5 Evaluate, but surfacing it per-task catches errors earlier.

**Applied in this PR**: SKILL.md Step 4-1.6 updated.

### F3 — manual output list construction (low)

`harness log --outputs` takes a JSON array. Claude must parse the Agent's free-form reply (or its own work summary) and construct this array. This is inherently non-deterministic — a misparse or forgotten file would silently omit outputs.

**Evidence**: In every task, I wrote `--outputs '["urldecode.py"]'` by hand. For tasks that create multiple files with glob-like patterns, this would be more error-prone.

**Mitigation**: Leaving this to Claude is correct (Agent reply parsing is non-deterministic), but SKILL.md could recommend cross-checking against `task_def.artifacts.outputs` (i.e., the planned outputs) — if Claude's parsed list differs from the plan, flag it.

**Not applied**: minor, and already partly covered by `verify` catching missing files.

### F4 — `log --status not_started` for user-approved retry (cosmetic)

The Phase 2 SKILL.md prose for class-B retry path says "`harness log <slug> <task_id> --status not_started`". In this run, it worked correctly — status went back to not_started, attempts stayed at 1, and the next loop iteration picked it up and bumped attempts to 2 normally. Just documenting that the flow is verified.

## Positives

- All 13 subcommands invoked at least once without error.
- Plan checksum mechanism prevented any stale-detection false positives (no plan edits mid-run).
- `next` returned the correct task at every step, respecting `depends_on` (Task 1.2 was held until 1.1 succeeded; 2.1 waited for 1.3).
- `summary`'s `totals` matched reality exactly after completion.
- Atomic sidecar writes — no partial/corrupt state even though I mutated files rapidly between calls.
- Gate enforcement: every step 1/3 attempt to skip approval was correctly blocked by `scan`'s `waiting_for_approval`.

## Patches applied in this PR

1. **SKILL.md CLI 호출 관례** — explicit note that `HARNESS_*` env vars must be passed inline on every Bash call if non-default budget is in effect.
2. **SKILL.md Step 4-1.6** — explicit note that `verify` is structural; Claude should run a language-appropriate sanity check (py_compile / tsc --noEmit / etc.) per task if the project has the relevant tool.

Both are prose additions; no schema or CLI changes.

## Follow-ups (out of scope)

- **P5**: `.harness/{slug}/config.json` support (F1 option 2) — CLI reads local config as budget fallback.
- **P5**: Optional `verify --check syntax` flag that runs a language-specific syntax check based on file extension.
- **P6**: Larger dogfood run with an existing non-empty codebase, multi-language project, or more realistic failure modes (e.g., Agent hallucinating a nonexistent API).
