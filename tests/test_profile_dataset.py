from __future__ import annotations

import json
import unittest

from test_support import FIXTURES, load_module, run_python


profile_dataset = load_module("scripts/profile_dataset.py", "profile_dataset")


class ProfileDatasetTests(unittest.TestCase):
    def test_nulls_duplicates_and_spelling_variants(self) -> None:
        report = profile_dataset.profile_dataset(
            FIXTURES / "data" / "nulls_duplicates_variants.csv"
        )
        columns = {column["name"]: column for column in report["columns"]}

        self.assertEqual(report["format"], "csv")
        self.assertEqual(report["row_count"], 8)
        self.assertEqual(report["duplicate_rows"], 2)
        self.assertEqual(report["duplicate_row_groups"], 1)
        self.assertEqual(columns["amount"]["null_count"], 5)
        self.assertEqual(columns["optional_note"]["null_percent"], 100.0)
        self.assertGreaterEqual(
            len(report["suspicious_categorical_variants"]), 2
        )
        self.assertNotIn("sample_values", json.dumps(report))

    def test_candidate_primary_key_is_reported_as_provisional(self) -> None:
        report = profile_dataset.profile_dataset(
            FIXTURES / "data" / "candidate_primary_key.csv"
        )
        columns = {column["name"]: column for column in report["columns"]}

        self.assertIn("event_id", report["possible_keys"])
        self.assertTrue(columns["event_id"]["possible_key"])
        self.assertEqual(columns["event_id"]["null_count"], 0)
        self.assertEqual(columns["event_id"]["unique_count"], report["row_count"])

    def test_jsonl_supports_blank_lines_nested_values_and_dates(self) -> None:
        report = profile_dataset.profile_dataset(
            FIXTURES / "data" / "practical_records.jsonl"
        )
        columns = {column["name"]: column for column in report["columns"]}

        self.assertEqual(report["format"], "jsonl")
        self.assertEqual(report["row_count"], 3)
        self.assertEqual(columns["observed_at"]["inferred_type"], "datetime")
        self.assertEqual(columns["metadata"]["null_count"], 2)
        self.assertEqual(columns["metadata"]["inferred_type"], "object")
        self.assertEqual(columns["score"]["null_count"], 1)
        self.assertTrue(columns["record_id"]["possible_key"])

    def test_json_object_with_one_record_array_profiles_array_rows(self) -> None:
        report = profile_dataset.profile_dataset(
            FIXTURES / "data" / "wrapped_records.json"
        )
        columns = {column["name"]: column for column in report["columns"]}

        self.assertEqual(report["row_count"], 2)
        self.assertEqual(report["column_count"], 3)
        self.assertTrue(columns["id"]["possible_key"])
        self.assertFalse(columns["id"]["potential_pii"])
        self.assertEqual(columns["updated_at"]["inferred_type"], "datetime")

    def test_cli_emits_deterministic_json(self) -> None:
        path = FIXTURES / "data" / "candidate_primary_key.csv"
        first = run_python("scripts/profile_dataset.py", str(path), "--pretty")
        second = run_python("scripts/profile_dataset.py", str(path), "--pretty")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue(json.loads(first.stdout)["ok"])

    def test_a_numeric_personal_column_reports_shape_without_reporting_range(self) -> None:
        report = profile_dataset.profile_dataset(FIXTURES / "data" / "numeric_pii.csv")
        columns = {column["name"]: column for column in report["columns"]}

        for name in ("ssn", "annual_salary", "account_balance"):
            with self.subTest(column=name):
                self.assertTrue(columns[name]["potential_pii"])
                self.assertEqual(columns[name]["numeric_range_suppressed"], "potential_pii")
                self.assertNotIn("numeric_min", columns[name])
                self.assertNotIn("numeric_max", columns[name])
                self.assertNotIn("outliers", columns[name])

        # Suppression has to stop somewhere, or the profile stops being useful.
        self.assertFalse(columns["order_count"]["potential_pii"])
        self.assertEqual(columns["order_count"]["numeric_max"], 11.0)
        self.assertFalse(columns["customer_id"]["potential_pii"])

    def test_a_sentinel_is_reported_as_a_sentinel_and_not_counted_as_a_null(self) -> None:
        report = profile_dataset.profile_dataset(FIXTURES / "data" / "null_sentinels.csv")
        columns = {column["name"]: column for column in report["columns"]}

        status = columns["status"]
        self.assertEqual(status["null_count"], 0, "no cell in this column is empty")
        self.assertEqual(status["sentinel_null_count"], 3)
        self.assertEqual(set(status["sentinel_null_values"]), {"-", "N/A", "unknown"})
        self.assertEqual(status["missing_count"], 3)

        shipped = columns["shipped_at"]
        self.assertEqual(shipped["null_count"], 1, "one cell is genuinely empty")
        self.assertEqual(shipped["sentinel_null_count"], 2)
        self.assertEqual(shipped["missing_count"], 3)

    def test_duplicate_and_blank_headers_are_renamed_on_the_record(self) -> None:
        report = profile_dataset.profile_dataset(
            FIXTURES / "data" / "duplicate_and_blank_headers.csv"
        )
        names = [column["name"] for column in report["columns"]]
        normalizations = {
            entry["renamed_to"]: entry for entry in report["header_normalizations"]
        }

        self.assertEqual(names, ["order_id", "amount", "column_3", "amount_2", "column_5"])
        self.assertEqual(normalizations["amount_2"]["reason"], "duplicate_header")
        self.assertEqual(normalizations["amount_2"]["original"], "amount")
        self.assertEqual(normalizations["column_3"]["reason"], "blank_header")

    def test_two_plausible_record_arrays_are_a_question_not_a_guess(self) -> None:
        path = FIXTURES / "data" / "two_record_arrays.json"

        with self.assertRaises(profile_dataset.ProfileError) as raised:
            profile_dataset.profile_dataset(path)
        message = str(raised.exception)
        self.assertIn("orders", message)
        self.assertIn("customers", message)
        self.assertIn("--record-path", message)

        chosen = profile_dataset.profile_dataset(path, record_path="customers")
        self.assertEqual(chosen["record_path"], "customers")
        self.assertEqual(chosen["row_count"], 3)
        self.assertEqual(
            [column["name"] for column in chosen["columns"]], ["customer_id", "region"]
        )

    def test_a_document_of_only_empty_arrays_is_not_one_record(self) -> None:
        with self.assertRaises(profile_dataset.ProfileError) as raised:
            profile_dataset.profile_dataset(FIXTURES / "data" / "only_empty_arrays.json")
        message = str(raised.exception)
        self.assertIn("customers", message)
        self.assertIn("orders", message)
        self.assertIn("--record-path", message)

    def test_one_empty_array_is_an_extract_that_returned_no_rows(self) -> None:
        report = profile_dataset.profile_dataset(
            FIXTURES / "data" / "single_empty_array.json"
        )

        self.assertEqual(report["record_path_inferred"], "customers")
        self.assertEqual(report["row_count"], 0)
        self.assertEqual(
            report["columns"],
            [],
            "profiling the wrapper would report one row and a generated_at column",
        )

    def test_blank_csv_lines_are_formatting_not_missing_data(self) -> None:
        report = profile_dataset.profile_dataset(FIXTURES / "data" / "blank_rows.csv")

        self.assertEqual(report["row_count"], 3)
        self.assertEqual(report["blank_rows_skipped"], 2)
        for column in report["columns"]:
            self.assertEqual(column["missing_count"], 0, column["name"])

    def test_na_is_reported_as_a_category_and_as_a_hypothesis(self) -> None:
        report = profile_dataset.profile_dataset(
            FIXTURES / "data" / "legitimate_na_category.csv"
        )
        country = {column["name"]: column for column in report["columns"]}["country"]

        self.assertEqual(country["observed"]["cardinality"], 4)
        self.assertEqual(country["observed"]["non_null_count"], 4)
        self.assertEqual(country["cardinality"], 3)
        self.assertEqual(country["missing_count"], 1)
        self.assertIn("4 observed categories", country["null_interpretation_note"])
        self.assertIn("3 substantive categories", country["null_interpretation_note"])

    def test_observed_typing_does_not_discard_sentinels(self) -> None:
        report = profile_dataset.profile_records(
            [{"code": "1"}, {"code": "2"}, {"code": "NA"}]
        )
        code = report["columns"][0]

        self.assertEqual(code["inferred_type"], "integer")
        self.assertEqual(
            code["observed"]["inferred_type"],
            "mixed",
            "treating NA as missing hid that the column is not uniformly numeric",
        )

    def test_invalid_jsonl_fails_with_actionable_error(self) -> None:
        with self.assertRaises(profile_dataset.ProfileError):
            profile_dataset.load_dataset(
                FIXTURES / "sql" / "correct_query.sql", input_format="jsonl"
            )


if __name__ == "__main__":
    unittest.main()
