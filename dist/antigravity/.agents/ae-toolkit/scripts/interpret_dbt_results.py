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


def interpret_results(
    run_results: str | Path | None = None,
    *,
    log_text: str | None = None,
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

    status = "failed" if failures else ("passed" if artifact_valid else "unknown")
    return {
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


def _parser() -> argparse.ArgumentParser:
    parser = inspect_dbt.JsonArgumentParser(description=__doc__)
    parser.add_argument("--run-results", help="Path to run_results.json")
    parser.add_argument("--log", help="Path to a bounded dbt log excerpt")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


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
    result = interpret_results(args.run_results, log_text=log_text)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
