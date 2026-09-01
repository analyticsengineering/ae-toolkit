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

import artifact_inventory  # noqa: E402
import inspect_dbt  # noqa: E402
import redact_secrets  # noqa: E402


# dbt's current run-results schema. A status the reader does not know is not a
# failure; treating `warn`, `no-op`, and `partial success` as failures reported
# problems that did not happen and hid the two batches that really failed.
RESULT_STATUS = {
    "success": "passed",
    "pass": "passed",
    "warn": "warned",
    "no-op": "no_op",
    "noop": "no_op",
    "skipped": "skipped",
    "partial success": "partial",
    "fail": "failed",
    "error": "failed",
    "runtime error": "failed",
}

# Worst-first, so one failed node decides the overall reading.
STATUS_PRECEDENCE = ("failed", "partial", "warned", "passed", "no_op", "skipped")


def _redact(message: str) -> str:
    return str(redact_secrets.inspect_text(message).get("redacted_content", message))


def _category(unique_id: str, message: str) -> str:
    """Classify a failure by what went wrong, not by what kind of node it was.

    A test node whose message says "permission denied" did not fail its
    assertion; it never ran. Reading the node type first turned an access
    problem into a data-quality finding and sent the reader to the wrong place.
    """
    lowered = message.lower()
    if "compilation error" in lowered or "compile error" in lowered:
        return "compile"
    if "permission" in lowered or "access denied" in lowered or "not authorized" in lowered:
        return "permission"
    if "database error" in lowered or "sql error" in lowered:
        return "database"
    if "dependency" in lowered or "package" in lowered:
        return "dependency"
    if unique_id.startswith("test."):
        return "test-assertion"
    return "unknown"


def _batch_summary(result: dict[str, Any]) -> dict[str, Any] | None:
    """Microbatch outcomes, which decide whether a partial run is nearly fine."""
    batches = result.get("batch_results")
    if not isinstance(batches, dict):
        return None
    successful = batches.get("successful") or []
    failed = batches.get("failed") or []
    if not isinstance(successful, list) or not isinstance(failed, list):
        return None
    return {
        "successful": len(successful),
        "failed": len(failed),
        "total": len(successful) + len(failed),
        "failed_batches": [str(item) for item in failed[:20]],
    }


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
            "valid": False,
            "path": str(path),
            "status": "unknown",
            "metadata": {},
            "results": [],
        }
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "present": True,
            "valid": False,
            "path": str(path),
            "status": "unknown",
            "error": str(exc),
            "metadata": {},
            "results": [],
        }
    if not isinstance(document, dict):
        return {
            "present": True,
            "valid": False,
            "path": str(path),
            "status": "unknown",
            "error": "sources.json root is not an object",
            "metadata": {},
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
        "valid": True,
        "path": str(path),
        "status": status,
        "generated_at": metadata.get("generated_at"),
        "dbt_version": metadata.get("dbt_version"),
        "metadata": artifact_inventory.artifact_metadata(document),
        "result_count": len(results),
        "stale_sources": [
            item["selector"] for item in results if item["status"] in {"warn", "error"}
        ],
        "results": results,
    }


