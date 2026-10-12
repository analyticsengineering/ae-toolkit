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
        for shipped in ("hooks/safety_gate.py", "rules/data-safety.mdc"):
            text = (PLUGIN_ROOT / shipped).read_text(encoding="utf-8")
            self.assertIn(
                "syntactic",
                text,
                f"{shipped} must say what the gate actually establishes",
            )
        for document in ("README.md", "SECURITY.md"):
            text = (PLUGIN_ROOT / document).read_text(encoding="utf-8")
            self.assertNotIn(
                "prove is a single `SELECT`",
                text,
                f"{document} claims proof the gate cannot supply",
            )

    def test_removing_single_statement_enforcement_recreates_the_defect(self) -> None:
        attack = "psql -c 'select 1; create table surprise as select 1'"
        self.assertEqual(safety_gate.classify(attack)["permission"], "deny")

        original = safety_gate.split_sql_statements
        safety_gate.split_sql_statements = lambda text: [text]
        try:
            self.assertEqual(safety_gate.classify(attack)["permission"], "ask")
        finally:
            safety_gate.split_sql_statements = original

    def test_ignoring_leading_assignments_recreates_the_bypass(self) -> None:
        attack = "FOO=1 rm -rf build/"
        self.assertEqual(safety_gate.classify(attack)["permission"], "deny")

        original = safety_gate.ASSIGNMENT
        safety_gate.ASSIGNMENT = safety_gate.re.compile(r"(?!)")
        try:
            self.assertEqual(safety_gate.classify(attack)["permission"], "allow")
        finally:
            safety_gate.ASSIGNMENT = original

    def test_every_launch_spelling_reaches_the_same_dbt_decision(self) -> None:
        """A launcher or alias that changes the decision is a way around the gate."""
        plain = safety_gate.classify("dbt build --select fct_orders")
        for wrapped in (
            "dbtf build --select fct_orders",
            "DBT build --select fct_orders",
            "FOO=1 dbt build --select fct_orders",
            "python3 -m dbt build --select fct_orders",
            "uv run --with dbt-core dbt build --select fct_orders",
            "pipx run dbt build --select fct_orders",
            "conda run -n analytics dbt build --select fct_orders",
            "timeout 600 dbt build --select fct_orders",
        ):
            with self.subTest(command=wrapped):
                self.assertEqual(safety_gate.classify(wrapped), plain)

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

    def gate(self, payload: dict) -> dict:
        result = run_python("hooks/cloud_data_gate.py", stdin=json.dumps(payload))
        self.assertEqual(result.returncode, 0)
        return json.loads(result.stdout)

    def test_dbt_warehouse_tools_require_explicit_approval(self) -> None:
        payload = self.gate(self.cases["cloud"])
        self.assertEqual(payload["permission"], "ask")
        self.assertEqual(payload["reason_code"], "dbt-warehouse-approval")
        self.assertIn("execute_sql", payload["user_message"])
        self.assertIn("Nothing runs until you approve", payload["user_message"])

    def test_every_dbt_tool_that_reaches_the_warehouse_is_held(self) -> None:
        for server, tool in (
            ("dbt", "build"),
            ("dbt-mcp", "run"),
            ("dbt_cloud", "show"),
            ("dbt", "query_metrics"),
            ("dbt", "text_to_sql"),
            ("dbt", "trigger_job_run"),
            ("dbt", "generate_staging_model"),
        ):
            with self.subTest(server=server, tool=tool):
                payload = self.gate(
                    {"mcp_server_name": server, "tool_name": tool, "tool_input": {}}
                )
                self.assertEqual(payload["permission"], "ask")

    def test_host_prefixed_tool_names_and_dbt_hosts_are_recognised(self) -> None:
        prefixed = {"tool_name": "mcp__dbt__build", "mcp_server_name": "dbt", "tool_input": {}}
        by_host = {
            "mcp_server_name": "warehouse-tools",
            "mcp_server_url": "https://abc.us1.dbt.com/api/ai/v1/mcp/",
            "tool_name": "execute_sql",
            "tool_input": {},
        }
        by_launch = {
            "mcp_server_name": "warehouse",
            "command": "uvx dbt-mcp",
            "tool_name": "build",
            "tool_input": {},
        }
        for payload in (prefixed, by_host, by_launch):
            with self.subTest(payload=payload["mcp_server_name"]):
                self.assertEqual(self.gate(payload)["reason_code"], "dbt-warehouse-approval")

    def test_dbt_metadata_reads_are_allowed(self) -> None:
        for tool in ("get_model_details", "list_metrics", "get_model_parents", "parse"):
            with self.subTest(tool=tool):
                payload = self.gate({"mcp_server_name": "dbt", "tool_name": tool, "tool_input": {}})
                self.assertEqual(payload["permission"], "allow")
                self.assertEqual(payload["reason_code"], "dbt-metadata")

    def test_an_unrecognised_dbt_tool_asks_rather_than_assuming_it_is_safe(self) -> None:
        payload = self.gate({"mcp_server_name": "dbt", "tool_name": "materialize_everything", "tool_input": {}})
        self.assertEqual(payload["permission"], "ask")
        self.assertEqual(payload["reason_code"], "dbt-unknown-tool-approval")

    def test_secrets_in_a_dbt_request_are_refused(self) -> None:
        secret = "gh" + "p_" + ("C" * 32)
        payload = self.gate(
            {"mcp_server_name": "dbt", "tool_name": "execute_sql", "tool_input": {"sql": f"select '{secret}'"}}
        )
        self.assertEqual(payload["permission"], "deny")
        self.assertEqual(payload["reason_code"], "potential-secret")

    def test_unrelated_identified_server_is_not_governed(self) -> None:
        payload = self.gate(self.cases["unrelated_cloud"])
        self.assertEqual(payload["permission"], "allow")
        self.assertEqual(payload["reason_code"], "unrelated-mcp-server")

    def test_dbt_is_matched_as_a_word_not_a_substring(self) -> None:
        payload = self.gate({"mcp_server_name": "mydbtools", "tool_name": "run", "tool_input": {}})
        self.assertEqual(payload["reason_code"], "unrelated-mcp-server")

    def test_secret_detection_recurses_without_network_access(self) -> None:
        secret = "gh" + "p_" + ("C" * 24)
        path = cloud_data_gate.find_secret(
            {"query": "select 1", "nested": [{"access_token": secret}]}
        )
        self.assertEqual(path, "$.nested[0].access_token")

    def test_missing_server_identity_fails_closed(self) -> None:
        response = self.gate({"tool_input": {}})
        self.assertEqual(response["permission"], "deny")
        self.assertEqual(response["reason_code"], "missing-server-identity")

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
