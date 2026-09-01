"""Repositories that combine several awkward traits at once.

Every trait covered here already has a fixture that exercises it alone. The
failures worth catching are the ones that only appear in combination: a Python
model is handled, and a custom `model-paths` is handled, but a Python model
under a custom `model-paths` in a project that is not the Git root was not. The
matrix below is curated rather than exhaustive, pairing the dimensions that
actually interact.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_support import FIXTURES, load_module


project_context = load_module("scripts/project_context.py", "project_context")
resource_identity = load_module("scripts/resource_identity.py", "resource_identity")
artifact_inventory = load_module("scripts/artifact_inventory.py", "artifact_inventory")
git_scope = load_module("scripts/git_scope.py", "git_scope")
planner = load_module("scripts/plan_dbt_validation.py", "plan_dbt_validation")
inspect_dbt = load_module("scripts/inspect_dbt.py", "inspect_dbt")
infer_conventions = load_module("scripts/infer_conventions.py", "infer_conventions")

DBT_FIXTURES = FIXTURES / "dbt"


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def committed_copy(destination: str, fixture: str) -> Path:
    """Copy a fixture into a temporary directory and commit it."""
    root = Path(destination) / "repo"
    shutil.copytree(DBT_FIXTURES / fixture, root)
    git(root, "init")
    git(root, "add", ".")
    git(
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


class MonorepoContextTests(unittest.TestCase):
    """Two projects under one Git root, one of which configures every path."""

    def test_a_repository_with_two_projects_asks_instead_of_picking_one(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "monorepo")

        self.assertFalse(context.is_dbt_project)
        self.assertEqual(
            sorted(path.name for path in context.sibling_projects),
            ["finance", "marketing"],
        )
        self.assertIn("name one explicitly", context.discovery_note or "")

    def test_configured_paths_replace_the_conventional_ones(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "monorepo/finance")
        layout = context.layout

        self.assertEqual(layout.name, "finance")
        self.assertEqual(layout.model_paths, ("transform",))
        self.assertEqual(layout.test_paths, ("assertions",))
        self.assertEqual(layout.macro_paths, ("udfs",))
        self.assertEqual(layout.target_path, "artifacts")
        self.assertEqual(layout.packages_install_path, "vendor")
        self.assertEqual(layout.kind_of("transform/marts/fct_revenue_v2.sql"), "model")
        self.assertEqual(layout.kind_of("assertions/assert_revenue_is_not_negative.sql"), "test")
        self.assertFalse(layout.is_own_code("vendor/dbt_utils/macros/surrogate_key.sql"))
        self.assertFalse(layout.is_own_code("artifacts/manifest.json"))

    def test_the_sibling_project_is_not_addressable_from_this_one(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "monorepo/finance")
        relative = "tests/fixtures/dbt/monorepo"

        self.assertIsNone(
            context.relative_to_project(f"{relative}/marketing/models/stg_campaigns.sql")
        )
        self.assertEqual(
            context.relative_to_project(f"{relative}/finance/transform/staging/stg_invoices.sql"),
            "transform/staging/stg_invoices.sql",
        )


class CrossedResourceIdentityTests(unittest.TestCase):
    """Python models, versioned models, and package-qualified refs together."""

    def setUp(self) -> None:
        self.context = project_context.resolve_project_context(
            DBT_FIXTURES / "monorepo/finance"
        )
        self.index = resource_identity.build_index(self.context)
        self.by_name = {
            (resource.resource_type, resource.name): resource
            for resource in self.index.resources
        }

    def test_a_python_model_is_a_model_with_its_refs_read(self) -> None:
        model = self.by_name[("model", "fct_customer_ltv")]

        self.assertEqual(model.language, "python")
        self.assertEqual(model.path, "transform/marts/fct_customer_ltv.py")
        self.assertEqual(
            sorted((ref.resource_type, ref.name, ref.version) for ref in model.refs),
            [
                ("model", "fct_revenue", "2"),
                ("model", "stg_invoices", None),
                ("source", "refunds", None),
            ],
        )

    def test_a_versioned_filename_is_one_model_at_a_version(self) -> None:
        model = self.by_name[("model", "fct_revenue")]

        self.assertEqual(model.version, "2")
        self.assertEqual(model.path, "transform/marts/fct_revenue_v2.sql")
        self.assertEqual(
            [(ref.name, ref.package) for ref in model.refs],
            [("stg_invoices", None), ("stg_adjustments", "shared_finance")],
        )

    def test_a_generic_test_definition_is_not_a_singular_test(self) -> None:
        self.assertIn(("generic_test", "positive_amount"), self.by_name)
        self.assertIn(("macro", "cents_to_dollars"), self.by_name)
        self.assertIn(("singular_test", "assert_revenue_is_not_negative"), self.by_name)
        self.assertNotIn(("singular_test", "positive_amount"), self.by_name)

    def test_an_installed_package_contributes_nothing(self) -> None:
        self.assertNotIn(("macro", "dbt_utils_surrogate_key"), self.by_name)

    def test_artifacts_are_read_from_the_configured_target_path(self) -> None:
        inventory = artifact_inventory.inventory_artifacts(self.context)
        manifest = inventory.current["manifest"]

        self.assertTrue(manifest.present, "the manifest lives under artifacts/, not target/")
        self.assertTrue(manifest.valid)
        self.assertFalse(inventory.has_prior_state)

        nodes = artifact_inventory.manifest_nodes(inventory.manifest_document())
        self.assertIn("model.finance.fct_revenue.v2", nodes)
        self.assertEqual(
            sorted(
                artifact_inventory.downstream_from_manifest(
                    inventory.manifest_document(), ["model.finance.stg_invoices"]
                )
            ),
            [
                "model.finance.fct_customer_ltv",
                "model.finance.fct_revenue.v2",
                "test.finance.assert_revenue_is_not_negative",
            ],
        )


class VersionedIdentityTests(unittest.TestCase):
    """A version is part of a model's identity, not a decoration on its filename."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.context = project_context.resolve_project_context(
            DBT_FIXTURES / "versioned_models"
        )
        cls.index = resource_identity.build_index(cls.context)
        cls.by_path = {
            resource.path: resource
            for resource in cls.index.resources
            if resource.path
        }

    def test_each_version_is_a_separate_resource_with_its_own_selector(self) -> None:
        first = self.by_path["models/orders_v1.sql"]
        second = self.by_path["models/orders_v2.sql"]

        self.assertEqual((first.name, first.version), ("orders", "1"))
        self.assertEqual((second.name, second.version), ("orders", "2"))
        self.assertNotEqual(first.key, second.key, "two versions are two relations")
        self.assertEqual(second.selector(), "orders.v2")

    def test_a_non_numeric_version_comes_from_yaml_not_the_filename(self) -> None:
        rebuild = self.by_path["models/customer_rebuild.sql"]

        self.assertEqual((rebuild.name, rebuild.version), ("customers", "beta"))
        self.assertEqual(rebuild.defined_in, "customer_rebuild")
        self.assertEqual(rebuild.identity_evidence, "yaml")
        self.assertTrue(rebuild.is_latest_version)

    def test_the_latest_version_may_keep_the_unsuffixed_filename(self) -> None:
        latest = self.by_path["models/dim_products.sql"]

        self.assertEqual((latest.name, latest.version), ("dim_products", "2"))
        self.assertTrue(latest.is_latest_version)
        self.assertIsNone(latest.defined_in, "dbt inferred this file; YAML did not name it")

    def test_the_latest_version_pointer_is_a_published_interface(self) -> None:
        orders = self.by_path["models/orders_v2.sql"]
        products = self.by_path["models/dim_products.sql"]
        customers = self.by_path["models/customer_rebuild.sql"]
        older = self.by_path["models/orders_v1.sql"]

        self.assertEqual(
            [(item.name, item.enabled, item.evidence) for item in orders.interfaces],
            [("orders_current", True, "model config")],
        )
        self.assertEqual(
            [(item.name, item.enabled, item.evidence) for item in products.interfaces],
            [("dim_products", False, "model config")],
            "a per-model disable overrides the project flag",
        )
        self.assertEqual(
            [(item.name, item.enabled, item.evidence) for item in customers.interfaces],
            [("customers", True, "project flag")],
        )
        self.assertEqual(older.interfaces, (), "only the latest version has a pointer")

    def test_an_unversioned_ref_resolves_to_the_latest_version_only(self) -> None:
        def downstream(version: str | None) -> list[str]:
            refs = [resource_identity.ResourceRef("model", "orders", version=version)]
            return [item.name for item in self.index.downstream_of(refs)]

        self.assertEqual(downstream("1"), ["legacy_report"])
        self.assertEqual(
            downstream("2"), ["fct_order_summary", "assert_summary_is_not_empty"]
        )

    def test_a_name_shared_across_resource_types_is_reported_as_ambiguous(self) -> None:
        regions = self.by_path["models/regions.sql"]
        orders = self.by_path["models/orders_v2.sql"]

        self.assertTrue(self.index.is_ambiguous(regions), "model, seed, and snapshot")
        self.assertEqual(regions.path_selector(), "path:models/regions.sql")
        self.assertFalse(
            self.index.is_ambiguous(orders),
            "a source named orders is selected as source:raw.orders",
        )

    def test_generic_test_usage_covers_models_and_sources(self) -> None:
        usages = self.index.generic_test_usages["positive_amount"]

        self.assertEqual(
            sorted((ref.resource_type, ref.name) for ref in usages),
            [("model", "orders"), ("source", "orders")],
        )

    def test_commented_out_references_are_not_dependencies(self) -> None:
        summary = self.by_path["models/fct_order_summary.sql"]
        python_model = self.by_path["models/customer_lifetime.py"]

        self.assertEqual(
            sorted((ref.name, ref.version) for ref in summary.refs),
            [("customers", "beta"), ("orders", None)],
        )
        self.assertEqual(
            sorted((ref.resource_type, ref.name) for ref in python_model.refs),
            [("model", "customers"), ("source", "payments")],
        )


