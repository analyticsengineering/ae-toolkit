#!/usr/bin/env python3
"""Statically detect analytics-engineering technologies in a repository."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "venv",
}
CONFIG_NAMES = {
    ".env",
    ".env.example",
    ".python-version",
    "airflow.cfg",
    "dbt_project.yml",
    "dbt_project.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
    "environment.yml",
    "packages.yml",
    "packages.yaml",
    "poetry.lock",
    "profiles.yml",
    "profiles.yaml",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "tox.ini",
}
WAREHOUSE_PATTERNS = {
    "bigquery": [
        re.compile(r"\b(?:from|import)\s+google\.cloud(?:\s+import\s+|\.)bigquery\b", re.I),
        re.compile(r"\bgoogle-cloud-bigquery\b", re.I),
        re.compile(r"\btype\s*:\s*bigquery\b", re.I),
        re.compile(r"\bBigQueryOperator\b", re.I),
        re.compile(r"`[\w-]+\.[\w-]+\.[\w$-]+`"),
    ],
    "snowflake": [
        re.compile(r"\b(?:from|import)\s+snowflake(?:\.connector)?\b", re.I),
        re.compile(r"\bsnowflake-connector-python\b", re.I),
        re.compile(r"\btype\s*:\s*snowflake\b", re.I),
    ],
    "redshift": [
        re.compile(r"\b(?:redshift_connector|redshift-connector)\b", re.I),
        re.compile(r"\btype\s*:\s*redshift\b", re.I),
    ],
    "databricks": [
        re.compile(r"\b(?:from|import)\s+databricks\b", re.I),
        re.compile(r"\bdatabricks-sql-connector\b", re.I),
        re.compile(r"\btype\s*:\s*databricks\b", re.I),
    ],
    "postgres": [
        re.compile(r"\b(?:from|import)\s+psycopg2?\b", re.I),
        re.compile(r"\b(?:psycopg2?-binary|postgresql://)\b", re.I),
        re.compile(r"\btype\s*:\s*postgres\b", re.I),
    ],
    "duckdb": [
        re.compile(r"\b(?:from|import)\s+duckdb\b", re.I),
        re.compile(r"(?m)^\s*duckdb(?:==|>=|~=|$)", re.I),
        re.compile(r"\btype\s*:\s*duckdb\b", re.I),
    ],
}


class RepoInspectionError(ValueError):
    """Raised for expected repository inspection errors."""


class JsonArgumentParser(argparse.ArgumentParser):
    """Emit parse failures as JSON for automation-friendly CLIs."""

    def error(self, message: str) -> None:
        print(
            json.dumps({"ok": False, "error": message, "error_type": "ArgumentError"}),
            file=sys.stderr,
        )
        raise SystemExit(2)


def _walk_files(root: Path) -> Iterable[Path]:
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in SKIP_DIRECTORIES
            and not (directory.startswith(".") and directory != ".ae")
        )
        for filename in sorted(filenames):
            yield Path(current, filename)


def _read_text(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError:
        return ""
    if b"\0" in raw:
        return ""
    return raw[:max_bytes].decode("utf-8", errors="replace")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def validate_exercise_config(value: Any) -> dict[str, Any]:
    """Validate the portable, intentionally small .ae/exercise.json schema."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(value, dict):
        return {
            "valid": False,
            "errors": ["root must be a JSON object"],
            "warnings": [],
        }

    course_fields = {"exercise_id", "module_id", "lesson_id", "skills", "course_url"}
    course_schema = bool(course_fields & value.keys())
    required = (
        course_fields | {"mode"}
        if course_schema
        else {
            "id",
            "mode",
            "constraints",
            "rubric",
            "allowed_tools",
            "expected_artifacts",
            "tasks",
        }
    )
    for field in sorted(required - value.keys()):
        errors.append(f"missing required field: {field}")

    for field in (
        "id",
        "exercise_id",
        "module_id",
        "lesson_id",
        "course_url",
        "rubric",
    ):
        if field in value and (
            not isinstance(value[field], str) or not value[field].strip()
        ):
            errors.append(f"{field} must be a non-empty string")

    if "mode" in value:
        if not isinstance(value["mode"], str) or value["mode"].lower() not in {
            "work",
            "learn",
            "assessment",
        }:
            errors.append("mode must be work, learn, or assessment")

    if "skills" in value:
        if not isinstance(value["skills"], list) or not all(
            isinstance(item, str) and item.strip() for item in value["skills"]
        ):
            errors.append("skills must be an array of non-empty strings")

    if "course_url" in value and isinstance(value["course_url"], str):
        if not re.match(r"^https://", value["course_url"], re.IGNORECASE):
            warnings.append("course_url should use HTTPS")

    optional_list_fields = (
        "constraints",
        "allowed_tools",
        "expected_artifacts",
    )
    for field in optional_list_fields:
        if field in value and (
            not isinstance(value[field], list)
            or not all(isinstance(item, str) and item.strip() for item in value[field])
        ):
            errors.append(f"{field} must be an array of non-empty strings")

    if "tasks" in value:
        if not isinstance(value["tasks"], list) or not value["tasks"]:
            errors.append("tasks must be a non-empty array")
        else:
            for index, task in enumerate(value["tasks"]):
                if not isinstance(task, dict):
                    errors.append(f"tasks[{index}] must be an object")
                    continue
                for field in ("id", "prompt"):
                    if not isinstance(task.get(field), str) or not task[field].strip():
                        errors.append(
                            f"tasks[{index}].{field} must be a non-empty string"
                        )

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def _inspect_exercise(root: Path) -> dict[str, Any]:
    path = root / ".ae" / "exercise.json"
    if not path.is_file():
        return {"present": False, "path": ".ae/exercise.json"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "present": True,
            "path": ".ae/exercise.json",
            "valid": False,
            "errors": [f"invalid JSON: {exc}"],
            "warnings": [],
        }
    validation = validate_exercise_config(value)
    metadata_fields = (
        "exercise_id",
        "module_id",
        "lesson_id",
        "mode",
        "skills",
        "course_url",
    )
    return {
        "present": True,
        "path": ".ae/exercise.json",
        **validation,
        "declared_fields": sorted(value) if isinstance(value, dict) else [],
        "metadata": (
            {field: value[field] for field in metadata_fields if field in value}
            if isinstance(value, dict)
            else {}
        ),
    }


