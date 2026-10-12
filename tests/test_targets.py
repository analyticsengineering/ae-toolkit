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
        expected = {path.parent.name for path in (PLUGIN_ROOT / "src" / "skills").glob("*/SKILL.md")}
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

    def test_guidance_never_names_a_bare_toolkit_path(self) -> None:
        """The dangling-path test above only sees paths already pointing at the host.

        A path written bare, as `references/privacy.md`, passes it while resolving
        against the user's own repository instead of the toolkit. That is the worse
        failure of the two: the rule still reads as enforced, and the file it
        delegates to is either absent or someone else's.

        A skill may also bundle its own `references/` directory, where the bare form
        is the correct relative link and must be left alone. So a bare path is only
        a defect when it resolves neither beside its document nor under the shared
        root, which is exactly the case generation is responsible for rewriting.
        """
        for name, target in TARGETS.items():
            root = DIST / name
            for doc in root.rglob("*.md"):
                text = doc.read_text(encoding="utf-8")
                for bare in set(re.findall(r"(?<![\w/.])((?:references|scripts)/[\w.-]+)", text)):
                    # The generated header credits the tool that wrote the file. It
                    # is provenance, not an instruction, and the tool is
                    # deliberately never shipped.
                    if Path(bare).name in build_targets.DEV_ONLY_SCRIPTS:
                        continue
                    # Only a resource sitting beside the document may be named
                    # bare. Anything else had to be rewritten to the shared root,
                    # and asking whether the file exists somewhere under that root
                    # would pass a document that never points at it.
                    self.assertTrue(
                        (doc.parent / bare).exists(),
                        f"{name}: {doc.relative_to(root)} names {bare!r}, which resolves "
                        f"against the user's repository rather than {target.shared_root}",
                    )

    def test_authored_guidance_never_promises_a_missing_reference(self) -> None:
        """A reference the repository does not contain is broken on every host.

        Generation cannot catch this one, because a path that ships nowhere is
        correctly left alone rather than rewritten into a target it is not in.
        """
        shared = {path.name for path in (PLUGIN_ROOT / "references").glob("*.md")}
        self.assertTrue(shared, "expected the toolkit to ship reference documents")
        for doc in build_targets.doc_sources():
            named = set(re.findall(r"references/([\w.-]+\.md)", doc.read_text(encoding="utf-8")))
            missing = sorted(
                reference
                for reference in named
                if reference not in shared
                and not (doc.parent / "references" / reference).is_file()
            )
            self.assertEqual(
                [],
                missing,
                f"{doc.relative_to(PLUGIN_ROOT)} references documents that do not exist: {missing}",
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


class PortableSkillTests(unittest.TestCase):
    """Skills an installer copies one directory at a time must still work.

    `npx skills add` copies a skill's own directory and nothing beside it, so any
    path into a shared tree is dead on arrival. Every check here is about a skill
    standing alone.
    """

    PORTABLE = build_targets.PORTABLE_ROOT
    PATH = re.compile(r"<skill-dir>/((?:scripts|references)/[A-Za-z0-9_.-]+)")

    def skills(self) -> list[Path]:
        skills = sorted(self.PORTABLE.glob("*/SKILL.md"))
        self.assertTrue(skills, "the portable target shipped no skills")
        return skills

    def test_committed_portable_skills_match_a_fresh_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "skills"
            build_targets.build_portable(fresh)
            self.assertEqual([], build_targets.differences(fresh, self.PORTABLE))

    def test_every_authored_skill_is_portable(self) -> None:
        authored = {path.parent.name for path in (PLUGIN_ROOT / "src" / "skills").glob("*/SKILL.md")}
        self.assertEqual(authored, {path.parent.name for path in self.skills()})

    def test_no_portable_skill_names_a_path_outside_itself(self) -> None:
        for skill in self.skills():
            root = skill.parent
            for doc in root.rglob("*.md"):
                text = doc.read_text(encoding="utf-8")
                with self.subTest(file=str(doc.relative_to(self.PORTABLE))):
                    self.assertNotIn("CURSOR_PLUGIN_ROOT", text)
                    for relative in self.PATH.findall(text):
                        self.assertTrue((root / relative).is_file(), f"{relative} is not bundled")

    def test_bundled_scripts_carry_every_sibling_they_import(self) -> None:
        known = {path.stem for path in (PLUGIN_ROOT / "scripts").glob("*.py")}
        for skill in self.skills():
            bundled = {path.stem for path in (skill.parent / "scripts").glob("*.py")}
            for script in (skill.parent / "scripts").glob("*.py"):
                imports = set(re.findall(r"^\s*(?:import|from)\s+([A-Za-z0-9_]+)", script.read_text(encoding="utf-8"), re.M))
                with self.subTest(skill=skill.parent.name, script=script.name):
                    self.assertEqual(set(), (imports & known) - bundled)

    def test_every_portable_skill_carries_the_rules_and_says_it_is_ungated(self) -> None:
        for skill in self.skills():
            text = skill.read_text(encoding="utf-8")
            with self.subTest(skill=skill.parent.name):
                self.assertTrue((skill.parent / "references" / "operating-rules.md").is_file())
                self.assertIn("no safety hooks", text)
                meta, _ = build_targets.split_frontmatter(text)
                self.assertEqual(meta.get("name"), skill.parent.name)
                self.assertLessEqual(len(meta.get("description", "")), 1024)

    def test_a_copied_skill_runs_its_scripts_away_from_the_repository(self) -> None:
        import subprocess
        import sys

        fixture = PLUGIN_ROOT / "tests" / "fixtures" / "dbt" / "ambiguous_adapter"
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / "validate-dbt"
            shutil.copytree(self.PORTABLE / "validate-dbt", installed)
            result = subprocess.run(
                [sys.executable, str(installed / "scripts" / "plan_dbt_validation.py"), str(fixture), "--intent", "static"],
                capture_output=True,
                text=True,
                cwd=tmp,
                timeout=60,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("validation_steps", json.loads(result.stdout))


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
        payload = {"toolName": "mcp__dbt__build", "toolInput": {}}
        self.assertEqual("allow", self.decision_for("vscode", payload))


class CloudGateHostContractTests(unittest.TestCase):
    """The connected-data gate must survive translation to every host.

    The shell gate was already covered here, but the cloud gate is the one that
    guards transmission off the machine, and it is the only gate with three
    distinct outcomes. A host that silently drops `ask` would turn a request for
    consent into either a refusal or, far worse, an unannounced send.
    """

    def setUp(self) -> None:
        self.gate = load_module("hooks/cloud_data_gate.py", "cloud_gate_under_test")

    def reply_for(self, host: str, payload: dict) -> dict:
        import sys as _sys

        stdin, stdout = _sys.stdin, _sys.stdout
        _sys.stdin, _sys.stdout = io.StringIO(json.dumps(payload)), io.StringIO()
        try:
            self.gate.main(["--host", host])
            return json.loads(_sys.stdout.getvalue())
        finally:
            _sys.stdin, _sys.stdout = stdin, stdout

    def decision_of(self, host: str, reply: dict) -> str:
        if host == "vscode":
            return reply["hookSpecificOutput"]["permissionDecision"]
        if host == "antigravity":
            return reply["decision"]
        return reply["permission"]

    def test_every_outcome_survives_translation_to_every_host(self) -> None:
        warehouse = {
            "tool_name": "mcp__dbt__execute_sql",
            "mcp_server_name": "dbt",
            "tool_input": {"sql": "select 1"},
        }
        leaked = {
            "tool_name": "mcp__dbt__execute_sql",
            "mcp_server_name": "dbt",
            "tool_input": {"sql": "select '" + "gh" + "p_" + ("C" * 32) + "'"},
        }
        unrelated = {
            "tool_name": "mcp__other__lookup",
            "mcp_server_name": "other",
            "tool_input": {},
        }
        for host in build_targets.TARGETS:
            for payload, expected in ((warehouse, "ask"), (leaked, "deny"), (unrelated, "allow")):
                with self.subTest(host=host, expected=expected):
                    reply = self.reply_for(host, payload)
                    self.assertEqual(expected, self.decision_of(host, reply))

    def test_the_reason_reaches_the_user_on_every_host(self) -> None:
        """An `ask` that does not say what will run is consent without disclosure."""
        payload = {
            "tool_name": "mcp__dbt__execute_sql",
            "mcp_server_name": "dbt",
            "tool_input": {"sql": "select 1"},
        }
        for host in build_targets.TARGETS:
            with self.subTest(host=host):
                reply = self.reply_for(host, payload)
                serialized = json.dumps(reply)
                self.assertIn("Nothing runs until you approve", serialized)
                self.assertIn("execute_sql", serialized)

    def test_the_cloud_gate_stands_aside_for_shell_traffic(self) -> None:
        payload = {"tool_name": "run_command", "tool_input": {"command": "ls"}}
        for host in build_targets.TARGETS:
            with self.subTest(host=host):
                reply = self.reply_for(host, payload)
                self.assertEqual("allow", self.decision_of(host, reply))

    def test_an_unreadable_payload_fails_closed_on_every_host(self) -> None:
        import sys as _sys

        for host in build_targets.TARGETS:
            with self.subTest(host=host):
                stdin, stdout = _sys.stdin, _sys.stdout
                _sys.stdin, _sys.stdout = io.StringIO("{not json"), io.StringIO()
                try:
                    self.gate.main(["--host", host])
                    reply = json.loads(_sys.stdout.getvalue())
                finally:
                    _sys.stdin, _sys.stdout = stdin, stdout
                self.assertEqual("deny", self.decision_of(host, reply))


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
        """Run for every host: a gate proven on one target proves nothing about the other."""
        for name in TARGETS:
            with self.subTest(host=name), tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp)
                with contextlib.redirect_stdout(io.StringIO()):
                    status = install_target.install(name, workspace, dry_run=False)
                self.assertEqual(0, status)
                ok, detail = install_target.verify_gate(workspace, TARGETS[name])
                self.assertTrue(ok, detail)

    def test_an_installed_gate_resolves_from_a_subdirectory(self) -> None:
        """The failure this prevents is silent on two of the three hosts.

        VS Code and Antigravity resolve a relative hook command against the
        directory the session started in, and neither blocks a tool call when its
        hook fails to launch. A gate left at a relative path therefore disappears
        without a message the moment work begins in a subdirectory.
        """
        for name, target in TARGETS.items():
            with self.subTest(host=name), tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp)
                with contextlib.redirect_stdout(io.StringIO()):
                    install_target.install(name, workspace, dry_run=False)

                config = json.loads((workspace / target.hooks_config).read_text(encoding="utf-8"))
                for command in re.findall(r'"command":\s*"([^"]+)"', json.dumps(config)):
                    script = command.split()[-1] if command.endswith(".py") else None
                    if script:
                        self.assertTrue(
                            Path(script).is_absolute(),
                            f"{name}: hook command is not absolute: {command}",
                        )
                        self.assertTrue(Path(script).is_file(), f"{name}: missing {script}")

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
