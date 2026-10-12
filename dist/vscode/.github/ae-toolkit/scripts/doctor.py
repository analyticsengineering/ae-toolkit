#!/usr/bin/env python3
"""Check that this toolkit install will actually protect and serve the workspace.

An install can look complete and still be inert: a plugin loaded through a
symlink is skipped without an error, a hook whose interpreter is missing lets
every call through on hosts that fail open, and a relative hook path stops
resolving the moment a session starts in a subdirectory. None of these produce a
message at the time they matter, so this asks each piece to prove it works.

Read-only and offline. The gates are run with canary payloads that they are
required to refuse or hold; nothing reaches a shell, a warehouse, or a network.

Usage:
    python3 scripts/doctor.py [--workspace PATH] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

MIN_PYTHON = (3, 9)
CANARY = "psql -c 'drop table orders'"
PLUGIN_NAME = "analytics-engineering-toolkit"
TARGET_CONFIGS = {
    ".github": ("vscode", ".github/hooks/ae-toolkit.json"),
    ".agents": ("antigravity", ".agents/hooks.json"),
}

PASS, WARN, FAIL, INFO = "pass", "warn", "fail", "info"


def finding(status: str, check: str, detail: str, fix: str = "") -> dict[str, str]:
    return {"status": status, "check": check, "detail": detail, "fix": fix}


def detect_layout(here: Path) -> dict[str, Any]:
    """Work out which install this copy of the doctor belongs to."""
    root = here.resolve().parent.parent
    if (root / ".cursor-plugin" / "plugin.json").is_file():
        return {"kind": "cursor", "host": "cursor", "root": root, "hooks": root / "hooks"}
    if root.name == "ae-toolkit" and root.parent.name in TARGET_CONFIGS:
        host, config = TARGET_CONFIGS[root.parent.name]
        workspace = root.parent.parent
        return {
            "kind": host,
            "host": host,
            "root": root,
            "hooks": root / "hooks",
            "workspace": workspace,
            "config": workspace / config,
        }
    if (root / "SKILL.md").is_file():
        return {"kind": "skills-only", "host": None, "root": root, "hooks": None}
    return {"kind": "unknown", "host": None, "root": root, "hooks": None}


def interpreter_version(executable: str) -> tuple[int, int] | None:
    try:
        completed = subprocess.run(
            [executable, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    parts = completed.stdout.split()
    if completed.returncode != 0 or len(parts) != 2:
        return None
    return int(parts[0]), int(parts[1])


def check_python() -> dict[str, str]:
    version = sys.version_info[:2]
    shown = f"{version[0]}.{version[1]}"
    if version < MIN_PYTHON:
        return finding(FAIL, "python", f"running on Python {shown}", "Install Python 3.9 or newer.")
    return finding(PASS, "python", f"running on Python {shown}")


def check_hook_interpreter(executable: str, label: str) -> dict[str, str]:
    resolved = executable if os.path.isabs(executable) else shutil.which(executable)
    if not resolved:
        return finding(
            FAIL,
            "hook interpreter",
            f"`{executable}` is not on PATH, so {label} cannot start",
            "Install Python 3.9+ so that `python3` resolves, or point the hook at an interpreter that exists.",
        )
    version = interpreter_version(resolved)
    if version is None:
        return finding(FAIL, "hook interpreter", f"{resolved} did not run", "Repair or replace that interpreter.")
    if version < MIN_PYTHON:
        return finding(
            FAIL,
            "hook interpreter",
            f"{resolved} is Python {version[0]}.{version[1]}; the gates need 3.9+",
            "Put Python 3.9 or newer first on PATH.",
        )
    return finding(PASS, "hook interpreter", f"{label} run under {resolved} (Python {version[0]}.{version[1]})")


def decision_of(host: str, reply: dict[str, Any]) -> str | None:
    if host == "vscode":
        return reply.get("hookSpecificOutput", {}).get("permissionDecision")
    if host == "antigravity":
        return reply.get("decision")
    return reply.get("permission")


def run_gate(script: Path, host: str, payload: dict[str, Any], python: str) -> tuple[str | None, str]:
    try:
        completed = subprocess.run(
            [python, str(script), "--host", host],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not run: {exc}"
    if completed.returncode != 0:
        return None, f"exited {completed.returncode}: {completed.stderr.strip()[:200]}"
    try:
        return decision_of(host, json.loads(completed.stdout)), ""
    except json.JSONDecodeError:
        return None, f"printed something other than JSON: {completed.stdout.strip()[:200]}"


def check_gates(hooks: Path, host: str, python: str) -> list[dict[str, str]]:
    shell_payload: dict[str, Any] = (
        {"command": CANARY} if host == "cursor" else {"tool_name": "run_command", "tool_input": {"command": CANARY}}
    )
    mcp_payload: dict[str, Any] = {"mcp_server_name": "dbt", "tool_name": "build", "tool_input": "{}"}
    if host != "cursor":
        mcp_payload["tool_name"] = "mcp__dbt__build"

    results = []
    for script, check, payload, expected, what in (
        ("safety_gate.py", "shell gate", shell_payload, "deny", f"refuses {CANARY!r}"),
        ("cloud_data_gate.py", "MCP gate", mcp_payload, "ask", "holds the dbt MCP `build` tool for approval"),
    ):
        path = hooks / script
        if not path.is_file():
            results.append(finding(FAIL, check, f"{path} is missing", "Reinstall the toolkit."))
            continue
        decision, problem = run_gate(path, host, payload, python)
        if decision == expected:
            results.append(finding(PASS, check, what))
        else:
            detail = problem or f"returned {decision!r} where {expected!r} is required"
            results.append(finding(FAIL, check, detail, "Reinstall the toolkit; do not rely on the gates until this passes."))
    return results


def check_cursor_install(here: Path, root: Path) -> list[dict[str, str]]:
    results = []
    manifest = json.loads((root / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8"))
    local = Path.home() / ".cursor" / "plugins" / "local"
    unresolved = Path(os.path.abspath(here)).parent.parent
    if manifest.get("name") != PLUGIN_NAME:
        results.append(finding(FAIL, "plugin manifest", f"name is {manifest.get('name')!r}", "Reinstall from a clean copy."))
    if str(unresolved).startswith(str(local)) and unresolved != root:
        results.append(
            finding(
                FAIL,
                "plugin install",
                f"{unresolved} is a symlink to {root}; Cursor skips a local plugin whose link leaves the plugins folder",
                "Replace the symlink with a real copy (see the README install steps).",
            )
        )
    elif root.parent == local:
        results.append(finding(PASS, "plugin install", f"installed as a real directory at {root}"))
    else:
        results.append(
            finding(
                INFO,
                "plugin install",
                f"running from {root}, not from {local}; Cursor loads the copy under its plugins folder",
                "Run this doctor from the installed copy to check what Cursor actually loads.",
            )
        )
    return results


def hook_commands(config: Any) -> list[str]:
    found: list[str] = []
    if isinstance(config, dict):
        for key, value in config.items():
            if key == "command" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(hook_commands(value))
    elif isinstance(config, list):
        for item in config:
            found.extend(hook_commands(item))
    return found


def check_target_config(layout: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    """Hook wiring for VS Code and Antigravity, and the interpreter it names."""
    config_path: Path = layout["config"]
    if not config_path.is_file():
        return [
            finding(
                FAIL,
                "hook config",
                f"{config_path} is missing, so no gate is registered",
                "Run scripts/install_target.py for this host.",
            )
        ], "python3"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [finding(FAIL, "hook config", f"{config_path} is not valid JSON: {exc}", "Reinstall.")], "python3"

    ours = [command for command in hook_commands(config) if "ae-toolkit" in command]
    if not ours:
        return [finding(FAIL, "hook config", "no toolkit gate is registered", "Run scripts/install_target.py.")], "python3"
    results = []
    python = "python3"
    relative = []
    for command in ours:
        match = re.match(r'\s*"?([^"\s]+)"?\s+"?([^"\s]+\.py)"?', command)
        if not match:
            continue
        python, script = match.groups()
        if not os.path.isabs(script):
            relative.append(script)
        elif not Path(script).is_file():
            results.append(finding(FAIL, "hook config", f"{script} does not exist", "Reinstall with scripts/install_target.py."))
    if relative:
        results.append(
            finding(
                WARN if layout["host"] == "vscode" else FAIL,
                "hook paths",
                "hook commands use relative paths, which stop resolving in a session started below the repository root",
                "Install with scripts/install_target.py, which writes absolute paths.",
            )
        )
    else:
        results.append(finding(PASS, "hook paths", "hook commands use absolute paths"))
    return results, python


def check_workspace(workspace: Path) -> list[dict[str, str]]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    results = []
    try:
        import project_context  # noqa: PLC0415

        projects = project_context.discover_projects(workspace)
    except Exception as exc:  # noqa: BLE001 -- a doctor reports, it does not crash
        return [finding(INFO, "workspace", f"could not read the workspace: {exc}")]
    if projects:
        shown = ", ".join(str(path.relative_to(workspace)) or "." for path in projects[:3])
        results.append(finding(INFO, "dbt project", f"found {len(projects)}: {shown}"))
    else:
        results.append(finding(INFO, "dbt project", f"no dbt project found under {workspace}"))
    profile = workspace / ".ae" / "project.yml"
    if profile.is_file():
        text = profile.read_text(encoding="utf-8")
        off = re.search(r"(?m)^\s*guard_published_models\s*:\s*false\b", text)
        results.append(
            finding(
                WARN if off else INFO,
                "project profile",
                ".ae/project.yml turns the published-model guard off" if off else ".ae/project.yml is present",
            )
        )
    return results


def diagnose(here: Path, workspace: Path) -> dict[str, Any]:
    layout = detect_layout(here)
    findings = [check_python()]
    kind = layout["kind"]

    if kind == "cursor":
        findings.extend(check_cursor_install(here, layout["root"]))
        findings.append(check_hook_interpreter("python3", "Cursor's hooks"))
        findings.extend(check_gates(layout["hooks"], "cursor", shutil.which("python3") or sys.executable))
    elif kind in ("vscode", "antigravity"):
        config_findings, python = check_target_config(layout)
        findings.extend(config_findings)
        findings.append(check_hook_interpreter(python, f"{kind} hooks"))
        findings.extend(check_gates(layout["hooks"], kind, python if os.path.isabs(python) else (shutil.which(python) or sys.executable)))
        if kind != "vscode":
            findings.append(
                finding(
                    INFO,
                    "fail-open host",
                    "Antigravity lets a call through when a hook cannot launch, so the interpreter check above is what keeps the gates real",
                )
            )
    elif kind == "skills-only":
        findings.append(
            finding(
                WARN,
                "gates",
                "skills-only install: no hooks are present, so approvals are asked for by the agent but not enforced",
                "Install the Cursor plugin, or the VS Code or Antigravity target, to enforce them.",
            )
        )
    else:
        findings.append(finding(FAIL, "install", f"could not recognise the install around {layout['root']}", "Reinstall."))

    findings.extend(check_workspace(workspace))
    return {
        "install": kind,
        "toolkit_root": str(layout["root"]),
        "workspace": str(workspace),
        "ok": not any(item["status"] == FAIL for item in findings),
        "findings": findings,
    }


def render(report: dict[str, Any]) -> str:
    lines = [f"AE Toolkit doctor: {report['install']} install at {report['toolkit_root']}", ""]
    for item in report["findings"]:
        lines.append(f"{item['status'].upper():5} {item['check']}: {item['detail']}")
        if item["fix"] and item["status"] in (FAIL, WARN):
            lines.append(f"      fix: {item['fix']}")
    lines.extend(["", "All required checks passed." if report["ok"] else "Some required checks failed; see the fixes above."])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", type=Path, default=None, help="repository to check (default: the current directory)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    here = Path(__file__)
    layout = detect_layout(here)
    workspace = (args.workspace or layout.get("workspace") or Path.cwd()).resolve()
    report = diagnose(here, workspace)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
