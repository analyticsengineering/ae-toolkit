from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from test_support import PLUGIN_ROOT, parse_frontmatter, read_json, load_module


EXPECTED_COMMANDS = {
    "ae-api-plan",
    "ae-build-model",
    "ae-capstone-check",
    "ae-dbt-health",
    "ae-debug",
    "ae-diagnostic",
    "ae-doctor",
    "ae-explain",
    "ae-grade",
    "ae-hint",
    "ae-learn",
    "ae-pr-review",
    "ae-profile-data",
    "ae-requirements",
    "ae-review-model",
    "ae-review-sql",
    "ae-trace",
    "ae-validate",
}
FREE_COMMANDS = {
    "ae-review-sql",
    "ae-profile-data",
    "ae-review-model",
    "ae-dbt-health",
    "ae-requirements",
    "ae-explain",
    "ae-learn",
    "ae-build-model",
    "ae-trace",
    "ae-validate",
    "ae-doctor",
}
EXPECTED_SKILLS = {
    "analytics-requirements",
    "api-pipeline",
    "build-model",
    "data-model-review",
    "data-profile",
    "data-quality-investigation",
    "dbt-health",
    "explain-data-code",
    "freshness-investigation",
    "incremental-model",
    "bi-model",
    "metric-definition",
    "migration-plan",
    "model-documentation",
    "model-tests",
    "pr-review",
    "project-profile",
    "refactor-model",
    "rename-model",
    "semantic-layer",
    "source-setup",
    "sql-review",
    "trace-lineage",
    "validate-dbt",
    "yaml-maintenance",
}
EXPECTED_AGENTS = {
    "data-quality-investigator",
    "learning-coach",
    "pipeline-architect",
    "senior-ae-reviewer",
}


