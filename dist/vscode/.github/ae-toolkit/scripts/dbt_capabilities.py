#!/usr/bin/env python3
"""What this dbt project's engine and configuration make possible, and how we know.

Every feature that differs between dbt v1 and dbt v2 is answered here, once, so
no other script compares version strings or guesses at a flag of its own. Each
answer carries the evidence behind it, because "available", "configured", and
"proven by dbt's own output" are different claims.

Static reading only: dbt is not run, nothing is fetched, and environment values
are those of this process, which may differ from the shell where dbt runs.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inspect_dbt  # noqa: E402
import project_context  # noqa: E402

AVAILABLE = "available"
UNAVAILABLE = "unavailable"
NOT_APPLICABLE = "not_applicable"
UNKNOWN = "unknown"
# Possible here, but only dbt's own output can show it happened.
NEEDS_EVIDENCE = "requires_evidence"

TRUE_WORDS = {"1", "true", "t", "yes", "y", "on"}
FALSE_WORDS = {"0", "false", "f", "no", "n", "off"}

STATIC_ANALYSIS_MODES = {"strict", "baseline", "off"}
DEPRECATED_STRICT = {"on", "unsafe"}
STATIC_ANALYSIS_SECTIONS = ("models", "data_tests", "seeds", "snapshots", "unit_tests")

INFO_SCHEMA_QUERY = "dbt show --info <view>"
LINEAGE_QUERY = "dbt show --info column_lineage"
LINEAGE_GENERATION = "dbt compile --generate-info-schema --static-analysis strict"
# Reading every file under checks/ would cost more than it tells; a count is
# what the report needs, and a project with more than this has plenty.
MAX_CHECK_FILES = 500


@dataclass
class Capability:
    name: str
    state: str
    basis: str
    evidence: str
    value: Any = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state": self.state,
            "basis": self.basis,
            "evidence": self.evidence,
        }
        if self.value is not None:
            payload["value"] = self.value
        if self.note:
            payload["note"] = self.note
        return payload


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in TRUE_WORDS:
            return True
        if lowered in FALSE_WORDS:
            return False
    return None


@dataclass
class CommandFlags:
    """The flags and leading assignments of one dbt command line."""

    write_json: bool | None = None
    static_analysis: str | None = None
    manage_state: bool | None = None
    skip_checks: bool = False
    assignments: dict[str, str] | None = None


def command_flags(command: str | None) -> CommandFlags:
    flags = CommandFlags(assignments={})
    if not command:
        return flags
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    leading = True
    for index, token in enumerate(tokens):
        if leading and "=" in token and token.split("=", 1)[0].isidentifier():
            name, value = token.split("=", 1)
            flags.assignments[name] = value
            continue
        leading = False
        if token == "--no-write-json":
            flags.write_json = False
        elif token == "--write-json":
            flags.write_json = True
        elif token == "--manage-state":
            flags.manage_state = True
        elif token == "--no-manage-state":
            flags.manage_state = False
        elif token == "--skip-checks":
            flags.skip_checks = True
        elif token.startswith("--static-analysis="):
            flags.static_analysis = token.split("=", 1)[1].lower()
        elif token == "--static-analysis" and index + 1 < len(tokens):
            flags.static_analysis = tokens[index + 1].lower()
    return flags


def _environment_value(
    names: Sequence[str], environ: Mapping[str, str], assignments: Mapping[str, str]
) -> tuple[str | None, str | None, str]:
    """A setting from the command's own assignments first, then this process."""
    for source, values in (("command", assignments), ("environment", environ)):
        for name in names:
            if name in values:
                return values[name], f"{name} in the {source}", source
    return None, None, "environment"


def _project_flag(context: Any, *names: str) -> tuple[Any, str | None]:
    flags = context.layout.flags if context is not None and context.layout else {}
    for name in names:
        if name in flags:
            return flags[name], f"flags.{name} in dbt_project.yml"
    return None, None


