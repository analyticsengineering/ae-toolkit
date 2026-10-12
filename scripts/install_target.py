#!/usr/bin/env python3
"""Install a generated target into a workspace, safely and verifiably.

`build_targets.py` produces a portable tree. Getting that tree into somebody's
repository raises three problems a plain copy does not solve.

Hook paths must be absolute. Antigravity resolves a relative hook command against
the directory the session started in, so a session opened from a subfolder fails to
launch the gate -- and a hook that fails to launch does not block the tool call it
was meant to gate. The failure is silent and it fails open, which is the worst
combination: the user still believes the guardrail is there. Stamping absolute
paths at install time is the only reliable fix, and it is why this script exists.

The workspace is not empty. `AGENTS.md` and `.agents/hooks.json` are shared
files that a team may already use, and the toolkit's own data-safety
rule says creating files is free while editing existing ones needs consent. So
shared files are merged, never clobbered, and the merge is idempotent so that
reinstalling updates in place rather than duplicating.

An unverified guardrail is not a guardrail. After installing, this runs a command
that must be denied and confirms it was, so the install either proves the gate
works on this machine or tells the user it does not.

Usage:
    python3 scripts/install_target.py --host antigravity --workspace /path/to/repo
    python3 scripts/install_target.py --host vscode --workspace . --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_targets import TARGETS, Target  # noqa: E402

BEGIN_MARKER = "<!-- BEGIN:ae-toolkit -->"
END_MARKER = "<!-- END:ae-toolkit -->"
HOOK_GROUP = "ae-toolkit-safety"

# A command the gate must refuse. Used only as gate input; never executed.
CANARY = "rm -rf /"


def managed_block(body: str) -> str:
    return f"{BEGIN_MARKER}\n{body.strip()}\n{END_MARKER}"


def merge_agents_md(existing: str, generated: str) -> str:
    """Place the toolkit's rules in a marked block inside a possibly shared file.

    Reinstalling replaces the block rather than appending a second copy, so the
    file converges instead of growing. Anything outside the markers is the team's
    and is left untouched.
    """
    block = managed_block(generated)
    if BEGIN_MARKER in existing and END_MARKER in existing:
        return re.sub(
            rf"{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}",
            lambda _: block,
            existing,
            flags=re.S,
        )
    separator = "" if existing.endswith("\n\n") or not existing.strip() else "\n\n"
    return f"{existing.rstrip()}{separator}\n{block}\n" if existing.strip() else f"{block}\n"


def merge_json(existing: dict, generated: dict, target: Target) -> dict:
    """Merge our entries into a config file the workspace may already own.

    Both hosts keep every hook group, and every MCP server, in one shared file.
    Our keys are namespaced, so a targeted key-level merge preserves the user's
    configuration while still letting a reinstall overwrite our own stale entries.
    """
    merged = dict(existing)
    if target.name == "vscode":
        # VS Code hooks live in a file of their own; only MCP is shared.
        for key, value in generated.items():
            if key == "servers" and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged

    for key, value in generated.items():
        if key == "mcpServers" and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def absolutize_hooks(config: dict, workspace: Path, target: Target) -> dict:
    """Rewrite each hook command to an absolute interpreter and script path.

    The generated config uses workspace-relative paths so the build output stays
    machine independent. Those only work when the session happens to start at the
    workspace root, so installation is where they become absolute.
    """
    python = sys.executable or "python3"

    def rewrite(command: str) -> str:
        return re.sub(
            rf"python3?\s+({re.escape(target.shared_root)}/\S+\.py)",
            lambda match: f'"{python}" "{workspace / match.group(1)}"',
            command,
        )

    def walk(node):
        if isinstance(node, dict):
            return {
                key: rewrite(value) if key == "command" and isinstance(value, str) else walk(value)
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(config)


def plan_copies(source_root: Path, target: Target) -> tuple[list[Path], list[Path]]:
    """Split the target's files into plain copies and files needing a merge."""
    shared_names = {"AGENTS.md", target.hooks_config}
    plain: list[Path] = []
    shared: list[Path] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_root)
        (shared if str(relative) in shared_names else plain).append(relative)
    return plain, shared


def verify_gate(workspace: Path, target: Target) -> tuple[bool, str]:
    """Prove the installed gate denies a command it is required to deny."""
    gate = workspace / target.shared_root / "hooks" / "safety_gate.py"
    if not gate.is_file():
        return False, f"gate script is missing at {gate}"

    try:
        completed = subprocess.run(
            [sys.executable or "python3", str(gate), "--host", target.name],
            input=json.dumps({"tool_name": "run_command", "tool_input": {"command": CANARY}}),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"gate could not be executed: {exc}"

    if completed.returncode != 0:
        return False, f"gate exited {completed.returncode}: {completed.stderr.strip()}"

    try:
        reply = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return False, f"gate emitted output that is not JSON: {completed.stdout.strip()[:200]}"

    decision = (
        reply.get("hookSpecificOutput", {}).get("permissionDecision")
        if target.name == "vscode"
        else reply.get("decision")
    )
    if decision != "deny":
        return False, f"gate returned {decision!r} for a command it must deny"
    return True, f"gate denied {CANARY!r} as required"


def install(host: str, workspace: Path, dry_run: bool) -> int:
    target = TARGETS[host]
    source_root = REPO_ROOT / "dist" / host
    if not source_root.is_dir():
        print(f"dist/{host} has not been generated. Run: python3 scripts/build_targets.py")
        return 1
    if not workspace.is_dir():
        print(f"workspace does not exist: {workspace}")
        return 1

    plain, shared = plan_copies(source_root, target)
    action = "Would install" if dry_run else "Installing"
    print(f"{action} the {host} target into {workspace}")
    print(f"  {len(plain)} files copied, {len(shared)} shared files merged")

    for relative in plain:
        destination = workspace / relative
        if dry_run:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, destination)

    for relative in shared:
        destination = workspace / relative
        generated_text = (source_root / relative).read_text(encoding="utf-8")
        existed = destination.is_file()

        if relative.name == "AGENTS.md":
            existing_text = destination.read_text(encoding="utf-8") if existed else ""
            result = merge_agents_md(existing_text, generated_text)
            note = "merged into existing block" if BEGIN_MARKER in existing_text else (
                "appended a managed block" if existed else "created"
            )
        else:
            generated_json = json.loads(generated_text)
            if str(relative) == target.hooks_config:
                generated_json = absolutize_hooks(generated_json, workspace, target)
            existing_json = json.loads(destination.read_text(encoding="utf-8")) if existed else {}
            result = json.dumps(merge_json(existing_json, generated_json, target), indent=2) + "\n"
            note = "merged with existing configuration" if existed else "created"

        print(f"  {relative}: {note}")
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(result, encoding="utf-8")

    if dry_run:
        print("\nDry run only; nothing was written.")
        return 0

    ok, detail = verify_gate(workspace, target)
    print(f"\nSafety gate verification: {'passed' if ok else 'FAILED'} -- {detail}")
    if not ok:
        print(
            "The toolkit is installed but its safety gate is not proven to work here. "
            "Treat destructive-command blocking as unavailable until this passes."
        )
        return 1

    print("Hook commands were written as absolute paths, so they resolve from any subdirectory.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=sorted(TARGETS))
    parser.add_argument("--workspace", required=True, type=Path, help="repository to install into")
    parser.add_argument("--dry-run", action="store_true", help="report what would change")
    args = parser.parse_args()
    return install(args.host, args.workspace.resolve(), args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
