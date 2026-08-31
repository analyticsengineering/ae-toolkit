from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_support import FIXTURES, load_module


planner = load_module("scripts/plan_dbt_validation.py", "plan_dbt_validation")
interpreter = load_module("scripts/interpret_dbt_results.py", "interpret_dbt_results")


class ValidationPlannerTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def project(self, directory: str) -> Path:
        root = Path(directory) / "project"
        shutil.copytree(FIXTURES / "dbt" / "clean_project", root)
        self.git(root, "init")
        self.git(root, "add", ".")
        self.git(
            root,
            "-c",
            "user.name=Toolkit Tests",
            "-c",
            "user.email=toolkit-tests@example.invalid",
            "commit",
            "-m",
            "fixture",
        )
        return root

    def test_changed_model_produces_bounded_static_and_build_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            model = root / "models" / "marts" / "fct_orders.sql"
            model.write_text(model.read_text(encoding="utf-8") + "\n-- changed\n", encoding="utf-8")
            plan = planner.plan_validation(root, target="dev", intent="build")

        self.assertEqual(plan["scope"]["models"], ["fct_orders"])
        self.assertEqual(plan["scope"]["selectors"], ["fct_orders"])
        self.assertIsNone(plan["blocked_reason"])
        self.assertEqual([step["command"].split()[1] for step in plan["commands"]], ["parse", "ls", "build"])
        self.assertFalse(plan["commands"][0]["requires_approval"])
        self.assertTrue(plan["commands"][-1]["requires_approval"])
        self.assertIn("--target dev", plan["commands"][-1]["command"])
        self.assertNotIn("--full-refresh", plan["commands"][-1]["command"])

    def test_yaml_comments_descriptions_and_tests_do_not_expand_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            schema = root / "models" / "schema.yml"
            schema.write_text(schema.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
            comments = planner.plan_validation(root, target="development", intent="test")

            original = subprocess.run(
                ["git", "-C", str(root), "show", "HEAD:models/schema.yml"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout
            schema.write_text(
                original.replace("description: Order fact table.", "description: Canonical order fact."),
                encoding="utf-8",
            )
            descriptions = planner.plan_validation(root, target="development", intent="test")
            schema.write_text(
                original.replace("          - not_null", "          - not_null\n          - accepted_values", 1),
                encoding="utf-8",
            )
            tests = planner.plan_validation(root, target="development", intent="test")

        for plan, kind in (
            (comments, "formatting_or_comments_only"),
            (descriptions, "description_only"),
            (tests, "test_only"),
        ):
            with self.subTest(kind=kind):
                self.assertFalse(plan["scope"]["contract_change"])
                self.assertEqual(plan["scope"]["yaml_change_kinds"]["models/schema.yml"], kind)
                self.assertTrue(plan["scope"]["models"])
                self.assertTrue(all(not selector.endswith("+") for selector in plan["scope"]["selectors"]))

    def test_yaml_change_kind_deterministically_limits_requested_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            schema = root / "models" / "schema.yml"
            original = schema.read_text(encoding="utf-8")

            schema.write_text(original + "\n# changed\n", encoding="utf-8")
            comments = planner.plan_validation(root, target="development", intent="build")

            schema.write_text(
                original.replace("          - not_null", "          - not_null\n          - accepted_values", 1),
                encoding="utf-8",
            )
            tests = planner.plan_validation(root, target="development", intent="build")
            overridden = planner.plan_validation(
                root,
                target="development",
                intent="build",
                allow_broader_intent=True,
            )

        self.assertEqual(comments["recommended_intent"], "static")
        self.assertEqual(comments["intent"], "static")
        self.assertTrue(comments["broader_intent_requires_override"])
        self.assertEqual([step["command"].split()[1] for step in comments["commands"]], ["parse", "ls"])

        self.assertEqual(tests["recommended_intent"], "test")
        self.assertEqual(tests["intent"], "test")
        self.assertTrue(tests["broader_intent_requires_override"])
        self.assertEqual([step["command"].split()[1] for step in tests["commands"]], ["parse", "ls", "test"])

        self.assertEqual(overridden["recommended_intent"], "test")
        self.assertEqual(overridden["intent"], "build")
        self.assertFalse(overridden["broader_intent_requires_override"])
        self.assertEqual(overridden["commands"][-1]["command"].split()[1], "build")

    def test_explicit_model_does_not_turn_a_description_edit_into_a_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            schema = root / "models" / "schema.yml"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace(
                    "description: Order fact table.",
                    "description: Canonical order fact.",
                ),
                encoding="utf-8",
            )
            minimal = planner.plan_validation(
                root,
                models=["fct_orders"],
                target="development",
                intent="build",
            )
            broader = planner.plan_validation(
                root,
                models=["fct_orders"],
                target="development",
                intent="build",
                allow_broader_intent=True,
            )

        self.assertEqual(minimal["intent"], "static")
        self.assertTrue(minimal["broader_intent_requires_override"])
        self.assertEqual([step["command"].split()[1] for step in minimal["commands"]], ["parse", "ls"])
        self.assertEqual(broader["intent"], "build")

    def test_changed_singular_test_selects_the_test_and_reads_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            tests = root / "tests"
            tests.mkdir()
            (tests / "assert_orders_have_customers.sql").write_text(
                "select * from {{ ref('fct_orders') }} where customer_id is null\n",
                encoding="utf-8",
            )
            plan = planner.plan_validation(root, target="development", intent="build")

        self.assertEqual(plan["recommended_intent"], "test")
        self.assertEqual(plan["scope"]["singular_tests"], ["assert_orders_have_customers"])
        self.assertIn("fct_orders", plan["scope"]["models"])
        self.assertEqual(plan["scope"]["selectors"], ["assert_orders_have_customers"])
        self.assertIn(
            "--select assert_orders_have_customers",
            plan["commands"][-1]["command"],
        )
        self.assertEqual(plan["commands"][-1]["command"].split()[1], "test")

    def test_source_freshness_change_gets_a_source_specific_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            schema = root / "models" / "schema.yml"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace(
                    "      - name: orders\n",
                    "      - name: orders\n"
                    "        config:\n"
                    "          loaded_at_field: _loaded_at\n"
                    "          freshness:\n"
                    "            warn_after:\n"
                    "              count: 12\n"
                    "              period: hour\n",
                ),
                encoding="utf-8",
            )
            plan = planner.plan_validation(root, target="development", intent="build")

        self.assertEqual(plan["recommended_intent"], "source_freshness")
        self.assertEqual(plan["intent"], "source_freshness")
        self.assertEqual(
            plan["scope"]["source_resources"],
            [{"source": "app", "table": "orders"}],
        )
        self.assertEqual(plan["scope"]["models"], ["stg_orders"])
        self.assertIn(
            "dbt source freshness",
            plan["commands"][-1]["command"],
        )
        self.assertIn("source:app.orders", plan["commands"][-1]["command"])

    def test_source_only_tests_are_scoped_without_rebuilding_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            schema = root / "models" / "schema.yml"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace(
                    "          - name: order_id\n",
                    "          - name: order_id\n"
                    "            data_tests:\n"
                    "              - not_null\n",
                    1,
                ),
                encoding="utf-8",
            )
            plan = planner.plan_validation(root, target="development", intent="build")

        self.assertEqual(plan["recommended_intent"], "test")
        self.assertEqual(plan["scope"]["selectors"], ["source:app.orders"])
        self.assertIn("--select source:app.orders", plan["commands"][-1]["command"])
        self.assertNotIn(" build ", f" {plan['commands'][-1]['command']} ")

    def test_modern_dbt_unit_test_changes_select_the_tested_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            unit_tests = root / "models" / "unit_tests.yml"
            unit_tests.write_text(
                "unit_tests:\n"
                "  - name: fct_orders_without_rows\n"
                "    model: fct_orders\n"
                "    given: []\n"
                "    expect:\n"
                "      rows: []\n",
                encoding="utf-8",
            )
            plan = planner.plan_validation(root, target="development", intent="build")

        self.assertEqual(plan["recommended_intent"], "test")
        self.assertEqual(plan["scope"]["models"], ["fct_orders"])
        self.assertEqual(plan["scope"]["selectors"], ["fct_orders"])
        self.assertEqual(plan["commands"][-1]["command"].split()[1], "test")

    def test_macro_and_project_config_changes_require_explicit_model_scope(self) -> None:
        for relative, content in (
            ("macros/cents_to_dollars.sql", "{% macro cents_to_dollars(x) %} {{ x }} / 100 {% endmacro %}\n"),
            ("dbt_project.yml", None),
        ):
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as tmp:
                root = self.project(tmp)
                path = root / relative
                if content is None:
                    path.write_text(
                        path.read_text(encoding="utf-8") + "\nmodels:\n  clean_project:\n    +materialized: view\n",
                        encoding="utf-8",
                    )
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                plan = planner.plan_validation(root, target="development", intent="build")
                scoped = planner.plan_validation(
                    root,
                    models=["fct_orders"],
                    target="development",
                    intent="build",
                )

                self.assertIn(relative, plan["scope"]["unresolved_dependency_changes"])
                self.assertEqual(plan["recommended_intent"], "static")
                self.assertIn("explicit affected model scope", plan["blocked_reason"])
                self.assertEqual(plan["commands"][0]["command"].split()[1], "parse")
                self.assertEqual(scoped["recommended_intent"], "build")
                self.assertIsNone(scoped["blocked_reason"])
                self.assertIn("--select fct_orders", scoped["commands"][-1]["command"])

    def test_yaml_contract_and_deleted_resources_expand_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            schema = root / "models" / "schema.yml"
            original = schema.read_text(encoding="utf-8")
            schema.write_text(
                original.replace(
                    "      - name: order_id\n        description: Stable order identifier.",
                    "      - name: order_id\n        data_type: string\n        description: Stable order identifier.",
                    1,
                ),
                encoding="utf-8",
            )
            contract = planner.plan_validation(root, target="development", intent="test")
            schema.unlink()
            deleted = planner.plan_validation(root, target="development", intent="test")

        for plan, kind in ((contract, "contract"), (deleted, "rename_or_delete")):
            with self.subTest(kind=kind):
                self.assertTrue(plan["scope"]["contract_change"])
                self.assertEqual(plan["scope"]["yaml_change_kinds"]["models/schema.yml"], kind)
                self.assertTrue(plan["scope"]["models"])
                self.assertTrue(all(selector.endswith("+") for selector in plan["scope"]["selectors"]))

    def test_semantic_changes_resolve_consumers_but_need_model_scope_to_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            semantic = root / "models" / "semantic.yml"
            semantic.write_text(
                "semantic_models:\n  - name: orders\n    model: ref('fct_orders')\n"
                "metrics:\n  - name: order_count\n    type: simple\n",
                encoding="utf-8",
            )
            plan = planner.plan_validation(root, target="development", intent="build")

        self.assertEqual(
            plan["scope"]["semantic_resources"],
            [
                {"resource_type": "metric", "name": "order_count"},
                {"resource_type": "semantic_model", "name": "orders"},
            ],
        )
        self.assertEqual(plan["scope"]["resolution_selectors"], ["order_count+", "orders+"])
        self.assertIn("explicit affected model scope", plan["blocked_reason"])
        self.assertNotIn("build", [step["command"].split()[1] for step in plan["commands"]])

    def test_missing_or_production_target_blocks_warehouse_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp)
            missing = planner.plan_validation(
                root,
                models=["fct_orders"],
                target=None,
                intent="build",
            )
            production = planner.plan_validation(
                root,
                models=["fct_orders"],
                target="analytics_prod",
                intent="build",
            )

        self.assertIn("must be named explicitly", missing["blocked_reason"])
        self.assertNotIn("build", [step["command"].split()[1] for step in missing["commands"]])
        self.assertIn("production-like", production["blocked_reason"])


class ValidationInterpreterTests(unittest.TestCase):
    def test_run_results_are_classified_and_secrets_are_redacted(self) -> None:
        token = "gh" + "p_" + ("Z" * 30)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_results.json"
            path.write_text(
                json.dumps(
                    {
                        "metadata": {"dbt_version": "1.10.0"},
                        "results": [
                            {
                                "unique_id": "test.project.unique_orders",
                                "status": "fail",
                                "message": f"Got 2 results; authorization=Bearer {token}",
                                "execution_time": 0.5,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = interpreter.interpret_results(path)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failures"][0]["category"], "test-assertion")
        self.assertNotIn(token, json.dumps(result))
        self.assertIn("[REDACTED]", result["failures"][0]["message"])

    def test_missing_artifact_is_unknown_and_log_errors_are_bounded(self) -> None:
        missing = interpreter.interpret_results("/definitely/missing/run_results.json")
        compiled = interpreter.interpret_results(
            None,
            log_text="Compilation Error in model fct_orders: unexpected token",
        )

        self.assertEqual(missing["status"], "unknown")
        self.assertEqual(compiled["status"], "failed")
        self.assertEqual(compiled["failures"][0]["category"], "compile")


if __name__ == "__main__":
    unittest.main()