class CrossedValidationPlanTests(unittest.TestCase):
    """A mixed dirty tree in a nested project keeps every bounded operation."""

    def plan_for_mixed_changes(self) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "monorepo")
            finance = root / "finance"

            model = finance / "transform" / "marts" / "fct_customer_ltv.py"
            model.write_text(model.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

            singular = finance / "assertions" / "assert_revenue_is_not_negative.sql"
            singular.write_text(
                singular.read_text(encoding="utf-8") + "\n-- changed\n", encoding="utf-8"
            )

            sources = finance / "transform" / "staging" / "sources.yml"
            sources.write_text(
                sources.read_text(encoding="utf-8").replace("count: 6", "count: 3"),
                encoding="utf-8",
            )

            unrelated = root / "marketing" / "models" / "sources.yml"
            unrelated.write_text(
                unrelated.read_text(encoding="utf-8") + "      - name: adgroups\n",
                encoding="utf-8",
            )

            return planner.plan_validation(finance, target="dev", intent="build")

    def setUp(self) -> None:
        self.plan = self.plan_for_mixed_changes()

    def test_three_independent_changes_produce_three_bounded_operations(self) -> None:
        operations = [step["operation"] for step in self.plan["validation_steps"]]

        self.assertEqual(
            operations,
            ["parse", "resolve", "source_freshness", "test", "model_validation"],
            "collapsing a mixed change into one intent loses two of the three checks",
        )

    def test_each_operation_is_selected_down_to_what_changed(self) -> None:
        steps = {step["operation"]: step for step in self.plan["validation_steps"]}

        self.assertEqual(steps["source_freshness"]["selectors"], ["source:billing.invoices"])
        self.assertEqual(steps["test"]["selectors"], ["assert_revenue_is_not_negative"])
        self.assertEqual(steps["model_validation"]["selectors"], ["fct_customer_ltv"])
        self.assertIn("--select source:billing.invoices", steps["source_freshness"]["command"])
        self.assertTrue(steps["source_freshness"]["command"].startswith("dbt source freshness"))

    def test_a_sibling_projects_dirty_file_is_excluded_and_named(self) -> None:
        excluded = {entry["path"]: entry["reason"] for entry in self.plan["scope"]["excluded_changes"]}

        self.assertIn("marketing/models/sources.yml", excluded)
        self.assertIn("outside the active dbt project", excluded["marketing/models/sources.yml"])
        self.assertNotIn(
            "marketing/models/sources.yml", self.plan["scope"]["changed_paths"]
        )

    def test_the_legacy_fields_still_describe_the_same_plan(self) -> None:
        self.assertEqual(self.plan["plan_version"], 2)
        self.assertEqual(
            [entry["step"] for entry in self.plan["commands"]],
            [step["step"] for step in self.plan["validation_steps"]],
        )
        self.assertEqual(self.plan["intent"], "build")
        self.assertEqual(self.plan["scope"]["selectors"], ["fct_customer_ltv"])

    def test_explicit_paths_isolate_the_scope_to_what_was_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "monorepo")
            finance = root / "finance"
            model = finance / "transform" / "marts" / "fct_customer_ltv.py"
            model.write_text(model.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
            singular = finance / "assertions" / "assert_revenue_is_not_negative.sql"
            singular.write_text(
                singular.read_text(encoding="utf-8") + "\n-- changed\n", encoding="utf-8"
            )
            plan = planner.plan_validation(
                finance,
                target="dev",
                intent="build",
                paths=["transform/marts/fct_customer_ltv.py"],
            )

        self.assertEqual(plan["scope"]["changed_paths"], ["transform/marts/fct_customer_ltv.py"])
        self.assertEqual(plan["scope"]["singular_tests"], [])
        self.assertNotIn(
            "test", [step["operation"] for step in plan["validation_steps"]]
        )


class EvidenceCoverageTests(unittest.TestCase):
    """Running a command successfully is not the same as validating the change."""

    def plan_after(self, mutate, **kwargs) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "versioned_models")
            mutate(root)
            return planner.plan_validation(root, target="dev", **kwargs)

    @staticmethod
    def edit_model(root: Path) -> None:
        model = root / "models" / "orders_v2.sql"
        model.write_text(model.read_text(encoding="utf-8") + "\n-- changed\n", "utf-8")

    def test_a_changed_model_owes_both_execution_and_tests(self) -> None:
        plan = self.plan_after(self.edit_model, intent="build")

        self.assertEqual(plan["required_evidence"], ["transformation", "tests"])
        self.assertEqual(plan["satisfied_evidence"], ["transformation", "tests"])
        self.assertEqual(plan["change_verification_status"], "fully_covered")

    def test_asking_only_for_tests_leaves_the_implementation_unproven(self) -> None:
        plan = self.plan_after(self.edit_model, intent="test", allow_broader_intent=True)

        self.assertEqual(plan["satisfied_evidence"], ["tests"])
        self.assertEqual(plan["unsatisfied_evidence"], ["transformation"])
        self.assertEqual(plan["change_verification_status"], "partially_covered")
        self.assertTrue(
            any(
                "changed model implementation was executed" in warning
                for warning in plan["warnings"]
            ),
            "the open obligation has to be said out loud",
        )

    def test_asking_only_to_run_leaves_the_tests_unproven(self) -> None:
        plan = self.plan_after(self.edit_model, intent="run", allow_broader_intent=True)

        self.assertEqual(plan["satisfied_evidence"], ["transformation"])
        self.assertEqual(plan["unsatisfied_evidence"], ["tests"])

    def test_compiling_proves_nothing_the_change_owes(self) -> None:
        plan = self.plan_after(self.edit_model, intent="compile", allow_broader_intent=True)

        self.assertEqual(plan["satisfied_evidence"], ["compilation"])
        self.assertEqual(plan["unsatisfied_evidence"], ["transformation", "tests"])
        self.assertEqual(plan["change_verification_status"], "not_covered")

    def test_each_step_declares_what_it_proves(self) -> None:
        plan = self.plan_after(self.edit_model, intent="build")
        build = next(
            step for step in plan["validation_steps"] if step["operation"] == "model_validation"
        )
        parse = next(
            step for step in plan["validation_steps"] if step["operation"] == "parse"
        )

        self.assertEqual(build["provides_evidence"], ["transformation", "tests"])
        self.assertEqual(
            parse["provides_evidence"],
            [],
            "parsing builds the graph; it does not execute the change",
        )

    def test_a_freshness_only_change_is_fully_covered_by_freshness(self) -> None:
        def edit(root: Path) -> None:
            sources = root / "models" / "sources.yml"
            sources.write_text(
                sources.read_text(encoding="utf-8").replace("count: 12", "count: 6"),
                encoding="utf-8",
            )

        plan = self.plan_after(edit, intent="source_freshness")

        self.assertEqual(plan["required_evidence"], ["freshness"])
        self.assertEqual(plan["change_verification_status"], "fully_covered")


