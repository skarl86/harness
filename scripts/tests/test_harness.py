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
        # completed should be reset on attempt-start (prior failure had stamped it)
        self.assertIsNone(r["completed"])

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


# --------------------------- approve ---------------------------

class TestApprove(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.slug_dir = self.base / "demo"

    def test_approve_step_1(self):
        (self.slug_dir / "01-clarify.md").write_text("clarified")
        r = harness.cmd_approve(ns(slug="demo", step=1, feedback="ok", force=False))
        self.assertEqual(r["step"], 1)
        self.assertTrue(r["artifact_checksum"].startswith("sha256:"))
        self.assertEqual(r["feedback"], "ok")

    def test_approve_step_3(self):
        self.write_plan(
            "demo",
            [{"phase": 1, "name": "s", "tasks": [{"id": "1.1", "name": "a", "prompt": "x", "depends_on": []}]}],
        )
        r = harness.cmd_approve(ns(slug="demo", step=3, feedback=None, force=False))
        self.assertEqual(r["step"], 3)
        self.assertIsNone(r["feedback"])
        self.assertTrue(r["artifact_checksum"].startswith("sha256:"))

    def test_missing_artifact_rejects(self):
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_approve(ns(slug="demo", step=1, feedback=None, force=False))
        self.assertEqual(cm.exception.code, harness.EXIT_STATE)

    def test_invalid_step_rejected(self):
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_approve(ns(slug="demo", step=2, feedback=None, force=False))
        self.assertEqual(cm.exception.code, harness.EXIT_USAGE)

    def test_double_approve_without_force_rejects(self):
        (self.slug_dir / "01-clarify.md").write_text("clarified")
        harness.cmd_approve(ns(slug="demo", step=1, feedback=None, force=False))
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_approve(ns(slug="demo", step=1, feedback=None, force=False))
        self.assertEqual(cm.exception.code, harness.EXIT_STATE)

    def test_force_overwrites(self):
        (self.slug_dir / "01-clarify.md").write_text("clarified")
        first = harness.cmd_approve(ns(slug="demo", step=1, feedback="a", force=False))
        second = harness.cmd_approve(ns(slug="demo", step=1, feedback="b", force=True))
        self.assertEqual(first["feedback"], "a")
        self.assertEqual(second["feedback"], "b")

    def test_artifact_checksum_matches_content(self):
        (self.slug_dir / "01-clarify.md").write_text("hello")
        r = harness.cmd_approve(ns(slug="demo", step=1, feedback=None, force=False))
        expected = harness.sha256_str("hello")
        self.assertEqual(r["artifact_checksum"], expected)


# --------------------------- archive-plan ---------------------------

class TestArchivePlan(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.slug_dir = self.base / "demo"

    def test_archive_first_time(self):
        self.write_plan(
            "demo",
            [{"phase": 1, "name": "s", "tasks": [{"id": "1.1", "name": "a", "prompt": "x", "depends_on": []}]}],
        )
        r = harness.cmd_archive_plan(ns(slug="demo"))
        self.assertEqual(r["archived_to"], "03-plan.v1/")
        self.assertEqual(r["new_version"], 2)
        self.assertTrue((self.slug_dir / "03-plan.v1").is_dir())
        self.assertTrue((self.slug_dir / "03-plan").is_dir())
        self.assertFalse(any((self.slug_dir / "03-plan").glob("phase-*.yaml")))

    def test_archive_increments_version(self):
        self.write_plan(
            "demo",
            [{"phase": 1, "name": "s", "tasks": [{"id": "1.1", "name": "a", "prompt": "x", "depends_on": []}]}],
        )
        harness.cmd_archive_plan(ns(slug="demo"))
        # Now write a new plan and archive again
        self.write_plan(
            "demo",
            [{"phase": 1, "name": "s", "tasks": [{"id": "1.1", "name": "a", "prompt": "y", "depends_on": []}]}],
        )
        r = harness.cmd_archive_plan(ns(slug="demo"))
        self.assertEqual(r["archived_to"], "03-plan.v2/")
        self.assertEqual(r["new_version"], 3)

    def test_no_plan_to_archive(self):
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_archive_plan(ns(slug="demo"))
        self.assertEqual(cm.exception.code, harness.EXIT_STATE)

    def test_empty_plan_dir_rejected(self):
        (self.slug_dir / "03-plan").mkdir()
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_archive_plan(ns(slug="demo"))
        self.assertEqual(cm.exception.code, harness.EXIT_STATE)

    def test_sidecars_survive_archive(self):
        # sidecars under 04-generate/ are not touched
        self.write_plan(
            "demo",
            [{"phase": 1, "name": "s", "tasks": [{"id": "1.1", "name": "a", "prompt": "x", "depends_on": []}]}],
        )
        harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="success", attempt_start=True, outputs=None, last_error=None)
        )
        harness.cmd_archive_plan(ns(slug="demo"))
        self.assertTrue((self.slug_dir / "04-generate" / "task-1.1.json").exists())


