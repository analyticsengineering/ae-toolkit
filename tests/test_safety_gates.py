from __future__ import annotations

import json
import unittest

from test_support import FIXTURES, PLUGIN_ROOT, load_module, read_json, run_python


safety_gate = load_module("hooks/safety_gate.py", "safety_gate")
cloud_data_gate = load_module("hooks/cloud_data_gate.py", "cloud_data_gate")


class ShellSafetyGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = read_json(FIXTURES / "safety" / "cases.json")

    def test_fixture_commands_have_exact_decisions(self) -> None:
        for case in self.cases["shell"]:
            with self.subTest(command=case["command"]):
                decision = safety_gate.classify(case["command"])
                self.assertEqual(decision["permission"], case["permission"])
                self.assertEqual(decision["reason_code"], case["reason_code"])

    def test_database_mutations_and_forced_clean_are_denied(self) -> None:
        cases = {
            "git clean -fdx": "destructive-git-clean",
            "DELETE FROM analytics.orders": "database-mutation",
            "mysql -e 'TRUNCATE TABLE events'": "destructive-database-ddl",
            "bq query 'ALTER TABLE x SET OPTIONS()'": "database-mutation",
        }
        for command, reason in cases.items():
            with self.subTest(command=command):
                result = safety_gate.classify(command)
                self.assertEqual(result["permission"], "deny")
                self.assertEqual(result["reason_code"], reason)

    def test_safe_local_operations_are_allowed(self) -> None:
        for command in (
            "python3 scripts/inspect_repo.py .",
            "git status --short",
            "git diff --check",
            "ls tests/fixtures",
        ):
            with self.subTest(command=command):
                self.assertEqual(safety_gate.classify(command)["permission"], "allow")

    def test_the_statement_class_survives_a_harmless_looking_prefix(self) -> None:
        cases = {
            "select * from orders": "select",
            "EXPLAIN SELECT 1": "explain",
            "explain analyze delete from orders": "delete",
            "with recent as (select 1) select * from recent": "select",
            "with recent as (select 1) delete from orders using recent": "delete",
            "create table t as select 1": "create",
            "show tables": "show",
            "select * into surprise from orders": "select-into",
            "explain select * into surprise from orders": "select-into",
            "select * from orders into outfile '/tmp/o.csv'": "select-into",
            "select * from orders where region in (select region from allowed)": "select",
        }
        for statement, expected in cases.items():
            with self.subTest(statement=statement):
                self.assertEqual(safety_gate.sql_statement_class(statement), expected)

    def test_semicolons_only_split_where_the_database_would_split(self) -> None:
        self.assertEqual(
            safety_gate.split_sql_statements("select ';' as delimiter"),
            ["select ';' as delimiter"],
        )
        self.assertEqual(safety_gate.split_sql_statements("select 1;"), ["select 1"])
        self.assertEqual(
            safety_gate.split_sql_statements("select 1; select 2"),
            ["select 1", "select 2"],
        )

    def test_the_allowed_statement_classes_are_exactly_what_the_policy_says(self) -> None:
        """Policy text and enforcement drift apart unless they are compared."""
        self.assertEqual(safety_gate.READ_STATEMENTS, {"select", "explain"})
        for document in ("README.md", "SECURITY.md"):
            text = (PLUGIN_ROOT / document).read_text(encoding="utf-8")
            self.assertIn("`SELECT`", text)
            self.assertIn("`EXPLAIN`", text)
            self.assertNotIn("`SHOW`", text)

    def test_the_documents_claim_eligibility_rather_than_proven_safety(self) -> None:
        """The gate reads syntax. Saying it proves more than that is the defect."""
        side_effecting = "psql -c 'select cleanup_everything()'"
        decision = safety_gate.classify(side_effecting)

        self.assertEqual(
            decision["permission"],
            "ask",
            "a well-formed SELECT that writes is exactly what syntax cannot catch",
        )
        for document in ("README.md", "SECURITY.md"):
            text = (PLUGIN_ROOT / document).read_text(encoding="utf-8")
            self.assertNotIn(
                "prove is a single `SELECT`",
                text,
                f"{document} claims proof the gate cannot supply",
            )
            self.assertIn("syntactic", text, f"{document} must state what the test is")

    def test_removing_single_statement_enforcement_recreates_the_defect(self) -> None:
        attack = "psql -c 'select 1; create table surprise as select 1'"
        self.assertEqual(safety_gate.classify(attack)["permission"], "deny")

        original = safety_gate.split_sql_statements
        safety_gate.split_sql_statements = lambda text: [text]
        try:
            self.assertEqual(safety_gate.classify(attack)["permission"], "ask")
        finally:
            safety_gate.split_sql_statements = original

    def test_hook_entry_point_fails_closed_on_malformed_input(self) -> None:
        result = run_python("hooks/safety_gate.py", stdin="{not json")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["permission"], "deny")
        self.assertEqual(payload["reason_code"], "invalid-hook-input")


class CloudDataGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = read_json(FIXTURES / "safety" / "cases.json")

    def test_connected_content_requires_explicit_approval(self) -> None:
        result = run_python(
            "hooks/cloud_data_gate.py",
            stdin=json.dumps(self.cases["cloud"]),
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["permission"], "ask")
        self.assertEqual(payload["reason_code"], "connected-analysis-approval")
        self.assertIn("$.query", payload["user_message"])
        self.assertIn("No content is sent until you approve", payload["user_message"])

    def test_unrelated_identified_server_is_not_governed(self) -> None:
        result = run_python(
            "hooks/cloud_data_gate.py",
            stdin=json.dumps(self.cases["unrelated_cloud"]),
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["permission"], "allow")
        self.assertEqual(payload["reason_code"], "unrelated-mcp-server")

    def test_secret_detection_recurses_without_network_access(self) -> None:
        secret = "gh" + "p_" + ("C" * 24)
        path = cloud_data_gate.find_secret(
            {"query": "select 1", "nested": [{"access_token": secret}]}
        )
        self.assertEqual(path, "$.nested[0].access_token")

    def test_server_spoofing_and_missing_identity_fail_closed(self) -> None:
        spoofed = {
            "mcp_server_name": "analytics-engineering",
            "mcp_server_url": "https://example.invalid/mcp",
            "tool_input": {},
        }
        for payload, reason in (
            (spoofed, "server-url-mismatch"),
            ({"tool_input": {}}, "missing-server-identity"),
        ):
            with self.subTest(reason=reason):
                result = run_python(
                    "hooks/cloud_data_gate.py", stdin=json.dumps(payload)
                )
                response = json.loads(result.stdout)
                self.assertEqual(response["permission"], "deny")
                self.assertEqual(response["reason_code"], reason)

    def test_string_tool_input_is_parsed_and_content_fields_are_named(self) -> None:
        parsed = cloud_data_gate.parse_tool_input('{"dataset": "orders"}')
        self.assertEqual(parsed, {"dataset": "orders"})
        self.assertEqual(cloud_data_gate.content_fields(parsed), (["$.dataset"], False))

    def test_a_preview_that_cannot_show_everything_says_so(self) -> None:
        payload = {"rows": [{"sql": f"select {index}"} for index in range(50)]}
        fields, truncated = cloud_data_gate.content_fields(payload)

        self.assertTrue(truncated, "a walk that stopped early must report that it did")
        self.assertEqual(len(fields), cloud_data_gate.PREVIEW_LIST_LIMIT)
        self.assertEqual(cloud_data_gate.payload_shape(payload), "object with 1 top-level fields")

    def test_the_cloud_gate_uses_the_canonical_secret_scanner(self) -> None:
        token = "gh" + "p_" + ("C" * 32)
        self.assertEqual(
            cloud_data_gate.find_secret({"notes": {"body": f"token {token}"}}),
            "$.notes.body",
        )
        self.assertEqual(cloud_data_gate.find_secret({"api_key": "your_api_key"}), None)


if __name__ == "__main__":
    unittest.main()