def inspect_repo(path: str | Path = ".") -> dict[str, Any]:
    """Inspect a directory and return deterministic technology signals."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise RepoInspectionError(f"Repository path is not a directory: {root}")

    files = list(_walk_files(root))
    relative_files = [_relative(file, root) for file in files]
    extension_counts: Counter[str] = Counter(
        file.suffix.lower() or "[no extension]" for file in files
    )
    sql_files = [file for file in files if file.suffix.lower() == ".sql"]
    python_files = [file for file in files if file.suffix.lower() == ".py"]
    yaml_files = [file for file in files if file.suffix.lower() in {".yml", ".yaml"}]
    config_files = sorted(
        _relative(file, root)
        for file in files
        if file.name.lower() in CONFIG_NAMES
        or file.name.lower().endswith((".toml", ".ini", ".cfg"))
    )

    warehouse_evidence: dict[str, set[str]] = defaultdict(set)
    airflow_evidence: set[str] = set()
    dbt_evidence: set[str] = set()
    python_signals: Counter[str] = Counter()
    sql_signals: Counter[str] = Counter()

    candidates = [
        file
        for file in files
        if file.resolve() != Path(__file__).resolve()
        if file.suffix.lower()
        in {".py", ".sql", ".yml", ".yaml", ".toml", ".txt", ".cfg", ".ini"}
        or file.name in {"Dockerfile"}
    ]
    for file in candidates:
        text = _read_text(file)
        if not text:
            continue
        relative = _relative(file, root)
        for warehouse, patterns in WAREHOUSE_PATTERNS.items():
            if any(pattern.search(text) for pattern in patterns):
                warehouse_evidence[warehouse].add(relative)

        if file.suffix.lower() == ".py":
            for name, pattern in {
                "pandas": r"\b(?:import|from)\s+pandas\b",
                "polars": r"\b(?:import|from)\s+polars\b",
                "pyspark": r"\b(?:import|from)\s+pyspark\b",
                "sqlalchemy": r"\b(?:import|from)\s+sqlalchemy\b",
                "jupyter_notebook_code": r"\bget_ipython\s*\(",
            }.items():
                if re.search(pattern, text):
                    python_signals[name] += 1
            if re.search(r"\bfrom\s+airflow\b|\bimport\s+airflow\b", text):
                airflow_evidence.add(relative)
            if re.search(r"\bDAG\s*\(|@dag\b", text):
                airflow_evidence.add(relative)

        if file.suffix.lower() == ".sql":
            for name, pattern in {
                "jinja": r"(?:\{\{|\{%)",
                "dbt_ref": r"\bref\s*\(",
                "dbt_source": r"\bsource\s*\(",
                "select_star": r"\bselect\s+(?:\w+\.)?\*",
                "merge": r"\bmerge\s+into\b",
                "qualify": r"\bqualify\b",
            }.items():
                if re.search(pattern, text, re.I):
                    sql_signals[name] += 1
            if re.search(r"\b(?:ref|source|config)\s*\(", text, re.I):
                dbt_evidence.add(relative)

    project_files = {
        file.name: _relative(file, root)
        for file in files
        if file.name in {"dbt_project.yml", "dbt_project.yaml"}
    }
    dbt_evidence.update(project_files.values())
    airflow_configs = [
        relative
        for relative in relative_files
        if Path(relative).name in {"airflow.cfg", "webserver_config.py"}
    ]
    airflow_evidence.update(airflow_configs)

    orchestration = {
        "airflow": {
            "detected": bool(airflow_evidence),
            "evidence_files": sorted(airflow_evidence)[:100],
        }
    }
    warehouses = {
        name: {
            "detected": bool(paths),
            "evidence_files": sorted(paths)[:100],
        }
        for name, paths in sorted(warehouse_evidence.items())
    }
    for expected in ("bigquery", "snowflake", "redshift", "databricks", "postgres", "duckdb"):
        warehouses.setdefault(expected, {"detected": False, "evidence_files": []})

    return {
        "ok": True,
        "root": str(root),
        "file_count": len(files),
        "file_types": dict(sorted(extension_counts.items())),
        "config_files": config_files,
        "technologies": {
            "dbt": {
                "detected": bool(dbt_evidence),
                "project_file": next(iter(sorted(project_files.values())), None),
                "evidence_files": sorted(dbt_evidence)[:100],
            },
            "sql": {
                "detected": bool(sql_files),
                "file_count": len(sql_files),
                "signals": dict(sorted(sql_signals.items())),
            },
            "python": {
                "detected": bool(python_files),
                "file_count": len(python_files),
                "signals": dict(sorted(python_signals.items())),
            },
            "bigquery": warehouses["bigquery"],
            "airflow": orchestration["airflow"],
        },
        "warehouses": dict(sorted(warehouses.items())),
        "orchestration": orchestration,
        "yaml_file_count": len(yaml_files),
        "exercise": _inspect_exercise(root),
        "inspection_note": "Detection is static and heuristic; inspected files were not modified.",
    }


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="Repository directory")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = inspect_repo(args.path)
    except (RepoInspectionError, OSError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
