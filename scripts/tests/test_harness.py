"""Unit tests for scripts/harness.py.

Each test builds a synthetic .harness/{slug}/ tree in a temp directory and
drives the CLI via internal function calls using types.SimpleNamespace.
Exit-code paths are exercised by asserting HarnessError.code.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import harness  # noqa: E402


def ns(**kw):
    return SimpleNamespace(**kw)


class HarnessTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.base = self.project / ".harness"
        self.base.mkdir()
        self._prev_env = {}
        for k, v in {
            "HARNESS_BASE_DIR": str(self.base),
            "HARNESS_MAX_ATTEMPTS": "1",
        }.items():
            self._prev_env[k] = os.environ.get(k)
            os.environ[k] = v

    def tearDown(self):
        for k, v in self._prev_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def write_plan(self, slug: str, phases: list[dict]):
        slug_dir = self.base / slug
        plan_dir = slug_dir / "03-plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        import yaml

        for p in phases:
            name = p.get("name", "phase").lower().replace(" ", "-")
            (plan_dir / f"phase-{p['phase']}-{name}.yaml").write_text(yaml.safe_dump(p))

    def touch(self, rel: str, content: str = "x"):
        p = self.project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p


# --------------------------- slug ---------------------------

class TestSlug(HarnessTestBase):
    def test_create(self):
        r = harness.cmd_slug(ns(request="로그인 기능 추가", suggested="add-login"))
        self.assertEqual(r["status"], "created")
        self.assertEqual(r["slug"], "add-login")
        self.assertTrue((self.base / "add-login" / "00-request.md").exists())

    def test_exists_same_request(self):
        harness.cmd_slug(ns(request="hello", suggested="demo"))
        r = harness.cmd_slug(ns(request="hello", suggested="demo"))
        self.assertEqual(r["status"], "exists")

    def test_collision_suggests_v2(self):
        harness.cmd_slug(ns(request="first", suggested="demo"))
        r = harness.cmd_slug(ns(request="different content", suggested="demo"))
        self.assertEqual(r["status"], "collision")
        self.assertEqual(r["suggested_slug"], "demo-v2")

    def test_collision_finds_next_available(self):
        harness.cmd_slug(ns(request="a", suggested="demo"))
        (self.base / "demo-v2").mkdir()
        (self.base / "demo-v3").mkdir()
        r = harness.cmd_slug(ns(request="different", suggested="demo"))
        self.assertEqual(r["suggested_slug"], "demo-v4")

    def test_canonicalizes_from_request_when_no_suggested(self):
        r = harness.cmd_slug(ns(request="Add Login!!", suggested=None))
        self.assertEqual(r["slug"], "add-login")

    def test_empty_request_rejected(self):
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_slug(ns(request="", suggested=None))
        self.assertEqual(cm.exception.code, harness.EXIT_USAGE)


# --------------------------- log ---------------------------

class TestLog(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.write_plan(
            "demo",
            [
                {
                    "phase": 1,
                    "name": "Setup",
                    "tasks": [
                        {
                            "id": "1.1",
                            "name": "install",
                            "prompt": "npm i",
                            "artifacts": {"outputs": ["package-lock.json"]},
                            "depends_on": [],
                        },
                        {
                            "id": "1.2",
                            "name": "tsconfig",
                            "prompt": "write tsconfig",
                            "artifacts": {"outputs": ["tsconfig.json"]},
                            "depends_on": ["1.1"],
                        },
                    ],
                }
            ],
        )

    def test_create_new_sidecar(self):
        r = harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="running", attempt_start=True, outputs=None, last_error=None)
        )
        self.assertEqual(r["status"], "running")
        self.assertEqual(r["attempts"], 1)
        self.assertIsNotNone(r["started"])
        self.assertIsNone(r["completed"])
        self.assertTrue(r["plan_checksum"].startswith("sha256:"))

    def test_transitions_to_terminal_stamps_completed(self):
        harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="running", attempt_start=True, outputs=None, last_error=None)
        )
        r = harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="success", attempt_start=False, outputs=None, last_error=None)
        )
        self.assertEqual(r["status"], "success")
        self.assertIsNotNone(r["completed"])

    def test_attempt_start_bumps_attempts_and_clears_error(self):
        harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="failed", attempt_start=True, outputs=None, last_error="boom")
        )
        r = harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="running", attempt_start=True, outputs=None, last_error=None)
        )
        self.assertEqual(r["attempts"], 2)
        self.assertIsNone(r["last_error"])

    def test_outputs_accepts_strings_and_objects(self):
        r = harness.cmd_log(
            ns(
                slug="demo",
                task_id="1.1",
                status="success",
                attempt_start=True,
                outputs=json.dumps(["a.txt", {"path": "b.txt", "size": 42, "exists": True}]),
                last_error=None,
            )
        )
        self.assertEqual(r["outputs"][0], {"path": "a.txt"})
        self.assertEqual(r["outputs"][1], {"path": "b.txt", "size": 42, "exists": True})

    def test_unknown_task_rejected(self):
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_log(
                ns(slug="demo", task_id="9.9", status="running", attempt_start=True, outputs=None, last_error=None)
            )
        self.assertEqual(cm.exception.code, harness.EXIT_STATE)

    def test_bad_status_rejected(self):
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_log(
                ns(slug="demo", task_id="1.1", status="bogus", attempt_start=False, outputs=None, last_error=None)
            )
        self.assertEqual(cm.exception.code, harness.EXIT_USAGE)


# --------------------------- verify ---------------------------

class TestVerify(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.write_plan(
            "demo",
            [
                {
                    "phase": 1,
                    "name": "Setup",
                    "tasks": [
                        {
                            "id": "1.1",
                            "name": "install",
                            "prompt": "x",
                            "artifacts": {"outputs": ["built.js"]},
                        }
                    ],
                }
            ],
        )
        harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="running", attempt_start=True, outputs=None, last_error=None)
        )

    def test_missing(self):
        r = harness.cmd_verify(ns(slug="demo", task_id="1.1"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["outputs"][0]["issue"], "missing")

    def test_empty(self):
        self.touch("built.js", "")
        r = harness.cmd_verify(ns(slug="demo", task_id="1.1"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["outputs"][0]["issue"], "empty")

    def test_ok(self):
        self.touch("built.js", "console.log(1)")
        r = harness.cmd_verify(ns(slug="demo", task_id="1.1"))
        self.assertTrue(r["ok"])
        self.assertIsNone(r["outputs"][0]["issue"])

    def test_updates_sidecar_outputs(self):
        self.touch("built.js", "hi")
        harness.cmd_verify(ns(slug="demo", task_id="1.1"))
        state = harness.load_task_state(self.base / "demo", "1.1")
        self.assertTrue(state["outputs"][0]["exists"])
        self.assertEqual(state["outputs"][0]["size"], 2)


# --------------------------- conflicts ---------------------------

class TestConflicts(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.write_plan(
            "demo",
            [
                {
                    "phase": 2,
                    "name": "API",
                    "tasks": [
                        {"id": "2.1", "name": "a", "prompt": "x", "artifacts": {"outputs": ["src/routes.ts", "src/a.ts"]}, "depends_on": []},
                        {"id": "2.2", "name": "b", "prompt": "x", "artifacts": {"outputs": ["src/b.ts"]}, "depends_on": []},
                        {"id": "2.3", "name": "c", "prompt": "x", "artifacts": {"outputs": ["src/routes.ts"]}, "depends_on": []},
                    ],
                }
            ],
        )

    def test_safe(self):
        r = harness.cmd_conflicts(ns(slug="demo", tasks="2.1,2.2"))
        self.assertTrue(r["safe"])
        self.assertEqual(r["conflicts"], [])

    def test_conflict(self):
        r = harness.cmd_conflicts(ns(slug="demo", tasks="2.1,2.3"))
        self.assertFalse(r["safe"])
        self.assertEqual(r["conflicts"][0]["path"], "src/routes.ts")
        self.assertEqual(r["conflicts"][0]["task_ids"], ["2.1", "2.3"])

    def test_unknown_task(self):
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_conflicts(ns(slug="demo", tasks="2.1,9.9"))
        self.assertEqual(cm.exception.code, harness.EXIT_USAGE)


# --------------------------- scan ---------------------------

class TestScan(HarnessTestBase):
    def _make_base(self, with_plan=True):
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        if with_plan:
            self.write_plan(
                "demo",
                [
                    {
                        "phase": 1,
                        "name": "setup",
                        "tasks": [
                            {"id": "1.1", "name": "a", "prompt": "x", "depends_on": []},
                            {"id": "1.2", "name": "b", "prompt": "x", "depends_on": ["1.1"]},
                        ],
                    },
                    {
                        "phase": 2,
                        "name": "api",
                        "tasks": [
                            {"id": "2.1", "name": "c", "prompt": "x", "depends_on": []},
                        ],
                    },
                ],
            )
        return self.base / "demo"

    def _log(self, tid, status, attempts=1):
        harness.cmd_log(
            ns(slug="demo", task_id=tid, status=status, attempt_start=(attempts > 0), outputs=None, last_error=None)
        )
        for _ in range(attempts - 1):
            harness.cmd_log(
                ns(slug="demo", task_id=tid, status=status, attempt_start=True, outputs=None, last_error=None)
            )

    def test_fresh_slug_blocks_on_step1(self):
        self._make_base(with_plan=False)
        r = harness.cmd_scan(ns(slug="demo"))
        self.assertEqual(r["pipeline_status"], "not_started")
        self.assertEqual(r["resume_point"]["reason"], "steps_incomplete")
        self.assertEqual(r["resume_point"]["step"], 1)

    def test_waits_for_step1_approval(self):
        d = self._make_base(with_plan=False)
        (d / "01-clarify.md").write_text("clarified")
        r = harness.cmd_scan(ns(slug="demo"))
        self.assertEqual(r["resume_point"]["reason"], "waiting_for_approval")
        self.assertEqual(r["resume_point"]["step"], 1)

    def test_step4_picks_first_not_started(self):
        d = self._make_base()
        # satisfy gates
        (d / "01-clarify.md").write_text("ok")
        harness.write_json(
            d / ".approvals" / "step-1.json",
            {"schema_version": 1, "step": 1, "approved_at": harness.now_iso(), "feedback": None},
        )
        (d / "02-context.md").write_text("ok")
        harness.write_json(
            d / ".approvals" / "step-3.json",
            {"schema_version": 1, "step": 3, "approved_at": harness.now_iso(), "feedback": None},
        )
        r = harness.cmd_scan(ns(slug="demo"))
        self.assertEqual(r["resume_point"]["task_id"], "1.1")
        self.assertEqual(r["resume_point"]["reason"], "not_started")

    def test_step4_respects_depends_on(self):
        d = self._make_base()
        for p in (1, 3):
            (d / ".approvals").mkdir(exist_ok=True)
            harness.write_json(
                d / ".approvals" / f"step-{p}.json",
                {"schema_version": 1, "step": p, "approved_at": harness.now_iso(), "feedback": None},
            )
        (d / "01-clarify.md").write_text("ok")
        (d / "02-context.md").write_text("ok")
        self._log("1.1", "success")
        r = harness.cmd_scan(ns(slug="demo"))
        self.assertEqual(r["resume_point"]["task_id"], "1.2")

    def test_failed_within_budget(self):
        d = self._make_base()
        for p in (1, 3):
            (d / ".approvals").mkdir(exist_ok=True)
            harness.write_json(
                d / ".approvals" / f"step-{p}.json",
                {"schema_version": 1, "step": p, "approved_at": harness.now_iso(), "feedback": None},
            )
        (d / "01-clarify.md").write_text("ok")
        (d / "02-context.md").write_text("ok")
        self._log("1.1", "success")
        self._log("1.2", "failed")
        os.environ["HARNESS_MAX_ATTEMPTS"] = "3"
        try:
            r = harness.cmd_scan(ns(slug="demo"))
        finally:
            os.environ["HARNESS_MAX_ATTEMPTS"] = "1"
        self.assertEqual(r["resume_point"]["task_id"], "1.2")
        self.assertEqual(r["resume_point"]["reason"], "failed_within_budget")

    def test_exceeded_budget_marks_blocked(self):
        d = self._make_base()
        for p in (1, 3):
            (d / ".approvals").mkdir(exist_ok=True)
            harness.write_json(
                d / ".approvals" / f"step-{p}.json",
                {"schema_version": 1, "step": p, "approved_at": harness.now_iso(), "feedback": None},
            )
        (d / "01-clarify.md").write_text("ok")
        (d / "02-context.md").write_text("ok")
        self._log("1.1", "failed")  # attempts=1, budget=1 → exceeded
        r = harness.cmd_scan(ns(slug="demo"))
        # 1.2 depends on 1.1 which is failed, so it is unresolved. 2.1 has no deps.
        # We expect 2.1 to be the next runnable task.
        self.assertEqual(r["resume_point"]["task_id"], "2.1")
        # Phase 1 should be blocked
        phase1 = next(p for p in r["phases"] if p["phase"] == 1)
        self.assertEqual(phase1["status"], "blocked")

    def test_pipeline_complete_when_all_done(self):
        d = self._make_base()
        for p in (1, 3):
            (d / ".approvals").mkdir(exist_ok=True)
            harness.write_json(
                d / ".approvals" / f"step-{p}.json",
                {"schema_version": 1, "step": p, "approved_at": harness.now_iso(), "feedback": None},
            )
        (d / "01-clarify.md").write_text("ok")
        (d / "02-context.md").write_text("ok")
        self._log("1.1", "success")
        self._log("1.2", "success")
        self._log("2.1", "success")
        (d / "05-evaluate.md").write_text("passed")
        r = harness.cmd_scan(ns(slug="demo"))
        self.assertEqual(r["pipeline_status"], "completed")
        self.assertEqual(r["resume_point"]["reason"], "pipeline_complete")

    def test_orphan_detection(self):
        d = self._make_base()
        # Log a task then remove it from plan
        self._log("1.1", "success")
        # Remove plan file for phase 1 to orphan task 1.1 and 1.2
        (d / "03-plan" / "phase-1-setup.yaml").unlink()
        r = harness.cmd_scan(ns(slug="demo"))
        self.assertIn("1.1", r["orphans"])

    def test_stale_detection_on_plan_change(self):
        d = self._make_base()
        # Initial log captures checksum of original task def
        self._log("1.1", "success")
        # Mutate plan — change prompt
        import yaml

        plan_file = d / "03-plan" / "phase-1-setup.yaml"
        data = yaml.safe_load(plan_file.read_text())
        data["tasks"][0]["prompt"] = "changed"
        plan_file.write_text(yaml.safe_dump(data))
        r = harness.cmd_scan(ns(slug="demo"))
        stale_ids = [s["task_id"] for s in r["stale"]]
        self.assertIn("1.1", stale_ids)


# --------------------------- next ---------------------------

class TestNext(HarnessTestBase):
    def test_next_returns_task_def(self):
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        d = self.base / "demo"
        self.write_plan(
            "demo",
            [{"phase": 1, "name": "s", "tasks": [{"id": "1.1", "name": "a", "prompt": "go", "depends_on": []}]}],
        )
        for p in (1, 3):
            harness.write_json(
                d / ".approvals" / f"step-{p}.json",
                {"schema_version": 1, "step": p, "approved_at": harness.now_iso(), "feedback": None},
            )
        (d / "01-clarify.md").write_text("ok")
        (d / "02-context.md").write_text("ok")
        r = harness.cmd_next(ns(slug="demo"))
        self.assertEqual(r["task_id"], "1.1")
        self.assertEqual(r["task"]["prompt"], "go")
        self.assertEqual(r["previous_attempts"], 0)

    def test_next_none_when_complete(self):
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        d = self.base / "demo"
        (d / "05-evaluate.md").write_text("ok")
        # still need gate approvals and prior steps
        for p in (1, 3):
            harness.write_json(
                d / ".approvals" / f"step-{p}.json",
                {"schema_version": 1, "step": p, "approved_at": harness.now_iso(), "feedback": None},
            )
        (d / "01-clarify.md").write_text("ok")
        (d / "02-context.md").write_text("ok")
        self.write_plan(
            "demo",
            [{"phase": 1, "name": "s", "tasks": [{"id": "1.1", "name": "a", "prompt": "x", "depends_on": []}]}],
        )
        harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="success", attempt_start=True, outputs=None, last_error=None)
        )
        r = harness.cmd_next(ns(slug="demo"))
        self.assertIsNone(r["task_id"])
        self.assertEqual(r["reason"], "pipeline_complete")


# --------------------------- summary ---------------------------

class TestSummary(HarnessTestBase):
    def test_writes_summary_and_counts(self):
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.write_plan(
            "demo",
            [
                {
                    "phase": 1,
                    "name": "s",
                    "tasks": [
                        {"id": "1.1", "name": "a", "prompt": "x", "depends_on": []},
                        {"id": "1.2", "name": "b", "prompt": "x", "depends_on": []},
                    ],
                }
            ],
        )
        harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="success", attempt_start=True, outputs=None, last_error=None)
        )
        harness.cmd_log(
            ns(slug="demo", task_id="1.2", status="failed", attempt_start=True, outputs=None, last_error="boom")
        )
        r = harness.cmd_summary(ns(slug="demo"))
        self.assertEqual(r["totals"]["success"], 1)
        self.assertEqual(r["totals"]["failed"], 1)
        sm = Path(r["summary_path"]).read_text()
        self.assertIn("1.1", sm)
        self.assertIn("1.2", sm)
        self.assertIn("boom", sm)


# --------------------------- integration: CLI exit codes ---------------------------

class TestCli(HarnessTestBase):
    def _run(self, *args):
        return harness.main(list(args))

    def test_slug_cli_success(self):
        import io
        buf = io.StringIO()
        _stdout, sys.stdout = sys.stdout, buf
        try:
            code = self._run("slug", "--request", "hello", "--suggested", "demo")
        finally:
            sys.stdout = _stdout
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["slug"], "demo")

    def test_scan_missing_slug_exit_3(self):
        _stderr, sys.stderr = sys.stderr, open(os.devnull, "w")
        try:
            code = self._run("scan", "no-such")
        finally:
            sys.stderr.close()
            sys.stderr = _stderr
        self.assertEqual(code, harness.EXIT_STATE)


if __name__ == "__main__":
    unittest.main()
