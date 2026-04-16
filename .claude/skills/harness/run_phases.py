#!/usr/bin/env python3
"""
run_phases.py - Phase/Task 파일을 읽고 Claude CLI로 실행하는 스크립트.

artifacts/ 기반 파이프라인의 독립 실행 도구.
SKILL.md의 Step 4(Generate)를 CLI 환경에서 직접 실행할 때 사용한다.

Usage:
    python3 run_phases.py artifacts/03-plan/
    python3 run_phases.py artifacts/03-plan/ --dry-run
    python3 run_phases.py artifacts/03-plan/ --phase 2
    python3 run_phases.py artifacts/03-plan/ --resume 2.3
    python3 run_phases.py artifacts/03-plan/ --parallel
"""

import argparse
import glob
import json
import os
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml


ARTIFACTS_DIR = "artifacts"
LOG_DIR = "logs"


def init_log(phases_dir: str) -> Path:
    """실행 로그 파일을 생성하고 경로를 반환한다."""
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(LOG_DIR) / f"run_{ts}.jsonl"
    return log_path


def log_event(log_path: Path, event: dict):
    """이벤트를 JSONL 로그 파일에 추가한다."""
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(log_path, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_phases(phases_dir: str) -> list[dict]:
    """phases 디렉토리에서 YAML 파일을 읽어 Phase 목록을 반환한다."""
    pattern = os.path.join(phases_dir, "phase-*.yaml")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"Error: No phase files found in {phases_dir}")
        sys.exit(1)

    phases = []
    for f in files:
        with open(f) as fh:
            data = yaml.safe_load(fh)
            data["_file"] = f
            phases.append(data)

    phases.sort(key=lambda p: p.get("phase", 0))
    return phases


def resolve_order(tasks: list[dict]) -> list[dict]:
    """depends_on을 기반으로 Task 실행 순서를 결정한다 (위상 정렬)."""
    by_id = {t["id"]: t for t in tasks}
    visited = set()
    order = []

    def visit(task_id: str):
        if task_id in visited:
            return
        visited.add(task_id)
        task = by_id[task_id]
        for dep in task.get("depends_on", []):
            if dep in by_id:
                visit(dep)
        order.append(task)

    for t in tasks:
        visit(t["id"])

    return order


def get_parallel_groups(tasks: list[dict]) -> list[list[dict]]:
    """의존관계 기반으로 병렬 실행 가능한 그룹을 반환한다."""
    by_id = {t["id"]: t for t in tasks}
    completed = set()
    remaining = {t["id"] for t in tasks}
    groups = []

    while remaining:
        # 의존관계가 모두 충족된 task들을 찾는다
        ready = []
        for tid in remaining:
            task = by_id[tid]
            deps = set(task.get("depends_on", []))
            if deps.issubset(completed):
                ready.append(task)

        if not ready:
            # 순환 의존관계 - 나머지를 순차 실행
            ready = [by_id[tid] for tid in sorted(remaining)]
            groups.append(ready)
            break

        groups.append(ready)
        for t in ready:
            completed.add(t["id"])
            remaining.discard(t["id"])

    return groups


def build_task_prompt(task: dict) -> str:
    """Task의 prompt에 artifact 컨텍스트 참조를 추가한다."""
    prompt = task.get("prompt", "").strip()
    if not prompt:
        return ""

    # artifact inputs가 있으면 프롬프트 앞에 참조 안내 추가
    artifacts = task.get("artifacts", {})
    inputs = artifacts.get("inputs", [])

    if inputs:
        ctx_lines = [
            "\n\n## 참고할 artifact 파일",
            "아래 파일들을 먼저 읽어 컨텍스트를 파악하세요:",
        ]
        for inp in inputs:
            ctx_lines.append(f"- {inp}")
        prompt = prompt + "\n".join(ctx_lines)

    return prompt


