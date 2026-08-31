from __future__ import annotations

import unittest

from test_support import PLUGIN_ROOT


class DayToDayWorkflowContractTests(unittest.TestCase):
    def skill(self, name: str) -> str:
        return (PLUGIN_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8").lower()

    def assert_terms(self, skill: str, *terms: str) -> None:
        text = self.skill(skill)
        for term in terms:
            with self.subTest(skill=skill, term=term):
                self.assertIn(term.lower(), text)

    def test_source_setup_covers_identity_freshness_and_staging_handoff(self) -> None:
        self.assert_terms(
            "source-setup",
            "identifier",
            "loaded_at_field",
            "freshness",
            "source(",
            "staging",
            "promise",
        )

    def test_documentation_separates_business_meaning_from_implementation(self) -> None:
        self.assert_terms(
            "model-documentation",
            "business",
            "implementation",
            "grain",
            "column",
            "approval",
        )

    def test_model_tests_are_derived_from_grain_and_specific_risk(self) -> None:
        self.assert_terms(
            "model-tests",
            "grain",
            "unique",
            "not_null",
            "relationships",
            "accepted-value",
            "risk",
        )

    def test_refactor_and_migration_have_different_contracts(self) -> None:
        self.assert_terms(
            "refactor-model",
            "preserve",
            "output contract",
            "grain",
            "lineage",
            "approval",
        )
        self.assert_terms(
            "migration-plan",
            "breaking",
            "compatibility",
            "cutover",
            "rollback",
            "deprecat",
        )

    def test_rename_scans_cross_layer_consumers(self) -> None:
        self.assert_terms(
            "rename-model",
            "sql",
            "yaml",
            "metric",
            "exposure",
            "lookml",
            "python",
            "downstream",
        )
        rename = self.skill("rename-model")
        self.assertIn("column", rename)
        self.assertIn("private/internal", rename)
        self.assertIn("published", rename)

    def test_incremental_design_handles_late_data_and_replay(self) -> None:
        self.assert_terms(
            "incremental-model",
            "unique_key",
            "late-arriving",
            "lookback",
            "idempot",
            "on_schema_change",
            "full-refresh",
        )
        incremental = self.skill("incremental-model")
        for critical_fact in ("change or disappear", "timestamp advances", "late changes"):
            self.assertIn(critical_fact, incremental)

    def test_question_policy_allows_unknown_correctness_critical_runtime_facts(self) -> None:
        policy = (PLUGIN_ROOT / "rules" / "ae-conventions.mdc").read_text(encoding="utf-8")

        self.assertIn("correctness-critical business or runtime facts", policy)
        self.assertIn("source mutation", policy)
        self.assertIn("hard/soft-delete", policy)
        self.assertIn("watermark", policy)
        self.assertNotIn("These four questions", policy)

    def test_build_model_treats_unprefixed_final_models_as_evidence(self) -> None:
        build = self.skill("build-model")

        self.assertIn("unprefixed final layer", build)
        self.assertIn("neighboring final models", build)
        self.assertIn("not an absence", build)

    def test_project_brain_separates_house_style_from_source_contracts(self) -> None:
        profile = self.skill("project-profile")
        source = self.skill("source-setup")

        self.assertIn("house conventions", profile)
        self.assertIn("observed resource patterns/contracts", profile)
        self.assertIn("never turn their majority into a default", profile)
        self.assertIn("not global house conventions", source)

    def test_metric_semantic_and_bi_boundaries_are_explicit(self) -> None:
        self.assert_terms(
            "metric-definition",
            "grain",
            "population",
            "time",
            "aggregation",
            "unit",
            "owner",
        )
        self.assert_terms(
            "semantic-layer",
            "semantic model",
            "entity",
            "metricflow",
            "repository",
        )
        self.assert_terms(
            "bi-model",
            "lookml",
            "join",
            "relationship",
            "measure",
            "existing",
        )

    def test_freshness_distinguishes_configured_from_observed_timing(self) -> None:
        self.assert_terms(
            "freshness-investigation",
            "configured",
            "observed",
            "source",
            "orchestration",
            "bi",
            "never",
        )

    def test_yaml_maintenance_preserves_human_structure(self) -> None:
        self.assert_terms(
            "yaml-maintenance",
            "comment",
            "anchor",
            "order",
            "split",
            "merge",
            "approval",
        )

    def test_creation_outputs_hide_framework_language(self) -> None:
        for name in (
            "build-model",
            "source-setup",
            "model-documentation",
            "model-tests",
            "yaml-maintenance",
            "refactor-model",
            "incremental-model",
            "metric-definition",
            "semantic-layer",
            "bi-model",
            "validate-dbt",
        ):
            text = self.skill(name)
            output = text.split("## output", 1)[-1].split("## verification", 1)[0]
            with self.subTest(skill=name):
                self.assertNotIn("mode;", output)
                for heading in ("changed", "why", "verified", "remaining uncertainty"):
                    self.assertIn(heading, output)

    def test_reversible_edits_do_not_require_a_second_approval(self) -> None:
        ordinary_writers = {
            "source-setup",
            "model-documentation",
            "model-tests",
            "refactor-model",
            "incremental-model",
            "semantic-layer",
            "bi-model",
            "yaml-maintenance",
        }
        for name in sorted(ordinary_writers):
            text = self.skill(name)
            with self.subTest(skill=name):
                self.assertIn("second approval", text)

        safety = (PLUGIN_ROOT / "rules" / "data-safety.mdc").read_text(encoding="utf-8").lower()
        self.assertIn("explicit user request", safety)
        self.assertIn("without asking for a second", safety)
        for guarded in ("renaming", "deleting", "published contract", "warehouse access", "external transmission"):
            self.assertIn(guarded, safety)

        for name in ("rename-model", "migration-plan", "validate-dbt"):
            with self.subTest(risky_skill=name):
                self.assertIn("approval", self.skill(name))

    def test_every_convention_dependent_skill_names_the_inference_command(self) -> None:
        """A workflow that only alludes to inference tends to skip it.

        "Use static convention inference" reads like an instruction but names
        nothing to run, so the agent substitutes glancing at a couple of files and
        then guesses a prefix the repository could have told it. The script is what
        produces the support counts these skills report, so each one has to name it.
        """
        for name in (
            "source-setup",
            "model-documentation",
            "model-tests",
            "yaml-maintenance",
            "refactor-model",
            "rename-model",
            "migration-plan",
            "incremental-model",
        ):
            with self.subTest(skill=name):
                self.assertIn("scripts/infer_conventions.py", self.skill(name))

    def test_a_non_dbt_repository_does_not_become_a_dbt_one(self) -> None:
        """Empty inference means the project is not dbt, not that it has no conventions."""
        conventions = (PLUGIN_ROOT / "rules" / "ae-conventions.mdc").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn("is_dbt_project", conventions)
        self.assertIn("inspect_repo.py", conventions)
        self.assertIn("ref()", conventions)

    def test_creation_commands_do_not_stack_a_review_persona(self) -> None:
        """Stacking the reviewer onto a build turns "write this model" into an audit.

        The reviewer agent requires Evidence/Risk/Recommendation/Verification with
        severity and confidence on every finding, which is right for a review and
        directly contradicts the Changed/Why/Verified contract these commands
        promise. Whichever one wins, the user gets the other one's format.
        """
        for name in ("ae-build-model", "ae-trace", "ae-learn"):
            body = (PLUGIN_ROOT / "commands" / f"{name}.md").read_text(encoding="utf-8")
            with self.subTest(command=name):
                self.assertNotIn("senior-ae-reviewer", body)

        for name in ("ae-review-sql", "ae-review-model", "ae-pr-review", "ae-dbt-health"):
            body = (PLUGIN_ROOT / "commands" / f"{name}.md").read_text(encoding="utf-8")
            with self.subTest(review_command=name):
                self.assertIn("senior-ae-reviewer", body)

    def test_static_dbt_commands_are_governed_consistently(self) -> None:
        """`dbt parse` was banned in one workflow and used in another.

        It costs nothing and touches no warehouse, so the audit's reason for
        declining it is that regenerating artifacts would change the evidence
        under review, not that the command is dangerous. Saying that plainly is
        what stops the toolkit from looking arbitrary across two workflows.
        """
        health = self.skill("dbt-health")
        self.assertIn("dbt parse", health)
        self.assertIn("static", health)
        self.assertIn("initiative", health)
        self.assertIn("dbt parse", self.skill("validate-dbt"))

    def test_review_length_follows_the_change_not_the_template(self) -> None:
        for name in ("sql-review", "data-model-review"):
            with self.subTest(skill=name):
                text = self.skill(name)
                self.assertIn("omit the heading", text)
                self.assertIn("formal review", text)

    def test_project_profile_persistence_is_opt_in(self) -> None:
        conventions = (PLUGIN_ROOT / "rules" / "ae-conventions.mdc").read_text(
            encoding="utf-8"
        ).lower()
        profile = self.skill("project-profile")
        self.assertIn("inference ephemeral by default", conventions)
        self.assertIn("do not add `.ae/project.yml`", conventions)
        self.assertIn("explicitly asks to persist or share", profile)


if __name__ == "__main__":
    unittest.main()
