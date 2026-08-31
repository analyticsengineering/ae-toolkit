#!/usr/bin/env python3
"""Interpret dbt output artifacts without executing dbt or exposing secrets."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inspect_dbt  # noqa: E402
import redact_secrets  # noqa: E402


def _redact(message: str) -> str:
    return str(redact_secrets.inspect_text(message).get("redacted_content", message))


def _category(unique_id: str, message: str) -> str:
    lowered = message.lower()
    if unique_id.startswith("test."):
        return "test-assertion"
    if "compilation error" in lowered or "compile error" in lowered:
        return "compile"
    if "database error" in lowered or "sql error" in lowered:
        return "database"
    if "dependency" in lowered or "package" in lowered:
        return "dependency"
    if "permission" in lowered or "access denied" in lowered:
        return "permission"
    return "unknown"


def _lag_seconds(criteria: Any, snapshotted_at: Any, max_loaded_at: Any) -> float | None:
    """How far behind the source was when freshness ran, in seconds."""
    from datetime import datetime, timezone

    def moment(value: Any) -> Any:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    snapshot, loaded = moment(snapshotted_at), moment(max_loaded_at)
    if snapshot is None or loaded is None:
        return None
    return round((snapshot - loaded).total_seconds(), 1)


def interpret_source_freshness(sources: str | Path) -> dict[str, Any]:
    """Read `sources.json` so a freshness run closes its own loop.

    Running `dbt source freshness` and then reading nothing back means the plan
    recommended a check whose result nobody interpreted. Freshness fails per
    table, and which table is late is the entire finding.
    """
    path = Path(sources).expanduser().resolve()
    if not path.is_file():
        return {
            "present": False,
            "path": str(path),
            "status": "unknown",
            "results": [],
        }
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "present": True,
            "path": str(path),
            "status": "unknown",
            "error": str(exc),
            "results": [],
        }
    if not isinstance(document, dict):
        return {
            "present": True,
            "path": str(path),
            "status": "unknown",
            "error": "sources.json root is not an object",
            "results": [],
        }

    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    results: list[dict[str, Any]] = []
    for entry in document.get("results") or []:
        if not isinstance(entry, dict):
            continue
        unique_id = str(entry.get("unique_id") or "unknown")
        parts = unique_id.split(".")
        source_name, table_name = (parts[-2], parts[-1]) if len(parts) >= 4 else (None, None)
        criteria = entry.get("criteria") if isinstance(entry.get("criteria"), dict) else {}
        results.append(
            {
                "unique_id": unique_id,
                "source": source_name,
                "table": table_name,
                "selector": f"source:{source_name}.{table_name}" if source_name else None,
                "status": str(entry.get("status") or "unknown").lower(),
                "max_loaded_at": entry.get("max_loaded_at"),
                "snapshotted_at": entry.get("snapshotted_at"),
                "lag_seconds": _lag_seconds(
                    criteria, entry.get("snapshotted_at"), entry.get("max_loaded_at")
                ),
                "warn_after": criteria.get("warn_after"),
                "error_after": criteria.get("error_after"),
            }
        )

    statuses = {item["status"] for item in results}
    if "error" in statuses or "runtime error" in statuses:
        status = "failed"
    elif "warn" in statuses:
        status = "warned"
    elif results:
        status = "passed"
    else:
        status = "unknown"
    return {
        "present": True,
        "path": str(path),
        "status": status,
        "generated_at": metadata.get("generated_at"),
        "dbt_version": metadata.get("dbt_version"),
        "result_count": len(results),
        "stale_sources": [
            item["selector"] for item in results if item["status"] in {"warn", "error"}
        ],
        "results": results,
    }


def interpret_results(
    run_results: str | Path | None = None,
    *,
    log_text: str | None = None,
    sources: str | Path | None = None,
) -> dict[str, Any]:
    artifact_present = False
    artifact_valid = False
    failures: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}

    if run_results is not None:
        path = Path(run_results).expanduser().resolve()
        artifact_present = path.is_file()
        if artifact_present:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                metadata["artifact_error"] = str(exc)
            else:
                artifact_valid = isinstance(document, dict)
                if artifact_valid:
                    raw_metadata = document.get("metadata")
                    if isinstance(raw_metadata, dict):
                        metadata["dbt_version"] = raw_metadata.get("dbt_version")
                        metadata["generated_at"] = raw_metadata.get("generated_at")
                    for result in document.get("results", []):
                        if not isinstance(result, dict):
                            continue
                        status = str(result.get("status") or "unknown")
                        if status.lower() in {"success", "pass", "skipped"}:
                            continue
                        unique_id = str(result.get("unique_id") or "unknown")
                        message = _redact(str(result.get("message") or "No failure message was recorded."))
                        failures.append(
                            {
                                "unique_id": unique_id,
                                "status": status,
                                "category": _category(unique_id, message),
                                "message": message,
                                "execution_time": result.get("execution_time"),
                            }
                        )

    if log_text:
        redacted = _redact(log_text)
        if not failures:
            match = re.search(
                r"(?im)^\s*(compilation error|database error|runtime error)\b[:\s-]*(.*)$",
                redacted,
            )
            if match:
                message = " ".join(part for part in match.groups() if part).strip()
                failures.append(
                    {
                        "unique_id": "log",
                        "status": "error",
                        "category": _category("", message),
                        "message": message,
                        "execution_time": None,
                    }
                )

    freshness = interpret_source_freshness(sources) if sources is not None else None

    status = "failed" if failures else ("passed" if artifact_valid else "unknown")
    if freshness is not None and freshness["status"] == "failed":
        status = "failed"
    elif status == "unknown" and freshness is not None and freshness["status"] in {"passed", "warned"}:
        status = freshness["status"]

    result: dict[str, Any] = {
        "ok": True,
        "status": status,
        "artifact": {
            "present": artifact_present,
            "valid": artifact_valid,
            **metadata,
        },
        "failure_count": len(failures),
        "failures": failures,
        "interpretation_note": "Artifacts and supplied logs only; dbt was not executed.",
    }
    if freshness is not None:
        result["source_freshness"] = freshness
    return result


def _parser() -> argparse.ArgumentParser:
    parser = inspect_dbt.JsonArgumentParser(description=__doc__)
    parser.add_argument("--run-results", help="Path to run_results.json")
    parser.add_argument("--sources", help="Path to sources.json from dbt source freshness")
    parser.add_argument(
        "--project-dir",
        help="dbt project directory; artifacts are read from its configured target path",
    )
    parser.add_argument("--log", help="Path to a bounded dbt log excerpt")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def _artifacts_from_project(project_dir: str) -> tuple[str | None, str | None]:
    """Resolve artifact paths through the project's configured `target-path`."""
    import artifact_inventory
    import project_context

    context = project_context.resolve_project_context(project_dir)
    if not context.is_dbt_project:
        raise inspect_dbt.DbtInspectionError(
            f"No dbt project was resolved at {project_dir}"
        )
    inventory = artifact_inventory.inventory_artifacts(context)
    run_results = inventory.current.get("run_results")
    sources = inventory.current.get("sources")
    return (
        str(run_results.path) if run_results and run_results.present else None,
        str(sources.path) if sources and sources.present else None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    log_text = None
    if args.log:
        try:
            log_text = Path(args.log).expanduser().read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(
                json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
                file=sys.stderr,
            )
            return 1

    run_results, sources = args.run_results, args.sources
    if args.project_dir:
        try:
            discovered_results, discovered_sources = _artifacts_from_project(args.project_dir)
        except (inspect_dbt.DbtInspectionError, OSError, ValueError) as exc:
            print(
                json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
                file=sys.stderr,
            )
            return 1
        run_results = run_results or discovered_results
        sources = sources or discovered_sources

    result = interpret_results(run_results, log_text=log_text, sources=sources)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
