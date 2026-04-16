# Dogfood run 2 — search-and-list on non-empty `notes.py`

**Date**: 2026-04-17
**Harness version**: main @ Phase 5 merge (config.json + verify --syntax available)
**Seed**: existing `notes.py` (23 LOC, 1 subcommand `add`) + `test_notes.py` (2 tests)
**Request**: "Add `search` and `list` subcommands to notes.py. search takes a query and prints matching lines (optional --regex). list prints all notes with line numbers."
**Outcome**: Pipeline completed. 4/4 tasks success. 7 tests passing (2 pre-existing + 5 new, zero regressions).

## What this run stress-tested

Unlike run 1 (fresh project, simulated failure), run 2 intentionally exercised features that run 1 either skipped or awkwardly worked around:

| Feature | Run 1 | Run 2 |
|---|---|---|
| `harness config --max-attempts` | unavailable (pre-Phase 5) | used before execution; **no HARNESS_MAX_ATTEMPTS env var needed for the entire run** |
| `harness verify --syntax` | unavailable; manual `py_compile` subprocess calls | used after every task; caught `verify`-passing files without Claude writing separate checks |
| `harness conflicts` | not triggered (every task wrote a unique file) | actively used — tasks 1.1 and 1.2 both target `notes.py`; correctly returned `safe: false` |
| Non-empty codebase context | empty | seed files + existing conventions; Context Agent had real material to report |
| Regression of existing tests | N/A | ran `python3 -m unittest test_notes` after every task touching `notes.py`; zero regressions |

## Pipeline timeline

| Moment | notable |
|---|---|
| `slug --request ...` | created |
| `config --max-attempts 2` | budget persisted; no env var used from here on |
| 01-clarify.md + approve --step 1 | standard |
| 02-context.md | 기존 코드 컨벤션 추출 (snake_case, `with open(... encoding="utf-8")` 일관 등) |
| plan YAMLs + approve --step 3 | 4 tasks across 2 phases |
| **conflicts check** 1.1 + 1.2 | `safe: false` — 둘 다 notes.py 수정 |
| task 1.1 (search_notes helper) | success, verify --syntax pass, regression tests pass |
| task 1.2 (list_notes helper) | success, verify --syntax pass, regression tests pass |
| task 2.1 (CLI wiring) | success, CLI smoke pass |
| task 2.2 (tests) | success, 7 tests pass |
| summary + 05-evaluate.md | pipeline_complete |

## Frictions observed

### F5 (minor): regression test invocation is skill-level, not CLI-level

After every task that modifies an existing file, Claude must run the project's test suite via Bash (`python3 -m unittest test_notes`). There is no `harness test` wrapper. This is correct by design — test frameworks vary wildly (pytest vs unittest vs jest vs cargo test), and embedding them in the CLI would violate the stdlib-only stance. But SKILL.md Step 4-1.6 doesn't explicitly tell Claude to run regression tests after editing existing files; it currently implies this only at Step 5 Evaluate.

**Impact**: Minor. An Agent breaking existing tests might not surface until Evaluate, costing tokens. In this run I ran regressions manually after each task touching `notes.py` and caught no issues, but only because I was being careful.

**Mitigation options**:
1. **Prose fix**: SKILL.md Step 4-1.6 gets a (e) subsection: "If the task modifies an existing source file, run the project's test command after `verify --syntax` passes. If regressions appear, treat as Class B (user judgment) — don't auto-retry since tests may need updating alongside code."
2. **CLI fix** (out of scope): shell-command passthrough subcommand — rejected, violates stdlib-only stance.

**Applied in this PR**: option 1 (SKILL.md Step 4-1.6 addition).

### F6 (cosmetic): `conflicts` behavior when tasks modify the same file

The conflicts check correctly surfaced that tasks 1.1 and 1.2 both target `notes.py`. Claude serialized them. But the plan's intent was "these are independent helper functions" — the fact that they share a file is incidental (both are editing the same source file to append new code). A more advanced conflict check could distinguish "both append to different locations" from "both rewrite the same function", but that requires parsing AST. The current declaration-based check is appropriately conservative.

**Impact**: Parallel speedup not realized for helpers that happen to share a file. Acceptable trade-off.

**Not applied**: out of scope; would require AST-level analysis.

## Positives confirmed

- `config.json` completely replaced the env-var dance from run 1. Not a single `HARNESS_MAX_ATTEMPTS=...` inline in this run.
- `verify --syntax` caught nothing (because the Agent-simulated code was clean), but exercising it at every task reassured us structurally — and it would have caught a SyntaxError immediately without separate subprocess.
- Context Agent successfully extracted existing conventions from `notes.py` (snake_case, `with open(... encoding="utf-8")`, Path usage, docstring style) and the Plan Agent honored them.
- Regression path: no existing test broke. The seed's 2 tests plus 5 new tests all passed.
- Conflicts check: worked exactly as documented.
- `archive-plan` not needed (clean run, no replan).

## Coverage note

Across runs 1 and 2, 11 of 13 CLI subcommands have been exercised in real scenarios:

| Subcommand | Run 1 | Run 2 |
|---|---|---|
| slug | ✓ | ✓ |
| scan | ✓ | ✓ |
| next | ✓ | ✓ |
| log | ✓ | ✓ |
| verify | ✓ | ✓ (with --syntax) |
| conflicts | ✓ (returned safe) | ✓ (returned unsafe) |
| classify-failure | ✓ | — |
| approve | ✓ | ✓ |
| summary | ✓ | ✓ |
| config | — | ✓ |
| archive-plan | — (only manual smoke) | — |
| stale | — (only embedded in scan) | — |
| cleanup | — (only unit tests) | — |
| list | — (only unit tests) | — |

`archive-plan`, `stale`, `cleanup`, `list` lack integration-level evidence. Acceptable — they are auxiliary ops; their unit tests cover behavior. A larger run with replan + multi-slug + backup would exercise them together.

## Patches applied in this PR

SKILL.md Step 4-1.6 gains a new (e) subsection on regression-test invocation for tasks that edit existing files. One-paragraph prose addition; no code change.

## Follow-ups (unchanged)

- **P7**: AST-aware conflicts (distinguish same-file-different-functions from same-file-same-function). Non-trivial; may never be worth it.
- **P8**: dogfood on a multi-language project or one with a failing Agent-hallucination mode.