class PluginManifestTests(unittest.TestCase):
    def test_plugin_manifest_declares_every_discovery_path(self) -> None:
        manifest = read_json(PLUGIN_ROOT / ".cursor-plugin" / "plugin.json")
        self.assertEqual(manifest["name"], "analytics-engineering-toolkit")
        self.assertEqual(
            {
                key: manifest[key]
                for key in ("rules", "skills", "agents", "commands", "hooks")
            },
            {
                "rules": "rules/",
                "skills": "src/skills/",
                "agents": "agents/",
                "commands": "commands/",
                "hooks": "hooks/hooks.json",
            },
        )
        for key in ("rules", "skills", "agents", "commands"):
            self.assertTrue((PLUGIN_ROOT / manifest[key]).is_dir(), key)
        self.assertTrue((PLUGIN_ROOT / manifest["hooks"]).is_file())
        self.assertNotIn("mcpServers", manifest, "the toolkit ships no MCP server")
        self.assertFalse((PLUGIN_ROOT / "mcp.json").exists())
        self.assertTrue((PLUGIN_ROOT / manifest["logo"]).is_file())

    def test_single_plugin_does_not_ship_marketplace_manifest(self) -> None:
        self.assertFalse(
            (PLUGIN_ROOT / ".cursor-plugin" / "marketplace.json").exists()
        )
        self.assertFalse(
            (PLUGIN_ROOT.parent / ".cursor-plugin" / "marketplace.json").exists()
        )

    def test_exact_command_skill_and_agent_sets(self) -> None:
        commands = {path.stem for path in (PLUGIN_ROOT / "commands").glob("*.md")}
        skills = {
            path.parent.name
            for path in (PLUGIN_ROOT / "src" / "skills").glob("*/SKILL.md")
        }
        agents = {path.stem for path in (PLUGIN_ROOT / "agents").glob("*.md")}
        self.assertEqual(commands, EXPECTED_COMMANDS)
        self.assertEqual(skills, EXPECTED_SKILLS)
        self.assertEqual(agents, EXPECTED_AGENTS)

    def test_free_commands_are_explicitly_local_only(self) -> None:
        self.assertEqual(len(FREE_COMMANDS), 11)
        for command in FREE_COMMANDS:
            text = (PLUGIN_ROOT / "commands" / f"{command}.md").read_text(
                encoding="utf-8"
            )
            with self.subTest(command=command):
                self.assertIn("Never require or call MCP", text)
                self.assertNotIn("Connected Advanced", text)

    def test_course_commands_work_without_a_course_service(self) -> None:
        """There is no course server, so a command that waits for one does nothing."""
        for command in ("ae-hint", "ae-grade", "ae-diagnostic", "ae-capstone-check"):
            text = (PLUGIN_ROOT / "commands" / f"{command}.md").read_text(encoding="utf-8")
            with self.subTest(command=command):
                for phrase in ("Connected Advanced", "uthenticate", "server policy", "server-authoritative"):
                    self.assertNotIn(phrase, text)
        coach = (PLUGIN_ROOT / "agents" / "learning-coach.md").read_text(encoding="utf-8")
        self.assertNotIn("uthenticate", coach)
        self.assertIn("not an official grade", (PLUGIN_ROOT / "commands" / "ae-grade.md").read_text(encoding="utf-8"))

    def test_skills_are_naturally_discoverable_and_default_to_work(self) -> None:
        trigger_terms = {
            "source-setup": "source",
            "model-documentation": "documentation",
            "model-tests": "tests",
            "refactor-model": "refactor",
            "rename-model": "rename",
            "migration-plan": "migration",
            "incremental-model": "incremental",
            "metric-definition": "metric",
            "semantic-layer": "semantic",
            "bi-model": "bi",
            "freshness-investigation": "freshness",
            "yaml-maintenance": "yaml",
            "validate-dbt": "validate",
        }
        for path in sorted((PLUGIN_ROOT / "src" / "skills").glob("*/SKILL.md")):
            with self.subTest(skill=path.parent.name):
                frontmatter = parse_frontmatter(path)
                description = frontmatter["description"].lower()
                body = path.read_text(encoding="utf-8")
                normalized_body = body.replace("*", "").lower()
                self.assertRegex(description, r"\buse (?:when|for|before)\b")
                self.assertNotEqual(frontmatter.get("disable-model-invocation"), "true")
                self.assertIn("silently", normalized_body)
                self.assertIn("work", normalized_body)
                self.assertNotIn("operating mode:", normalized_body)
                expected = trigger_terms.get(path.parent.name)
                if expected:
                    self.assertIn(expected, description)

    def test_all_component_frontmatter_is_complete_and_consistent(self) -> None:
        component_paths = [
            *((PLUGIN_ROOT / "commands").glob("*.md")),
            *((PLUGIN_ROOT / "src" / "skills").glob("*/SKILL.md")),
            *((PLUGIN_ROOT / "agents").glob("*.md")),
        ]
        self.assertEqual(
            len(component_paths),
            len(EXPECTED_COMMANDS) + len(EXPECTED_SKILLS) + len(EXPECTED_AGENTS),
        )
        for path in component_paths:
            with self.subTest(path=path.relative_to(PLUGIN_ROOT)):
                frontmatter = parse_frontmatter(path)
                expected_name = path.parent.name if path.name == "SKILL.md" else path.stem
                self.assertEqual(frontmatter.get("name"), expected_name)
                self.assertTrue(frontmatter.get("description"))
                body = path.read_text(encoding="utf-8").split("---", 2)[-1]
                self.assertIn("#", body)

    def test_rule_frontmatter_and_sql_reference_discovery(self) -> None:
        rules = sorted((PLUGIN_ROOT / "rules").glob("*.mdc"))
        self.assertEqual(
            {path.name for path in rules},
            {"ae-conventions.mdc", "ae-methodology.mdc", "data-safety.mdc"},
        )
        for path in rules:
            frontmatter = parse_frontmatter(path)
            self.assertTrue(frontmatter.get("description"))
            self.assertEqual(frontmatter.get("alwaysApply"), "true")

        sql_skill = PLUGIN_ROOT / "src" / "skills" / "sql-review" / "SKILL.md"
        report_reference = (
            PLUGIN_ROOT / "src" / "skills" / "sql-review" / "references" / "report-format.md"
        )
        self.assertTrue(report_reference.is_file())
        self.assertIn(
            "references/report-format.md", sql_skill.read_text(encoding="utf-8")
        )


