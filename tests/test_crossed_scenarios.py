"""Repositories that combine several awkward traits at once.

Every trait covered here already has a fixture that exercises it alone. The
failures worth catching are the ones that only appear in combination: a Python
model is handled, and a custom `model-paths` is handled, but a Python model
under a custom `model-paths` in a project that is not the Git root was not. The
matrix below is curated rather than exhaustive, pairing the dimensions that
actually interact.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_support import FIXTURES, load_module


project_context = load_module("scripts/project_context.py", "project_context")
resource_identity = load_module("scripts/resource_identity.py", "resource_identity")
artifact_inventory = load_module("scripts/artifact_inventory.py", "artifact_inventory")
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
            ["assert_revenue_is_not_negative", "fct_customer_ltv", "fct_revenue"],
            "everything the prior state recorded as a consumer, including the test",
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


class UnsupportedYamlTests(unittest.TestCase):
    """A file the reader cannot interpret must not produce a confident answer."""

    def test_anchors_and_aliases_are_named_rather_than_misread(self) -> None:
        text = (DBT_FIXTURES / "ambiguous_yaml" / "models" / "schema.yml").read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            project_context.unsupported_yaml_constructs(text), ["alias", "anchor"]
        )
        _, constructs = project_context.parse_yaml_checked(text)
        self.assertEqual(constructs, ["alias", "anchor"])

    def test_the_planner_reports_the_construct_instead_of_a_freshness_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_copy(tmp, "ambiguous_yaml")
            schema = root / "models" / "schema.yml"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace("count: 12", "count: 6"),
                encoding="utf-8",
            )
            plan = planner.plan_validation(root, target="dev", intent="build")

        self.assertIn("models/schema.yml", plan["scope"]["unsupported_yaml"])
        self.assertIn("anchor", plan["scope"]["unsupported_yaml"]["models/schema.yml"])


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

        context.layout.vendored_directories = frozenset()
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

    def test_without_the_unsupported_yaml_patterns_an_alias_parses_as_a_string(self) -> None:
        text = (DBT_FIXTURES / "ambiguous_yaml" / "models" / "schema.yml").read_text(
            encoding="utf-8"
        )
        document = infer_conventions.parse_yaml(text)
        orders = document["sources"][0]["tables"][0]

        self.assertEqual(
            orders["freshness"],
            "*standard_freshness",
            "the reader really does return a string here, which is why it must say so",
        )


if __name__ == "__main__":
    unittest.main()
