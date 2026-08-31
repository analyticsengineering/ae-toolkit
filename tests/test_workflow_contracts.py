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

    def test_every_writing_workflow_preserves_the_edit_boundary(self) -> None:
        writers = {
            "source-setup",
            "model-documentation",
            "model-tests",
            "refactor-model",
            "rename-model",
            "incremental-model",
            "semantic-layer",
            "bi-model",
            "yaml-maintenance",
        }
        for name in sorted(writers):
            text = self.skill(name)
            with self.subTest(skill=name):
                self.assertIn("existing", text)
                self.assertIn("approval", text)
                self.assertIn("new file", text)


if __name__ == "__main__":
    unittest.main()