class TypedObligationTests(unittest.TestCase):
    """Identity survives into the selectors, and one file can owe several checks."""

    def plan_after(self, mutate, **kwargs) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "versioned_models")
            mutate(root)
            return planner.plan_validation(root, target="dev", **kwargs)

    def test_changing_one_version_selects_only_that_version(self) -> None:
        def edit(root: Path) -> None:
            model = root / "models" / "orders_v2.sql"
            model.write_text(model.read_text(encoding="utf-8") + "\n-- changed\n", "utf-8")

        plan = self.plan_after(edit, intent="build")
        build = next(
            step for step in plan["validation_steps"] if step["operation"] == "model_validation"
        )

        self.assertEqual(build["selectors"], ["orders.v2"])
        self.assertIn("--select orders.v2", build["command"])

    def test_a_rename_resolves_the_old_identity_and_validates_the_new_one(self) -> None:
        def rename(root: Path) -> None:
            git(root, "mv", "models/orders_v2.sql", "models/orders_current.sql")

        plan = self.plan_after(rename, intent="build")
        rename_record = plan["scope"]["renames"][0]
        build = next(
            step for step in plan["validation_steps"] if step["operation"] == "model_validation"
        )

        self.assertEqual(rename_record["from"]["name"], "orders")
        self.assertEqual(rename_record["from"]["version"], "2")
        self.assertEqual(rename_record["to"]["name"], "orders_current")
        self.assertIn(
            "orders_current",
            build["selectors"],
            "the arriving file is the definition that needs validating",
        )
        self.assertNotIn(
            "orders_current",
            [item for record in plan["scope"]["renames"] for item in record["consumers"]],
            "state is asked about the departing identity, not the arriving one",
        )

    def test_a_rename_reports_references_that_were_not_migrated(self) -> None:
        def rename(root: Path) -> None:
            git(root, "mv", "models/customer_rebuild.sql", "models/customers_current.sql")

        plan = self.plan_after(rename, intent="build")
        rename_record = plan["scope"]["renames"][0]

        self.assertEqual(rename_record["from"]["version"], "beta")
        self.assertEqual(
            sorted(rename_record["surviving_references"]),
            ["customer_lifetime", "fct_order_summary", "orders.v2"],
            "each still calls ref('customers', v='beta'), and one of them is a version",
        )
        self.assertTrue(
            any("still reference customers" in warning for warning in plan["warnings"])
        )

    def test_one_yaml_file_can_owe_several_independent_checks(self) -> None:
        def edit(root: Path) -> None:
            schema = root / "models" / "sources.yml"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace("count: 12", "count: 6"),
                encoding="utf-8",
            )
            models = root / "models" / "schema.yml"
            models.write_text(
                models.read_text(encoding="utf-8").replace(
                    "      - name: amount\n",
                    "      - name: amount\n        data_type: numeric\n",
                    1,
                ),
                encoding="utf-8",
            )

        plan = self.plan_after(edit, intent="build")
        operations = [step["operation"] for step in plan["validation_steps"]]

        self.assertIn("source_freshness", operations)
        self.assertIn("model_validation", operations)

    def test_a_mixed_document_keeps_the_source_and_the_model_obligation(self) -> None:
        def edit(root: Path) -> None:
            schema = root / "models" / "sources.yml"
            text = schema.read_text(encoding="utf-8").replace("count: 12", "count: 6")
            text += (
                "\nmodels:\n"
                "  - name: fct_order_summary\n"
                "    columns:\n"
                "      - name: amount\n"
                "        data_type: numeric\n"
            )
            schema.write_text(text, encoding="utf-8")

        plan = self.plan_after(edit, intent="build")
        kinds = {
            delta["kind"] for delta in plan["scope"]["yaml_deltas"]["models/sources.yml"]
        }

        self.assertEqual(kinds, {"source_freshness", "contract"})
        self.assertEqual(
            plan["scope"]["yaml_change_kinds"]["models/sources.yml"],
            "contract",
            "the single legacy label still reports the most consequential change",
        )
        steps = {step["operation"]: step for step in plan["validation_steps"]}
        self.assertEqual(steps["source_freshness"]["selectors"], ["source:raw.orders"])
        self.assertIn("fct_order_summary+", steps["model_validation"]["selectors"])

    def test_a_contract_change_on_one_version_selects_only_that_version(self) -> None:
        def edit(root: Path) -> None:
            schema = root / "models" / "schema.yml"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace(
                    "    versions:\n      - v: 1\n      - v: 2\n",
                    "    versions:\n"
                    "      - v: 1\n"
                    "        columns:\n"
                    "          - name: amount\n"
                    "            data_type: numeric\n"
                    "      - v: 2\n",
                    1,
                ),
                encoding="utf-8",
            )

        plan = self.plan_after(edit, intent="build")
        build = next(
            step for step in plan["validation_steps"] if step["operation"] == "model_validation"
        )

        self.assertEqual(build["selectors"], ["orders.v1+"])
        self.assertEqual(
            plan["scope"]["yaml_deltas"]["models/schema.yml"][0]["models"], ["orders.v1"]
        )

    def test_a_test_change_on_one_version_tests_only_that_version(self) -> None:
        def edit(root: Path) -> None:
            schema = root / "models" / "schema.yml"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace(
                    "    versions:\n      - v: 1\n      - v: 2\n",
                    "    versions:\n"
                    "      - v: 1\n"
                    "      - v: 2\n"
                    "        data_tests:\n"
                    "          - unique\n",
                    1,
                ),
                encoding="utf-8",
            )

        plan = self.plan_after(edit, intent="build")
        test_step = next(
            step for step in plan["validation_steps"] if step["operation"] == "test"
        )

        self.assertEqual(test_step["selectors"], ["orders.v2"])

    def test_a_shared_model_field_still_reaches_every_version(self) -> None:
        def edit(root: Path) -> None:
            schema = root / "models" / "schema.yml"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace(
                    "      - name: order_id\n",
                    "      - name: order_id\n        data_type: bigint\n",
                    1,
                ),
                encoding="utf-8",
            )

        plan = self.plan_after(edit, intent="build")
        build = next(
            step for step in plan["validation_steps"] if step["operation"] == "model_validation"
        )

        self.assertEqual(
            build["selectors"],
            ["orders.v1+", "orders.v2+"],
            "a column shared by every version obliges every version",
        )

    def test_a_freshness_request_never_becomes_a_freshness_command_for_tests(self) -> None:
        def edit(root: Path) -> None:
            singular = root / "tests" / "assert_summary_is_not_empty.sql"
            singular.write_text(
                singular.read_text(encoding="utf-8") + "\n-- changed\n", encoding="utf-8"
            )
            sources = root / "models" / "sources.yml"
            sources.write_text(
                sources.read_text(encoding="utf-8").replace("count: 12", "count: 6"),
                encoding="utf-8",
            )

        plan = self.plan_after(edit, intent="source_freshness")
        steps = {step["operation"]: step for step in plan["validation_steps"]}

        self.assertIn("source_freshness", steps)
        self.assertTrue(steps["source_freshness"]["command"].startswith("dbt source freshness"))
        self.assertNotIn(
            "test",
            steps,
            "asking for freshness does less; it does not run tests as freshness",
        )
        for step in plan["validation_steps"]:
            if step["executes_warehouse"]:
                self.assertNotIn("assert_summary_is_not_empty", step["command"])

    def test_a_changed_generic_test_tests_the_models_and_sources_that_use_it(self) -> None:
        def edit(root: Path) -> None:
            macro = root / "macros" / "generic_tests.sql"
            macro.write_text(
                macro.read_text(encoding="utf-8").replace("<= 0", "< 0"), encoding="utf-8"
            )

        plan = self.plan_after(edit, intent="build")
        steps = {step["operation"]: step for step in plan["validation_steps"]}

        self.assertEqual(
            sorted(steps["test"]["selectors"]), ["orders", "source:raw.orders"]
        )
        self.assertEqual(plan["scope"]["unresolved_dependency_changes"], [])
        self.assertIsNone(plan["blocked_reason"])

    def test_a_name_shared_by_a_model_and_a_seed_is_selected_by_path(self) -> None:
        def edit(root: Path) -> None:
            model = root / "models" / "regions.sql"
            model.write_text(model.read_text(encoding="utf-8") + "\n-- changed\n", "utf-8")

        plan = self.plan_after(edit, intent="build")
        build = next(
            step for step in plan["validation_steps"] if step["operation"] == "model_validation"
        )

        self.assertEqual(build["selectors"], ["path:models/regions.sql"])
        self.assertEqual(
            plan["scope"]["ambiguous_selectors"][0]["also_named"], ["seed", "snapshot"]
        )

    def test_removing_a_source_declaration_names_its_surviving_consumers(self) -> None:
        def edit(root: Path) -> None:
            sources = root / "models" / "sources.yml"
            sources.write_text(
                sources.read_text(encoding="utf-8").replace("      - name: products\n", ""),
                encoding="utf-8",
            )

        plan = self.plan_after(edit, intent="build")
        removal = plan["scope"]["source_removals"][0]

        self.assertEqual(removal["sources"], [{"source": "raw", "table": "products"}])
        self.assertEqual(
            removal["surviving_consumers"],
            ["dim_products.v1", "dim_products.v2"],
            "both versions read the removed source, and both are named",
        )
        self.assertTrue(
            any("still read it" in warning for warning in plan["warnings"])
        )

    def test_a_source_read_by_one_version_selects_only_that_version(self) -> None:
        def edit(root: Path) -> None:
            sources = root / "models" / "sources.yml"
            sources.write_text(
                sources.read_text(encoding="utf-8").replace(
                    "      - name: payments\n",
                    "      - name: payments\n        description: Legacy payment feed.\n"
                    "        columns:\n          - name: order_id\n"
                    "            data_tests:\n              - not_null\n",
                ),
                encoding="utf-8",
            )

        plan = self.plan_after(edit, intent="build")
        selectors = plan["scope"]["selectors"]

        self.assertIn("orders.v1+", selectors)
        self.assertNotIn(
            "orders.v2+", selectors, "version 2 stopped reading this source"
        )
        self.assertNotIn("orders+", selectors, "a bare name would select both versions")


