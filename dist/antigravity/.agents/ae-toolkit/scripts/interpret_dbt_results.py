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
import dbt_capabilities  # noqa: E402
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
    # dbt State: the node passed earlier against identical inputs and was not
    # run this time.
    "reused": "reused",
}

# dbt State also reports `success` for a model it cloned from another
# environment or skipped as fresh enough, and has changed which status those
# carry between releases, so the message is read as well as the status.
NOT_EXECUTED_MESSAGE = re.compile(
    r"cloned from (?:an)?other environment|within lag tolerance|\breused\b", re.IGNORECASE
)

# Worst-first, so one failed node decides the overall reading.
STATUS_PRECEDENCE = ("failed", "partial", "warned", "passed", "no_op", "reused", "skipped")


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


def _read_freshness_json(path_value: str | Path) -> dict[str, Any]:
    """Recognize dbt v2's `freshness.json` without claiming to understand it.

    dbt publishes no schema for this file yet, so its provenance is checked the
    same way as any artifact's and its per-node results are counted, but no
    pass or fail reading is derived from a structure nobody has documented.
    """
    path = Path(path_value).expanduser().resolve()
    base: dict[str, Any] = {"path": str(path), "present": path.is_file(), "valid": False, "metadata": {}}
    if not base["present"]:
        return base
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {**base, "error": str(exc)}
    if not isinstance(document, dict):
        return {**base, "error": "freshness.json root is not an object"}
    results = document.get("results")
    return {
        **base,
        "valid": True,
        "metadata": artifact_inventory.artifact_metadata(document),
        "result_count": len(results) if isinstance(results, list) else None,
        "note": (
            "freshness.json is recognized as the result of `dbt freshness`, but its "
            "contents are not interpreted. Run `dbt source freshness` for a source "
            "reading this toolkit can explain, or read the command's own output."
        ),
    }


def _not_written(
    json_artifacts: dbt_capabilities.Capability,
    expected_operation: str | None,
    log_text: str | None,
) -> dict[str, Any]:
    """The answer when the command that ran was not writing artifacts."""
    result: dict[str, Any] = {
        "ok": True,
        "status": "not_written",
        "artifact": {"kind": None, "present": False, "valid": False},
        "failure_count": 0,
        "failures": [],
        "warning_count": 0,
        "warnings": [],
        "json_artifacts": json_artifacts.as_dict(),
        "artifact_verified": False,
        "verified": False,
        "interpretation_note": (
            "JSON artifacts were turned off for this command "
            f"({json_artifacts.evidence}), so no artifact in the target directory "
            "describes it, including any left by an earlier run. Report the "
            "command's exit status and log, or rerun it with JSON artifacts on."
        ),
    }
    if expected_operation:
        result["expected_operation"] = expected_operation
        result["expected_artifact"] = artifact_inventory.OPERATION_ARTIFACTS.get(expected_operation)
    if log_text:
        redacted = _redact(log_text)
        match = re.search(
            r"(?im)^\s*(compilation error|database error|runtime error)\b[:\s-]*(.*)$", redacted
        )
        if match:
            message = " ".join(part for part in match.groups() if part).strip()
            result["status"] = "failed"
            result["failures"] = [
                {
                    "unique_id": "log",
                    "status": "error",
                    "reading": "failed",
                    "category": _category("", message),
                    "message": message,
                    "execution_time": None,
                }
            ]
            result["failure_count"] = 1
    return result


