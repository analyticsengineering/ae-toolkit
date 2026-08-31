#!/usr/bin/env python3
"""Inspect a dbt project statically without executing dbt."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


SKIP_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "__pycache__", "logs"}
MODEL_SUFFIXES = {".sql", ".py"}
# Incremental strategies that replace or append whole partitions do not need a
# unique key. Warning about them taught readers to ignore the warning.
STRATEGIES_WITHOUT_UNIQUE_KEY = {"append", "insert_overwrite", "microbatch"}
# Keys that mark semantic-layer configuration attached to a model entry rather
# than declared at the top of a file.
MODEL_SEMANTIC_KEYS = {"semantic_model", "measures", "entities", "dimensions"}
PROJECT_LIST_KEYS = {
    "model-paths",
    "seed-paths",
    "snapshot-paths",
    "test-paths",
    "analysis-paths",
    "macro-paths",
}
SQL_PATTERNS = {
    "ref_calls": re.compile(r"\bref\s*\(", re.I),
    "source_calls": re.compile(r"\bsource\s*\(", re.I),
    "config_calls": re.compile(r"\bconfig\s*\(", re.I),
    "var_calls": re.compile(r"\bvar\s*\(", re.I),
    "is_incremental_calls": re.compile(r"\bis_incremental\s*\(", re.I),
    "select_star": re.compile(r"\bselect\s+(?:\w+\.)?\*", re.I),
    "hardcoded_schema_tables": re.compile(
        r"\b(?:from|join)\s+(?!\{\{)[`\"\[]?[A-Za-z_][\w$-]*\.[A-Za-z_][\w$-]*",
        re.I,
    ),
    "jinja_blocks": re.compile(r"(?:\{\{|\{%)"),
}


class DbtInspectionError(ValueError):
    """Raised for expected dbt inspection errors."""


class JsonArgumentParser(argparse.ArgumentParser):
    """Emit parse failures as JSON for automation-friendly CLIs."""

    def error(self, message: str) -> None:
        print(
            json.dumps({"ok": False, "error": message, "error_type": "ArgumentError"}),
            file=sys.stderr,
        )
        raise SystemExit(2)


def _strip_yaml_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    result = []
    for char in value:
        if escaped:
            result.append(char)
            escaped = False
        elif char == "\\" and quote == '"':
            result.append(char)
            escaped = True
        elif char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            result.append(char)
        elif char == "#" and quote is None:
            break
        else:
            result.append(char)
    return "".join(result).strip()


def _yaml_scalar(value: str) -> Any:
    value = _strip_yaml_comment(value).strip()
    if not value:
        return None
    if value[0:1] == value[-1:] and value.startswith(("'", '"')):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        return [
            _yaml_scalar(part)
            for part in re.split(r",(?=(?:[^'\"]|'[^']*'|\"[^\"]*\")*$)", inner)
            if part.strip()
        ]
    return value


def parse_dbt_project(text: str) -> dict[str, Any]:
    """Extract common top-level dbt_project.yml values with a YAML-lite parser."""
    result: dict[str, Any] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^([A-Za-z_][\w-]*):(?:\s*(.*))?$", line)
        if not match:
            index += 1
            continue
        key, raw_value = match.group(1), match.group(2) or ""
        value = _yaml_scalar(raw_value)
        if key in PROJECT_LIST_KEYS and value is None:
            items: list[Any] = []
            following = index + 1
            while following < len(lines):
                item_match = re.match(r"^\s+-\s*(.*?)\s*$", lines[following])
                if not item_match:
                    if lines[following].strip() and not lines[following].startswith((" ", "\t")):
                        break
                    following += 1
                    continue
                items.append(_yaml_scalar(item_match.group(1)))
                following += 1
            value = items
        result[key] = value
        index += 1
    return result


def _walk_files(root: Path) -> Iterable[Path]:
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in SKIP_DIRECTORIES and not directory.startswith(".")
        )
        for filename in sorted(files):
            yield Path(current, filename)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _manifest_summary(manifest_path: Path, root: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "present": True,
            "path": _relative(manifest_path, root),
            "valid": False,
            "error": str(exc),
        }
    if not isinstance(manifest, dict):
        return {
            "present": True,
            "path": _relative(manifest_path, root),
            "valid": False,
            "error": "manifest root is not an object",
        }

    nodes = manifest.get("nodes") if isinstance(manifest.get("nodes"), dict) else {}
    sources = manifest.get("sources") if isinstance(manifest.get("sources"), dict) else {}
    node_types: Counter[str] = Counter()
    materializations: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        resource_type = str(node.get("resource_type") or "unknown")
        node_types[resource_type] += 1
        config = node.get("config")
        if isinstance(config, dict) and config.get("materialized"):
            materializations[str(config["materialized"])] += 1
        if node.get("language"):
            languages[str(node["language"])] += 1

    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    return {
        "present": True,
        "path": _relative(manifest_path, root),
        "valid": True,
        "dbt_schema_version": metadata.get("dbt_schema_version"),
        "dbt_version": metadata.get("dbt_version"),
        "generated_at": metadata.get("generated_at"),
        "node_count": len(nodes),
        "source_count": len(sources),
        "nodes_by_resource_type": dict(sorted(node_types.items())),
        "models_by_materialization": dict(sorted(materializations.items())),
        "nodes_by_language": dict(sorted(languages.items())),
        "macro_count": len(manifest.get("macros", {}))
        if isinstance(manifest.get("macros"), dict)
        else 0,
        "exposure_count": len(manifest.get("exposures", {}))
        if isinstance(manifest.get("exposures"), dict)
        else 0,
        "metric_count": len(manifest.get("metrics", {}))
        if isinstance(manifest.get("metrics"), dict)
        else 0,
    }


def _semantic_declarations(text: str) -> dict[str, bool]:
    """Find semantic-layer configuration by structure, not by substring.

    Matching `metrics:` at any indentation counts a column named `metrics` as a
    metric definition. The keys are read at the top of the document, where dbt
    actually accepts them, and separately under model entries, where teams
    inline measures and entities.
    """
    import project_context

    document, unsupported = project_context.parse_yaml_checked(text)
    found = {"semantic_models": False, "metrics": False, "saved_queries": False}
    if not isinstance(document, dict):
        return {**found, "unsupported_yaml": unsupported}
    for key in found:
        value = document.get(key)
        if isinstance(value, list) and value:
            found[key] = True
    models = document.get("models")
    if isinstance(models, list):
        for model in models:
            if isinstance(model, dict) and MODEL_SEMANTIC_KEYS.intersection(model):
                found["semantic_models"] = True
    return {**found, "unsupported_yaml": unsupported}


def _yaml_summary(path: Path, root: Path) -> dict[str, Any]:
    text = _read_text(path)
    semantic = _semantic_declarations(text)
    return {
        "path": _relative(path, root),
        "source_blocks": len(re.findall(r"(?m)^\s*sources\s*:", text)),
        "model_blocks": len(re.findall(r"(?m)^\s*models\s*:", text)),
        "seed_blocks": len(re.findall(r"(?m)^\s*seeds\s*:", text)),
        "snapshot_blocks": len(re.findall(r"(?m)^\s*snapshots\s*:", text)),
        "test_keys": len(re.findall(r"(?m)^\s*(?:tests|data_tests)\s*:", text)),
        "description_fields": len(re.findall(r"(?m)^\s*description\s*:", text)),
        "column_entries": len(re.findall(r"(?m)^\s*-\s+name\s*:", text)),
        "contains_exposures": bool(re.search(r"(?m)^exposures\s*:", text)),
        "contains_metrics": semantic["metrics"],
        "contains_semantic_models": semantic["semantic_models"],
        "contains_saved_queries": semantic["saved_queries"],
        "unsupported_yaml": semantic["unsupported_yaml"],
    }


def _sql_summary(path: Path, root: Path) -> dict[str, Any]:
    text = _read_text(path)
    pattern_counts = {
        name: len(pattern.findall(text)) for name, pattern in SQL_PATTERNS.items()
    }
    materializations = sorted(
        set(
            re.findall(
                r"materialized\s*=\s*['\"]([A-Za-z_][\w-]*)['\"]",
                text,
                flags=re.I,
            )
        )
    )
    return {
        "path": _relative(path, root),
        "language": "python" if path.suffix.lower() == ".py" else "sql",
        "line_count": len(text.splitlines()),
        "patterns": pattern_counts,
        "configured_materializations": materializations,
        "incremental_strategies": sorted(
            set(
                re.findall(
                    r"incremental_strategy\s*=\s*['\"]([A-Za-z_][\w-]*)['\"]",
                    text,
                    flags=re.I,
                )
            )
        ),
        "on_schema_change": sorted(
            set(
                re.findall(
                    r"on_schema_change\s*=\s*['\"]([A-Za-z_][\w-]*)['\"]",
                    text,
                    flags=re.I,
                )
            )
        ),
        "has_unique_key_config": bool(
            re.search(r"\bunique_key\s*=", text, flags=re.I)
        ),
    }


def inspect_dbt(path: str | Path) -> dict[str, Any]:
    """Return deterministic static metadata about a potential dbt project."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise DbtInspectionError(f"Project path is not a directory: {root}")

    project_file = root / "dbt_project.yml"
    if not project_file.is_file():
        alternate = root / "dbt_project.yaml"
        project_file = alternate if alternate.is_file() else project_file

    project: dict[str, Any] | None = None
    project_error: str | None = None
    if project_file.is_file():
        try:
            project = parse_dbt_project(_read_text(project_file))
        except OSError as exc:
            project_error = str(exc)

    import project_context

    layout = project_context.DbtProjectLayout(root, project)
    files: list[Path] = []
    vendored_file_count = 0
    for file in _walk_files(root):
        if layout.is_own_code(file.relative_to(root).as_posix()):
            files.append(file)
        elif file.suffix.lower() in {*MODEL_SUFFIXES, ".yml", ".yaml"}:
            vendored_file_count += 1
    yaml_files = [
        file
        for file in files
        if file.suffix.lower() in {".yml", ".yaml"} and file != project_file
    ]

    configured_model_paths = list(layout.model_paths)
    model_roots = {(root / model_path).resolve() for model_path in configured_model_paths}
    model_files = [
        file
        for file in files
        if file.suffix.lower() in MODEL_SUFFIXES
        and any(
            model_root == file.parent or model_root in file.parents
            for model_root in model_roots
        )
    ]

    sql_details = [_sql_summary(file, root) for file in model_files]
    staging_roots = {
        (root / model_path / directory).resolve()
        for model_path in configured_model_paths
        for directory in ("staging", "stage", "base", "src")
    }
    has_staging_layer = any(
        directory.is_dir() and any(directory.rglob("*.sql")) for directory in staging_roots
    ) or any(
        Path(detail["path"]).stem.lower().startswith(("stg_", "staging_", "base_", "src_"))
        for detail in sql_details
    )
    yaml_details = [_yaml_summary(file, root) for file in yaml_files]
    lookml_files = [
        _relative(file, root) for file in files if file.suffix.lower() == ".lkml"
    ]
    aggregate_patterns: Counter[str] = Counter()
    materializations: Counter[str] = Counter()
    directories: Counter[str] = Counter()
    for detail in sql_details:
        aggregate_patterns.update(detail["patterns"])
        materializations.update(detail["configured_materializations"])
        parent = str(Path(detail["path"]).parent)
        directories[parent] += 1

    findings: list[dict[str, str]] = []
    for detail in sql_details:
        is_incremental = (
            "incremental" in detail["configured_materializations"]
            or detail["patterns"]["is_incremental_calls"] > 0
        )
        strategies = {value.lower() for value in detail["incremental_strategies"]}
        if (
            is_incremental
            and not detail["has_unique_key_config"]
            and not strategies & STRATEGIES_WITHOUT_UNIQUE_KEY
        ):
            findings.append(
                {
                    "code": "incremental_without_unique_key",
                    "severity": "warning",
                    "path": detail["path"],
                    "message": (
                        "Incremental model has no explicit unique_key config and no "
                        "strategy that replaces rows without one."
                    ),
                }
            )
        # Reading a source in a mart is only a violation where the project has a
        # staging layer to bypass. Flagging it in a project without one reports
        # the absence of a convention as a breach of it.
        if (
            has_staging_layer
            and "marts" in Path(detail["path"]).parts
            and detail["patterns"]["source_calls"] > 0
        ):
            findings.append(
                {
                    "code": "raw_source_in_mart",
                    "severity": "warning",
                    "path": detail["path"],
                    "message": "Mart model references a source directly, bypassing the staging layer.",
                }
            )
    for detail in yaml_details:
        if detail["source_blocks"] and not detail["description_fields"]:
            findings.append(
                {
                    "code": "undocumented_source",
                    "severity": "warning",
                    "path": detail["path"],
                    "message": "Source YAML contains no description fields.",
                }
            )

    # Artifacts live wherever `target-path` says, and the walk above excludes
    # that directory as build output, so look it up directly.
    manifest_candidates = [
        root / layout.target_path / "manifest.json",
        root / "manifest.json",
    ]
    manifest_path = next((item for item in manifest_candidates if item.is_file()), None)
    manifest = (
        _manifest_summary(manifest_path, root) if manifest_path else {"present": False}
    )

    return {
        "ok": True,
        "root": str(root),
        "is_dbt_project": project_file.is_file(),
        "project_file": _relative(project_file, root) if project_file.is_file() else None,
        "project": project,
        "project_parse_error": project_error,
        "manifest": manifest,
        "yaml_files": yaml_details,
        "yaml_file_count": len(yaml_files),
        "model_tree": {
            "configured_paths": configured_model_paths,
            "model_count": len(model_files),
            "python_model_count": sum(
                1 for detail in sql_details if detail["language"] == "python"
            ),
            "directories": dict(sorted(directories.items())),
            "files": [_relative(file, root) for file in model_files],
        },
        "layout": layout.as_dict(),
        "has_staging_layer": has_staging_layer,
        "excluded_vendored_file_count": vendored_file_count,
        "unsupported_yaml": {
            detail["path"]: detail["unsupported_yaml"]
            for detail in yaml_details
            if detail["unsupported_yaml"]
        },
        "sql_patterns": dict(sorted(aggregate_patterns.items())),
        "configured_materializations": dict(sorted(materializations.items())),
        "models": sql_details,
        "semantic_layer": {
            "detected": any(
                detail["contains_semantic_models"]
                or detail["contains_metrics"]
                or detail["contains_saved_queries"]
                for detail in yaml_details
            ),
            "semantic_model_file_count": sum(
                detail["contains_semantic_models"] for detail in yaml_details
            ),
            "metric_file_count": sum(detail["contains_metrics"] for detail in yaml_details),
            "saved_query_file_count": sum(
                detail["contains_saved_queries"] for detail in yaml_details
            ),
        },
        "bi": {
            "looker_detected": bool(lookml_files),
            "lookml_file_count": len(lookml_files),
            "lookml_files": lookml_files,
        },
        "findings": sorted(findings, key=lambda item: (item["path"], item["code"])),
        "execution_note": "Static inspection only; dbt was not executed.",
    }


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="dbt project directory")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = inspect_dbt(args.path)
    except (DbtInspectionError, OSError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