def invocation_id_from_log(log_path: str | Path) -> str | None:
    """Read back the invocation ID dbt chose for a run.

    dbt generates `invocation_id` itself and documents no flag or environment
    variable to set it, so the only way to hold an artifact to an exact command
    is to run that command with JSON logging and recover the ID it recorded.
    """
    path = Path(log_path).expanduser()
    if path.is_dir():
        path = path / "dbt.log"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for holder in (event.get("info"), event.get("data"), event):
            if isinstance(holder, dict) and holder.get("invocation_id"):
                return str(holder["invocation_id"])
    match = re.search(r'"invocation_id"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else None


def _evidence(
    kind: str,
    path: str | Path | None,
    metadata: dict[str, Any],
    *,
    since: str | None,
    invocation_id: str | None,
) -> artifact_inventory.ArtifactEvidence:
    """Judge one artifact's provenance through the one shared rule."""
    correlated, reason = artifact_inventory.correlate(
        metadata, since=since, invocation_id=invocation_id
    )
    return artifact_inventory.ArtifactEvidence(
        kind=kind,
        path=Path(path) if path is not None else None,
        metadata=metadata,
        correlated=correlated,
        reason=reason,
    )


def interpret_results(
    run_results: str | Path | None = None,
    *,
    log_text: str | None = None,
    sources: str | Path | None = None,
    expected_operation: str | None = None,
    since: str | None = None,
    invocation_id: str | None = None,
) -> dict[str, Any]:
    artifact_present = False
    artifact_valid = False
    findings: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    node_statuses: list[str] = []
    batches: list[dict[str, Any]] = []
    evidence: dict[str, artifact_inventory.ArtifactEvidence] = {}

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
                    metadata.update(artifact_inventory.artifact_metadata(document))
                    evidence["run_results"] = _evidence(
                        "run_results",
                        path,
                        dict(metadata),
                        since=since,
                        invocation_id=invocation_id,
                    )
                    for result in document.get("results", []):
                        if not isinstance(result, dict):
                            continue
                        raw_status = str(result.get("status") or "unknown")
                        reading = RESULT_STATUS.get(raw_status.lower(), "failed")
                        node_statuses.append(reading)
                        batch = _batch_summary(result)
                        if batch:
                            batches.append(
                                {"unique_id": str(result.get("unique_id") or ""), **batch}
                            )
                        if reading in {"passed", "skipped", "no_op"}:
                            continue
                        unique_id = str(result.get("unique_id") or "unknown")
                        message = _redact(
                            str(result.get("message") or "No failure message was recorded.")
                        )
                        entry = {
                            "unique_id": unique_id,
                            "status": raw_status,
                            "reading": reading,
                            "category": _category(unique_id, message),
                            "message": message,
                            "execution_time": result.get("execution_time"),
                        }
                        if batch:
                            entry["batches"] = batch
                        findings.append(entry)

    if log_text:
        redacted = _redact(log_text)
        if not findings:
            match = re.search(
                r"(?im)^\s*(compilation error|database error|runtime error)\b[:\s-]*(.*)$",
                redacted,
            )
            if match:
                message = " ".join(part for part in match.groups() if part).strip()
                findings.append(
                    {
                        "unique_id": "log",
                        "status": "error",
                        "reading": "failed",
                        "category": _category("", message),
                        "message": message,
                        "execution_time": None,
                    }
                )
                node_statuses.append("failed")

    freshness = interpret_source_freshness(sources) if sources is not None else None
    if freshness is not None and freshness.get("valid"):
        evidence["sources"] = _evidence(
            "sources",
            freshness.get("path"),
            dict(freshness.get("metadata") or {}),
            since=since,
            invocation_id=invocation_id,
        )
        freshness["provenance"] = evidence["sources"].as_dict()

    status = _overall_status(node_statuses, artifact_valid)
    mismatch = _provenance_mismatch(run_results, sources, metadata)
    if freshness is not None and not mismatch:
        status = _combine_freshness(status, freshness["status"])

    # A warning counted as a failure sends a reader looking for a break that did
    # not happen, so each reading keeps its own list.
    failures = [item for item in findings if item["reading"] == "failed"]
    warnings = [item for item in findings if item["reading"] == "warned"]
    partial = [item for item in findings if item["reading"] == "partial"]

    if run_results is None and freshness is not None:
        artifact_block = {
            "kind": "sources",
            "present": bool(freshness.get("present")),
            "valid": bool(freshness.get("valid")),
            **(freshness.get("metadata") or {}),
        }
    else:
        artifact_block = {
            "kind": "run_results",
            "present": artifact_present,
            "valid": artifact_valid,
            **metadata,
        }

    result: dict[str, Any] = {
        "ok": True,
        "status": status,
        "artifact": artifact_block,
        "failure_count": len(failures),
        "failures": failures,
        "warning_count": len(warnings),
        "warnings": warnings,
        "interpretation_note": "Artifacts and supplied logs only; dbt was not executed.",
    }
    if partial:
        result["partial"] = partial
    if expected_operation:
        expected_kind = artifact_inventory.OPERATION_ARTIFACTS.get(expected_operation)
        result["expected_operation"] = expected_operation
        result["expected_artifact"] = expected_kind
    else:
        expected_kind = "run_results" if run_results is not None else (
            "sources" if sources is not None else None
        )
    proof = evidence.get(expected_kind) if expected_kind else None
    if evidence:
        result["evidence"] = {kind: item.as_dict() for kind, item in sorted(evidence.items())}
    if proof is not None:
        result["provenance"] = proof.as_dict()
    # Proving the artifact is current is a claim about the file, not about the
    # change. Freshness now earns it through the same rule run-results does.
    result["artifact_verified"] = bool(proof is not None and proof.correlated)
    result["verified"] = result["artifact_verified"]
    if batches:
        result["batches"] = batches
    if mismatch:
        result["provenance_mismatch"] = mismatch
    if freshness is not None:
        result["source_freshness"] = freshness
    return result


def _overall_status(readings: Sequence[str], artifact_valid: bool) -> str:
    if not readings:
        return "passed" if artifact_valid else "unknown"
    for candidate in STATUS_PRECEDENCE:
        if candidate in readings:
            # A run in which every node was skipped completed nothing, so
            # calling it "passed" retires an obligation nobody satisfied.
            return "incomplete" if candidate == "skipped" else candidate
    return "unknown"


def _combine_freshness(status: str, freshness_status: str) -> str:
    if freshness_status == "failed":
        return "failed"
    if status == "unknown" and freshness_status in {"passed", "warned"}:
        return freshness_status
    return status


def _provenance_mismatch(
    run_results: str | Path | None,
    sources: str | Path | None,
    metadata: dict[str, Any],
) -> str | None:
    """Refuse to merge two artifacts that different commands produced."""
    if run_results is None or sources is None:
        return None
    path = Path(sources).expanduser().resolve()
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    freshness_metadata = artifact_inventory.artifact_metadata(document)
    left, right = metadata.get("invocation_id"), freshness_metadata.get("invocation_id")
    if left and right and left == right:
        return None
    return (
        "run_results.json and sources.json record different dbt invocations "
        f"({left or 'unknown'} and {right or 'unknown'}), so their outcomes "
        "describe different commands and are reported separately."
    )


def _parser() -> argparse.ArgumentParser:
    parser = inspect_dbt.JsonArgumentParser(description=__doc__)
    parser.add_argument("--run-results", help="Path to run_results.json")
    parser.add_argument("--sources", help="Path to sources.json from dbt source freshness")
    parser.add_argument(
        "--project-dir",
        help="dbt project directory; artifacts are read from its configured target path",
    )
    parser.add_argument("--log", help="Path to a bounded dbt log excerpt")
    parser.add_argument(
        "--expect-operation",
        choices=sorted(
            key
            for key, value in artifact_inventory.OPERATION_ARTIFACTS.items()
            if value is not None
        ),
        help="The validation operation whose artifact should be read",
    )
    parser.add_argument(
        "--since",
        help="ISO timestamp captured before the command ran; the artifact must be newer",
    )
    parser.add_argument(
        "--invocation-id",
        help="The dbt invocation ID the artifact must record",
    )
    parser.add_argument(
        "--invocation-log",
        help=(
            "A JSON dbt log directory or file from the command that just ran; "
            "the invocation ID is read from it"
        ),
    )
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def _artifacts_from_project(
    project_dir: str,
    expected_operation: str | None,
) -> tuple[str | None, str | None]:
    """Resolve artifact paths through the project's configured `target-path`.

    Reading every artifact in the directory is how a failed build from an hour
    ago got reported as the outcome of a freshness check. When the operation is
    known, only its artifact is read.
    """
    import project_context

    context = project_context.resolve_project_context(project_dir)
    if not context.is_dbt_project:
        raise inspect_dbt.DbtInspectionError(
            f"No dbt project was resolved at {project_dir}"
        )
    inventory = artifact_inventory.inventory_artifacts(context)
    resolved = inventory.resolve_operation_paths(expected_operation)
    return (
        str(resolved["run_results"]) if resolved["run_results"] else None,
        str(resolved["sources"]) if resolved["sources"] else None,
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

    invocation_id = args.invocation_id
    log_invocation_missing = False
    if not invocation_id and args.invocation_log:
        invocation_id = invocation_id_from_log(args.invocation_log)
        log_invocation_missing = invocation_id is None

    run_results, sources = args.run_results, args.sources
    if args.project_dir:
        try:
            discovered_results, discovered_sources = _artifacts_from_project(
                args.project_dir, args.expect_operation
            )
        except (inspect_dbt.DbtInspectionError, OSError, ValueError) as exc:
            print(
                json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
                file=sys.stderr,
            )
            return 1
        run_results = run_results or discovered_results
        sources = sources or discovered_sources

    result = interpret_results(
        run_results,
        log_text=log_text,
        sources=sources,
        expected_operation=args.expect_operation,
        since=args.since,
        invocation_id=invocation_id,
    )
    if log_invocation_missing:
        result["invocation_log_note"] = (
            "No invocation ID was found in the named dbt log, so correlation fell "
            "back to the generation timestamp."
        )
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
