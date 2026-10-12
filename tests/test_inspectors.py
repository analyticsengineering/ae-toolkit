from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from test_support import FIXTURES, load_module, run_python


inspect_dbt = load_module("scripts/inspect_dbt.py", "inspect_dbt")
infer_conventions = load_module("scripts/infer_conventions.py", "infer_conventions")
inspect_repo = load_module("scripts/inspect_repo.py", "inspect_repo")
inspect_git = load_module("scripts/inspect_git.py", "inspect_git")
redact_secrets = load_module("scripts/redact_secrets.py", "redact_secrets")


class DbtInspectorTests(unittest.TestCase):
    def fixture(self, name: str) -> Path:
        return FIXTURES / "dbt" / name

    def test_clean_project_and_manifest_are_discovered(self) -> None:
        report = inspect_dbt.inspect_dbt(self.fixture("clean_project"))

        self.assertTrue(report["is_dbt_project"])
        self.assertEqual(report["model_tree"]["model_count"], 2)
        self.assertEqual(report["sql_patterns"]["ref_calls"], 1)
        self.assertEqual(report["sql_patterns"]["source_calls"], 1)
        self.assertTrue(report["manifest"]["valid"])
        self.assertEqual(report["manifest"]["node_count"], 2)
        self.assertEqual(report["manifest"]["source_count"], 1)
        self.assertEqual(
            report["manifest"]["models_by_materialization"],
            {"table": 1, "view": 1},
        )

    def test_raw_source_in_mart_fixture_is_visible_to_static_checks(self) -> None:
        report = inspect_dbt.inspect_dbt(self.fixture("raw_source_in_mart"))
        model = report["models"][0]

        self.assertEqual(model["path"], "models/marts/fct_payments.sql")
        self.assertEqual(model["patterns"]["source_calls"], 1)
        self.assertIn(
            "bypasses staging",
            (self.fixture("raw_source_in_mart") / model["path"]).read_text(
                encoding="utf-8"
            ),
        )

    def test_incremental_without_unique_key_fixture(self) -> None:
        root = self.fixture("incremental_missing_unique_key")
        report = inspect_dbt.inspect_dbt(root)
        text = (root / "models" / "fct_events.sql").read_text(encoding="utf-8")

        self.assertEqual(report["configured_materializations"], {"incremental": 1})
        self.assertEqual(report["sql_patterns"]["is_incremental_calls"], 1)
        self.assertIn("materialized='incremental'", text)
        self.assertNotIn("unique_key", text)

    def test_undocumented_source_fixture(self) -> None:
        report = inspect_dbt.inspect_dbt(self.fixture("undocumented_source"))
        yaml_summary = report["yaml_files"][0]

        self.assertEqual(yaml_summary["source_blocks"], 1)
        self.assertEqual(yaml_summary["description_fields"], 0)
        self.assertEqual(report["sql_patterns"]["source_calls"], 1)