class DeletionWithAndWithoutStateTests(unittest.TestCase):
    """A deleted model cannot be selected, so its consumers have to be found."""

    def delete_staging_model(self, tmp: str, *, with_state: bool) -> dict:
        root = committed_copy(tmp, "monorepo")
        finance = root / "finance"
        (finance / "transform" / "staging" / "stg_invoices.sql").unlink()

        state_dir = None
        if with_state:
            state_dir = Path(tmp) / "prior"
            state_dir.mkdir()
            shutil.copy(finance / "artifacts" / "manifest.json", state_dir / "manifest.json")
        else:
            shutil.rmtree(finance / "artifacts")

        return planner.plan_validation(
            finance, target="dev", intent="build", state_dir=state_dir
        )

    def test_prior_state_resolves_the_consumers_of_a_deleted_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.delete_staging_model(tmp, with_state=True)

        build = next(
            step for step in plan["validation_steps"] if step["operation"] == "model_validation"
        )
        self.assertEqual(plan["scope"]["unresolvable_deletions"], [])
        self.assertNotIn(
            "stg_invoices",
            build["selectors"],
            "a deleted model cannot be a selector; its consumers are the scope",
        )
        self.assertEqual(
            sorted(build["selectors"]),
            ["assert_revenue_is_not_negative", "fct_customer_ltv", "fct_revenue.v2"],
            "every consumer prior state recorded, at the version it recorded",
        )
        self.assertIsNone(plan["blocked_reason"])

    def test_without_state_the_plan_asks_for_scope_rather_than_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.delete_staging_model(tmp, with_state=False)

        deletions = plan["scope"]["unresolvable_deletions"]
        self.assertEqual([entry["name"] for entry in deletions], ["stg_invoices"])
        self.assertIn("name the affected downstream models", plan["blocked_reason"])
        self.assertNotIn(
            "model_validation", [step["operation"] for step in plan["validation_steps"]]
        )

    def test_state_from_three_days_ago_is_evidence_but_not_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "monorepo")
            finance = root / "finance"
            (finance / "transform" / "staging" / "stg_invoices.sql").unlink()
            shutil.rmtree(finance / "artifacts")

            state_dir = Path(tmp) / "prior"
            state_dir.mkdir()
            manifest = json.loads(
                (FIXTURES / "dbt" / "monorepo" / "finance" / "artifacts" / "manifest.json")
                .read_text(encoding="utf-8")
            )
            old = datetime.now(timezone.utc) - timedelta(hours=72)
            manifest.setdefault("metadata", {})["generated_at"] = old.isoformat().replace(
                "+00:00", "Z"
            )
            (state_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            plan = planner.plan_validation(
                finance, target="dev", intent="build", state_dir=state_dir
            )

        build = next(
            step for step in plan["validation_steps"] if step["operation"] == "model_validation"
        )
        self.assertEqual(
            build["confidence"],
            "medium",
            "a three-day-old graph can inform a plan but cannot be its whole basis",
        )

    def test_a_state_path_that_does_not_exist_is_an_error_not_a_shrug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "monorepo")
            with self.assertRaises(planner.ValidationPlanError) as raised:
                planner.plan_validation(
                    root / "finance", state_dir=Path(tmp) / "no-such-state"
                )
        self.assertIn("does not exist", str(raised.exception))


