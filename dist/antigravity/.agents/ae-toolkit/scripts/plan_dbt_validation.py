#!/usr/bin/env python3
"""Plan the smallest dbt validation command from repository evidence.

This script never executes dbt. It emits a deterministic JSON plan for an agent
to preview and approve before running any warehouse-capable command.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import infer_conventions  # noqa: E402
import inspect_dbt  # noqa: E402
import inspect_git  # noqa: E402


PRODUCTION_TARGET = re.compile(
    r"(?:^|[-_])(?:prod|production|prd|main)(?:$|[-_])",
    re.IGNORECASE,
)
WAREHOUSE_INTENTS = {"compile", "test", "run", "build"}


class ValidationPlanError(ValueError):
    """Raised when repository evidence cannot produce a safe validation plan."""


def _changed_paths(report: dict[str, Any]) -> list[dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    for item in report.get("status", []):
        if isinstance(item, dict) and item.get("path"):
            changes[str(item["path"])] = item
    for key in ("working_tree", "staged"):
        for item in report.get("diffs", {}).get(key, {}).get("files", []):
            if isinstance(item, dict) and item.get("path"):
                changes.setdefault(str(item["path"]), item)
    return [changes[path] for path in sorted(changes)]


def _yaml_models(path: Path) -> list[str]:
    try:
        document = infer_conventions.parse_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return []
    models = document.get("models") if isinstance(document, dict) else None
    if not isinstance(models, list):
        return []
    return sorted(
        {
            str(model["name"])
            for model in models
            if isinstance(model, dict) and model.get("name")
        }
    )


def _models_from_changes(root: Path, changes: Iterable[dict[str, Any]]) -> tuple[list[str], bool]:
    models: set[str] = set()
    contract_change = False
    for change in changes:
        relative = str(change.get("path") or "")
        path = root / relative
        suffix = path.suffix.lower()
        status = str(change.get("status") or "")
        renamed_or_deleted = status.startswith(("R", "D")) or change.get("index_status") in {"R", "D"}
        contract_change = contract_change or renamed_or_deleted
        if suffix == ".sql" and "models" in Path(relative).parts:
            models.add(path.stem)
        elif suffix in {".yml", ".yaml"} and path.is_file():
            yaml_models = _yaml_models(path)
            models.update(yaml_models)
            contract_change = contract_change or bool(yaml_models)
    return sorted(models), contract_change


def _command(*parts: str) -> str:
    return shlex.join(parts)


def plan_validation(
    path: str | Path,
    *,
    models: Sequence[str] | None = None,
    target: str | None = None,
    intent: str = "build",
) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValidationPlanError(f"Project path is not a directory: {root}")
    if intent not in {"static", *WAREHOUSE_INTENTS}:
        raise ValidationPlanError(f"Unsupported validation intent: {intent}")

    dbt = inspect_dbt.inspect_dbt(root)
    if not dbt.get("is_dbt_project"):
        raise ValidationPlanError("No dbt_project.yml was found.")

    git_error: str | None = None
    try:
        git = inspect_git.inspect_git(root)
        changes = _changed_paths(git)
    except inspect_git.GitInspectionError as exc:
        changes = []
        git_error = str(exc)

    inferred_models, contract_change = _models_from_changes(root, changes)
    selected = sorted({item.strip() for item in (models or inferred_models) if item.strip()})
    source = "explicit" if models else "git_diff"
    selectors = [f"{name}+" if contract_change else name for name in selected]

    commands: list[dict[str, Any]] = [
        {
            "step": 1,
            "command": _command("dbt", "parse", "--project-dir", str(root)),
            "executes_warehouse": False,
            "requires_approval": False,
            "purpose": "Validate project parsing, Jinja, and graph construction.",
        }
    ]
    if selectors:
        commands.append(
            {
                "step": 2,
                "command": _command(
                    "dbt",
                    "ls",
                    "--project-dir",
                    str(root),
                    "--select",
                    *selectors,
                    "--output",
                    "name",
                ),
                "executes_warehouse": False,
                "requires_approval": False,
                "purpose": "Confirm the selector resolves only the intended resources.",
            }
        )

    blocked_reason: str | None = None
    if not selected and intent != "static":
        blocked_reason = "No changed or explicitly named dbt models established a bounded scope."
    elif intent in WAREHOUSE_INTENTS and not target:
        blocked_reason = "A local or development target must be named explicitly before warehouse validation."
    elif target and PRODUCTION_TARGET.search(target):
        blocked_reason = f"Target {target!r} appears production-like and is not eligible for automated validation."
    elif intent in WAREHOUSE_INTENTS:
        commands.append(
            {
                "step": len(commands) + 1,
                "command": _command(
                    "dbt",
                    intent,
                    "--project-dir",
                    str(root),
                    "--select",
                    *selectors,
                    "--target",
                    str(target),
                ),
                "executes_warehouse": True,
                "requires_approval": True,
                "purpose": f"Run bounded {intent} validation for the selected resources.",
            }
        )

    return {
        "ok": True,
        "project_root": str(root),
        "scope": {
            "models": selected,
            "selectors": selectors,
            "source": source,
            "contract_change": contract_change,
            "changed_paths": [str(item.get("path")) for item in changes],
        },
        "target": {
            "name": target,
            "production_like": bool(target and PRODUCTION_TARGET.search(target)),
        },
        "intent": intent,
        "commands": commands,
        "blocked_reason": blocked_reason,
        "warnings": ([f"Git scope unavailable: {git_error}"] if git_error else []),
        "execution_note": "Planning only; dbt was not executed and no warehouse was contacted.",
    }


def _parser() -> argparse.ArgumentParser:
    parser = inspect_dbt.JsonArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="dbt project directory")
    parser.add_argument("--model", action="append", dest="models", help="Model to validate; repeatable")
    parser.add_argument("--target", help="Explicit local or development dbt target")
    parser.add_argument(
        "--intent",
        choices=["static", "compile", "test", "run", "build"],
        default="build",
    )
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = plan_validation(
            args.path,
            models=args.models,
            target=args.target,
            intent=args.intent,
        )
    except (ValidationPlanError, inspect_dbt.DbtInspectionError, OSError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