def run_task(
    task: dict, project_dir: str, log_path: Path, dry_run: bool = False
) -> dict:
    """단일 Task를 Claude CLI로 실행한다. 결과 dict를 반환."""
    task_id = task["id"]
    name = task.get("name", "")
    prompt = build_task_prompt(task)

    result_info = {
        "task_id": task_id,
        "name": name,
        "status": "unknown",
        "changed_files": [],
        "summary": "",
    }

    print(f"\n{'='*60}")
    print(f"Task {task_id}: {name}")
    print(f"{'='*60}")

    if dry_run:
        print(f"[DRY RUN] Would execute prompt:\n{prompt[:200]}...")
        log_event(log_path, {"event": "dry_run", "task": task_id, "name": name})
        result_info["status"] = "dry_run"
        return result_info

    if not prompt:
        print(f"[SKIP] Empty prompt for task {task_id}")
        log_event(log_path, {"event": "skip", "task": task_id, "reason": "empty prompt"})
        result_info["status"] = "skipped"
        return result_info

    log_event(log_path, {"event": "start", "task": task_id, "name": name})

    cmd = [
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
        )

        # task별 로그 저장
        task_log_dir = Path(LOG_DIR) / "tasks"
        os.makedirs(task_log_dir, exist_ok=True)
        task_log_file = task_log_dir / f"task_{task_id.replace('.', '_')}.log"
        with open(task_log_file, "w") as f:
            f.write(f"=== Task {task_id}: {name} ===\n")
            f.write(f"=== stdout ===\n{result.stdout}\n")
            if result.stderr:
                f.write(f"=== stderr ===\n{result.stderr}\n")
            f.write(f"=== exit code: {result.returncode} ===\n")

        if result.returncode != 0:
            print(f"[WARN] Task {task_id} exited with code {result.returncode}")
            print(f"       Log: {task_log_file}")
            log_event(log_path, {
                "event": "fail",
                "task": task_id,
                "exit_code": result.returncode,
                "log_file": str(task_log_file),
            })
            result_info["status"] = "failed"
            result_info["summary"] = f"Exit code {result.returncode}"
            return result_info

        print(f"[DONE] Task {task_id} completed")
        print(f"       Log: {task_log_file}")
        log_event(log_path, {
            "event": "done",
            "task": task_id,
            "log_file": str(task_log_file),
        })
        result_info["status"] = "success"
        result_info["summary"] = result.stdout[:500] if result.stdout else ""
        return result_info
    except FileNotFoundError:
        print("Error: 'claude' CLI not found. Install it first.")
        sys.exit(1)
    except KeyboardInterrupt:
        log_event(log_path, {"event": "interrupted", "task": task_id})
        print(f"\n[INTERRUPTED] Task {task_id}")
        sys.exit(130)