# --------------------------- classify-failure ---------------------------

class TestClassifyFailure(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.write_plan(
            "demo",
            [
                {
                    "phase": 1,
                    "name": "s",
                    "tasks": [
                        {
                            "id": "1.1",
                            "name": "a",
                            "prompt": "x",
                            "artifacts": {"outputs": ["out.ts", "side.ts"]},
                            "depends_on": [],
                        },
                        {
                            "id": "1.2",
                            "name": "b",
                            "prompt": "x",
                            "artifacts": {"outputs": []},
                            "depends_on": [],
                        },
                    ],
                }
            ],
        )
        os.environ["HARNESS_MAX_ATTEMPTS"] = "2"

    def _fail(self, tid, error="", attempts=1):
        harness.cmd_log(
            ns(slug="demo", task_id=tid, status="running", attempt_start=True, outputs=None, last_error=None)
        )
        for _ in range(attempts - 1):
            harness.cmd_log(
                ns(slug="demo", task_id=tid, status="running", attempt_start=True, outputs=None, last_error=None)
            )
        harness.cmd_log(
            ns(slug="demo", task_id=tid, status="failed", attempt_start=False, outputs=None, last_error=error)
        )

    def test_all_outputs_missing_no_error_is_class_c(self):
        self._fail("1.1")  # no error
        r = harness.cmd_classify_failure(ns(slug="demo", task_id="1.1"))
        self.assertEqual(r["suggested_class"], "C")
        self.assertEqual(r["confidence"], "high")

    def test_all_outputs_missing_with_transient_is_class_a(self):
        self._fail("1.1", error="ImportError: no module named foo")
        r = harness.cmd_classify_failure(ns(slug="demo", task_id="1.1"))
        self.assertEqual(r["suggested_class"], "A")
        self.assertEqual(r["confidence"], "medium")

    def test_some_outputs_missing_is_class_a(self):
        self._fail("1.1")
        self.touch("out.ts", "x")
        # side.ts still missing
        r = harness.cmd_classify_failure(ns(slug="demo", task_id="1.1"))
        self.assertEqual(r["suggested_class"], "A")
        self.assertEqual(r["confidence"], "high")

    def test_empty_output_counts_as_issue(self):
        self._fail("1.1")
        self.touch("out.ts", "x")
        self.touch("side.ts", "")
        r = harness.cmd_classify_failure(ns(slug="demo", task_id="1.1"))
        self.assertEqual(r["suggested_class"], "A")

    def test_transient_error_pattern_is_class_a(self):
        self._fail("1.1", error="TypeError at line 42")
        # all outputs exist
        self.touch("out.ts", "x")
        self.touch("side.ts", "y")
        r = harness.cmd_classify_failure(ns(slug="demo", task_id="1.1"))
        self.assertEqual(r["suggested_class"], "A")

    def test_non_transient_error_is_class_b(self):
        self._fail("1.1", error="the design is fundamentally wrong")
        self.touch("out.ts", "x")
        self.touch("side.ts", "y")
        r = harness.cmd_classify_failure(ns(slug="demo", task_id="1.1"))
        self.assertEqual(r["suggested_class"], "B")

    def test_exceeded_budget_upgrades_a_to_b(self):
        self._fail("1.1", error="TypeError", attempts=2)  # attempts=2, budget=2
        self.touch("out.ts", "x")
        self.touch("side.ts", "y")
        r = harness.cmd_classify_failure(ns(slug="demo", task_id="1.1"))
        self.assertEqual(r["suggested_class"], "B")
        self.assertEqual(r["confidence"], "high")

    def test_no_declared_outputs_is_class_c_low(self):
        self._fail("1.2")
        r = harness.cmd_classify_failure(ns(slug="demo", task_id="1.2"))
        self.assertEqual(r["suggested_class"], "C")
        self.assertEqual(r["confidence"], "low")

    def test_non_failed_status_rejected(self):
        harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="success", attempt_start=True, outputs=None, last_error=None)
        )
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_classify_failure(ns(slug="demo", task_id="1.1"))
        self.assertEqual(cm.exception.code, harness.EXIT_STATE)


# --------------------------- stale ---------------------------

