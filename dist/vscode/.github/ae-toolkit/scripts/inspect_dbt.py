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


def _yaml_summary(path: Path, root: Path) -> dict[str, Any]:
    text = _read_text(path)
    return {
        "path": _relative(path, root),
        "source_blocks": len(re.findall(r"(?m)^\s*sources\s*:", text)),
        "model_blocks": len(re.findall(r"(?m)^\s*models\s*:", text)),
        "seed_blocks": len(re.findall(r"(?m)^\s*seeds\s*:", text)),
        "snapshot_blocks": len(re.findall(r"(?m)^\s*snapshots\s*:", text)),
        "test_keys": len(re.findall(r"(?m)^\s*(?:tests|data_tests)\s*:", text)),
        "description_fields": len(re.findall(r"(?m)^\s*description\s*:", text)),
        "column_entries": len(re.findall(r"(?m)^\s*-\s+name\s*:", text)),
        "contains_exposures": bool(re.search(r"(?m)^\s*exposures\s*:", text)),
        "contains_metrics": bool(re.search(r"(?m)^\s*metrics\s*:", text)),
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
        "line_count": len(text.splitlines()),
        "patterns": pattern_counts,
        "configured_materializations": materializations,
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

    files = list(_walk_files(root))
    yaml_files = [
        file
        for file in files
        if file.suffix.lower() in {".yml", ".yaml"} and file != project_file
    ]
    sql_files = [file for file in files if file.suffix.lower() == ".sql"]

    configured_model_paths = (
        project.get("model-paths") if isinstance(project, dict) else None
    )
    if not isinstance(configured_model_paths, list) or not configured_model_paths:
        configured_model_paths = ["models"]
    model_roots = {
        (root / str(model_path)).resolve()
        for model_path in configured_model_paths
        if isinstance(model_path, str)
    }
    model_files = [
        file
        for file in sql_files
        if any(model_root == file.parent or model_root in file.parents for model_root in model_roots)
    ]

    sql_details = [_sql_summary(file, root) for file in model_files]
    yaml_details = [_yaml_summary(file, root) for file in yaml_files]
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
        if is_incremental and not detail["has_unique_key_config"]:
            findings.append(
                {
                    "code": "incremental_without_unique_key",
                    "severity": "warning",
                    "path": detail["path"],
                    "message": "Incremental model has no explicit unique_key config.",
                }
            )
        if (
            "marts" in Path(detail["path"]).parts
            and detail["patterns"]["source_calls"] > 0
        ):
            findings.append(
                {
                    "code": "raw_source_in_mart",
                    "severity": "warning",
                    "path": detail["path"],
                    "message": "Mart model references a source directly.",
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

    manifests = [
        file
        for file in files
        if file.name == "manifest.json"
        and (file.parent.name == "target" or file.parent == root)
    ]
    manifest = (
        _manifest_summary(manifests[0], root)
        if manifests
        else {"present": False}
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
            "directories": dict(sorted(directories.items())),
            "files": [_relative(file, root) for file in model_files],
        },
        "sql_patterns": dict(sorted(aggregate_patterns.items())),
        "configured_materializations": dict(sorted(materializations.items())),
        "models": sql_details,
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