class SqlFixtureContractTests(unittest.TestCase):
    def test_all_sql_review_cases_are_present(self) -> None:
        fixture_dir = PLUGIN_ROOT / "tests" / "fixtures" / "sql"
        self.assertEqual(
            {path.name for path in fixture_dir.glob("*.sql")},
            {
                "bad_group_by.sql",
                "correct_query.sql",
                "null_sensitive_filter.sql",
                "one_to_many_fanout.sql",
                "window_function.sql",
            },
        )

    def test_fanout_fixture_and_skill_encode_detection_procedure(self) -> None:
        fixture = (
            PLUGIN_ROOT / "tests" / "fixtures" / "sql" / "one_to_many_fanout.sql"
        ).read_text(encoding="utf-8").lower()
        skill = (
            PLUGIN_ROOT / "src" / "skills" / "sql-review" / "SKILL.md"
        ).read_text(encoding="utf-8").lower()

        self.assertIn("one-to-many", fixture)
        self.assertIn("fans out", fixture)
        self.assertIn("join order_items", fixture)
        self.assertIn("sum(o.order_amount)", fixture)
        for procedure_term in ("record grain changes", "key completeness", "fanout"):
            self.assertIn(procedure_term, skill)
        self.assertIn("many-to-many", skill)
        self.assertIn("do not assume source uniqueness", skill)

    def test_other_sql_fixtures_encode_the_intended_edge_cases(self) -> None:
        fixtures = PLUGIN_ROOT / "tests" / "fixtures" / "sql"
        bad_group = (fixtures / "bad_group_by.sql").read_text(encoding="utf-8").lower()
        null_filter = (fixtures / "null_sensitive_filter.sql").read_text(
            encoding="utf-8"
        ).lower()
        window = (fixtures / "window_function.sql").read_text(encoding="utf-8").lower()
        correct = (fixtures / "correct_query.sql").read_text(encoding="utf-8").lower()

        self.assertIn("order_status", bad_group)
        self.assertNotIn("group by customer_id, order_status", bad_group)
        self.assertIn("<> 'cancelled'", null_filter)
        self.assertIn("three-valued logic", null_filter)
        self.assertIn("row_number() over", window)
        self.assertIn("order by ordered_at desc, order_id desc", window)
        self.assertLess(correct.index("group by order_id"), correct.index("join item_totals"))
        self.assertIn("left join", correct)


