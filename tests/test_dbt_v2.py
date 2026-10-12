"""dbt v2 behaviour: one capability model, and readings that never over-claim."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_support import FIXTURES, PLUGIN_ROOT, load_module, run_python


capabilities = load_module("scripts/dbt_capabilities.py", "dbt_capabilities")
context_module = load_module("scripts/project_context.py", "project_context")
inventory_module = load_module("scripts/artifact_inventory.py", "artifact_inventory")
interpreter = load_module("scripts/interpret_dbt_results.py", "interpret_dbt_results")

V2 = FIXTURES / "dbt" / "v2_project"
QUIET = FIXTURES / "dbt" / "v2_no_write_json"
MIGRATING = FIXTURES / "dbt" / "v2_with_v1_artifacts"
CORE = FIXTURES / "dbt" / "engine_core"


def _context(path: Path):
    return context_module.resolve_project_context(path)


def _project(directory: str, dbt_project: str, files: dict[str, str] | None = None) -> Path:
    root = Path(directory) / "project"
    (root / "models").mkdir(parents=True)
    (root / "dbt_project.yml").write_text(dbt_project, encoding="utf-8")
    (root / "models" / "one.sql").write_text("select 1 as id\n", encoding="utf-8")
    for relative, text in (files or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


class EngineInferenceTests(unittest.TestCase):
    def test_a_version_requirement_that_admits_one_major_decides_the_engine(self) -> None:
        cases = {
            ">=2.0.0": "fusion",
            "2.0.1": "fusion",
            "<2.0.0": "core",
            "~=1.10": "core",
            ">=1.10.0,<3.0.0": None,
            ">=1.8": None,
            "<=2.0.0": None,
            "not a version": None,
        }
        for requirement, expected in cases.items():
            with self.subTest(requirement=requirement):
                self.assertEqual(context_module._required_engine(requirement), expected)
        self.assertEqual(context_module._required_engine([">=1.7.0", "<2.0.0"]), "core")

    def test_v2_distribution_pins_identify_v2(self) -> None:
        for pin in ("dbt-oss==2.0.1", "dbt-fusion==2.0.0", "dbt==2.0.1"):
            with self.subTest(pin=pin), tempfile.TemporaryDirectory() as directory:
                root = _project(
                    directory,
                    "name: p\nversion: '1'\nconfig-version: 2\n",
                    {"requirements.txt": pin + "\n"},
                )
                self.assertEqual(_context(root).engine, "fusion")

    def test_a_pin_that_contradicts_the_requirement_is_not_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _project(
                directory,
                "name: p\nversion: '1'\nconfig-version: 2\nrequire-dbt-version: '>=2.0.0'\n",
                {"requirements.txt": "dbt-core==1.10.4\n"},
            )
            context = _context(root)
        self.assertEqual(context.engine, "unknown")
        self.assertIn("contradicts", context.engine_evidence)

    def test_declared_engine_accepts_major_version_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _project(
                directory,
                "name: p\nversion: '1'\nconfig-version: 2\n",
                {".ae/project.yml": "engine: v2\n"},
            )
            self.assertEqual(_context(root).engine, "fusion")

    def test_artifacts_are_the_weakest_evidence(self) -> None:
        migrating = _context(MIGRATING)
        self.assertEqual(migrating.engine, "fusion")
        self.assertIn("require-dbt-version", migrating.engine_evidence)
        note = capabilities.assess(migrating, environ={})["engine"].note
        self.assertIn("written by dbt v1", note)

        clean = _context(FIXTURES / "dbt" / "clean_project")
        self.assertEqual(clean.engine, "core")
        self.assertIn("manifest.json was written by dbt v1", clean.engine_evidence)

    def test_the_engine_is_read_from_the_head_of_an_artifact_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            head = '{"metadata": {"dbt_version": "2.0.1", "generated_at": "2026-10-05T00:00:00Z"}, "nodes": {'
            # Truncated, so a reader that parsed the whole document would fail.
            (target / "manifest.json").write_text(head + '"x": ' * 10, encoding="utf-8")
            self.assertEqual(context_module.artifact_engine(target), ("fusion", "manifest.json"))

    def test_conventions_and_project_context_agree_on_the_engine(self) -> None:
        conventions = load_module("scripts/infer_conventions.py", "infer_conventions")
        for fixture in (V2, MIGRATING, CORE, FIXTURES / "dbt" / "engine_unknown"):
            with self.subTest(fixture=fixture.name):
                context = _context(fixture)
                facts = conventions.infer_conventions(fixture)
                self.assertEqual(facts["project"]["engine"], context.engine)


class CapabilityTests(unittest.TestCase):
    def test_a_v2_project_reports_what_it_configures_and_what_needs_proof(self) -> None:
        found = capabilities.assess(_context(V2), environ={})
        self.assertEqual(found["engine"].value, "fusion")
        self.assertEqual(found["information_schema"].state, "available")
        self.assertEqual(found["information_schema"].value["declared_version"], 1)
        self.assertEqual(found["checks"].value["count"], 1)
        self.assertEqual(found["static_analysis"].value, "strict")
        self.assertIn("dbt login", found["static_analysis"].note)
        self.assertIn("downstream", found["static_analysis"].note)
        self.assertTrue(found["managed_state"].value)
        self.assertIn("reused", found["managed_state"].note)

    def test_column_lineage_is_never_available_without_dbt_output(self) -> None:
        found = capabilities.assess(_context(V2), environ={})["column_lineage"]
        self.assertEqual(found.state, "requires_evidence")
        self.assertIn("dbt show --info column_lineage", found.note)
        self.assertIn("contents not read", found.evidence)

    def test_v2_only_features_are_not_applicable_on_v1(self) -> None:
        found = capabilities.assess(_context(CORE), environ={})
        for name in ("information_schema", "checks", "static_analysis", "column_lineage"):
            with self.subTest(name=name):
                self.assertEqual(found[name].state, "not_applicable")
        self.assertEqual(found["json_artifacts"].value, True)
        self.assertEqual(found["freshness"].state, "available")

    def test_json_artifact_setting_follows_dbt_precedence(self) -> None:
        context = _context(QUIET)
        written = capabilities.json_artifacts_written
        self.assertEqual((written(context, environ={}).value, written(context, environ={}).basis), (False, "declared"))
        self.assertEqual(written(context, environ={"DBT_ENGINE_WRITE_JSON": "true"}).basis, "environment")
        self.assertTrue(written(context, environ={"DBT_ENGINE_WRITE_JSON": "true"}).value)
        assigned = written(context, command="DBT_WRITE_JSON=1 dbt run", environ={"DBT_WRITE_JSON": "0"})
        self.assertEqual((assigned.value, assigned.basis), (True, "command"))
        flagged = written(context, command="dbt run --write-json", environ={"DBT_WRITE_JSON": "0"})
        self.assertEqual((flagged.value, flagged.basis), (True, "command"))
        self.assertFalse(written(None, command="dbt build --no-write-json", environ={}).value)
        self.assertEqual(written(None, environ={}).basis, "default")

    def test_deprecated_strict_spellings_are_read_as_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _project(
                directory,
                "name: p\nversion: '1'\nconfig-version: 2\nrequire-dbt-version: '>=2.0.0'\n"
                "models:\n  p:\n    +static_analysis: unsafe\n",
            )
            found = capabilities.assess(_context(root), environ={})["static_analysis"]
        self.assertEqual(found.value, "strict")
        self.assertIn("deprecated", found.note)

    def test_command_and_environment_override_project_static_analysis(self) -> None:
        context = _context(V2)
        command = capabilities.assess(context, command="dbt compile --static-analysis=baseline", environ={})
        self.assertEqual((command["static_analysis"].value, command["static_analysis"].basis), ("baseline", "command"))
        environment = capabilities.assess(context, environ={"DBT_STATIC_ANALYSIS": "off"})
        self.assertEqual(environment["static_analysis"].value, "off")

    def test_cli_reports_without_running_dbt(self) -> None:
        completed = run_python("scripts/dbt_capabilities.py", str(V2))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["engine"], "fusion")
        self.assertIn("dbt was not run", payload["note"])


class ReusedNodeTests(unittest.TestCase):
    def test_reused_and_cloned_nodes_are_not_evidence_for_this_change(self) -> None:
        result = interpreter.interpret_results(V2 / "target" / "run_results.json")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(
            sorted(item["unique_id"] for item in result["not_executed"]),
            ["model.analytics_v2.fct_orders", "test.analytics_v2.unique_stg_orders_order_id"],
        )

    def test_reading_status_alone_counts_a_clone_as_a_fresh_build(self) -> None:
        with mock.patch.object(interpreter, "NOT_EXECUTED_MESSAGE", re.compile(r"(?!)")):
            result = interpreter.interpret_results(V2 / "target" / "run_results.json")
        self.assertNotIn(
            "model.analytics_v2.fct_orders",
            [item["unique_id"] for item in result.get("not_executed", [])],
        )

    def test_a_run_where_everything_was_reused_did_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_results.json"
            path.write_text(
                json.dumps(
                    {
                        "metadata": {"dbt_version": "2.0.1", "generated_at": "2026-10-05T12:00:00Z"},
                        "results": [
                            {"unique_id": "test.p.a", "status": "reused"},
                            {"unique_id": "model.p.b", "status": "success", "message": "Within lag tolerance"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = interpreter.interpret_results(path)
        self.assertEqual(result["status"], "reused")
        self.assertEqual(result["not_executed_count"], 2)


class SuppressedArtifactTests(unittest.TestCase):
    def test_no_write_json_never_reads_the_previous_runs_artifact(self) -> None:
        completed = run_python(
            "scripts/interpret_dbt_results.py",
            "--project-dir",
            str(V2),
            "--expect-operation",
            "test",
            "--command",
            "dbt build --select stg_orders --no-write-json",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "not_written")
        self.assertFalse(result["verified"])
        self.assertEqual(result["failures"], [])

    def test_a_project_that_disables_json_reports_not_written(self) -> None:
        completed = run_python(
            "scripts/interpret_dbt_results.py",
            "--project-dir",
            str(QUIET),
            "--expect-operation",
            "model_validation",
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "not_written")
        self.assertIn("flags.write_json", result["json_artifacts"]["evidence"])

    def test_log_failures_still_surface_when_no_artifact_was_written(self) -> None:
        result = interpreter.interpret_results(
            None,
            log_text="Database Error in model one: relation does not exist",
            json_artifacts=capabilities.json_artifacts_written(None, command="dbt run --no-write-json", environ={}),
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failures"][0]["category"], "database")

    def test_inventory_marks_artifacts_it_cannot_trust(self) -> None:
        inventory = inventory_module.inventory_artifacts(_context(QUIET)).as_dict()
        self.assertEqual(inventory["current"]["run_results"]["trust"], "unproven")
        self.assertEqual(inventory["current"]["manifest"]["trust"], "not-written")
        self.assertEqual(inventory["json_artifacts"]["state"], "unavailable")

        default = inventory_module.inventory_artifacts(_context(FIXTURES / "dbt" / "clean_project")).as_dict()
        self.assertNotIn("json_artifacts", default)
        self.assertEqual(default["current"]["run_results"]["trust"], "missing")


class FreshnessArtifactTests(unittest.TestCase):
    def test_freshness_json_is_proven_current_but_not_interpreted(self) -> None:
        result = interpreter.interpret_results(
            None,
            freshness_json=V2 / "target" / "freshness.json",
            expected_operation="freshness",
            invocation_id="v2-invocation-b",
        )
        self.assertEqual(result["status"], "uninterpreted")
        self.assertTrue(result["artifact_verified"])
        self.assertEqual(result["freshness"]["result_count"], 2)
        self.assertIn("not interpreted", result["freshness"]["note"])

    def test_freshness_json_from_another_invocation_is_not_verified(self) -> None:
        result = interpreter.interpret_results(
            None,
            freshness_json=V2 / "target" / "freshness.json",
            expected_operation="freshness",
            invocation_id="v2-invocation-a",
        )
        self.assertFalse(result["artifact_verified"])

    def test_the_project_resolver_hands_freshness_its_own_artifact(self) -> None:
        inventory = inventory_module.inventory_artifacts(_context(V2))
        paths = inventory.resolve_operation_paths("freshness")
        self.assertEqual(Path(paths["freshness"]).name, "freshness.json")
        self.assertIsNone(paths["run_results"])
        self.assertIsNone(inventory.resolve_operation_paths("test")["freshness"])


class PlannerTests(unittest.TestCase):
    def test_a_project_without_json_artifacts_gets_steps_that_write_them(self) -> None:
        planner = load_module("scripts/plan_dbt_validation.py", "plan_dbt_validation")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            shutil.copytree(QUIET, root)
            plan = planner.plan_validation(root, models=["one"], target="dev", intent="build")
            default_root = Path(directory) / "default"
            shutil.copytree(FIXTURES / "dbt" / "clean_project", default_root)
            default = planner.plan_validation(
                default_root, models=["fct_orders"], target="dev", intent="build"
            )
        warehouse = [step["command"] for step in plan["commands"] if step["requires_approval"]]
        self.assertTrue(warehouse)
        self.assertTrue(all("--write-json" in command for command in warehouse))
        self.assertTrue(any("JSON artifacts are turned off" in item for item in plan["warnings"]))
        self.assertFalse(any("--write-json" in step["command"] for step in default["commands"]))


class PlannedCommandCompatibilityTests(unittest.TestCase):
    # Flags dbt v2 deprecates; a plan that used them would fail or warn there.
    DEPRECATED = re.compile(r"(?:^|\s)(?:--models|-m|--partial-parse|--no-partial-parse)(?:\s|=|$)")

    def test_planned_commands_run_unchanged_on_both_engines(self) -> None:
        planner = load_module("scripts/plan_dbt_validation.py", "plan_dbt_validation")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            shutil.copytree(FIXTURES / "dbt" / "clean_project", root)
            plans = [
                planner.plan_validation(root, models=["fct_orders"], target="dev", intent=intent)
                for intent in ("static", "test", "run", "build")
            ]
        commands = [step["command"] for plan in plans for step in plan["commands"]]
        self.assertTrue(commands)
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(self.DEPRECATED.search(command))
                self.assertTrue(command.startswith("dbt "))


class V1RegressionTests(unittest.TestCase):
    def test_v1_projects_keep_their_existing_readings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            shutil.copytree(FIXTURES / "dbt" / "clean_project", root)
            found = capabilities.assess(_context(root), environ={})
            self.assertEqual(found["engine"].value, "core")
            self.assertEqual(found["json_artifacts"].value, True)
            inventory = inventory_module.inventory_artifacts(_context(root))
            self.assertEqual(inventory.current["manifest"].trust, "stale")


if __name__ == "__main__":
    unittest.main()