class DependencyExtractionTests(unittest.TestCase):
    """A reference the interpreter would never make is not a dependency."""

    def refs(self, text: str, language: str) -> list[tuple[str, str | None]]:
        found = resource_identity.parse_refs(text, language=language)
        return sorted((ref.name, ref.version) for ref in found)

    def test_sql_and_jinja_comments_cannot_create_edges(self) -> None:
        text = (
            "-- ref('line_comment')\n"
            "/* ref('block_comment') */\n"
            "{# ref('jinja_comment') #}\n"
            "select * from {{ ref('real_model') }}\n"
        )

        self.assertEqual(self.refs(text, "sql"), [("real_model", None)])

    def test_a_comment_marker_inside_a_string_does_not_hide_the_rest(self) -> None:
        text = "select '-- not a comment' as note, x from {{ ref('real_model') }}\n"

        self.assertEqual(self.refs(text, "sql"), [("real_model", None)])

    def test_an_unterminated_block_comment_swallows_the_rest_of_the_file(self) -> None:
        text = "select 1\n/* ref('never_closed')\nfrom {{ ref('unreachable') }}\n"

        self.assertEqual(self.refs(text, "sql"), [])

    def test_python_docstrings_comments_and_strings_are_not_calls(self) -> None:
        text = (
            '"""dbt.ref("docstring_model")"""\n'
            "def model(dbt, session):\n"
            '    # dbt.ref("comment_model")\n'
            '    note = "dbt.ref(\'string_model\')"\n'
            '    return dbt.ref("real_model", v="beta")\n'
        )

        self.assertEqual(self.refs(text, "python"), [("real_model", "beta")])

    def test_a_computed_reference_is_reported_rather_than_guessed(self) -> None:
        text = "def model(dbt, session):\n    return dbt.ref(chosen_name)\n"
        refs, notes = resource_identity.parse_refs_checked(text, language="python")

        self.assertEqual(refs, ())
        self.assertIn("computed value", notes[0])

    def test_python_that_does_not_parse_says_so_instead_of_guessing(self) -> None:
        text = 'def model(dbt, session):\n    return dbt.ref("orders"\n'
        refs, notes = resource_identity.parse_refs_checked(text, language="python")

        self.assertEqual(refs, ())
        self.assertIn("could not be parsed", notes[0])

    def test_the_planner_reports_a_file_whose_dependencies_are_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "versioned_models")
            broken = root / "models" / "unparseable_model.py"
            broken.write_text(broken.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            plan = planner.plan_validation(root, target="dev", intent="build")

        self.assertIn("models/unparseable_model.py", plan["scope"]["unknown_dependencies"])
        self.assertTrue(
            any("could not be parsed" in warning for warning in plan["warnings"])
        )


class GitOperationTests(unittest.TestCase):
    """Git spells six different things with two letters; they are not one thing."""

    def scope_after(self, tmp: str, mutate) -> tuple[object, dict[str, object]]:
        root = committed_copy(tmp, "versioned_models")
        mutate(root)
        context = project_context.resolve_project_context(root)
        scope = git_scope.collect_scope(context)
        return context, {change.path: change for change in scope.changes}

    def test_a_rename_carries_both_the_old_and_the_new_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _context, changes = self.scope_after(
                tmp,
                lambda root: git(root, "mv", "models/regions.sql", "models/dim_regions.sql"),
            )

        renamed = changes["models/dim_regions.sql"]
        self.assertEqual(renamed.change_type, git_scope.RENAMED)
        self.assertEqual(renamed.original_path, "models/regions.sql")
        self.assertTrue(renamed.is_rename)
        self.assertTrue(renamed.is_removal, "the old relation is gone")

    def test_a_copy_is_not_a_removal_of_the_original(self) -> None:
        copied = git_scope._change_type({"status": "C085", "path": "models/orders_v3.sql"})
        renamed = git_scope._change_type({"status": "R100", "path": "models/orders_v3.sql"})

        self.assertEqual(copied, git_scope.COPIED)
        self.assertEqual(renamed, git_scope.RENAMED)
        self.assertFalse(
            git_scope.ChangedPath("a.sql", git_scope.COPIED, "a.sql").is_removal,
            "the source of a copy is still built and still has consumers",
        )

    def test_every_unmerged_state_is_a_conflict_rather_than_an_edit(self) -> None:
        for code in sorted(git_scope.UNMERGED_CODES):
            with self.subTest(code=code):
                record = {"index_status": code[0], "worktree_status": code[1]}
                self.assertEqual(git_scope._change_type(record), git_scope.CONFLICTED)
                self.assertEqual(git_scope.unmerged_code(record), code)

    def test_a_conflicted_tree_blocks_planning_and_says_which_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "versioned_models")
            model = root / "models" / "orders_v2.sql"
            author = ["-c", "user.name=T", "-c", "user.email=t@example.invalid"]

            git(root, "checkout", "-b", "left")
            model.write_text("select 1 as left_side\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, *author, "commit", "-m", "left")

            git(root, "checkout", "-b", "right", "HEAD~1")
            model.write_text("select 1 as right_side\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, *author, "commit", "-m", "right")

            merge = subprocess.run(
                ["git", "-C", str(root), *author, "merge", "left"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(merge.returncode, 0, "the merge is supposed to conflict")

            plan = planner.plan_validation(root, target="dev", intent="build")

        self.assertEqual(
            [entry["path"] for entry in plan["scope"]["unmerged_paths"]],
            ["models/orders_v2.sql"],
        )
        self.assertIn("Unresolved merge conflicts", plan["blocked_reason"])
        self.assertEqual(
            [step["operation"] for step in plan["validation_steps"]
             if step["executes_warehouse"]],
            [],
        )


class ConfiguredPathTests(unittest.TestCase):
    """Configured paths are compared as prefixes, after being canonicalized."""

    def setUp(self) -> None:
        self.context = project_context.resolve_project_context(
            DBT_FIXTURES / "nested_packages_path"
        )
        self.layout = self.context.layout

    def test_relative_and_repeated_separators_are_normalized(self) -> None:
        self.assertEqual(self.layout.model_paths, ("models",))
        self.assertEqual(self.layout.seed_paths, ("seeds",))
        self.assertEqual(self.layout.target_path, "build/artifacts")
        self.assertEqual(self.layout.packages_install_path, "tooling/vendor")
        self.assertEqual(project_context.normalize_relative("./a//./b/"), "a/b")
        self.assertEqual(project_context.normalize_relative("../escape"), "")

    def test_a_nested_packages_path_still_excludes_the_package(self) -> None:
        self.assertFalse(
            self.layout.is_own_code("tooling/vendor/dbt_utils/macros/star.sql"),
            "a two-segment packages path is one prefix, not two directory names",
        )
        self.assertFalse(self.layout.is_own_code("build/artifacts/manifest.json"))

    def test_a_directory_that_merely_shares_the_name_is_still_ours(self) -> None:
        own = "models/vendor/stg_vendor_payments.sql"

        self.assertTrue(self.layout.is_own_code(own))
        self.assertEqual(self.layout.kind_of(own), "model")

        index = resource_identity.build_index(self.context)
        self.assertIn(
            ("model", "stg_vendor_payments"),
            {(item.resource_type, item.name) for item in index.resources},
        )

    def test_the_same_holds_for_a_single_segment_packages_path(self) -> None:
        finance = project_context.resolve_project_context(DBT_FIXTURES / "monorepo/finance")

        self.assertTrue(finance.layout.is_own_code("transform/vendor/stg_vendor_invoices.sql"))
        self.assertFalse(finance.layout.is_own_code("vendor/dbt_utils/macros/surrogate_key.sql"))


class ModernYamlTests(unittest.TestCase):
    """dbt documents anchors, aliases, merge keys, and flow mappings."""

    def setUp(self) -> None:
        self.text = (DBT_FIXTURES / "modern_yaml" / "models" / "schema.yml").read_text(
            encoding="utf-8"
        )
        self.document, self.constructs = project_context.parse_yaml_checked(self.text)

    def test_a_documented_dbt_document_is_readable(self) -> None:
        self.assertEqual(self.constructs, [])

    def test_a_flow_mapping_becomes_a_mapping(self) -> None:
        orders = self.document["sources"][0]["tables"][0]

        self.assertEqual(
            orders["freshness"]["warn_after"], {"count": 12, "period": "hour"}
        )

    def test_an_alias_reproduces_the_anchored_value(self) -> None:
        tables = self.document["sources"][0]["tables"]

        self.assertEqual(tables[0]["freshness"], tables[1]["freshness"])

    def test_an_alias_copies_rather_than_shares_the_anchored_value(self) -> None:
        tables = self.document["sources"][0]["tables"]
        tables[0]["freshness"]["warn_after"]["count"] = 999

        self.assertEqual(
            tables[1]["freshness"]["warn_after"]["count"],
            12,
            "sharing one object would let an edit to orders rewrite customers",
        )

    def test_a_sequence_anchor_survives_aliasing(self) -> None:
        events = self.document["models"][1]

        self.assertEqual(events["columns"], [{"name": "_loaded_at", "description": "Warehouse load time."}])

    def test_merge_precedence_follows_the_yaml_rules(self) -> None:
        freshness = self.document["sources"][0]["tables"][2]["freshness"]

        self.assertEqual(
            freshness["warn_after"],
            {"count": 1, "period": "hour"},
            "the first alias in the merge sequence wins",
        )
        self.assertEqual(
            freshness["error_after"],
            {"count": 6, "period": "hour"},
            "the mapping's own key outranks anything merged in",
        )

    def test_the_planner_plans_freshness_from_a_merged_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "modern_yaml")
            schema = root / "models" / "schema.yml"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace("count: 6", "count: 3"),
                encoding="utf-8",
            )
            plan = planner.plan_validation(root, target="dev", intent="build")

        self.assertEqual(plan["scope"]["unsupported_yaml"], {})
        freshness = next(
            step
            for step in plan["validation_steps"]
            if step["operation"] == "source_freshness"
        )
        self.assertEqual(freshness["selectors"], ["source:app.events"])


class UnsupportedYamlTests(unittest.TestCase):
    """A file the reader cannot interpret must not produce a confident answer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = (
            DBT_FIXTURES / "unsupported_yaml" / "models" / "schema.yml"
        ).read_text(encoding="utf-8")

    def test_a_custom_tag_is_named_rather_than_misread(self) -> None:
        self.assertEqual(
            project_context.unsupported_yaml_constructs(self.text), ["custom_tag"]
        )

    def test_an_alias_with_no_anchor_is_reported_rather_than_guessed(self) -> None:
        _, constructs = project_context.parse_yaml_checked(self.text)

        self.assertIn("custom_tag", constructs)
        self.assertIn("unresolved_alias: never_declared", constructs)

    def test_the_planner_reports_the_construct_instead_of_a_freshness_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "unsupported_yaml")
            schema = root / "models" / "schema.yml"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace("count: 12", "count: 6"),
                encoding="utf-8",
            )
            plan = planner.plan_validation(root, target="dev", intent="build")

        self.assertIn("models/schema.yml", plan["scope"]["unsupported_yaml"])
        self.assertIn("custom_tag", plan["scope"]["unsupported_yaml"]["models/schema.yml"])


class AmbiguousAdapterTests(unittest.TestCase):
    """Shared syntax is not evidence, and an append incremental is not a defect."""

    def setUp(self) -> None:
        self.report = inspect_dbt.inspect_dbt(DBT_FIXTURES / "ambiguous_adapter")
        self.profile = infer_conventions.infer_conventions(DBT_FIXTURES / "ambiguous_adapter")

    def test_partition_and_cluster_syntax_alone_names_no_warehouse(self) -> None:
        project = self.profile["project"]

        self.assertIsNone(
            project["adapter"],
            "partition_by and cluster_by are written on several warehouses",
        )
        self.assertEqual(project["adapter_confidence"], "none")

    def test_an_append_incremental_needs_no_unique_key(self) -> None:
        flagged = {
            finding["path"]
            for finding in self.report["findings"]
            if finding["code"] == "incremental_without_unique_key"
        }

        self.assertNotIn("models/fct_events.sql", flagged, "append replaces no rows")
        self.assertIn("models/fct_sessions.sql", flagged, "merge without a key is a defect")


class VersionOrderingTests(unittest.TestCase):
    """dbt decides which version is latest; the toolkit reproduces that rule."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.context = project_context.resolve_project_context(
            DBT_FIXTURES / "stale_manifest"
        )
        cls.index = resource_identity.build_index(cls.context)
        cls.by_path = {
            resource.path: resource for resource in cls.index.resources if resource.path
        }
        document = infer_conventions.parse_yaml(
            (DBT_FIXTURES / "stale_manifest/models/schema.yml").read_text(encoding="utf-8")
        )
        cls.declared = {
            declaration.name: declaration
            for declaration in resource_identity.model_declarations(
                document, "models/schema.yml"
            )
        }

    def test_declaration_order_does_not_decide_the_latest_version(self) -> None:
        self.assertEqual(self.declared["shipments"].resolved_latest(), "4")

    def test_quoted_numeric_versions_still_compare_numerically(self) -> None:
        self.assertEqual(
            self.declared["invoices"].resolved_latest(),
            "10",
            "dbt casts version identifiers to float before comparing them",
        )

    def test_an_arbitrary_string_version_keeps_its_exact_text(self) -> None:
        forecasts = self.by_path["models/forecasts_current.sql"]

        self.assertEqual((forecasts.name, forecasts.version), ("forecasts", "2026-q3"))
        self.assertEqual(forecasts.selector(), "forecasts.v2026-q3")
        self.assertTrue(forecasts.is_latest_version)

    def test_a_string_version_in_a_ref_is_not_truncated(self) -> None:
        refs = resource_identity.parse_refs(
            "select * from {{ ref('forecasts', version='2026-q3') }}"
        )

        self.assertEqual([(ref.name, ref.version) for ref in refs], [("forecasts", "2026-q3")])

    def test_a_slash_bearing_version_survives_parsing(self) -> None:
        refs = resource_identity.parse_refs(
            'select * from {{ ref("orders", v="release/2") }}'
        )

        self.assertEqual([ref.version for ref in refs], ["release/2"])

    def test_a_stale_manifest_cannot_veto_the_current_yaml(self) -> None:
        first = self.by_path["models/orders_v1.sql"]
        second = self.by_path["models/orders_v2.sql"]

        self.assertFalse(first.is_latest_version, "the tree has moved past v1")
        self.assertTrue(second.is_latest_version)
        self.assertEqual(first.identity_evidence, "yaml")

    def test_the_previous_latest_is_kept_as_historical_evidence(self) -> None:
        first = self.by_path["models/orders_v1.sql"]

        self.assertEqual(
            first.prior_latest_version,
            "1",
            "the last build's opinion is recorded, not applied",
        )

    def test_a_corroborating_manifest_still_supplies_the_unique_id(self) -> None:
        first = self.by_path["models/orders_v1.sql"]
        second = self.by_path["models/orders_v2.sql"]

        self.assertEqual(first.unique_id, "model.analytics.orders.v1")
        self.assertIsNone(second.unique_id, "the last build never saw this version")

    def test_without_dbt_ordering_the_first_declared_version_wins(self) -> None:
        """The defect this replaced: `versions[-1]` called 1 the latest of 4,3,2,1."""
        shipments = self.declared["shipments"]

        self.assertEqual(shipments.versions[-1].version, "1")
        self.assertNotEqual(shipments.resolved_latest(), "1")


class EngineAndFunctionTests(unittest.TestCase):
    """Current dbt has an engine question and a function resource type."""

    def test_a_pinned_core_dependency_turns_the_pointer_default_off(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "engine_core")

        self.assertEqual(context.engine, "core")
        self.assertFalse(context.latest_version_pointer_default)
        self.assertEqual(context.pointer_default_evidence, "core default")

    def test_a_pinned_fusion_dependency_turns_the_pointer_default_on(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "engine_fusion")

        self.assertEqual(context.engine, "fusion")
        self.assertTrue(context.latest_version_pointer_default)
        self.assertEqual(context.pointer_default_evidence, "fusion default")

    def test_an_unknown_engine_leaves_the_pointer_default_unknown(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "engine_unknown")

        self.assertEqual(context.engine, "unknown")
        self.assertIsNone(
            context.latest_version_pointer_default,
            "coercing this to false would invent a published relation's absence",
        )
        index = resource_identity.build_index(context)
        latest = next(
            item for item in index.resources if item.path == "models/orders_v2.sql"
        )
        self.assertEqual(
            [(item.enabled, item.evidence) for item in latest.interfaces],
            [(None, "engine unknown")],
        )

    def test_a_human_declared_engine_outranks_dependency_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            shutil.copytree(DBT_FIXTURES / "engine_core", root)
            (root / ".ae").mkdir()
            (root / ".ae" / "project.yml").write_text("engine: fusion\n", encoding="utf-8")
            context = project_context.resolve_project_context(root)

        self.assertEqual(context.engine, "fusion")
        self.assertIn(".ae/project.yml", context.engine_evidence)
        self.assertTrue(context.latest_version_pointer_default)

    def test_an_explicit_project_flag_outranks_the_engine_default(self) -> None:
        context = project_context.resolve_project_context(
            DBT_FIXTURES / "versioned_models"
        )

        self.assertTrue(context.latest_version_pointer_default)
        self.assertEqual(context.pointer_default_evidence, "project flag")

    def test_functions_are_typed_resources_under_their_configured_path(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "functions")
        index = resource_identity.build_index(context)
        functions = {
            resource.path: resource
            for resource in index.by_type(resource_identity.FUNCTION)
            if resource.path
        }

        self.assertEqual(
            functions["functions/cents_to_dollars.sql"].language,
            resource_identity.SQL,
        )
        self.assertEqual(
            functions["functions/normalize_email.js"].language,
            resource_identity.JAVASCRIPT,
        )
        self.assertEqual(
            functions["functions/order_total.py"].language,
            resource_identity.PYTHON,
        )

    def test_two_overloads_share_one_dag_identity(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "functions")
        index = resource_identity.build_index(context)
        overloads = [
            resource
            for resource in index.by_type(resource_identity.FUNCTION)
            if resource.name == "cents_to_dollars"
        ]

        self.assertGreaterEqual(len(overloads), 2, "each definition is its own file")
        self.assertEqual({resource.selector() for resource in overloads}, {"cents_to_dollars"})
        signatures = {
            resource.signature for resource in overloads if resource.signature
        }
        self.assertEqual(
            signatures,
            {"cents_to_dollars(bigint) -> numeric", "cents_to_dollars(numeric) -> numeric"},
        )

    def test_a_changed_function_gets_a_bounded_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "functions")
            definition = root / "functions" / "cents_to_dollars.sql"
            definition.write_text(
                definition.read_text(encoding="utf-8") + "\n-- changed\n", encoding="utf-8"
            )
            plan = planner.plan_validation(root, target="dev", intent="build")

        build = next(
            step for step in plan["validation_steps"] if step["operation"] == "model_validation"
        )
        self.assertEqual(build["selectors"], ["cents_to_dollars"])

    def test_a_deleted_function_says_its_callers_cannot_be_proven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "functions")
            (root / "functions" / "normalize_email.js").unlink()
            plan = planner.plan_validation(root, target="dev", intent="build")

        deletion = plan["scope"]["unresolvable_deletions"][0]
        self.assertEqual(deletion["resource_type"], "function")
        self.assertEqual(deletion["name"], "normalize_email")
        self.assertIn("arbitrary SQL", deletion["reason"])