def write_generate_report(results: list[dict]):
    """실행 결과를 artifacts/04-generate.md에 기록한다."""
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    report_path = Path(ARTIFACTS_DIR) / "04-generate.md"

    success = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "failed")
    skipped = sum(1 for r in results if r["status"] in ("skipped", "dry_run"))

    lines = [
        "# 생성 결과 리포트",
        "",
        "## 실행 요약",
        f"- 총 Task: {len(results)}개",
        f"- 성공: {success}개",
        f"- 실패: {failed}개",
        f"- 건너뜀: {skipped}개",
        "",
        "## Task별 결과",
        "",
    ]

    for r in results:
        status_icon = {"success": "✅", "failed": "❌", "skipped": "⏭", "dry_run": "🔍"}.get(
            r["status"], "❓"
        )
        lines.append(f"### Task {r['task_id']}: {r['name']}")
        lines.append(f"- 상태: {status_icon} {r['status']}")
        if r.get("summary"):
            lines.append(f"- 요약: {r['summary'][:200]}")
        lines.append("")

    with open(report_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\n[REPORT] {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Phase/Task 실행기 (artifact 기반)")
    parser.add_argument(
        "phases_dir",
        nargs="?",
        default="artifacts/03-plan",
        help="Phase YAML 파일이 있는 디렉토리 (기본: artifacts/03-plan)",
    )
    parser.add_argument("--dry-run", action="store_true", help="실제 실행 없이 계획만 출력")
    parser.add_argument("--phase", type=int, help="특정 Phase만 실행")
    parser.add_argument("--resume", help="특정 Task ID부터 재개 (예: 2.3)")
    parser.add_argument("--parallel", action="store_true", help="의존관계 없는 Task를 병렬 실행")
    parser.add_argument("--max-workers", type=int, default=3, help="병렬 실행 시 최대 동시 Task 수")
    parser.add_argument("--project-dir", default=".", help="프로젝트 루트 디렉토리")
    parser.add_argument("--no-report", action="store_true", help="04-generate.md 리포트 생성 안함")
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    phases = load_phases(args.phases_dir)
    log_path = init_log(args.phases_dir)

    if args.phase is not None:
        phases = [p for p in phases if p.get("phase") == args.phase]
        if not phases:
            print(f"Error: Phase {args.phase} not found")
            sys.exit(1)

    total_tasks = sum(len(p.get("tasks", [])) for p in phases)
    print(f"Phases: {len(phases)}, Tasks: {total_tasks}")
    print(f"Log: {log_path}")
    if args.dry_run:
        print("[DRY RUN MODE]")
    if args.parallel:
        print(f"[PARALLEL MODE] max_workers={args.max_workers}")
    print()

    log_event(log_path, {
        "event": "run_start",
        "phases_dir": args.phases_dir,
        "total_phases": len(phases),
        "total_tasks": total_tasks,
        "dry_run": args.dry_run,
        "parallel": args.parallel,
        "resume": args.resume,
    })

    resuming = args.resume is not None
    skipping = resuming
    all_results = []

    for phase in phases:
        phase_num = phase.get("phase", "?")
        phase_name = phase.get("name", "")
        tasks = phase.get("tasks", [])

        print(f"\n{'#'*60}")
        print(f"# Phase {phase_num}: {phase_name}")
        print(f"{'#'*60}")

        log_event(log_path, {
            "event": "phase_start",
            "phase": phase_num,
            "name": phase_name,
            "task_count": len(tasks),
        })

        if args.parallel:
            groups = get_parallel_groups(tasks)
            for group in groups:
                # resume 처리
                if skipping:
                    group_filtered = []
                    for task in group:
                        if task["id"] == args.resume:
                            skipping = False
                            group_filtered.append(task)
                        elif not skipping:
                            group_filtered.append(task)
                        else:
                            print(f"[SKIP] Task {task['id']} (resuming from {args.resume})")
                    group = group_filtered
                    if not group:
                        continue

                if len(group) == 1:
                    result = run_task(group[0], project_dir, log_path, args.dry_run)
                    all_results.append(result)
                    if result["status"] == "failed" and not args.dry_run:
                        print(f"\n[FAILED] Task {result['task_id']} failed.")
                        break
                else:
                    print(f"\n[PARALLEL] Running {len(group)} tasks: {[t['id'] for t in group]}")
                    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
                        futures = {
                            executor.submit(run_task, t, project_dir, log_path, args.dry_run): t
                            for t in group
                        }
                        for future in as_completed(futures):
                            result = future.result()
                            all_results.append(result)

                    failed_in_group = [r for r in all_results[-len(group):] if r["status"] == "failed"]
                    if failed_in_group and not args.dry_run:
                        for r in failed_in_group:
                            print(f"\n[FAILED] Task {r['task_id']} failed.")
                        break
        else:
            ordered_tasks = resolve_order(tasks)
            for task in ordered_tasks:
                if skipping:
                    if task["id"] == args.resume:
                        skipping = False
                    else:
                        print(f"[SKIP] Task {task['id']} (resuming from {args.resume})")
                        continue

                result = run_task(task, project_dir, log_path, args.dry_run)
                all_results.append(result)

                if result["status"] == "failed" and not args.dry_run:
                    log_event(log_path, {
                        "event": "run_end",
                        "status": "failed",
                        "completed": sum(1 for r in all_results if r["status"] == "success"),
                        "failed": 1,
                        "stopped_at": task["id"],
                    })
                    print(f"\n[FAILED] Task {task['id']} failed. Resume with: --resume {task['id']}")
                    if not args.no_report:
                        write_generate_report(all_results)
                    sys.exit(1)

        log_event(log_path, {"event": "phase_done", "phase": phase_num})

    if skipping:
        print(f"Error: Resume task ID '{args.resume}' not found")
        sys.exit(1)

    completed = sum(1 for r in all_results if r["status"] == "success")
    failed = sum(1 for r in all_results if r["status"] == "failed")

    log_event(log_path, {
        "event": "run_end",
        "status": "success" if failed == 0 else "partial",
        "completed": completed,
        "failed": failed,
    })

    if not args.no_report:
        write_generate_report(all_results)

    print(f"\n{'='*60}")
    print(f"All phases completed. ({completed} tasks succeeded, {failed} failed)")
    print(f"Log: {log_path}")
    print(f"{'='*60}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
