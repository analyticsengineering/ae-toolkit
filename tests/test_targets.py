"""Guard the generated VS Code and Antigravity targets against drift and defects.

The toolkit is authored once and generated into three host layouts. That only holds
if something fails loudly when the generated output stops matching the source, so
the central test here is a rebuild-and-compare. The rest assert the properties that
made porting worth doing: identical judgement on every host, no reference to a file
the target does not carry, and an installer that cannot quietly damage a repository.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from test_support import PLUGIN_ROOT, load_module

build_targets = load_module("scripts/build_targets.py", "build_targets")
install_target = load_module("scripts/install_target.py", "install_target")

DIST = PLUGIN_ROOT / "dist"
TARGETS = build_targets.TARGETS


class GeneratedTargetTests(unittest.TestCase):
    def test_committed_targets_match_a_fresh_build(self) -> None:
        """The central guard: a source edit that is not rebuilt fails here.

        Without this, the Cursor plugin and the two generated copies drift apart,
        and a safety rule tightened in one host silently stays loose in another.
        """
        with tempfile.TemporaryDirectory() as tmp:
            for name, target in TARGETS.items():
                fresh = Path(tmp) / name
                build_targets.build_target(target, fresh)
                committed = DIST / name
                self.assertTrue(committed.is_dir(), f"dist/{name} has not been generated")
                problems = build_targets.differences(fresh, committed)
                self.assertEqual(
                    [],
                    problems,
                    f"dist/{name} is stale. Run: python3 scripts/build_targets.py\n"
                    + "\n".join(problems),
                )

    def test_drift_is_actually_detected(self) -> None:
        """A guard that cannot fail is not a guard, so prove the comparison bites."""
        with tempfile.TemporaryDirectory() as tmp:
            target = TARGETS["vscode"]
            left, right = Path(tmp) / "a", Path(tmp) / "b"
            build_targets.build_target(target, left)
            shutil.copytree(left, right)
            self.assertEqual([], build_targets.differences(left, right))

            (right / "AGENTS.md").write_text("tampered\n", encoding="utf-8")
            (right / "extra.md").write_text("unexpected\n", encoding="utf-8")
            problems = build_targets.differences(left, right)
            self.assertTrue(any("content differs" in p for p in problems), problems)
            self.assertTrue(any("stale file" in p for p in problems), problems)

    def test_every_authored_skill_reaches_every_target(self) -> None:
        expected = {path.parent.name for path in (PLUGIN_ROOT / "skills").glob("*/SKILL.md")}
        for name, target in TARGETS.items():
            shipped = {p.parent.name for p in (DIST / name / target.skills_dir).glob("*/SKILL.md")}
            self.assertTrue(expected <= shipped, f"{name} is missing skills: {sorted(expected - shipped)}")

    def test_commands_survive_as_the_host_expresses_them(self) -> None:
        """Commands become prompt files on VS Code and skills on Antigravity."""
        authored = {path.stem for path in (PLUGIN_ROOT / "commands").glob("*.md")}

        prompts = {p.name.removesuffix(".prompt.md") for p in (DIST / "vscode/.github/prompts").glob("*.prompt.md")}
        self.assertEqual(authored, prompts)

        skills = {p.parent.name for p in (DIST / "antigravity/.agents/skills").glob("*/SKILL.md")}
        self.assertTrue(authored <= skills, f"missing: {sorted(authored - skills)}")

    def test_no_target_keeps_a_cursor_only_path(self) -> None:
        for name in TARGETS:
            for path in (DIST / name).rglob("*"):
                if path.is_file() and path.suffix in {".md", ".json", ".py"}:
                    self.assertNotIn(
                        build_targets.PLUGIN_ROOT_TOKEN,
                        path.read_text(encoding="utf-8"),
                        f"{path} still points at the Cursor plugin root",
                    )

    def test_guidance_never_names_a_file_the_target_lacks(self) -> None:
        """A dangling script path is an instruction the agent cannot carry out.

        This caught a real defect: the rules reference a secret-redaction script
        that the first generator did not ship, which would have degraded the
        privacy boundary on both hosts while still reading as enforced.
        """
        for name, target in TARGETS.items():
            root = DIST / name
            for doc in root.rglob("*.md"):
                text = doc.read_text(encoding="utf-8")
                for reference in set(re.findall(rf"{re.escape(target.shared_root)}/[\w/.-]+", text)):
                    self.assertTrue(
                        (root / reference).exists(),
                        f"{name}: {doc.relative_to(root)} references missing {reference}",
                    )

    def test_every_skill_satisfies_the_rules_that_govern_silent_loading(self) -> None:
        """Three ways a skill fails to load without saying so.

        VS Code requires the `name` field to match the parent directory, permits
        only lowercase letters, numbers, and hyphens in it, and caps `description`
        at 1024 characters. Violating any of these makes the skill silently fail
        to load, which is the worst outcome available: the target installs, the
        files are present, and the workflow is simply absent. Nothing at runtime
        would tell us, so it has to be caught here.
        """
        valid_name = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        for name, target in TARGETS.items():
            skills = sorted((DIST / name / target.skills_dir).glob("*/SKILL.md"))
            self.assertTrue(skills, f"{name} shipped no skills at all")
            for skill in skills:
                meta, _ = build_targets.split_frontmatter(skill.read_text(encoding="utf-8"))
                directory = skill.parent.name
                skill_name = meta.get("name", "")
                description = meta.get("description", "")

                self.assertEqual(skill_name, directory, f"{name}: {directory} name does not match its directory")
                self.assertRegex(skill_name, valid_name, f"{name}: {directory} name would prevent loading")
                self.assertLessEqual(len(skill_name), 64, f"{name}: {directory} name exceeds 64 characters")
                self.assertTrue(description, f"{name}: {directory} has no description, so it is never selected")
                self.assertLessEqual(
                    len(description), 1024, f"{name}: {directory} description exceeds the 1024 character limit"
                )

    def test_development_tooling_is_not_shipped_to_users(self) -> None:
        for name, target in TARGETS.items():
            shipped = {p.name for p in (DIST / name / target.shared_root / "scripts").glob("*.py")}
            leaked = shipped & build_targets.DEV_ONLY_SCRIPTS
            self.assertEqual(set(), leaked, f"{name} ships development-only scripts: {sorted(leaked)}")

    def test_agents_md_carries_every_always_applied_rule(self) -> None:
        rules = sorted((PLUGIN_ROOT / "rules").glob("*.mdc"))
        self.assertTrue(rules, "expected always-applied rules to exist")
        for name in TARGETS:
            text = (DIST / name / "AGENTS.md").read_text(encoding="utf-8")
            for rule in rules:
                _, body = build_targets.split_frontmatter(rule.read_text(encoding="utf-8"))
                heading = next(line for line in body.splitlines() if line.startswith("#"))
                self.assertIn(heading.lstrip("# ").strip(), text, f"{name} lost {rule.name}")

    def test_both_gates_are_wired_into_the_blocking_event(self) -> None:
        """Losing a gate in generation would remove enforcement without a signal."""
        for name, target in TARGETS.items():
            config = json.loads((DIST / name / target.hooks_config).read_text(encoding="utf-8"))
            serialized = json.dumps(config)
            self.assertIn("PreToolUse", serialized)
            self.assertIn("safety_gate.py", serialized)
            self.assertIn("cloud_data_gate.py", serialized)
            self.assertIn(f"--host {name}", serialized)


class HostContractTests(unittest.TestCase):
    """Each host phrases a refusal differently; all three must still refuse."""

    def setUp(self) -> None:
        self.gate = load_module("hooks/safety_gate.py", "gate_under_test")

    def decision_for(self, host: str, payload: dict) -> str:
        import io
        import sys as _sys

        stdin, stdout = _sys.stdin, _sys.stdout
        _sys.stdin, _sys.stdout = io.StringIO(json.dumps(payload)), io.StringIO()
        try:
            self.gate.main(["--host", host])
            reply = json.loads(_sys.stdout.getvalue())
        finally:
            _sys.stdin, _sys.stdout = stdin, stdout

        if host == "vscode":
            return reply["hookSpecificOutput"]["permissionDecision"]
        if host == "antigravity":
            return reply["decision"]
        return reply["permission"]

    def test_a_destructive_command_is_denied_on_every_host(self) -> None:
        """Payloads match each host's documented field names.

        VS Code and Antigravity both document snake_case `tool_name` and
        `tool_input`; Cursor passes the command at the top level.
        """
        payloads = {
            "cursor": {"command": "rm -rf /"},
            "vscode": {"tool_name": "runTerminalCommand", "tool_input": {"command": "rm -rf /"}},
            "antigravity": {"tool_name": "run_command", "tool_input": {"command": "rm -rf /"}},
        }
        for host, payload in payloads.items():
            self.assertEqual("deny", self.decision_for(host, payload), f"{host} failed to deny")

    def test_both_copilot_payload_dialects_are_inspected(self) -> None:
        """One host family, two payload shapes, so extraction cannot assume either.

        VS Code documents snake_case fields with an object argument, while Copilot
        CLI documents camelCase with the arguments encoded as a JSON string. Both
        reach the same gate, so both are exercised here.
        """
        vscode_shape = {"tool_name": "runTerminalCommand", "tool_input": {"command": "rm -rf /"}}
        cli_shape = {"toolName": "bash", "toolArgs": json.dumps({"command": "rm -rf /"})}
        self.assertEqual("deny", self.decision_for("vscode", vscode_shape))
        self.assertEqual("deny", self.decision_for("vscode", cli_shape))

    def test_an_unreadable_payload_fails_closed(self) -> None:
        """Hosts change field names; an unrecognised shape must not mean approval."""
        self.assertEqual("deny", self.decision_for("vscode", {"toolName": "runTerminalCommand"}))

    def test_the_shell_gate_stands_aside_for_mcp_traffic(self) -> None:
        payload = {"toolName": "mcp__analytics-engineering__grade", "toolInput": {}}
        self.assertEqual("allow", self.decision_for("vscode", payload))


class InstallerTests(unittest.TestCase):
    """Installing must not damage a repository that already has its own config."""

    def test_existing_agents_md_is_preserved_and_reinstall_is_idempotent(self) -> None:
        original = "# Team Rules\n\nAlways use tabs.\n"
        once = install_target.merge_agents_md(original, "TOOLKIT BODY")
        self.assertIn("Always use tabs.", once)
        self.assertIn("TOOLKIT BODY", once)

        twice = install_target.merge_agents_md(once, "TOOLKIT BODY")
        self.assertEqual(1, twice.count(install_target.BEGIN_MARKER))
        self.assertIn("Always use tabs.", twice)

        updated = install_target.merge_agents_md(twice, "REVISED BODY")
        self.assertIn("REVISED BODY", updated)
        self.assertNotIn("TOOLKIT BODY", updated)
        self.assertIn("Always use tabs.", updated)

    def test_existing_hook_groups_and_mcp_servers_survive_a_merge(self) -> None:
        target = TARGETS["antigravity"]
        existing = {"our-linter": {"enabled": True}, "mcpServers": {"ours": {"url": "https://example.com"}}}
        generated = {install_target.HOOK_GROUP: {"enabled": True}, "mcpServers": {"ae": {"url": "https://ae"}}}
        merged = install_target.merge_json(existing, generated, target)

        self.assertIn("our-linter", merged)
        self.assertIn(install_target.HOOK_GROUP, merged)
        self.assertEqual({"ours", "ae"}, set(merged["mcpServers"]))

    def test_hook_commands_become_absolute_so_a_subdirectory_session_is_gated(self) -> None:
        """Antigravity resolves relative hook paths against the session directory,
        and a hook that fails to launch does not block the call it should gate."""
        target = TARGETS["antigravity"]
        workspace = Path("/tmp/example-workspace")
        config = json.loads(build_targets.build_hooks_config(target))
        self.assertIn(target.shared_root, json.dumps(config))

        absolute = install_target.absolutize_hooks(config, workspace, target)
        command = absolute[install_target.HOOK_GROUP]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn(str(workspace / target.shared_root / "hooks" / "safety_gate.py"), command)
        self.assertNotIn(f'"{target.shared_root}/hooks', command)

    def test_install_verifies_the_gate_rather_than_assuming_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                status = install_target.install("antigravity", workspace, dry_run=False)
            self.assertEqual(0, status)
            ok, detail = install_target.verify_gate(workspace, TARGETS["antigravity"])
            self.assertTrue(ok, detail)

    def test_verification_fails_when_the_gate_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, detail = install_target.verify_gate(Path(tmp), TARGETS["antigravity"])
            self.assertFalse(ok)
            self.assertIn("missing", detail)

    def test_a_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                install_target.install("vscode", workspace, dry_run=True)
            self.assertEqual([], list(workspace.iterdir()))


if __name__ == "__main__":
    unittest.main()
