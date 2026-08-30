from __future__ import annotations

import json
import unittest

from test_support import FIXTURES, load_module, read_json, run_python


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
        self.assertEqual(cloud_data_gate.content_fields(parsed), ["$.dataset"])


if __name__ == "__main__":
    unittest.main()