class GuardsAreLoadBearingTests(unittest.TestCase):
    """Disable each new guard and confirm the bad outcome comes back.

    A passing assertion proves nothing on its own; it may be passing because the
    input never reached the code it claims to exercise. Each case here removes
    the guard and shows the failure it was written to prevent.
    """

    def test_without_sibling_isolation_a_foreign_path_resolves_into_this_project(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "monorepo/finance")
        foreign = "tests/fixtures/dbt/monorepo/marketing/models/stg_campaigns.sql"

        self.assertIsNone(context.relative_to_project(foreign))

        context.sibling_projects = ()
        relative = (
            (context.git_root / foreign).resolve().relative_to(context.dbt_root.parent).as_posix()
        )
        self.assertTrue(
            relative.startswith("marketing/"),
            "without the sibling list this path is simply joined onto the wrong root",
        )

    def test_without_the_packages_exclusion_vendored_macros_become_house_code(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "monorepo/finance")
        vendored = "vendor/dbt_utils/macros/surrogate_key.sql"

        self.assertFalse(context.layout.is_own_code(vendored))

        context.layout.vendored_prefixes = frozenset()
        self.assertTrue(
            context.layout.is_own_code(vendored),
            "the exclusion, not the path shape, is what keeps packages out",
        )

    def test_without_the_pii_name_patterns_a_salary_range_is_published(self) -> None:
        profile_dataset = load_module("scripts/profile_dataset.py", "profile_dataset_mutation")
        path = FIXTURES / "data" / "numeric_pii.csv"

        guarded = profile_dataset.profile_dataset(path)
        guarded_columns = {column["name"]: column for column in guarded["columns"]}
        self.assertNotIn("numeric_max", guarded_columns["annual_salary"])

        profile_dataset.PII_NAME_PATTERNS = {}
        profile_dataset.PII_VALUE_PATTERNS = {}
        unguarded = profile_dataset.profile_dataset(path)
        unguarded_columns = {column["name"]: column for column in unguarded["columns"]}
        self.assertEqual(
            unguarded_columns["annual_salary"]["numeric_max"],
            158000.0,
            "the name patterns are the only thing suppressing this range",
        )

    def test_without_alias_resolution_a_freshness_contract_becomes_a_string(self) -> None:
        text = (DBT_FIXTURES / "modern_yaml" / "models" / "schema.yml").read_text(
            encoding="utf-8"
        )
        module = load_module("scripts/infer_conventions.py", "infer_conventions_mutation")
        module.ALIAS_VALUE = re.compile(r"^(?!)$")
        orders = module.parse_yaml(text)["sources"][0]["tables"][0]

        self.assertEqual(
            orders["freshness"],
            "*standard_freshness",
            "declining to resolve the alias is what silently dropped the contract",
        )

    def test_without_merge_precedence_the_documents_own_key_loses(self) -> None:
        text = (DBT_FIXTURES / "modern_yaml" / "models" / "schema.yml").read_text(
            encoding="utf-8"
        )
        module = load_module("scripts/infer_conventions.py", "infer_conventions_merge")
        original = module._parse_mapping

        # Reverse the rule instead of removing it: apply merges over the
        # explicit keys and the source's own six-hour threshold disappears.
        def wrong_precedence(lines, indent, anchors):
            explicit = original(lines, indent, anchors)
            sources = [
                value
                for _, line in lines
                if (match := module.KEY_LINE.match(line))
                and match.group(1).strip() == "<<"
                for value in module._merge_sources((match.group(2) or "").strip(), anchors)
            ]
            for source in sources:
                explicit.update(source)
            return explicit

        module._parse_mapping = wrong_precedence
        try:
            document = module.parse_yaml(text)
        finally:
            module._parse_mapping = original
        freshness = document["sources"][0]["tables"][2]["freshness"]

        self.assertEqual(
            freshness["error_after"],
            {"count": 24, "period": "hour"},
            "letting a merged mapping win is what discarded the declared 6 hours",
        )

    def test_without_the_single_empty_array_rule_no_rows_becomes_one_row(self) -> None:
        module = load_module("scripts/profile_dataset.py", "profile_dataset_empty")
        original = module._records_from_json

        def ignore_single_empty(value, record_path, notes):
            if isinstance(value, dict) and not record_path:
                return [value]
            return original(value, record_path, notes)

        module._records_from_json = ignore_single_empty
        report = module.profile_dataset(FIXTURES / "data" / "single_empty_array.json")

        self.assertEqual(
            report["row_count"],
            1,
            "profiling the wrapper is what invented a row the extract never returned",
        )
        self.assertIn("generated_at", [column["name"] for column in report["columns"]])

    def test_without_engine_awareness_an_unknown_pointer_reads_as_absent(self) -> None:
        context = project_context.resolve_project_context(DBT_FIXTURES / "engine_unknown")

        self.assertIsNone(context.latest_version_pointer_default)
        self.assertIs(
            bool(context.latest_version_pointer_default),
            False,
            "collapsing the third state to a boolean is what asserted no pointer exists",
        )

    def test_without_the_version_in_the_key_two_versions_become_one_resource(self) -> None:
        identity = load_module("scripts/resource_identity.py", "resource_identity_mutation")
        context = project_context.resolve_project_context(DBT_FIXTURES / "versioned_models")
        index = identity.build_index(context)
        versions = [
            resource
            for resource in index.resources
            if resource.name == "orders" and resource.resource_type == "model"
        ]

        self.assertEqual(len({resource.key for resource in versions}), len(versions))

        keys = {(resource.resource_type, resource.package, resource.name) for resource in versions}
        self.assertEqual(
            len(keys),
            1,
            "dropping the version from the key is what collapsed v1 and v2 into one model",
        )

    def test_without_dual_identity_a_rename_looks_like_a_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "monorepo")
            finance = root / "finance"
            staging = finance / "transform" / "staging"
            git(root, "mv", str(staging / "stg_invoices.sql"), str(staging / "stg_bills.sql"))
            scope = git_scope.collect_scope(
                project_context.resolve_project_context(finance)
            )

        renamed = [change for change in scope.changes if change.is_rename]
        self.assertEqual(len(renamed), 1)
        change = renamed[0]
        self.assertTrue(change.path.endswith("stg_bills.sql"))
        self.assertTrue(str(change.original_path).endswith("stg_invoices.sql"))
        self.assertNotEqual(
            change.path,
            change.original_path,
            "reading only the new path is what turned a rename into a deleted stg_bills",
        )

    def test_without_multiple_deltas_one_yaml_owes_one_obligation(self) -> None:
        change = planner.YamlChange(
            deltas=[
                planner.YamlDelta(kind="test_only", models=["fct_revenue"]),
                planner.YamlDelta(
                    kind="source_freshness",
                    sources=[{"source": "raw", "table": "invoices"}],
                ),
            ]
        )

        self.assertEqual(len(change.deltas), 2)
        self.assertEqual(
            change.kind,
            "source_freshness",
            "the single legacy kind is exactly the field that used to swallow the "
            "other obligation in the same document",
        )

    def test_without_the_compatibility_matrix_a_test_becomes_a_freshness_command(self) -> None:
        self.assertIsNone(
            planner.operation_verb("test", "source_freshness"),
            "a freshness request cannot turn a test selector into a freshness command",
        )
        self.assertEqual(
            planner.operation_verb("source_freshness", "source_freshness"),
            "source freshness",
        )
        self.assertEqual(
            planner.operation_verb("test", "build"),
            "test",
            "a broader request does not promote a test operation into a build",
        )

    def test_without_version_level_yaml_diffing_one_edit_obliges_every_version(self) -> None:
        """The defect this replaced: the diff compared whole `models:` entries."""
        before = {
            "models": [
                {"name": "orders", "versions": [{"v": 1}, {"v": 2}]},
            ]
        }
        current = {
            "models": [
                {
                    "name": "orders",
                    "versions": [{"v": 1, "columns": [{"name": "amount"}]}, {"v": 2}],
                }
            ]
        }

        self.assertEqual(
            [ref.selector() for ref in planner._changed_model_refs(before, current)],
            ["orders.v1"],
        )
        self.assertEqual(
            planner._changed_model_names(before, current),
            ["orders"],
            "the bare-name view is what used to reach both versions",
        )

    def test_without_typed_consumers_a_source_change_selects_every_version(self) -> None:
        context = project_context.resolve_project_context(
            DBT_FIXTURES / "versioned_models"
        )
        index = resource_identity.build_index(context)
        consumers = planner._source_consumers(
            index, [{"source": "raw", "table": "payments"}]
        )

        self.assertEqual(
            [item.selector() for item in consumers], ["customer_lifetime", "orders.v1"]
        )
        self.assertEqual(
            sorted({item.name for item in consumers}),
            ["customer_lifetime", "orders"],
            "flattening to names is what put every version of orders back in scope",
        )


if __name__ == "__main__":
    unittest.main()