class TestStale(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.slug_dir = self.base / "demo"

    def test_no_stale_initially(self):
        self.write_plan(
            "demo",
            [{"phase": 1, "name": "s", "tasks": [{"id": "1.1", "name": "a", "prompt": "x", "depends_on": []}]}],
        )
        harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="success", attempt_start=True, outputs=None, last_error=None)
        )
        r = harness.cmd_stale(ns(slug="demo"))
        self.assertEqual(r["stale_tasks"], [])
        self.assertEqual(r["stale_approvals"], [])

    def test_stale_task_after_plan_edit(self):
        self.write_plan(
            "demo",
            [{"phase": 1, "name": "s", "tasks": [{"id": "1.1", "name": "a", "prompt": "x", "depends_on": []}]}],
        )
        harness.cmd_log(
            ns(slug="demo", task_id="1.1", status="success", attempt_start=True, outputs=None, last_error=None)
        )
        # Mutate plan
        import yaml
        plan_file = self.slug_dir / "03-plan" / "phase-1-s.yaml"
        data = yaml.safe_load(plan_file.read_text())
        data["tasks"][0]["prompt"] = "changed"
        plan_file.write_text(yaml.safe_dump(data))
        r = harness.cmd_stale(ns(slug="demo"))
        self.assertEqual(len(r["stale_tasks"]), 1)
        self.assertEqual(r["stale_tasks"][0]["task_id"], "1.1")

    def test_stale_approval_after_artifact_edit(self):
        (self.slug_dir / "01-clarify.md").write_text("original")
        harness.cmd_approve(ns(slug="demo", step=1, feedback=None, force=False))
        (self.slug_dir / "01-clarify.md").write_text("edited later")
        r = harness.cmd_stale(ns(slug="demo"))
        self.assertEqual(len(r["stale_approvals"]), 1)
        self.assertEqual(r["stale_approvals"][0]["step"], 1)


# --------------------------- cleanup ---------------------------