def _json_artifacts(context: Any, command: CommandFlags, environ: Mapping[str, str]) -> Capability:
    if command.write_json is not None:
        flag = "--write-json" if command.write_json else "--no-write-json"
        return Capability(
            "json_artifacts",
            AVAILABLE if command.write_json else UNAVAILABLE,
            "command",
            f"{flag} on the command",
            value=command.write_json,
            note=None if command.write_json else _NO_JSON_NOTE,
        )
    raw, source, basis = _environment_value(
        ("DBT_ENGINE_WRITE_JSON", "DBT_WRITE_JSON"), environ, command.assignments or {}
    )
    if raw is None:
        raw, source = _project_flag(context, "write_json")
        basis = "declared"
    parsed = parse_bool(raw) if raw is not None else None
    if parsed is None:
        return Capability(
            "json_artifacts", AVAILABLE, "default", "dbt writes JSON artifacts by default", value=True
        )
    return Capability(
        "json_artifacts",
        AVAILABLE if parsed else UNAVAILABLE,
        basis,
        str(source),
        value=parsed,
        note=None if parsed else _NO_JSON_NOTE,
    )


_NO_JSON_NOTE = (
    "dbt writes no manifest.json or run_results.json, and the files already in the "
    "target directory are left in place from an earlier run, so they cannot prove "
    "what this command did. Read the command's exit status and log instead."
)


def _engine(context: Any) -> Capability:
    engine = context.engine
    labels = project_context.ENGINE_LABELS
    note = labels.get(engine)
    written, artifact = project_context.artifact_engine(context.target_dir())
    if written and engine != project_context.ENGINE_UNKNOWN and written != engine:
        note = (
            f"{note}. The existing {artifact} was written by {labels[written]}, so it "
            "predates the current engine and may describe the graph differently."
        )
    return Capability(
        "engine",
        UNKNOWN if engine == project_context.ENGINE_UNKNOWN else AVAILABLE,
        "declared" if str(context.engine_evidence).startswith("declared") else "inferred",
        str(context.engine_evidence),
        value=engine,
        note=note,
    )


V2_ONLY = {
    "information_schema": "The dbt Information Schema exists only in dbt v2",
    "checks": "Checks exist only in dbt v2",
    "static_analysis": "Static analysis exists only in dbt v2",
    "column_lineage": "Column-level lineage exists only in dbt v2",
}


def _v2_only(name: str, context: Any) -> Capability | None:
    if context.engine == project_context.ENGINE_CORE:
        return Capability(name, NOT_APPLICABLE, "inferred", V2_ONLY[name])
    return None


def _info_schema_dirs(context: Any) -> list[Path]:
    root = context.target_dir() / "info_schema"
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.iterdir() if path.is_dir() and path.name[:1] == "v" and path.name[1:].isdigit()
    )


def _information_schema(context: Any) -> Capability:
    not_v2 = _v2_only("information_schema", context)
    if not_v2:
        not_v2.note = "Use manifest.json and catalog.json for dbt v1 metadata."
        return not_v2
    document = context.layout.document if context.layout else {}
    declared = document.get("info_schema") if isinstance(document, dict) else None
    declared_version = declared.get("version") if isinstance(declared, dict) else None
    generated = _info_schema_dirs(context)
    if generated:
        tables = sorted(
            {entry.stem for directory in generated for entry in directory.glob("*.parquet")}
        )
        return Capability(
            "information_schema",
            AVAILABLE,
            "observed",
            "generated files under "
            + ", ".join(path.relative_to(context.dbt_root).as_posix() for path in generated),
            value={"declared_version": declared_version, "tables": tables[:50]},
            note=(
                f"Query it with `{INFO_SCHEMA_QUERY}`, which reads local metadata without a "
                "warehouse connection. Files written by `parse` carry no column types, "
                "lineage, or run results."
            ),
        )
    state = UNKNOWN if context.engine == project_context.ENGINE_UNKNOWN else NEEDS_EVIDENCE
    return Capability(
        "information_schema",
        state,
        "declared" if declared_version is not None else "none",
        (
            f"info_schema.version {declared_version} in dbt_project.yml"
            if declared_version is not None
            else "no generated Information Schema in the target directory"
        ),
        value={"declared_version": declared_version, "tables": []},
        note=(
            "dbt v2 writes it with `--generate-info-schema` on parse, compile, run, or build. "
            f"`{INFO_SCHEMA_QUERY}` reads it once generated."
        ),
    )