class RuntimeConfigurationTests(unittest.TestCase):
    def test_python_hook_requirement_is_explicit_and_fail_closed(self) -> None:
        hooks = read_json(PLUGIN_ROOT / "hooks" / "hooks.json")
        configured = [
            (event, hook)
            for event, hook_group in hooks["hooks"].items()
            for hook in hook_group
        ]
        self.assertEqual(len(configured), 4)
        for event, hook in configured:
            self.assertTrue(hook["command"].startswith("python3 "))
            self.assertIn("${CURSOR_PLUGIN_ROOT}", hook["command"])
            # A message hook that failed closed would stop the person from sending anything.
            self.assertEqual(bool(hook.get("failClosed")), event != "beforeSubmitPrompt")
            self.assertGreater(hook["timeout"], 0)
            self.assertNotIn("fallback", hook["command"].lower())

        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        contributing = (PLUGIN_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("Use `python3`", readme)
        self.assertIn("Python 3 for hooks and tests", contributing)
        for script in [
            *(PLUGIN_ROOT / "hooks").glob("*.py"),
            *(PLUGIN_ROOT / "scripts").glob("*.py"),
        ]:
            self.assertEqual(
                script.read_text(encoding="utf-8").splitlines()[0],
                "#!/usr/bin/env python3",
            )

    def test_reading_a_credential_is_not_reported_as_holding_one(self) -> None:
        """Flagging `api_key=os.environ[...]` teaches people to ignore the scanner.

        The gate uses these findings to decide whether content is safe to send, so
        a detector that fires on the correct way to handle a secret produces
        warnings on files that deserve trust, and the habit it builds is the
        problem: a reader who dismisses the noise dismisses the real finding too.
        Literal secrets must still be caught, which is why both halves are asserted
        together.
        """
        redactor = load_module("scripts/redact_secrets.py", "redactor_under_test")
        for safe in (
            'api_key=os.environ["CURSOR_API_KEY"]',
            'api_key = os.getenv("SERVICE_KEY")',
            "token: process.env.TOKEN",
            'password = "<your-password>"',
        ):
            with self.subTest(safe=safe):
                self.assertEqual([], redactor.findings_for_text(safe))

        # Assembled at runtime so the repository-wide scan below does not flag this
        # file for carrying the examples that prove the scan works.
        for unsafe in (
            "password = " + '"hunter" + "2xyz"'.replace('" + "', ""),
            "api_key: " + '"sk' + "_live_ABCDEFGHIJKLMNOP" + '"',
            "client_secret=" + "aB3xY9zQ" + "1mN7pL2k",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertTrue(redactor.findings_for_text(unsafe), f"missed {unsafe!r}")

    def test_distributed_text_contains_no_obvious_secret_values(self) -> None:
        redactor = load_module("scripts/redact_secrets.py", "contract_redactor")
        excluded_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}
        # None of these are distributed content. Third-party dependencies in
        # particular carry thousands of credential-shaped strings in their own
        # tests and docs, and letting them into this scan produces a failure list
        # long enough that nobody reads it -- which costs exactly the signal the
        # test exists to give.
        excluded_dirs = {"__pycache__", ".git", ".venv", "venv", "node_modules", "runs"}
        findings: dict[str, list[dict[str, object]]] = {}

        for path in PLUGIN_ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() in excluded_suffixes:
                continue
            if excluded_dirs.intersection(path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            detected = redactor.findings_for_text(text)
            if detected:
                findings[path.relative_to(PLUGIN_ROOT).as_posix()] = detected

        self.assertEqual(
            findings,
            {},
            "Potential secret patterns found (values intentionally omitted): "
            + json.dumps(findings, sort_keys=True),
        )

    def test_no_shipped_code_can_open_a_network_connection(self) -> None:
        """Enforce the zero-transmission promise instead of merely asserting it.

        PRIVACY.md commits to no telemetry, and the commitment is credible only
        because a reader can verify it from the source. That makes it a property
        of the code rather than of anyone's intent, so it needs to survive a
        contributor who never opened PRIVACY.md. The single outbound path this
        product ships no MCP server either; any server a team adds is dialled by
        the host, and nothing here opens a connection itself.

        Imports are read with the AST rather than matched with a regex, because
        the distinction that matters is a fine one. `urllib.parse` is string
        handling and the MCP gate legitimately needs it to recognise a dbt host;
        `urllib.request` is a transport and must never appear. Only a parser
        separates them reliably, and a regex would either miss the second or ban
        the first.
        """
        forbidden = (
            "aiohttp",
            "ftplib",
            "http",
            "httpx",
            "imaplib",
            "nntplib",
            "poplib",
            "requests",
            "smtplib",
            "socket",
            "telnetlib",
            "urllib.error",
            "urllib.request",
            "urllib3",
            "websocket",
            "websockets",
            "xmlrpc",
        )

        def transports(module: str) -> bool:
            return any(module == name or module.startswith(f"{name}.") for name in forbidden)

        violations: list[str] = []
        sources = sorted(
            [*(PLUGIN_ROOT / "hooks").glob("*.py"), *(PLUGIN_ROOT / "scripts").glob("*.py")]
        )
        self.assertTrue(sources, "expected hook and script sources to exist")

        for path in sources:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    violations.extend(
                        f"{path.name}:{node.lineno} imports {alias.name}"
                        for alias in node.names
                        if transports(alias.name)
                    )
                elif isinstance(node, ast.ImportFrom):
                    # A relative import cannot reach a networking module.
                    if node.level == 0 and node.module and transports(node.module):
                        violations.append(f"{path.name}:{node.lineno} imports from {node.module}")

        self.assertEqual(
            [],
            violations,
            "Shipped code gained the ability to open a network connection, which "
            "contradicts the zero-telemetry commitment in PRIVACY.md:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