class RepositoryInspectorTests(unittest.TestCase):
    def test_repo_inspector_detects_dbt_and_static_signals(self) -> None:
        report = inspect_repo.inspect_repo(FIXTURES / "dbt" / "clean_project")

        self.assertTrue(report["technologies"]["dbt"]["detected"])
        self.assertTrue(report["technologies"]["sql"]["detected"])
        self.assertEqual(report["technologies"]["sql"]["signals"]["dbt_ref"], 1)
        self.assertFalse(report["exercise"]["present"])

    def test_exercise_json_is_recognized_and_validated(self) -> None:
        report = inspect_repo.inspect_repo(FIXTURES / "exercise")

        self.assertTrue(report["exercise"]["present"])
        self.assertTrue(report["exercise"]["valid"], report["exercise"]["errors"])
        self.assertEqual(report["exercise"]["path"], ".ae/exercise.json")
        self.assertIn("mode", report["exercise"]["declared_fields"])
        self.assertIn("exercise_id", report["exercise"]["declared_fields"])
        self.assertIn("skills", report["exercise"]["declared_fields"])
        self.assertIn("course_url", report["exercise"]["declared_fields"])
        self.assertEqual(
            report["exercise"]["metadata"]["exercise_id"], "sql-fanout-001"
        )
        self.assertEqual(report["exercise"]["metadata"]["mode"], "Assessment")

    def test_inspect_repo_cli_is_json_and_read_only(self) -> None:
        result = run_python(
            "scripts/inspect_repo.py", str(FIXTURES / "exercise"), "--pretty"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("not modified", payload["inspection_note"])


class SecretRedactionTests(unittest.TestCase):
    def test_direct_import_detects_and_redacts_without_echoing_secret(self) -> None:
        token = "gh" + "p_" + ("A" * 30)
        source = f'authorization = "Bearer {token}"'
        report = redact_secrets.inspect_text(source)

        self.assertGreaterEqual(report["finding_count"], 1)
        self.assertNotIn(token, json.dumps(report))
        self.assertIn("[REDACTED]", report["redacted_content"])
        self.assertTrue(all(not item["value_emitted"] for item in report["findings"]))

    def test_placeholders_are_not_reported_as_credentials(self) -> None:
        report = redact_secrets.inspect_text('api_key = "your_api_key"')
        self.assertEqual(report["finding_count"], 0)

    def test_cli_findings_only_never_emits_input_content(self) -> None:
        token = "sk_" + "live_" + ("B" * 20)
        result = run_python(
            "scripts/redact_secrets.py",
            "--stdin",
            "--findings-only",
            stdin=("to" + "ken=" + token),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(token, result.stdout)
        self.assertNotIn("redacted_content", result.stdout)
        self.assertGreater(json.loads(result.stdout)["total_findings"], 0)


@unittest.skipUnless(shutil.which("git"), "Git is not available")
class GitInspectorTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )

    def test_temporary_repository_status_and_diffs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.git(root, "init")
            tracked = root / "model.sql"
            tracked.write_text("select 1 as value;\n", encoding="utf-8")
            self.git(root, "add", "model.sql")
            self.git(
                root,
                "-c",
                "user.name=Toolkit Tests",
                "-c",
                "user.email=toolkit-tests@example.invalid",
                "commit",
                "-m",
                "initial fixture",
            )

            tracked.write_text("select 2 as value;\n", encoding="utf-8")
            (root / "notes.txt").write_text("untracked\n", encoding="utf-8")
            report = inspect_git.inspect_git(root)

            self.assertFalse(report["clean"])
            self.assertTrue(report["read_only"])
            self.assertEqual(report["status_counts"]["unstaged"], 1)
            self.assertEqual(report["status_counts"]["untracked"], 1)
            self.assertEqual(report["diffs"]["working_tree"]["file_count"], 1)
            self.assertEqual(report["diffs"]["working_tree"]["additions"], 1)
            self.assertEqual(report["diffs"]["working_tree"]["deletions"], 1)

            self.git(root, "add", "model.sql")
            staged = inspect_git.inspect_git(root)
            self.assertEqual(staged["diffs"]["staged"]["file_count"], 1)
            self.assertEqual(staged["status_counts"]["staged"], 1)

    def test_git_diff_text_fixtures_capture_distinct_review_risk(self) -> None:
        metric = (FIXTURES / "git" / "metric_changing.diff").read_text(
            encoding="utf-8"
        )
        formatting = (FIXTURES / "git" / "safe_formatting.diff").read_text(
            encoding="utf-8"
        )

        self.assertIn("- sum(discount_amount)", metric)
        self.assertIn("as revenue", metric)
        self.assertNotIn("discount_amount", formatting)
        self.assertIn("-select order_id,customer_id", formatting)
        self.assertIn("+    customer_id", formatting)


class ConventionInferenceTests(unittest.TestCase):
    def fixture(self, name: str) -> Path:
        return FIXTURES / "dbt" / name

    def infer(self, name: str) -> dict:
        return infer_conventions.infer_conventions(self.fixture(name))

    def test_repeated_patterns_become_strong_conventions(self) -> None:
        report = self.infer("established_conventions")
        conventions = report["conventions"]

        self.assertEqual(conventions["models"]["staging_prefix"], "stg_")
        self.assertEqual(conventions["models"]["staging_directory"], "models/staging")
        self.assertEqual(
            conventions["surrogate_key"]["macro"], "dbt_utils.generate_surrogate_key"
        )
        self.assertEqual(conventions["tests"]["key"], "data_tests")
        self.assertEqual(conventions["tests"]["primary_key"], ["not_null", "unique"])
        self.assertTrue(conventions["sql"]["leading_commas"])
        self.assertTrue(conventions["sql"]["lowercase_keywords"])
        self.assertEqual(conventions["sql"]["indent_width"], 4)
        source_contracts = report["resource_patterns"]["sources"]
        self.assertTrue(
            all(item["loaded_at_field"] == "_loaded_at" for item in source_contracts)
        )
        self.assertTrue(
            all(item["freshness"]["warn_after"] == "12 hour" for item in source_contracts)
        )
        self.assertNotIn("loaded_at_field", conventions["sources"])
        self.assertNotIn("freshness_warn_after", conventions["sources"])
        self.assertFalse(conventions["sources"]["identifier_required"])
        self.assertEqual(conventions["sources"]["filename_pattern"], "sources.yml")
        self.assertEqual(report["open_questions"], [])

        for key in ("models.staging_prefix", "sql.leading_commas", "surrogate_key.macro"):
            with self.subTest(convention=key):
                observation = report["evidence"][key]
                self.assertEqual(observation["strength"], "strong")
                self.assertEqual(observation["contradicting"], 0)
                self.assertTrue(observation["examples"])

    def test_thin_evidence_stays_weak_rather_than_becoming_settled_practice(self) -> None:
        report = self.infer("clean_project")
        observation = report["evidence"]["models.staging_prefix"]

        self.assertEqual(observation["value"], "stg_")
        self.assertEqual(observation["confidence"], 1.0)
        self.assertEqual(observation["strength"], "weak")

    def test_contradictory_repository_yields_questions_not_guesses(self) -> None:
        report = self.infer("split_conventions")
        contested = {
            "models.staging_prefix",
            "sql.leading_commas",
            "surrogate_key.macro",
            "tests.key",
        }
        asked = {question["convention"] for question in report["open_questions"]}
        self.assertTrue(contested.issubset(asked))

        for key in sorted(contested):
            with self.subTest(convention=key):
                observation = report["evidence"][key]
                self.assertEqual(observation["strength"], "split")
                self.assertIsNone(observation["value"], "a tie must not be resolved silently")
                self.assertGreaterEqual(len(observation["candidates"]), 2)

        self.assertNotIn("staging_prefix", report["conventions"].get("models", {}))
        self.assertNotIn("macro", report["conventions"].get("surrogate_key", {}))
        for question in report["open_questions"]:
            self.assertTrue(question["question"].endswith("?"))

    def test_vendored_packages_do_not_define_house_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            shutil.copytree(self.fixture("established_conventions"), project)
            baseline = infer_conventions.infer_conventions(project)

            vendored = project / "dbt_packages" / "vendor" / "models"
            vendored.mkdir(parents=True)
            (vendored / "schema.yml").write_text(
                "version: 2\nmodels:\n"
                + "".join(
                    f"  - name: vendor_{index}\n"
                    f"    columns:\n"
                    f"      - name: vendor_{index}_id\n"
                    f"        tests:\n          - unique\n"
                    for index in range(6)
                ),
                encoding="utf-8",
            )
            polluted = infer_conventions.infer_conventions(project)

        self.assertEqual(polluted["conventions"], baseline["conventions"])
        self.assertEqual(
            polluted["project"]["excluded_vendored_files"],
            baseline["project"]["excluded_vendored_files"] + 1,
        )
        self.assertEqual(polluted["conventions"]["tests"]["key"], "data_tests")

    def test_uppercase_model_names_are_read_as_conventions_not_as_absence(self) -> None:
        # Snowflake folds unquoted identifiers to upper case, so a project full
        # of STG_ models is as conventional there as stg_ is elsewhere. Reading
        # the prefix as absent would let a later workflow invent a lower case
        # default and write a model that matches nothing around it.
        report = self.infer("uppercase_snowflake")
        conventions = report["conventions"]

        self.assertEqual(conventions["models"]["staging_prefix"], "STG_")
        self.assertEqual(conventions["models"]["fact_prefix"], "FCT_")
        self.assertEqual(conventions["models"]["dimension_prefix"], "DIM_")
        self.assertEqual(report["evidence"]["models.staging_prefix"]["strength"], "strong")
        self.assertFalse(conventions["sql"]["lowercase_keywords"])

    def test_inconsistent_identifier_case_is_reported_rather_than_settled(self) -> None:
        report = self.infer("mixed_case_prefixes")
        prefix = report["evidence"]["models.staging_prefix"]

        self.assertNotEqual(prefix["strength"], "strong")
        self.assertEqual(set(prefix["candidates"]), {"stg_", "STG_"})

    def test_the_warehouse_is_identified_without_a_committed_profile(self) -> None:
        # profiles.yml holds credentials and usually is not committed, so a
        # project that never ships one still has to be recognisable.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            shutil.copytree(self.fixture("uppercase_snowflake"), project)
            self.assertFalse((project / "profiles.yml").exists())

            from_config = infer_conventions.infer_conventions(project)
            self.assertEqual(from_config["project"]["adapter"], "snowflake")

            (project / "requirements.txt").write_text(
                "dbt-core==1.8.7\ndbt-databricks==1.8.5\n", encoding="utf-8"
            )
            from_requirement = infer_conventions.infer_conventions(project)

        # A pinned adapter package outranks a configuration key, which can
        # outlive the migration that left it behind.
        self.assertEqual(from_requirement["project"]["adapter"], "databricks")
        self.assertEqual(from_requirement["project"]["adapter_source"], "requirements.txt")

    def test_two_pinned_adapters_yield_no_warehouse_rather_than_a_guess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "dbt_project.yml").write_text("name: ambiguous\n", encoding="utf-8")
            (project / "models").mkdir()
            (project / "requirements.txt").write_text(
                "dbt-core==1.8.7\ndbt-snowflake==1.8.3\ndbt-bigquery==1.8.2\n", encoding="utf-8"
            )
            report = infer_conventions.infer_conventions(project)

        self.assertIsNone(report["project"]["adapter"])
        self.assertIn("more than one adapter", report["project"]["adapter_source"])

    def test_a_directory_boundary_becomes_a_question_not_a_majority_vote(self) -> None:
        report = self.infer("split_conventions")
        prefix = report["evidence"]["models.staging_prefix"]
        self.assertEqual(prefix["strength"], "split")

        counts = Counter({"stg_": 4, "staging_": 2})
        examples = {
            "stg_": [f"models/current/stg_{name}.sql" for name in "abcd"],
            "staging_": [f"models/archive/staging_{name}.sql" for name in "ef"],
        }
        partitioned = infer_conventions.conclude(counts, examples)
        self.assertTrue(partitioned["partitioned"])
        self.assertEqual(partitioned["strength"], "split")
        self.assertIsNone(partitioned["value"])
        self.assertEqual(partitioned["candidates"], {"stg_": 4, "staging_": 2})

    def test_a_stray_outlier_does_not_unsettle_an_established_convention(self) -> None:
        counts = Counter({"stg_": 20, "staging_": 1})
        examples = {
            "stg_": [f"models/staging/stg_{index}.sql" for index in range(20)],
            "staging_": ["models/scratch/staging_experiment.sql"],
        }
        observation = infer_conventions.conclude(counts, examples)

        self.assertFalse(observation["partitioned"])
        self.assertEqual(observation["strength"], "strong")
        self.assertEqual(observation["value"], "stg_")

    def test_every_open_question_carries_its_competing_candidates(self) -> None:
        report = self.infer("split_conventions")
        self.assertTrue(report["open_questions"])
        for question in report["open_questions"]:
            with self.subTest(convention=question["convention"]):
                counts = question["candidates"]
                self.assertGreaterEqual(len(counts), 2)
                self.assertTrue(all(count > 0 for count in counts.values()))

    def test_inference_reads_the_yaml_shapes_dbt_projects_actually_use(self) -> None:
        document = infer_conventions.parse_yaml(
            (self.fixture("established_conventions") / "models" / "schema.yml").read_text(
                encoding="utf-8"
            )
        )
        models = {model["name"]: model for model in document["models"]}

        self.assertEqual(len(models), 10)
        self.assertEqual(
            models["stg_orders"]["columns"][0]["data_tests"], ["unique", "not_null"]
        )
        relationship = models["fct_orders"]["columns"][1]["data_tests"][0]
        self.assertEqual(relationship["relationships"]["field"], "customer_id")

        sources = infer_conventions.parse_yaml(
            (self.fixture("established_conventions") / "models" / "sources.yml").read_text(
                encoding="utf-8"
            )
        )["sources"]
        self.assertEqual(sources[0]["freshness"]["warn_after"]["count"], 12)
        self.assertEqual(len(sources[0]["tables"]), 5)

    def test_modern_source_config_is_normalized_per_table_not_globalized(self) -> None:
        report = self.infer("modern_source_config")
        contracts = {
            (item["source"], item["table"]): item
            for item in report["resource_patterns"]["sources"]
        }

        self.assertEqual(
            contracts[("jaffle_shop", "raw_orders")]["loaded_at_field"],
            "ordered_at",
        )
        self.assertEqual(
            contracts[("jaffle_shop", "raw_orders")]["freshness"]["warn_after"],
            "12 hour",
        )
        self.assertEqual(
            contracts[("jaffle_shop", "raw_stores")]["loaded_at_field"],
            "opened_at",
        )
        self.assertEqual(
            contracts[("jaffle_shop", "raw_stores")]["freshness"]["warn_after"],
            "24 hour",
        )
        self.assertEqual(
            contracts[("jaffle_shop", "raw_customers")]["loaded_at_field"],
            "_ingested_at",
        )
        self.assertNotIn("loaded_at_field", report["conventions"]["sources"])
        self.assertEqual(
            report["evidence"]["sources.loaded_at_field"]["candidates"],
            {"_ingested_at": 1, "opened_at": 1, "ordered_at": 1},
        )

    def test_documentation_coverage_uses_every_project_model_as_denominator(self) -> None:
        report = self.infer("sparse_documentation")
        evidence = report["evidence"]["documentation.model_descriptions_required"]

        self.assertEqual(evidence["total"], 6)
        self.assertEqual(evidence["candidates"], {"false": 4, "true": 2})
        self.assertFalse(report["conventions"]["documentation"]["model_descriptions_required"])
        self.assertNotIn(
            "column_descriptions_required",
            report["conventions"]["documentation"],
            "listed YAML columns do not establish coverage of model output columns",
        )

    def test_docs_blocks_are_named_and_their_reuse_is_a_convention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            shutil.copytree(self.fixture("clean_project"), project)
            (project / "models" / "docs.md").write_text(
                "{% docs order_id %}\nThe order.\n{% enddocs %}\n\n{%- docs ordered_at -%}\nWhen.\n{%- enddocs -%}\n",
                encoding="utf-8",
            )
            (project / "models" / "_docs_reuse.yml").write_text(
                "version: 2\n\nmodels:\n"
                + "".join(
                    f"  - name: reuse_{index}\n    columns:\n"
                    "      - name: order_id\n        description: '{{ doc(\"order_id\") }}'\n"
                    "      - name: status\n        description: Inline prose for a column with no block.\n"
                    for index in range(5)
                ),
                encoding="utf-8",
            )
            report = infer_conventions.infer_conventions(project)

        blocks = report["project"]["docs_blocks"]
        self.assertEqual(blocks["count"], 2)
        self.assertEqual(blocks["names"], {"order_id": "models/docs.md", "ordered_at": "models/docs.md"})
        evidence = report["evidence"]["documentation.column_docs_blocks"]
        self.assertEqual(evidence["candidates"].get("true"), 5)
        self.assertTrue(report["conventions"]["documentation"]["column_docs_blocks"])

    def test_written_conventions_are_listed_and_said_to_outrank_inference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            shutil.copytree(self.fixture("clean_project"), project)
            (project / "README.md").write_text(
                "# shop\n\n## Conventions\n\n- Staging models are `stg_<source>__<table>`.\n", encoding="utf-8"
            )
            (project / "docs").mkdir(exist_ok=True)
            (project / "docs" / "onboarding.md").write_text("# Onboarding\n\nAsk in the channel.\n", encoding="utf-8")
            report = infer_conventions.infer_conventions(project)

        self.assertEqual(report["project"]["written_conventions"], [{"path": "README.md", "headings": ["Conventions"]}])
        self.assertIn("README.md", report["inference_note"])
        self.assertIn("outranks", report["inference_note"])

    def test_unprefixed_root_marts_are_positive_naming_evidence(self) -> None:
        report = self.infer("legacy_unprefixed_finals")

        self.assertEqual(report["conventions"]["models"]["final_naming"], "unprefixed")
        self.assertEqual(report["conventions"]["models"]["final_directory"], "models")
        self.assertEqual(report["evidence"]["models.final_naming"]["total"], 2)

    def test_saved_queries_alone_still_identify_the_semantic_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            shutil.copytree(self.fixture("clean_project"), project)
            (project / "models" / "saved_queries.yml").write_text(
                "saved_queries:\n  - name: weekly_orders\n",
                encoding="utf-8",
            )
            report = infer_conventions.infer_conventions(project)
            inspection = inspect_dbt.inspect_dbt(project)

        self.assertTrue(report["project"]["semantic_layer"]["detected"])
        self.assertEqual(report["project"]["semantic_layer"]["saved_query_file_count"], 1)
        self.assertTrue(inspection["semantic_layer"]["detected"])

    def test_a_non_dbt_directory_reports_nothing_instead_of_inventing_conventions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = infer_conventions.infer_conventions(tmp)

        self.assertFalse(report["is_dbt_project"])
        self.assertEqual(report["conventions"], {})
        self.assertEqual(report["open_questions"], [])

    def test_rendered_profile_is_readable_and_omits_unsupported_conventions(self) -> None:
        report = self.infer("established_conventions")
        rendered = infer_conventions.to_project_yaml(report)

        self.assertIn("staging_prefix: stg_", rendered)
        self.assertIn("_evidence:", rendered)
        self.assertIn('database: "{{ target.database }}"', rendered)
        self.assertNotIn("open_questions:", rendered)

        split = infer_conventions.to_project_yaml(self.infer("split_conventions"))
        self.assertIn("open_questions:", split)

    def test_the_cli_writes_a_profile_without_clobbering_an_edited_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            shutil.copytree(self.fixture("established_conventions"), project)

            first = run_python("scripts/infer_conventions.py", str(project), "--write")
            self.assertEqual(first.returncode, 0, first.stderr)
            profile = project / ".ae" / "project.yml"
            self.assertTrue(profile.is_file())

            profile.write_text("version: 1\n# hand edited\n", encoding="utf-8")
            second = run_python("scripts/infer_conventions.py", str(project), "--write")
            self.assertEqual(second.returncode, 1)
            self.assertIn("already exists", second.stderr)
            self.assertIn("hand edited", profile.read_text(encoding="utf-8"))

            forced = run_python(
                "scripts/infer_conventions.py", str(project), "--write", "--force"
            )
            self.assertEqual(forced.returncode, 0, forced.stderr)
            self.assertNotIn("hand edited", profile.read_text(encoding="utf-8"))

    def test_profile_fingerprint_detects_repository_drift_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            shutil.copytree(self.fixture("clean_project"), project)
            initial = infer_conventions.infer_conventions(project)
            profile = project / ".ae" / "project.yml"
            profile.parent.mkdir()
            profile.write_text(
                "version: 1\nproject:\n"
                f"  profile_fingerprint: {initial['project']['profile_fingerprint']}\n"
                "conventions:\n  models:\n    staging_prefix: custom_\n",
                encoding="utf-8",
            )

            current = infer_conventions.infer_conventions(project)
            self.assertFalse(current["profile"]["stale"])
            model = project / "models" / "staging" / "stg_orders.sql"
            model.write_text(model.read_text(encoding="utf-8") + "\n-- changed\n", encoding="utf-8")
            changed = infer_conventions.infer_conventions(project)

        self.assertTrue(changed["profile"]["stale"])
        self.assertEqual(
            changed["profile"]["stored_fingerprint"],
            initial["project"]["profile_fingerprint"],
        )

    def test_incremental_semantic_bi_and_orchestration_context_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            shutil.copytree(self.fixture("clean_project"), project)
            incremental = project / "models" / "fct_events.sql"
            incremental.write_text(
                "{{ config(materialized='incremental', incremental_strategy='merge', "
                "unique_key='event_id', on_schema_change='sync_all_columns') }}\n"
                "select event_id, updated_at from {{ ref('stg_orders') }}\n"
                "{% if is_incremental() %}\n"
                "where updated_at >= (select max(updated_at) from {{ this }})\n"
                "{% endif %}\n",
                encoding="utf-8",
            )
            (project / "models" / "semantic.yml").write_text(
                "semantic_models:\n  - name: orders\nmetrics:\n  - name: order_count\n",
                encoding="utf-8",
            )
            (project / "orders.view.lkml").write_text("view: orders {}\n", encoding="utf-8")
            workflows = project / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "dbt.yml").write_text("jobs:\n  build:\n    name: dbt build\n", encoding="utf-8")

            report = infer_conventions.infer_conventions(project)
            inspection = inspect_dbt.inspect_dbt(project)

        self.assertEqual(report["conventions"]["incremental"]["strategy"], "merge")
        self.assertEqual(report["conventions"]["incremental"]["unique_key_style"], "single")
        self.assertEqual(report["conventions"]["incremental"]["on_schema_change"], "sync_all_columns")
        self.assertEqual(report["conventions"]["incremental"]["filter_timestamp"], "updated_at")
        self.assertTrue(report["project"]["semantic_layer"]["detected"])
        self.assertTrue(report["project"]["bi"]["looker_detected"])
        self.assertIn("github-actions", report["project"]["orchestration"])
        self.assertTrue(inspection["semantic_layer"]["detected"])
        self.assertTrue(inspection["bi"]["looker_detected"])


if __name__ == "__main__":
    unittest.main()