def _checks(context: Any) -> Capability:
    not_v2 = _v2_only("checks", context)
    if not_v2:
        return not_v2
    root = context.dbt_root
    paths = context.layout.check_paths if context.layout else ("checks",)
    found: list[str] = []
    for relative in paths:
        directory = root / relative
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.sql")):
            found.append(path.relative_to(root).as_posix())
            if len(found) >= MAX_CHECK_FILES:
                break
    document = context.layout.document if context.layout else {}
    declared = document.get("info_schema") if isinstance(document, dict) else None
    notes = [
        "`dbt build` runs checks before any model unless `--skip-checks` is passed, and a "
        "disabled check is skipped without a message, so a quiet run is not proof every "
        "check ran. `dbt check` reads project metadata locally and does not query the warehouse."
    ]
    if found and not isinstance(declared, dict):
        notes.append("Checks need `info_schema: version: 1` in dbt_project.yml to resolve.")
    return Capability(
        "checks",
        AVAILABLE if found else UNAVAILABLE,
        "observed",
        (
            f"{len(found)} check file(s) under {', '.join(paths)}"
            if found
            else f"no check files under {', '.join(paths)}"
        ),
        value={"count": len(found), "files": found[:20]},
        note=" ".join(notes),
    )


def _declared_static_analysis(document: Any) -> list[tuple[str, str]]:
    """Every `static_analysis` value in dbt_project.yml, with where it was set."""
    found: list[tuple[str, str]] = []

    def walk(node: Any, trail: str) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            key_text = str(key)
            here = f"{trail}.{key_text}" if trail else key_text
            if key_text.lstrip("+") == "static_analysis" and isinstance(value, str):
                found.append((here, value.strip().lower()))
            elif isinstance(value, dict):
                walk(value, here)

    if isinstance(document, dict):
        for section in STATIC_ANALYSIS_SECTIONS:
            walk(document.get(section), section)
    return found


def _static_analysis(context: Any, command: CommandFlags, environ: Mapping[str, str]) -> Capability:
    not_v2 = _v2_only("static_analysis", context)
    if not_v2:
        return not_v2
    document = context.layout.document if context.layout else {}
    declared = _declared_static_analysis(document)
    modes = {mode for _where, mode in declared}

    if command.static_analysis:
        mode, basis, evidence = command.static_analysis, "command", "--static-analysis on the command"
    else:
        raw, source, origin = _environment_value(
            ("DBT_STATIC_ANALYSIS",), environ, command.assignments or {}
        )
        if raw is not None:
            mode, basis, evidence = raw.strip().lower(), origin, str(source)
        elif declared:
            # The shallowest model setting is the project default; deeper ones
            # are overrides for a folder.
            model_settings = [(where.count("."), value) for where, value in declared if where.startswith("models.")]
            shallowest = min((depth for depth, _value in model_settings), default=None)
            defaults = {value for depth, value in model_settings if depth == shallowest}
            mode = next(iter(defaults)) if len(defaults) == 1 else "mixed"
            basis = "declared"
            evidence = "; ".join(f"{where}: {value}" for where, value in declared[:10])
        else:
            mode, basis, evidence = "baseline", "default", "dbt v2 defaults to baseline"

    notes: list[str] = []
    if mode in DEPRECATED_STRICT or modes & DEPRECATED_STRICT:
        notes.append("`on` and `unsafe` are deprecated spellings of `strict`.")
        if mode in DEPRECATED_STRICT:
            mode = "strict"
    if mode == "strict" or "strict" in modes or modes & DEPRECATED_STRICT:
        notes.append(
            "Strict analysis downloads source schemas from the warehouse and needs "
            "`dbt login`; a run without it falls back to baseline, so a strict setting "
            "is not proof that strict analysis ran."
        )
    if "off" in modes or mode == "off":
        notes.append("`off` applies to a model and everything downstream of it.")
    if mode not in STATIC_ANALYSIS_MODES and mode != "mixed":
        return Capability(
            "static_analysis", UNKNOWN, basis, f"unrecognized mode {mode!r} from {evidence}"
        )
    state = UNKNOWN if context.engine == project_context.ENGINE_UNKNOWN else AVAILABLE
    return Capability(
        "static_analysis",
        state,
        basis,
        evidence,
        value=mode,
        note=" ".join(notes) or None,
    )