def interpret_results(
    run_results: str | Path | None = None,
    *,
    log_text: str | None = None,
    sources: str | Path | None = None,
    freshness_json: str | Path | None = None,
    expected_operation: str | None = None,
    since: str | None = None,
    invocation_id: str | None = None,
    json_artifacts: dbt_capabilities.Capability | None = None,
) -> dict[str, Any]:
    artifact_present = False
    artifact_valid = False
    findings: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    node_statuses: list[str] = []
    batches: list[dict[str, Any]] = []
    not_executed: list[dict[str, Any]] = []
    evidence: dict[str, artifact_inventory.ArtifactEvidence] = {}

    if json_artifacts is not None and json_artifacts.value is False:
        return _not_written(json_artifacts, expected_operation, log_text)

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
                        raw_message = str(result.get("message") or "")
                        if reading == "passed" and NOT_EXECUTED_MESSAGE.search(raw_message):
                            reading = "reused"
                        node_statuses.append(reading)
                        batch = _batch_summary(result)
                        if batch:
                            batches.append(
                                {"unique_id": str(result.get("unique_id") or ""), **batch}
                            )
                        if reading == "reused":
                            not_executed.append(
                                {
                                    "unique_id": str(result.get("unique_id") or "unknown"),
                                    "status": raw_status,
                                    "message": _redact(raw_message) or None,
                                }
                            )
                            continue
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

    model_freshness = _read_freshness_json(freshness_json) if freshness_json is not None else None
    if model_freshness is not None and model_freshness["valid"]:
        evidence["freshness"] = _evidence(
            "freshness",
            model_freshness["path"],
            dict(model_freshness["metadata"]),
            since=since,
            invocation_id=invocation_id,
        )

    status = _overall_status(node_statuses, artifact_valid)
    mismatch = _provenance_mismatch(run_results, sources, metadata)
    if freshness is not None and not mismatch:
        status = _combine_freshness(status, freshness["status"])

    # A warning counted as a failure sends a reader looking for a break that did
    # not happen, so each reading keeps its own list.
    failures = [item for item in findings if item["reading"] == "failed"]
    warnings = [item for item in findings if item["reading"] == "warned"]
    partial = [item for item in findings if item["reading"] == "partial"]

    if run_results is None and sources is None and model_freshness is not None:
        artifact_block = {
            "kind": "freshness",
            "present": model_freshness["present"],
            "valid": model_freshness["valid"],
            **model_freshness["metadata"],
        }
        if status == "unknown" and model_freshness["valid"]:
            status = "uninterpreted"
    elif run_results is None and freshness is not None:
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
    if not_executed:
        # Reused and cloned nodes are not failures, and they are not evidence
        # either: the code they would have tested is not the code that ran.
        result["not_executed_count"] = len(not_executed)
        result["not_executed"] = not_executed[:50]
        result["not_executed_note"] = (
            "dbt State reused or cloned these nodes instead of running them, so their "
            "status describes an earlier run, not this change."
        )
    if model_freshness is not None:
        result["freshness"] = {
            key: value for key, value in model_freshness.items() if key != "metadata"
        }
    if expected_operation:
        expected_kind = artifact_inventory.OPERATION_ARTIFACTS.get(expected_operation)
        result["expected_operation"] = expected_operation
        result["expected_artifact"] = expected_kind
    else:
        expected_kind = "run_results" if run_results is not None else (
            "sources" if sources is not None else (
                "freshness" if freshness_json is not None else None
            )
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
    parser.add_argument("--freshness", help="Path to freshness.json from dbt v2 `dbt freshness`")
    parser.add_argument(
        "--command",
        help=(
            "The exact dbt command that ran; with `--no-write-json` no artifact can "
            "describe it, and the reader says so instead of reading an older one"
        ),
    )
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
    command: str | None = None,
) -> tuple[dict[str, str | None], dbt_capabilities.Capability]:
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
    paths = {kind: str(path) if path else None for kind, path in resolved.items()}
    return paths, dbt_capabilities.json_artifacts_written(context, command=command)


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

    run_results, sources, freshness = args.run_results, args.sources, args.freshness
    json_artifacts = (
        dbt_capabilities.json_artifacts_written(None, command=args.command)
        if args.command
        else None
    )
    if args.project_dir:
        try:
            discovered, json_artifacts = _artifacts_from_project(
                args.project_dir, args.expect_operation, args.command
            )
        except (inspect_dbt.DbtInspectionError, OSError, ValueError) as exc:
            print(
                json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
                file=sys.stderr,
            )
            return 1
        run_results = run_results or discovered["run_results"]
        sources = sources or discovered["sources"]
        freshness = freshness or discovered["freshness"]

    result = interpret_results(
        run_results,
        log_text=log_text,
        sources=sources,
        freshness_json=freshness,
        expected_operation=args.expect_operation,
        since=args.since,
        invocation_id=invocation_id,
        json_artifacts=json_artifacts,
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
