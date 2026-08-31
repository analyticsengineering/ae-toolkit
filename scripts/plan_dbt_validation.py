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
    return _document_models(document)


def _document_models(document: Any) -> list[str]:
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


def _without_keys(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_keys(item, keys)
            for key, item in value.items()
            if key not in keys
        }
    if isinstance(value, list):
        return [_without_keys(item, keys) for item in value]
    return value


def _parse_yaml_text(text: str) -> dict[str, Any]:
    document = infer_conventions.parse_yaml(text)
    return document if isinstance(document, dict) else {}


def _metadata_only_document(document: dict[str, Any]) -> bool:
    if set(document) - {"version", "models"}:
        return False
    models = document.get("models")
    if not isinstance(models, list):
        return False
    for model in models:
        if not isinstance(model, dict) or set(model) - {"name", "description", "columns", "tests", "data_tests"}:
            return False
        for column in model.get("columns") or []:
            if not isinstance(column, dict) or set(column) - {"name", "description", "tests", "data_tests"}:
                return False
    return True


def _contains_test_declaration(value: Any) -> bool:
    if isinstance(value, dict):
        if "tests" in value or "data_tests" in value:
            return True
        return any(_contains_test_declaration(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_test_declaration(item) for item in value)
    return False


def _semantic_resources(document: dict[str, Any]) -> list[dict[str, str]]:
    resources: list[dict[str, str]] = []
    for key, resource_type in (
        ("semantic_models", "semantic_model"),
        ("metrics", "metric"),
        ("saved_queries", "saved_query"),
    ):
        entries = document.get(key)
        if not isinstance(entries, list):
            continue
        resources.extend(
            {"resource_type": resource_type, "name": str(entry["name"])}
            for entry in entries
            if isinstance(entry, dict) and entry.get("name")
        )
    return resources


def _yaml_change(
    root: Path,
    change: dict[str, Any],
) -> tuple[str, list[str], list[dict[str, str]]]:
    relative = str(change.get("path") or "")
    path = root / relative
    status = str(change.get("status") or "")
    renamed_or_deleted = status.startswith(("R", "D")) or change.get("index_status") in {"R", "D"}
    if renamed_or_deleted or not path.is_file():
        previous_path = str(change.get("original_path") or relative)
        previous = inspect_git._git(root, ["show", f"HEAD:{previous_path}"], check=False)
        if previous.returncode:
            return "rename_or_delete", [], []
        before = _parse_yaml_text(previous.stdout)
        return "rename_or_delete", _document_models(before), _semantic_resources(before)

    current_text = path.read_text(encoding="utf-8", errors="replace")
    current = _parse_yaml_text(current_text)
    models = _yaml_models(path)
    semantic = _semantic_resources(current)

    previous = inspect_git._git(root, ["show", f"HEAD:{relative}"], check=False)
    if previous.returncode:
        if semantic:
            return "semantic_or_metric", models, semantic
        if _metadata_only_document(current):
            kind = "test_only" if _contains_test_declaration(current) else "description_only"
            return kind, models, []
        return "contract", models, []

    before = _parse_yaml_text(previous.stdout)
    if before == current:
        return "formatting_or_comments_only", models, []
    if _without_keys(before, {"description"}) == _without_keys(current, {"description"}):
        return "description_only", models, []
    if _without_keys(before, {"description", "tests", "data_tests"}) == _without_keys(
        current,
        {"description", "tests", "data_tests"},
    ):
        return "test_only", models, []
    if any(
        before.get(key) != current.get(key)
        for key in ("semantic_models", "metrics", "saved_queries")
    ):
        semantic_by_identity = {
            (item["resource_type"], item["name"]): item
            for item in [*_semantic_resources(before), *semantic]
        }
        return (
            "semantic_or_metric",
            models,
            sorted(
                semantic_by_identity.values(),
                key=lambda item: (item["resource_type"], item["name"]),
            ),
        )
    return "contract", models, []


def _models_from_changes(
    root: Path,
    changes: Iterable[dict[str, Any]],
) -> tuple[list[str], set[str], list[dict[str, str]], dict[str, str]]:
    models: set[str] = set()
    downstream_models: set[str] = set()
    semantic_resources: list[dict[str, str]] = []
    yaml_change_kinds: dict[str, str] = {}
    for change in changes:
        relative = str(change.get("path") or "")
        path = root / relative
        suffix = path.suffix.lower()
        status = str(change.get("status") or "")
        renamed_or_deleted = status.startswith(("R", "D")) or change.get("index_status") in {"R", "D"}
        if suffix == ".sql" and "models" in Path(relative).parts:
            models.add(path.stem)
            if renamed_or_deleted:
                downstream_models.add(path.stem)
        elif suffix in {".yml", ".yaml"}:
            kind, yaml_models, semantic = _yaml_change(root, change)
            yaml_change_kinds[relative] = kind
            models.update(yaml_models)
            semantic_resources.extend(semantic)
            if kind in {"contract", "rename_or_delete"}:
                downstream_models.update(yaml_models)
    return (
        sorted(models),
        downstream_models,
        sorted(semantic_resources, key=lambda item: (item["resource_type"], item["name"])),
        yaml_change_kinds,
    )


def _command(*parts: str) -> str:
    return shlex.join(parts)


def _recommend_intent(
    requested_intent: str,
    *,
    explicit_models: bool,
    changes: Sequence[dict[str, Any]],
    downstream_models: set[str],
    semantic_resources: Sequence[dict[str, str]],
    yaml_change_kinds: dict[str, str],
) -> tuple[str, str]:
    if explicit_models:
        return requested_intent, "The user supplied both model scope and validation intent."

    changed_model_sql = any(
        Path(str(change.get("path") or "")).suffix.lower() == ".sql"
        and "models" in Path(str(change.get("path") or "")).parts
        for change in changes
    )
    if changed_model_sql or downstream_models:
        return "build", "Model SQL, contract, rename, or deletion changes require model and test validation."
    if semantic_resources:
        return "static", "Semantic resources must be resolved to affected models before warehouse validation."
    if "test_only" in set(yaml_change_kinds.values()):
        return "test", "Only test declarations changed, so rebuilding models is unnecessary."
    return "static", "Only comments, formatting, descriptions, or other non-executable metadata changed."


def plan_validation(
    path: str | Path,
    *,
    models: Sequence[str] | None = None,
    target: str | None = None,
    intent: str = "build",
    allow_broader_intent: bool = False,
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

    inferred_models, downstream_models, semantic_resources, yaml_change_kinds = _models_from_changes(
        root,
        changes,
    )
    selected = sorted({item.strip() for item in (models or inferred_models) if item.strip()})
    source = "explicit" if models else "git_diff"
    model_selectors = [f"{name}+" if name in downstream_models else name for name in selected]
    scoped_semantic = [] if models else semantic_resources
    semantic_selectors = [f"{item['name']}+" for item in scoped_semantic]
    resolution_selectors = sorted(set([*model_selectors, *semantic_selectors]))
    selectors = model_selectors or semantic_selectors
    contract_change = any(name in downstream_models for name in selected) or bool(scoped_semantic)
    recommended_intent, recommendation_reason = _recommend_intent(
        intent,
        explicit_models=bool(models),
        changes=changes,
        downstream_models=downstream_models,
        semantic_resources=scoped_semantic,
        yaml_change_kinds=yaml_change_kinds,
    )
    over_validation = (
        recommended_intent in {"static", "test"}
        and intent in WAREHOUSE_INTENTS
        and intent != recommended_intent
    )
    effective_intent = intent if allow_broader_intent or not over_validation else recommended_intent

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
                    *resolution_selectors,
                    "--output",
                    "name",
                ),
                "executes_warehouse": False,
                "requires_approval": False,
                "purpose": "Confirm the selector resolves only the intended resources.",
            }
        )

    blocked_reason: str | None = None
    if scoped_semantic and not selected and intent in WAREHOUSE_INTENTS:
        blocked_reason = (
            "Semantic or metric changes require an explicit affected model scope "
            "before warehouse validation."
        )
    elif not selected and not semantic_resources and effective_intent != "static":
        blocked_reason = "No changed or explicitly named dbt models established a bounded scope."
    elif effective_intent in WAREHOUSE_INTENTS and not target:
        blocked_reason = "A local or development target must be named explicitly before warehouse validation."
    elif target and PRODUCTION_TARGET.search(target):
        blocked_reason = f"Target {target!r} appears production-like and is not eligible for automated validation."
    elif effective_intent in WAREHOUSE_INTENTS:
        commands.append(
            {
                "step": len(commands) + 1,
                "command": _command(
                    "dbt",
                    effective_intent,
                    "--project-dir",
                    str(root),
                    "--select",
                    *model_selectors,
                    "--target",
                    str(target),
                ),
                "executes_warehouse": True,
                "requires_approval": True,
                "purpose": f"Run bounded {effective_intent} validation for the selected resources.",
            }
        )

    warnings = [f"Git scope unavailable: {git_error}"] if git_error else []
    if over_validation and not allow_broader_intent:
        warnings.append(
            f"Requested intent {intent!r} exceeds the deterministic recommendation "
            f"{recommended_intent!r}; the broader warehouse command was omitted. "
            "Review the recommendation or explicitly allow the broader intent."
        )

    return {
        "ok": True,
        "project_root": str(root),
        "scope": {
            "models": selected,
            "selectors": selectors,
            "resolution_selectors": resolution_selectors,
            "source": source,
            "contract_change": contract_change,
            "yaml_change_kinds": yaml_change_kinds,
            "semantic_resources": scoped_semantic,
            "changed_paths": [str(item.get("path")) for item in changes],
        },
        "target": {
            "name": target,
            "production_like": bool(target and PRODUCTION_TARGET.search(target)),
        },
        "intent": effective_intent,
        "requested_intent": intent,
        "recommended_intent": recommended_intent,
        "recommendation_reason": recommendation_reason,
        "broader_intent_requires_override": over_validation and not allow_broader_intent,
        "commands": commands,
        "blocked_reason": blocked_reason,
        "warnings": warnings,
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
    parser.add_argument(
        "--allow-broader-intent",
        action="store_true",
        help="Keep a requested warehouse intent even when static analysis recommends less work",
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
            allow_broader_intent=args.allow_broader_intent,
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
