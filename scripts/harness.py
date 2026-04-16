#!/usr/bin/env python3
"""harness CLI - deterministic state for the harness pipeline.

Contract lives in scripts/README.md. Never calls LLMs; never prompts the user.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_BASE = ".harness"
DEFAULT_MAX_ATTEMPTS = 1

EXIT_SUCCESS = 0
EXIT_USAGE = 1
EXIT_MISSING_DEP = 2
EXIT_STATE = 3
EXIT_IO = 4
EXIT_SCHEMA = 5

VALID_STATUSES = ("not_started", "running", "success", "failed", "blocked", "skipped")
TERMINAL_STATUSES = ("success", "failed", "blocked", "skipped")
TASK_ID_RE = re.compile(r"^[0-9]+\.[0-9]+$")


class HarnessError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(message)


# ---------- env / paths ----------

def get_base_dir() -> Path:
    return Path(os.environ.get("HARNESS_BASE_DIR", DEFAULT_BASE))


def get_max_attempts() -> int:
    raw = os.environ.get("HARNESS_MAX_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS))
    try:
        n = int(raw)
    except ValueError:
        raise HarnessError(EXIT_USAGE, f"HARNESS_MAX_ATTEMPTS must be int, got {raw!r}")
    if n < 0:
        raise HarnessError(EXIT_USAGE, "HARNESS_MAX_ATTEMPTS must be >= 0")
    return n


def project_root() -> Path:
    return get_base_dir().resolve().parent


def slug_path(slug: str) -> Path:
    return get_base_dir() / slug


def require_slug_dir(slug: str) -> Path:
    p = slug_path(slug)
    if not p.exists():
        raise HarnessError(EXIT_STATE, f"slug not found: {slug}")
    return p


def task_state_path(slug_dir: Path, task_id: str) -> Path:
    return slug_dir / "04-generate" / f"task-{task_id}.json"


# ---------- time / hashing / slug canonicalization ----------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_str(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonical_task_json(task: dict) -> str:
    return json.dumps(task, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canonical_slug(candidate: str) -> str:
    s = candidate.lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:50]


# ---------- atomic IO ----------

def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if Path(tmp).exists():
            Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path: Path, obj) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise HarnessError(EXIT_SCHEMA, f"corrupted JSON at {path}: {e}")


# ---------- plan loading ----------

def _require_yaml():
    try:
        import yaml
        return yaml
    except ImportError:
        raise HarnessError(
            EXIT_MISSING_DEP,
            "PyYAML required for plan parsing. Install: pip install pyyaml",
        )


def load_plan(slug_dir: Path) -> dict:
    """Load current plan. Returns {'phases': [...], 'tasks_by_id': {...}}.

    Missing 03-plan/ or empty plan returns empty structures. Caller decides
    whether that is an error for their subcommand.
    """
    yaml = _require_yaml()
    plan_dir = slug_dir / "03-plan"
    phases: list[dict] = []
    tasks_by_id: dict[str, dict] = {}
    task_phase: dict[str, int] = {}
    if plan_dir.exists():
        for f in sorted(plan_dir.glob("phase-*.yaml")):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
            except yaml.YAMLError as e:
                raise HarnessError(EXIT_SCHEMA, f"invalid YAML at {f}: {e}")
            if not isinstance(data, dict):
                raise HarnessError(EXIT_SCHEMA, f"plan file not a mapping: {f}")
            if "phase" not in data or "tasks" not in data:
                raise HarnessError(EXIT_SCHEMA, f"plan file missing required fields: {f}")
            phases.append(data)
            for t in data.get("tasks", []) or []:
                tid = t.get("id")
                if not tid or not TASK_ID_RE.match(tid):
                    raise HarnessError(EXIT_SCHEMA, f"bad task id in {f}: {tid!r}")
                if tid in tasks_by_id:
                    raise HarnessError(EXIT_SCHEMA, f"duplicate task id across plan: {tid}")
                tasks_by_id[tid] = t
                task_phase[tid] = data["phase"]
    return {"phases": phases, "tasks_by_id": tasks_by_id, "task_phase": task_phase, "plan_dir": plan_dir}


def find_plan_archives(slug_dir: Path) -> list[str]:
    return sorted(p.name for p in slug_dir.glob("03-plan.v*") if p.is_dir())


# ---------- task state loading ----------

def load_task_state(slug_dir: Path, task_id: str) -> dict | None:
    p = task_state_path(slug_dir, task_id)
    if not p.exists():
        return None
    state = read_json(p)
    if state.get("schema_version") != SCHEMA_VERSION:
        raise HarnessError(
            EXIT_SCHEMA,
            f"unknown schema_version {state.get('schema_version')!r} in {p}",
        )
    return state


def load_all_task_states(slug_dir: Path) -> dict[str, dict]:
    gen_dir = slug_dir / "04-generate"
    if not gen_dir.exists():
        return {}
    result = {}
    for f in sorted(gen_dir.glob("task-*.json")):
        m = re.match(r"^task-(\d+\.\d+)\.json$", f.name)
        if not m:
            continue
        tid = m.group(1)
        state = read_json(f)
        if state.get("schema_version") != SCHEMA_VERSION:
            raise HarnessError(EXIT_SCHEMA, f"unknown schema_version in {f}")
        result[tid] = state
    return result


# ---------- approvals ----------

def approval_path(slug_dir: Path, step: int) -> Path:
    return slug_dir / ".approvals" / f"step-{step}.json"


def load_approval(slug_dir: Path, step: int) -> dict | None:
    p = approval_path(slug_dir, step)
    if not p.exists():
        return None
    data = read_json(p)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise HarnessError(EXIT_SCHEMA, f"unknown schema_version in {p}")
    return data


# ---------- scan logic ----------

def _step_statuses(slug_dir: Path, plan: dict, task_states: dict[str, dict]) -> dict:
    """Compute per-step status view."""
    steps = {}

    # Step 1 Clarify
    clarify = slug_dir / "01-clarify.md"
    appr1 = load_approval(slug_dir, 1)
    if not clarify.exists():
        steps["1_clarify"] = {"status": "not_started"}
    elif appr1:
        steps["1_clarify"] = {
            "status": "approved",
            "artifact": "01-clarify.md",
            "approved_at": appr1["approved_at"],
        }
    else:
        steps["1_clarify"] = {"status": "completed", "artifact": "01-clarify.md"}

    # Step 2 Context
    context = slug_dir / "02-context.md"
    steps["2_context"] = (
        {"status": "completed", "artifact": "02-context.md"}
        if context.exists()
        else {"status": "not_started"}
    )

    # Step 3 Plan
    archives = find_plan_archives(slug_dir)
    has_plan = bool(plan["phases"])
    appr3 = load_approval(slug_dir, 3)
    plan_version = len(archives) + 1  # current is always "latest"
    if not has_plan:
        steps["3_plan"] = {"status": "not_started"}
    elif appr3:
        steps["3_plan"] = {
            "status": "approved",
            "plan_version": plan_version,
            "archived": archives,
            "approved_at": appr3["approved_at"],
        }
    else:
        steps["3_plan"] = {
            "status": "completed",
            "plan_version": plan_version,
            "archived": archives,
        }

    # Step 4 Generate (derived from task states)
    step4_status = _derive_step4_status(plan, task_states)
    steps["4_generate"] = {"status": step4_status}

    # Step 5 Evaluate
    evaluate = slug_dir / "05-evaluate.md"
    steps["5_evaluate"] = (
        {"status": "completed", "artifact": "05-evaluate.md"}
        if evaluate.exists()
        else {"status": "not_started"}
    )
    return steps


def _derive_step4_status(plan: dict, task_states: dict[str, dict]) -> str:
    if not plan["phases"]:
        return "not_started"
    any_progress = False
    any_blocked = False
    all_success = True
    for tid in plan["tasks_by_id"]:
        st = task_states.get(tid)
        if st is None:
            all_success = False
            continue
        s = st.get("status")
        if s == "success":
            any_progress = True
            continue
        if s == "skipped":
            any_progress = True
            continue
        all_success = False
        if s == "blocked":
            any_blocked = True
            any_progress = True
        elif s in ("running", "failed", "not_started"):
            any_progress = True
    if all_success and plan["tasks_by_id"]:
        return "completed"
    if any_blocked:
        return "blocked"
    if any_progress:
        return "in_progress"
    return "not_started"


def _phase_rollup(plan: dict, task_states: dict[str, dict], max_attempts: int) -> list[dict]:
    rollup = []
    for phase in plan["phases"]:
        tasks_view = []
        phase_statuses = []
        for t in phase.get("tasks", []) or []:
            tid = t["id"]
            st = task_states.get(tid)
            if st is None:
                tv = {"id": tid, "status": "not_started", "attempts": 0}
                phase_statuses.append("not_started")
            else:
                tv = {
                    "id": tid,
                    "status": st["status"],
                    "attempts": st.get("attempts", 0),
                }
                if st.get("last_error"):
                    tv["last_error"] = st["last_error"]
                phase_statuses.append(st["status"])
            tasks_view.append(tv)
        if phase_statuses and all(s in ("success", "skipped") for s in phase_statuses):
            pstatus = "completed"
        elif any(
            s == "failed" and task_states.get(tv["id"], {}).get("attempts", 0) >= max_attempts
            for s, tv in zip(phase_statuses, tasks_view)
        ) or any(s == "blocked" for s in phase_statuses):
            pstatus = "blocked"
        elif any(s not in ("not_started",) for s in phase_statuses):
            pstatus = "in_progress"
        else:
            pstatus = "not_started"
        rollup.append(
            {
                "phase": phase["phase"],
                "name": phase.get("name", ""),
                "status": pstatus,
                "tasks": tasks_view,
            }
        )
    return rollup


def _resume_point(
    steps: dict, phases: list[dict], plan: dict, task_states: dict[str, dict], max_attempts: int
) -> dict:
    # Gate checks first
    s1 = steps["1_clarify"]["status"]
    if s1 == "not_started":
        return {"task_id": None, "phase": None, "reason": "steps_incomplete", "step": 1}
    if s1 == "completed":
        return {"task_id": None, "phase": None, "reason": "waiting_for_approval", "step": 1}

    s2 = steps["2_context"]["status"]
    if s2 == "not_started":
        return {"task_id": None, "phase": None, "reason": "steps_incomplete", "step": 2}

    s3 = steps["3_plan"]["status"]
    if s3 == "not_started":
        return {"task_id": None, "phase": None, "reason": "steps_incomplete", "step": 3}
    if s3 == "completed":
        return {"task_id": None, "phase": None, "reason": "waiting_for_approval", "step": 3}

    # Step 4: find first runnable or blocking task
    blocked_ids: list[str] = []
    for phase in phases:
        for tv in phase["tasks"]:
            tid = tv["id"]
            st = task_states.get(tid)
            status = tv["status"]
            attempts = tv["attempts"]
            if status in ("success", "skipped"):
                continue
            # Check deps satisfied
            task_def = plan["tasks_by_id"].get(tid, {})
            deps = task_def.get("depends_on", []) or []
            unresolved = [
                d
                for d in deps
                if (task_states.get(d) or {}).get("status") not in ("success", "skipped")
            ]
            if unresolved:
                continue
            if status == "failed":
                if attempts >= max_attempts:
                    blocked_ids.append(tid)
                    continue
                return {"task_id": tid, "phase": phase["phase"], "reason": "failed_within_budget"}
            if status == "blocked":
                blocked_ids.append(tid)
                continue
            if status == "running":
                return {"task_id": tid, "phase": phase["phase"], "reason": "in_progress"}
            if status == "not_started":
                return {"task_id": tid, "phase": phase["phase"], "reason": "not_started"}
        # If the whole phase is blocked, keep scanning — later phases might have independent chains,
        # but typically blocked predecessor chains will leave deps unresolved. That's expected.
    # All runnable tasks exhausted
    s4 = steps["4_generate"]["status"]
    if s4 == "completed":
        s5 = steps["5_evaluate"]["status"]
        if s5 == "not_started":
            return {"task_id": None, "phase": None, "reason": "steps_incomplete", "step": 5}
        return {"task_id": None, "phase": None, "reason": "pipeline_complete"}
    if blocked_ids:
        return {
            "task_id": None,
            "phase": None,
            "reason": "blocked",
            "blocked_tasks": blocked_ids,
        }
    return {"task_id": None, "phase": None, "reason": "pipeline_complete"}


def _orphans_and_stale(
    plan: dict, task_states: dict[str, dict]
) -> tuple[list[str], list[dict]]:
    orphans = [tid for tid in task_states if tid not in plan["tasks_by_id"]]
    stale = []
    for tid, st in task_states.items():
        if tid not in plan["tasks_by_id"]:
            continue
        current = sha256_str(canonical_task_json(plan["tasks_by_id"][tid]))
        recorded = st.get("plan_checksum")
        if recorded and recorded != current:
            stale.append({"task_id": tid, "recorded": recorded, "current": current})
    return sorted(orphans), stale


def _pipeline_status(steps: dict, phases: list[dict]) -> str:
    if steps["5_evaluate"]["status"] == "completed":
        return "completed"
    for p in phases:
        if p["status"] == "blocked":
            return "blocked"
    if steps["1_clarify"]["status"] == "not_started":
        return "not_started"
    return "in_progress"


def _current_step(steps: dict) -> int:
    order = ["1_clarify", "2_context", "3_plan", "4_generate", "5_evaluate"]
    for i, key in enumerate(order, start=1):
        if steps[key]["status"] in ("not_started", "completed", "in_progress"):
            return i
    return 5


# ---------- subcommands ----------

def cmd_slug(args) -> dict:
    if not args.request:
        raise HarnessError(EXIT_USAGE, "--request is required")
    base_candidate = args.suggested if args.suggested else args.request
    slug = canonical_slug(base_candidate)
    if not slug:
        raise HarnessError(EXIT_USAGE, "could not derive a valid slug")

    request_text = args.request
    if not request_text.endswith("\n"):
        request_text = request_text + "\n"
    request_checksum = sha256_str(request_text)

    path = slug_path(slug)
    if path.exists():
        req_file = path / "00-request.md"
        if req_file.exists():
            existing = req_file.read_text(encoding="utf-8")
            if sha256_str(existing) == request_checksum:
                return {
                    "slug": slug,
                    "path": str(path) + "/",
                    "status": "exists",
                    "request_checksum": request_checksum,
                }
        n = 2
        while slug_path(f"{slug}-v{n}").exists():
            n += 1
        return {
            "slug": slug,
            "path": str(path) + "/",
            "status": "collision",
            "request_checksum": request_checksum,
            "suggested_slug": f"{slug}-v{n}",
        }

    path.mkdir(parents=True, exist_ok=False)
    atomic_write_text(path / "00-request.md", request_text)
    return {
        "slug": slug,
        "path": str(path) + "/",
        "status": "created",
        "request_checksum": request_checksum,
    }


def cmd_scan(args) -> dict:
    slug_dir = require_slug_dir(args.slug)
    plan = load_plan(slug_dir)
    task_states = load_all_task_states(slug_dir)
    max_attempts = get_max_attempts()

    steps = _step_statuses(slug_dir, plan, task_states)
    phases = _phase_rollup(plan, task_states, max_attempts)
    orphans, stale = _orphans_and_stale(plan, task_states)
    pipeline_status = _pipeline_status(steps, phases)
    current_step = _current_step(steps)
    resume_point = _resume_point(steps, phases, plan, task_states, max_attempts)

    return {
        "slug": args.slug,
        "base_path": str(slug_dir) + "/",
        "pipeline_status": pipeline_status,
        "current_step": current_step,
        "steps": steps,
        "phases": phases,
        "resume_point": resume_point,
        "orphans": orphans,
        "stale": stale,
    }


def cmd_next(args) -> dict:
    scan = cmd_scan(args)
    rp = scan["resume_point"]
    if rp["task_id"] is None:
        out = {"task_id": None, "reason": rp["reason"]}
        for k in ("step", "blocked_tasks"):
            if k in rp:
                out[k] = rp[k]
        return out
    slug_dir = require_slug_dir(args.slug)
    plan = load_plan(slug_dir)
    task_def = plan["tasks_by_id"].get(rp["task_id"])
    if task_def is None:
        raise HarnessError(EXIT_STATE, f"resume_point task {rp['task_id']} not in plan")
    states = load_all_task_states(slug_dir)
    prev_attempts = (states.get(rp["task_id"]) or {}).get("attempts", 0)
    return {
        "task_id": rp["task_id"],
        "phase": rp["phase"],
        "reason": rp["reason"],
        "task": task_def,
        "previous_attempts": prev_attempts,
    }


def cmd_log(args) -> dict:
    slug_dir = require_slug_dir(args.slug)
    task_id = args.task_id
    if not TASK_ID_RE.match(task_id):
        raise HarnessError(EXIT_USAGE, f"bad task id: {task_id!r}")
    if args.status not in VALID_STATUSES:
        raise HarnessError(EXIT_USAGE, f"invalid status: {args.status}")

    plan = load_plan(slug_dir)
    if task_id not in plan["tasks_by_id"]:
        raise HarnessError(EXIT_STATE, f"task {task_id} not in current plan")
    task_def = plan["tasks_by_id"][task_id]
    phase = plan["task_phase"][task_id]

    existing = load_task_state(slug_dir, task_id)
    now = now_iso()
    if existing is None:
        existing = {
            "schema_version": SCHEMA_VERSION,
            "id": task_id,
            "phase": phase,
            "status": "not_started",
            "attempts": 0,
            "started": None,
            "completed": None,
            "last_updated": now,
            "outputs": [],
            "depends_on": task_def.get("depends_on", []) or [],
            "last_error": None,
            "plan_checksum": sha256_str(canonical_task_json(task_def)),
        }

    if args.attempt_start:
        existing["attempts"] = existing.get("attempts", 0) + 1
        existing["started"] = now
        existing["completed"] = None
        existing["last_error"] = None
        existing["plan_checksum"] = sha256_str(canonical_task_json(task_def))
        existing["depends_on"] = task_def.get("depends_on", []) or []

    existing["status"] = args.status
    existing["last_updated"] = now
    if args.status in TERMINAL_STATUSES:
        existing["completed"] = now

    if args.outputs is not None:
        try:
            parsed = json.loads(args.outputs)
        except json.JSONDecodeError as e:
            raise HarnessError(EXIT_USAGE, f"--outputs must be JSON array: {e}")
        if not isinstance(parsed, list):
            raise HarnessError(EXIT_USAGE, "--outputs must be a JSON array")
        normalized = []
        for o in parsed:
            if isinstance(o, str):
                normalized.append({"path": o})
            elif isinstance(o, dict) and "path" in o:
                entry = {"path": o["path"]}
                if "size" in o and isinstance(o["size"], int):
                    entry["size"] = o["size"]
                if "exists" in o and isinstance(o["exists"], bool):
                    entry["exists"] = o["exists"]
                normalized.append(entry)
            else:
                raise HarnessError(EXIT_USAGE, f"invalid --outputs entry: {o!r}")
        existing["outputs"] = normalized

    if args.last_error is not None:
        existing["last_error"] = args.last_error if args.last_error else None

    write_json(task_state_path(slug_dir, task_id), existing)
    return existing


def cmd_verify(args) -> dict:
    slug_dir = require_slug_dir(args.slug)
    task_id = args.task_id
    if not TASK_ID_RE.match(task_id):
        raise HarnessError(EXIT_USAGE, f"bad task id: {task_id!r}")

    plan = load_plan(slug_dir)
    if task_id not in plan["tasks_by_id"]:
        raise HarnessError(EXIT_STATE, f"task {task_id} not in current plan")
    task_def = plan["tasks_by_id"][task_id]
    declared = (task_def.get("artifacts") or {}).get("outputs", []) or []

    root = project_root()
    results = []
    ok = True
    issues = 0
    for out_path in declared:
        full = (root / out_path) if not os.path.isabs(out_path) else Path(out_path)
        entry = {"path": out_path, "exists": full.exists(), "size": None, "issue": None}
        if not full.exists():
            entry["issue"] = "missing"
            ok = False
            issues += 1
        else:
            size = full.stat().st_size
            entry["size"] = size
            if size == 0:
                entry["issue"] = "empty"
                ok = False
                issues += 1
        results.append(entry)

    state = load_task_state(slug_dir, task_id)
    if state is not None:
        state["outputs"] = [
            {"path": r["path"], "size": r["size"] if r["size"] is not None else 0, "exists": r["exists"]}
            for r in results
        ]
        state["last_updated"] = now_iso()
        write_json(task_state_path(slug_dir, task_id), state)

    return {"task_id": task_id, "ok": ok, "outputs": results, "issues_count": issues}


def cmd_conflicts(args) -> dict:
    slug_dir = require_slug_dir(args.slug)
    if not args.tasks:
        raise HarnessError(EXIT_USAGE, "--tasks is required")
    task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
    if not task_ids:
        raise HarnessError(EXIT_USAGE, "--tasks must contain at least one id")

    plan = load_plan(slug_dir)
    owners: dict[str, list[str]] = {}
    for tid in task_ids:
        if tid not in plan["tasks_by_id"]:
            raise HarnessError(EXIT_USAGE, f"unknown task id: {tid}")
        outs = (plan["tasks_by_id"][tid].get("artifacts") or {}).get("outputs", []) or []
        for path in outs:
            owners.setdefault(path, []).append(tid)

    conflicts = [
        {"path": path, "task_ids": sorted(tids)}
        for path, tids in sorted(owners.items())
        if len(tids) > 1
    ]
    return {"safe": not conflicts, "conflicts": conflicts}


def cmd_summary(args) -> dict:
    slug_dir = require_slug_dir(args.slug)
    plan = load_plan(slug_dir)
    if not plan["phases"]:
        raise HarnessError(EXIT_STATE, "no plan loaded; nothing to summarize")
    states = load_all_task_states(slug_dir)

    phases_md = []
    total_tasks = 0
    counts = {s: 0 for s in VALID_STATUSES}
    plan_changes = []
    for phase in plan["phases"]:
        rows = []
        for t in phase.get("tasks", []) or []:
            tid = t["id"]
            total_tasks += 1
            st = states.get(tid)
            status = st["status"] if st else "not_started"
            counts[status] = counts.get(status, 0) + 1
            note = ""
            if st:
                if st.get("attempts", 0) > 1:
                    note = f"{st['attempts']}회 시도"
                if st.get("last_error"):
                    note = (note + "; " if note else "") + f"error: {st['last_error']}"
            rows.append((tid, t.get("name", ""), status, note))
        phases_md.append((phase["phase"], phase.get("name", ""), rows))

    body = ["# 생성 결과 리포트", ""]
    body.append("## 실행 요약")
    body.append(f"- 총 Phase: {len(plan['phases'])}개")
    body.append(f"- 총 Task: {total_tasks}개")
    for s in ("success", "failed", "blocked", "skipped", "running", "not_started"):
        if counts.get(s, 0):
            body.append(f"- {s}: {counts[s]}개")
    body.append("")
    body.append("## Task별 결과")
    body.append("| Task | 이름 | 상태 | 비고 |")
    body.append("|------|------|------|------|")
    for phase_num, phase_name, rows in phases_md:
        for tid, name, status, note in rows:
            body.append(f"| {tid} | {name} | {status} | {note} |")
    body.append("")
    body.append("## 계획 대비 주요 변경점")
    body.append("(Task 로그의 outputs·error를 참고. 자동 수집 범위 외 변경점은 Claude가 보완할 수 있음.)")
    body.append("")

    out_path = slug_dir / "04-generate" / "summary.md"
    atomic_write_text(out_path, "\n".join(body))

    totals = {
        "phases": len(plan["phases"]),
        "tasks": total_tasks,
        "success": counts.get("success", 0),
        "failed": counts.get("failed", 0),
        "blocked": counts.get("blocked", 0),
        "skipped": counts.get("skipped", 0),
        "running": counts.get("running", 0),
        "not_started": counts.get("not_started", 0),
    }
    return {"summary_path": str(out_path), "totals": totals}


def _artifact_checksum_for_step(slug_dir: Path, step: int) -> str | None:
    """Compute checksum of the gated artifact. None if artifact missing."""
    if step == 1:
        f = slug_dir / "01-clarify.md"
        if not f.exists():
            return None
        return sha256_str(f.read_text(encoding="utf-8"))
    if step == 3:
        plan_dir = slug_dir / "03-plan"
        if not plan_dir.exists():
            return None
        parts = []
        for f in sorted(plan_dir.glob("phase-*.yaml")):
            parts.append(f.name)
            parts.append(f.read_text(encoding="utf-8"))
        if not parts:
            return None
        return sha256_str("\n".join(parts))
    return None


def cmd_approve(args) -> dict:
    slug_dir = require_slug_dir(args.slug)
    if args.step not in (1, 3):
        raise HarnessError(EXIT_USAGE, "--step must be 1 or 3")

    path = approval_path(slug_dir, args.step)
    if path.exists() and not args.force:
        raise HarnessError(
            EXIT_STATE,
            f"step {args.step} already approved at {path}; pass --force to overwrite",
        )

    checksum = _artifact_checksum_for_step(slug_dir, args.step)
    if checksum is None:
        artifact = "01-clarify.md" if args.step == 1 else "03-plan/*.yaml"
        raise HarnessError(
            EXIT_STATE,
            f"cannot approve step {args.step}: gated artifact {artifact} is missing",
        )

    record = {
        "schema_version": SCHEMA_VERSION,
        "step": args.step,
        "approved_at": now_iso(),
        "feedback": args.feedback if args.feedback else None,
        "artifact_checksum": checksum,
    }
    write_json(path, record)
    return record


def cmd_archive_plan(args) -> dict:
    slug_dir = require_slug_dir(args.slug)
    plan_dir = slug_dir / "03-plan"
    if not plan_dir.exists() or not any(plan_dir.glob("phase-*.yaml")):
        raise HarnessError(
            EXIT_STATE, "no current plan to archive (03-plan/ missing or empty)"
        )
    existing = find_plan_archives(slug_dir)
    highest = 0
    for name in existing:
        m = re.match(r"^03-plan\.v(\d+)$", name)
        if m:
            n = int(m.group(1))
            if n > highest:
                highest = n
    archive_label = highest + 1          # the label the old plan is archived under
    next_live_label = archive_label + 1  # the label the new (about-to-be-written) plan will carry
    archived_to = f"03-plan.v{archive_label}"
    dest = slug_dir / archived_to
    if dest.exists():
        raise HarnessError(EXIT_STATE, f"archive target already exists: {dest}")
    os.rename(plan_dir, dest)
    plan_dir.mkdir()
    return {"archived_to": archived_to + "/", "new_version": next_live_label}


# ---------- argparse plumbing ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("slug", help="create or canonicalize a slug directory")
    s.add_argument("--request", required=True, help="raw request text")
    s.add_argument("--suggested", help="candidate slug; CLI canonicalizes")
    s.set_defaults(func=cmd_slug)

    s = sub.add_parser("scan", help="compute full resume state")
    s.add_argument("slug")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("next", help="next runnable task or reason")
    s.add_argument("slug")
    s.set_defaults(func=cmd_next)

    s = sub.add_parser("log", help="create or update a task sidecar")
    s.add_argument("slug")
    s.add_argument("task_id")
    s.add_argument("--status", required=True)
    s.add_argument("--attempt-start", action="store_true")
    s.add_argument("--outputs", help="JSON array of outputs")
    s.add_argument("--last-error")
    s.set_defaults(func=cmd_log)

    s = sub.add_parser("verify", help="check declared outputs exist and non-empty")
    s.add_argument("slug")
    s.add_argument("task_id")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("conflicts", help="detect output overlap for parallel tasks")
    s.add_argument("slug")
    s.add_argument("--tasks", required=True, help="comma-separated task ids")
    s.set_defaults(func=cmd_conflicts)

    s = sub.add_parser("summary", help="write summary.md aggregating task states")
    s.add_argument("slug")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("approve", help="record user approval for a gated step")
    s.add_argument("slug")
    s.add_argument("--step", type=int, required=True, help="1 (Clarify) or 3 (Plan)")
    s.add_argument("--feedback", help="free-form user comment captured with the approval")
    s.add_argument("--force", action="store_true", help="overwrite an existing approval")
    s.set_defaults(func=cmd_approve)

    s = sub.add_parser(
        "archive-plan",
        help="move current 03-plan/ to 03-plan.v{N+1}/ and create empty 03-plan/",
    )
    s.add_argument("slug")
    s.set_defaults(func=cmd_archive_plan)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except HarnessError as e:
        print(str(e), file=sys.stderr)
        return e.code
    except FileNotFoundError as e:
        print(f"I/O error: {e}", file=sys.stderr)
        return EXIT_IO
    except PermissionError as e:
        print(f"permission denied: {e}", file=sys.stderr)
        return EXIT_IO
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