def _column_lineage(context: Any, static_analysis: Capability, info_schema: Capability) -> Capability:
    not_v2 = _v2_only("column_lineage", context)
    if not_v2:
        not_v2.note = "Trace dbt v1 lineage at model level from manifest.json."
        return not_v2
    tables = (info_schema.value or {}).get("tables") or []
    generated = [name for name in tables if "lineage" in name]
    evidence = (
        f"generated lineage table(s) present: {', '.join(generated)}; contents not read"
        if generated
        else "no generated column lineage in the target directory"
    )
    return Capability(
        "column_lineage",
        NEEDS_EVIDENCE if context.engine != project_context.ENGINE_UNKNOWN else UNKNOWN,
        "observed" if generated else "none",
        evidence,
        note=(
            "Column lineage exists only for models analyzed in strict mode, and a model "
            "qualifies only when every parent does. Claim a column-level dependency only "
            f"from `{LINEAGE_QUERY}` output, generated by `{LINEAGE_GENERATION}`, which "
            "contacts the warehouse."
        ),
    )


def _managed_state(context: Any, command: CommandFlags, environ: Mapping[str, str]) -> Capability:
    implication = (
        "With dbt State, a test that already passed against unchanged code reports "
        "`reused` and a model cloned from another environment reports `success`; neither "
        "ran against this change. dbt State is a dbt platform service."
    )
    if command.manage_state is not None:
        return Capability(
            "managed_state",
            AVAILABLE if command.manage_state else UNAVAILABLE,
            "command",
            "--manage-state on the command" if command.manage_state else "--no-manage-state on the command",
            value=command.manage_state,
            note=implication if command.manage_state else None,
        )
    raw, source, basis = _environment_value(
        ("DBT_ENGINE_MANAGE_STATE", "DBT_ENGINE_ENABLE_STATE"), environ, command.assignments or {}
    )
    if raw is None:
        raw, source = _project_flag(context, "manage_state", "enable_state")
        basis = "declared"
    parsed = parse_bool(raw) if raw is not None else None
    if parsed is None:
        return Capability(
            "managed_state", UNAVAILABLE, "default", "dbt State is off unless enabled", value=False
        )
    return Capability(
        "managed_state",
        AVAILABLE if parsed else UNAVAILABLE,
        basis,
        str(source),
        value=parsed,
        note=implication if parsed else None,
    )


def _freshness(context: Any) -> Capability:
    target = context.target_dir()
    observed = [name for name in ("sources.json", "freshness.json") if (target / name).is_file()]
    v2 = context.engine != project_context.ENGINE_CORE
    note = "`dbt source freshness` writes sources.json on both engines and is interpreted fully."
    if v2:
        note += (
            " dbt v2's `dbt freshness` also covers models and writes freshness.json, which is "
            "recognized as that command's result but whose contents are not interpreted yet."
        )
    return Capability(
        "freshness",
        AVAILABLE,
        "observed" if observed else "default",
        ("present: " + ", ".join(observed)) if observed else "no freshness artifact in the target directory",
        value={"artifacts": observed},
        note=note,
    )


def assess(
    context: Any,
    *,
    command: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Capability]:
    """Every engine-dependent capability for one resolved project."""
    environment = os.environ if environ is None else environ
    flags = command_flags(command)
    info_schema = _information_schema(context)
    static_analysis = _static_analysis(context, flags, environment)
    capabilities = [
        _engine(context),
        _json_artifacts(context, flags, environment),
        info_schema,
        _checks(context),
        static_analysis,
        _column_lineage(context, static_analysis, info_schema),
        _managed_state(context, flags, environment),
        _freshness(context),
    ]
    return {item.name: item for item in capabilities}


def json_artifacts_written(
    context: Any, *, command: str | None = None, environ: Mapping[str, str] | None = None
) -> Capability:
    """Whether the command that produced the artifacts was writing them at all.

    `context` may be None when only the command line is known.
    """
    environment = os.environ if environ is None else environ
    return _json_artifacts(context, command_flags(command), environment)


def report(path: str, *, command: str | None = None) -> dict[str, Any]:
    context = project_context.resolve_project_context(path)
    if not context.is_dbt_project:
        return {"ok": False, "error": f"No dbt project was resolved at {path}"}
    capabilities = assess(context, command=command)
    return {
        "ok": True,
        "project_root": context.dbt_root.as_posix(),
        "engine": context.engine,
        "capabilities": {name: item.as_dict() for name, item in capabilities.items()},
        "note": (
            "Static reading; dbt was not run. Environment values are this process's, "
            "which may differ from the shell where dbt runs."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = inspect_dbt.JsonArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="Repository or dbt project directory")
    parser.add_argument(
        "--command",
        help="The dbt command line being planned or interpreted, so its flags are considered",
    )
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = report(args.path, command=args.command)
    except (project_context.ProjectContextError, OSError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
