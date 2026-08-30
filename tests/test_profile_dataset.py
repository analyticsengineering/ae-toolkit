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

    def test_invalid_jsonl_fails_with_actionable_error(self) -> None:
        with self.assertRaises(profile_dataset.ProfileError):
            profile_dataset.load_dataset(
                FIXTURES / "sql" / "correct_query.sql", input_format="jsonl"
            )


if __name__ == "__main__":
    unittest.main()