class TestCleanup(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.slug_dir = self.base / "demo"

    def test_backup_default(self):
        r = harness.cmd_cleanup(ns(slug="demo", purge=False))
        self.assertEqual(r["action"], "backed_up")
        self.assertIsNotNone(r["backup_path"])
        self.assertFalse(self.slug_dir.exists())
        # backup dir should exist
        matches = list(self.base.glob("demo.backup-*"))
        self.assertEqual(len(matches), 1)

    def test_purge(self):
        r = harness.cmd_cleanup(ns(slug="demo", purge=True))
        self.assertEqual(r["action"], "purged")
        self.assertIsNone(r["backup_path"])
        self.assertFalse(self.slug_dir.exists())

    def test_missing_slug_rejected(self):
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_cleanup(ns(slug="nope", purge=False))
        self.assertEqual(cm.exception.code, harness.EXIT_STATE)


# --------------------------- list ---------------------------

class TestList(HarnessTestBase):
    def test_empty(self):
        # base exists but no slugs
        r = harness.cmd_list(ns())
        self.assertEqual(r["slugs"], [])

    def test_skips_backups(self):
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        (self.base / "demo.backup-2026").mkdir()
        r = harness.cmd_list(ns())
        self.assertEqual([s["slug"] for s in r["slugs"]], ["demo"])

    def test_reports_pipeline_status(self):
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        r = harness.cmd_list(ns())
        self.assertEqual(len(r["slugs"]), 1)
        self.assertEqual(r["slugs"][0]["slug"], "demo")
        self.assertEqual(r["slugs"][0]["pipeline_status"], "not_started")
        self.assertIsNotNone(r["slugs"][0]["created_at"])


# --------------------------- config + max_attempts resolution ---------------------------

class TestConfig(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.slug_dir = self.base / "demo"

    def test_view_when_no_config(self):
        r = harness.cmd_config(ns(slug="demo", max_attempts=None))
        self.assertEqual(r, {"schema_version": 1})
        self.assertFalse(harness.config_path(self.slug_dir).exists())

    def test_set_max_attempts_writes_file(self):
        r = harness.cmd_config(ns(slug="demo", max_attempts=3))
        self.assertEqual(r["max_attempts"], 3)
        self.assertTrue(harness.config_path(self.slug_dir).exists())
        written = json.loads(harness.config_path(self.slug_dir).read_text())
        self.assertEqual(written, {"schema_version": 1, "max_attempts": 3})

    def test_negative_max_attempts_rejected(self):
        with self.assertRaises(harness.HarnessError) as cm:
            harness.cmd_config(ns(slug="demo", max_attempts=-1))
        self.assertEqual(cm.exception.code, harness.EXIT_USAGE)

    def test_update_preserves_other_fields(self):
        harness.cmd_config(ns(slug="demo", max_attempts=5))
        # View again with no args — should return what was set
        r = harness.cmd_config(ns(slug="demo", max_attempts=None))
        self.assertEqual(r["max_attempts"], 5)


class TestMaxAttemptsResolution(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.slug_dir = self.base / "demo"
        # Clear env to start
        self._prev_env.setdefault("HARNESS_MAX_ATTEMPTS", os.environ.get("HARNESS_MAX_ATTEMPTS"))
        os.environ.pop("HARNESS_MAX_ATTEMPTS", None)

    def test_default_when_no_env_no_config(self):
        self.assertEqual(harness.get_max_attempts(self.slug_dir), 1)

    def test_config_overrides_default(self):
        harness.cmd_config(ns(slug="demo", max_attempts=4))
        self.assertEqual(harness.get_max_attempts(self.slug_dir), 4)

    def test_env_overrides_config(self):
        harness.cmd_config(ns(slug="demo", max_attempts=4))
        os.environ["HARNESS_MAX_ATTEMPTS"] = "7"
        try:
            self.assertEqual(harness.get_max_attempts(self.slug_dir), 7)
        finally:
            os.environ.pop("HARNESS_MAX_ATTEMPTS", None)

    def test_env_without_slug_still_works(self):
        os.environ["HARNESS_MAX_ATTEMPTS"] = "9"
        try:
            self.assertEqual(harness.get_max_attempts(), 9)
        finally:
            os.environ.pop("HARNESS_MAX_ATTEMPTS", None)


# --------------------------- verify --syntax ---------------------------

class TestVerifySyntax(HarnessTestBase):
    def setUp(self):
        super().setUp()
        harness.cmd_slug(ns(request="demo", suggested="demo"))
        self.write_plan(
            "demo",
            [{
                "phase": 1, "name": "s",
                "tasks": [
                    {"id": "1.1", "name": "py", "prompt": "x",
                     "artifacts": {"outputs": ["a.py"]}, "depends_on": []},
                    {"id": "1.2", "name": "json", "prompt": "x",
                     "artifacts": {"outputs": ["a.json"]}, "depends_on": []},
                    {"id": "1.3", "name": "yaml", "prompt": "x",
                     "artifacts": {"outputs": ["a.yaml"]}, "depends_on": []},
                    {"id": "1.4", "name": "unknown", "prompt": "x",
                     "artifacts": {"outputs": ["a.ts"]}, "depends_on": []},
                ],
            }],
        )
        for tid in ("1.1", "1.2", "1.3", "1.4"):
            harness.cmd_log(
                ns(slug="demo", task_id=tid, status="running", attempt_start=True,
                   outputs=None, last_error=None)
            )

    def test_python_syntax_pass(self):
        self.touch("a.py", "x = 1\n")
        r = harness.cmd_verify(ns(slug="demo", task_id="1.1", syntax=True))
        self.assertTrue(r["ok"])

    def test_python_syntax_fail(self):
        self.touch("a.py", "def broken(:\n    pass\n")
        r = harness.cmd_verify(ns(slug="demo", task_id="1.1", syntax=True))
        self.assertFalse(r["ok"])
        self.assertIn("syntax_error", r["outputs"][0]["issue"])

    def test_python_structural_only_skips_syntax(self):
        self.touch("a.py", "def broken(:\n    pass\n")
        r = harness.cmd_verify(ns(slug="demo", task_id="1.1", syntax=False))
        self.assertTrue(r["ok"])  # structural passes, syntax not checked

    def test_json_syntax_pass(self):
        self.touch("a.json", '{"ok": 1}')
        r = harness.cmd_verify(ns(slug="demo", task_id="1.2", syntax=True))
        self.assertTrue(r["ok"])

    def test_json_syntax_fail(self):
        self.touch("a.json", '{not valid json')
        r = harness.cmd_verify(ns(slug="demo", task_id="1.2", syntax=True))
        self.assertFalse(r["ok"])
        self.assertIn("syntax_error: JSONDecodeError", r["outputs"][0]["issue"])

    def test_yaml_syntax_pass(self):
        self.touch("a.yaml", "a: 1\nb: 2\n")
        r = harness.cmd_verify(ns(slug="demo", task_id="1.3", syntax=True))
        self.assertTrue(r["ok"])

    def test_yaml_syntax_fail(self):
        self.touch("a.yaml", "a: 1\nb: : : bad\n")
        r = harness.cmd_verify(ns(slug="demo", task_id="1.3", syntax=True))
        self.assertFalse(r["ok"])

    def test_unknown_extension_skips_syntax(self):
        # .ts has no registered check -> structural pass applies
        self.touch("a.ts", "const x: number = 1")
        r = harness.cmd_verify(ns(slug="demo", task_id="1.4", syntax=True))
        self.assertTrue(r["ok"])


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
