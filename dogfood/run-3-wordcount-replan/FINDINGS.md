# Dogfood run 3 — word-counter with mid-pipeline re-plan

**Date**: 2026-04-17
**Harness version**: main @ Phase 7 merge (README + all prior phases)
**Scenario**: Empty project. Initial plan (text output only) → execute task 1.1 → user requests JSON mode → **archive-plan** → write v2 plan (JSON support added, task 1.1 redefined + new task 1.2 + updated 2.1) → **stale detection fires on task 1.1** → re-run 1.1 → proceed → `pipeline_complete`.
**Outcome**: Pipeline completed. 3/3 tasks success under v2 plan. 5 unit tests passing (Counter helper + both output modes).

## What this run stress-tested

First run to exercise **`archive-plan`** and **`stale`** at the integration level. Previous dogfoods gave these unit-test coverage only; run 3 shows the full replan loop working end-to-end.

| Feature | Observed |
|---|---|
| `harness archive-plan` | Moved `03-plan/` to `03-plan.v1/`, created fresh empty `03-plan/` |
| `scan.stale[]` | Correctly flagged task 1.1 whose recorded `plan_checksum` (v1's canonical hash) no longer matched the current v2 hash |
| `scan.stale[]` clears | After re-running 1.1 under v2, next `scan` returned empty `stale[]` — fresh sidecar carries v2 checksum |
| `harness list` | Demoed at completion; returned 1 slug with `pipeline_status: completed` |

## Pipeline timeline

```
slug word-counter                          pipeline=not_started, resume=steps_incomplete step=1
config --max-attempts 2
...standard steps 1-3 for plan v1 (3 tasks)...
approve --step 3                           resume → 1.1 not_started
log 1.1 running+success + verify --syntax  resume → 2.1 not_started (phase 2)

=== MID-PIPELINE PIVOT ===

archive-plan                               03-plan/ → 03-plan.v1/, new_version=2
(write updated 03-plan/phase-*.yaml)       v2 adds --json mode, redefines 1.1 prompt
approve --step 3 --force --feedback ...    first --force use in a dogfood
scan                                       stale=[{task_id: "1.1", recorded: ..., current: ...}]
                                           resume → 1.2 not_started
                                           (1.1 status=success survives, but Claude should act on stale)

log 1.1 not_started                        user-approved rerun
log 1.1 running+success+verify --syntax    fresh sidecar, v2 plan_checksum
scan                                       stale=[] — cleared

log 1.2 running+success+verify --syntax    new task, JSON mode
log 2.1 running+success+verify --syntax    tests pass (5 tests)
summary                                    totals.success=3
(write 05-evaluate.md)
scan                                       pipeline_complete
list                                       [{slug: word-counter, status: completed}]
```

## Frictions observed

### F7 (medium, patched): re-approving step 3 after archive-plan requires `--force`

After `archive-plan`, the existing `.approvals/step-3.json` from plan v1 was still present. `harness approve <slug> --step 3 --feedback "..."` without `--force` failed with exit 3 ("already approved"). This makes sense semantically — re-approval is a user-intent signal that shouldn't be silent — but SKILL.md Step 3 re-plan guidance didn't mention it.

**Evidence**: Without `--force`, approve emits:
```
step 3 already approved at .../step-3.json; pass --force to overwrite
```

**Impact**: Claude following SKILL.md without this knowledge would get a confusing exit 3 on what should be a normal replan flow.

**Fix**: SKILL.md Step 3 "재계획 판정" section now explicitly calls out that after `archive-plan`, the step-3 approval from the previous plan invalidates and needs `approve --step 3 --force` with the new feedback text.

### F8 (cosmetic, not patched): stale tasks don't block the resume point

`scan` found task 1.1 stale but still returned `resume_point: {task_id: "1.2", reason: "not_started"}`. This is correct — stale is informational — but a naive skill could ignore the `stale[]` field and jump to 1.2, skipping the staleness check.

**Mitigation**: SKILL.md already tells Claude to inspect `stale[]` at Step 3 replan time and Step 4 loop entry. Behavior is correct; no code change needed. Flagged for awareness.

## Positives confirmed

- **archive-plan preserved sidecars correctly.** After archive, `04-generate/task-1.1.json` still existed with its v1 `plan_checksum`. No data loss.
- **Stale detection used canonical JSON sorting.** Prompt change ("add json import") produced a different SHA-256 as expected; unrelated reordering of keys would not.
- **Resume clarity.** After re-running 1.1, scan's next resume point shifted cleanly from 1.2 (in v2's phase 1) to 2.1 (phase 2) as each task completed.
- **`list` output** makes multi-slug session management feasible; reports `created_at` from the 00-request.md mtime.

## Coverage across three runs

12 of 13 CLI subcommands now have integration-level evidence. Only `cleanup` remains unit-tested-only:

| | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| slug | ✓ | ✓ | ✓ |
| scan | ✓ | ✓ | ✓ |
| next | ✓ | ✓ | ✓ |
| log | ✓ | ✓ | ✓ |
| verify (+syntax) | ✓ | ✓ (with syntax) | ✓ (with syntax) |
| conflicts | ✓ (safe) | ✓ (unsafe) | — |
| summary | ✓ | ✓ | ✓ |
| approve | ✓ | ✓ | ✓ (incl. `--force`) |
| classify-failure | ✓ | — | — |
| config | — | ✓ | ✓ |
| **archive-plan** | — | — | ✓ |
| **stale** | — | — | ✓ |
| **list** | — | — | ✓ |
| cleanup | — | — | — |

## Patches applied in this PR

- SKILL.md Step 3 재계획 섹션: `archive-plan` 이후 `approve --step 3 --force` 필요함을 명시.

## Follow-ups (unchanged)

- **P7**: AST-aware conflicts (likely rejected)
- **P9**: dedicated dogfood for `cleanup` (and optionally multi-slug setup via sequential `slug` + `cleanup` between)
- **P10**: Agent-hallucination dogfood (Agent returns success but produces wrong outputs structurally)
