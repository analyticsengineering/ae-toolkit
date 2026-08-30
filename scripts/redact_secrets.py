#!/usr/bin/env python3
"""Detect and redact obvious secrets without modifying source files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


DISCLAIMER = (
    "Secret detection is best-effort and may miss secrets or flag non-secrets; "
    "do not treat this result as a complete security audit."
)
PLACEHOLDERS = {
    "",
    "changeme",
    "example",
    "password",
    "redacted",
    "replace_me",
    "secret",
    "test",
    "token",
    "your_api_key",
    "your_token",
}


@dataclass(frozen=True)
class SecretMatch:
    """An internal secret span; its raw value is intentionally not serializable."""

    kind: str
    start: int
    end: int
    confidence: str


@dataclass(frozen=True)
class PatternSpec:
    kind: str
    pattern: re.Pattern[str]
    confidence: str = "high"
    group: str | int = "secret"


PATTERNS = (
    PatternSpec(
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"
            r"[\s\S]*?"
            r"-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"
        ),
        group=0,
    ),
    PatternSpec(
        "service_account_private_key",
        re.compile(
            r'(?i)"private_key"\s*:\s*"(?P<secret>(?:\\.|[^"\\]){20,})"'
        ),
    ),
    PatternSpec(
        "service_account_private_key_id",
        re.compile(r'(?i)"private_key_id"\s*:\s*"(?P<secret>[a-f0-9]{20,})"'),
    ),
    PatternSpec(
        "github_token",
        re.compile(
            r"(?<![A-Za-z0-9_])(?P<secret>gh(?:p|o|u|s|r)_[A-Za-z0-9_]{30,})(?![A-Za-z0-9_])"
        ),
    ),
    PatternSpec(
        "slack_token",
        re.compile(
            r"(?<![A-Za-z0-9-])(?P<secret>xox(?:a|b|p|r|s)-[A-Za-z0-9-]{10,})(?![A-Za-z0-9-])"
        ),
    ),
    PatternSpec(
        "aws_access_key_id",
        re.compile(r"(?<![A-Z0-9])(?P<secret>(?:AKIA|ASIA)[A-Z0-9]{16})(?![A-Z0-9])"),
    ),
    PatternSpec(
        "google_api_key",
        re.compile(r"(?<![A-Za-z0-9_-])(?P<secret>AIza[A-Za-z0-9_-]{35})(?![A-Za-z0-9_-])"),
    ),
    PatternSpec(
        "stripe_secret_key",
        re.compile(
            r"(?<![A-Za-z0-9_])(?P<secret>(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,})(?![A-Za-z0-9_])"
        ),
    ),
    PatternSpec(
        "jwt",
        re.compile(
            r"(?<![A-Za-z0-9_-])(?P<secret>eyJ[A-Za-z0-9_-]{8,}\."
            r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})(?![A-Za-z0-9_-])"
        ),
        confidence="medium",
    ),
    PatternSpec(
        "authorization_bearer_token",
        re.compile(r"(?i)\bBearer\s+(?P<secret>[A-Za-z0-9._~+/=-]{12,})"),
    ),
    PatternSpec(
        "credential_in_url",
        re.compile(
            r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:(?P<secret>[^@\s/]{6,})@"
        ),
    ),
    PatternSpec(
        "password_or_token_assignment",
        re.compile(
            r"""(?ix)
            ["']?\b(?:password|passwd|pwd|secret|client_secret|api_?key|
                access_?token|auth_?token|refresh_?token|token|
                private_?key|aws_secret_access_key)
            \b["']?\s*[:=]\s*
            (?:
                ["'](?P<quoted_secret>[^"'\r\n]{6,})["']
                |
                (?P<unquoted_secret>[^\s,;#}\]]{6,})
            )
            """
        ),
        confidence="medium",
        group="dynamic",
    ),
)


class RedactionError(ValueError):
    """Raised for expected redaction input errors."""


class JsonArgumentParser(argparse.ArgumentParser):
    """Emit parse failures as JSON for automation-friendly CLIs."""

    def error(self, message: str) -> None:
        print(
            json.dumps({"ok": False, "error": message, "error_type": "ArgumentError"}),
            file=sys.stderr,
        )
        raise SystemExit(2)


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        normalized in PLACEHOLDERS
        or normalized.startswith(("${", "{{", "<"))
        or normalized.endswith(("}}", ">"))
        or set(normalized) <= {"*", "x", "X", "-"}
    )


def _span_for_match(spec: PatternSpec, match: re.Match[str]) -> tuple[int, int]:
    if spec.group == "dynamic":
        group = "quoted_secret" if match.groupdict().get("quoted_secret") else "unquoted_secret"
        return match.span(group)
    return match.span(spec.group)


def find_secrets(text: str) -> list[SecretMatch]:
    """Find non-overlapping likely-secret spans without returning secret values."""
    candidates: list[SecretMatch] = []
    for spec in PATTERNS:
        for match in spec.pattern.finditer(text):
            start, end = _span_for_match(spec, match)
            if start < 0 or end <= start:
                continue
            if spec.kind == "password_or_token_assignment" and _looks_like_placeholder(
                text[start:end]
            ):
                continue
            candidates.append(SecretMatch(spec.kind, start, end, spec.confidence))

    # Prefer longer/high-confidence spans, then present findings in source order.
    confidence_rank = {"high": 0, "medium": 1, "low": 2}
    selected: list[SecretMatch] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            confidence_rank.get(item.confidence, 9),
            -(item.end - item.start),
            item.start,
        ),
    ):
        if any(
            candidate.start < existing.end and existing.start < candidate.end
            for existing in selected
        ):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: (item.start, item.end, item.kind))


def _line_and_column(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    column = offset + 1 if last_newline < 0 else offset - last_newline
    return line, column


def findings_for_text(text: str) -> list[dict[str, Any]]:
    """Return safe metadata about likely secrets, never their values."""
    findings = []
    for match in find_secrets(text):
        line, column = _line_and_column(text, match.start)
        end_line, end_column = _line_and_column(text, match.end)
        findings.append(
            {
                "kind": match.kind,
                "confidence": match.confidence,
                "line": line,
                "column": column,
                "end_line": end_line,
                "end_column": end_column,
                "value_emitted": False,
            }
        )
    return findings


def detect_secrets(text: str) -> list[dict[str, Any]]:
    """Public alias returning safe, JSON-serializable secret findings."""
    return findings_for_text(text)


def redact_text(text: str, replacement: str = "[REDACTED]") -> tuple[str, list[dict[str, Any]]]:
    """Return redacted text and safe finding metadata."""
    matches = find_secrets(text)
    redacted = text
    for match in reversed(matches):
        marker = replacement
        if "{kind}" in replacement:
            marker = replacement.replace("{kind}", match.kind)
        redacted = redacted[: match.start] + marker + redacted[match.end :]
    return redacted, findings_for_text(text)


def inspect_text(
    text: str,
    *,
    source: str = "text",
    emit_content: bool = True,
    replacement: str = "[REDACTED]",
) -> dict[str, Any]:
    """Inspect one text input and optionally return its redacted form."""
    redacted, findings = redact_text(text, replacement)
    result: dict[str, Any] = {
        "source": source,
        "finding_count": len(findings),
        "findings": findings,
    }
    if emit_content:
        result["redacted_content"] = redacted
    return result


def redact_files(
    paths: Iterable[str | Path],
    *,
    emit_content: bool = True,
    replacement: str = "[REDACTED]",
    encoding: str = "utf-8",
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Read and inspect files without writing to them."""
    inputs: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        try:
            if not path.is_file():
                raise OSError("path does not exist or is not a regular file")
            text = path.read_text(encoding=encoding)
            inputs.append(
                inspect_text(
                    text,
                    source=str(path.resolve()),
                    emit_content=emit_content,
                    replacement=replacement,
                )
            )
        except (OSError, UnicodeError) as exc:
            errors.append({"source": str(path), "error": str(exc)})
    return inputs, errors


def _report(inputs: list[dict[str, Any]], errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "best_effort": True,
        "disclaimer": DISCLAIMER,
        "total_findings": sum(item["finding_count"] for item in inputs),
        "inputs": inputs,
        "errors": errors,
        "inputs_modified": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Files to inspect read-only")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--stdin", action="store_true", help="Read content from stdin")
    source.add_argument("--json-text", help="Inspect literal JSON text")
    parser.add_argument(
        "--findings-only",
        action="store_true",
        help="Do not include redacted content in the JSON report",
    )
    parser.add_argument(
        "--replacement",
        default="[REDACTED:{kind}]",
        help="Replacement marker; {kind} expands to the finding kind",
    )
    parser.add_argument("--encoding", default="utf-8", help="File encoding")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    emit_content = not args.findings_only
    inputs: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    if args.files and (args.stdin or args.json_text is not None):
        errors.append(
            {
                "source": "arguments",
                "error": "provide files, --stdin, or --json-text, not a combination",
            }
        )
    elif args.json_text is not None:
        try:
            json.loads(args.json_text)
        except json.JSONDecodeError as exc:
            errors.append(
                {
                    "source": "json-text",
                    "error": f"invalid JSON at line {exc.lineno}, column {exc.colno}",
                }
            )
        else:
            inputs.append(
                inspect_text(
                    args.json_text,
                    source="json-text",
                    emit_content=emit_content,
                    replacement=args.replacement,
                )
            )
    elif args.files:
        inputs, errors = redact_files(
            args.files,
            emit_content=emit_content,
            replacement=args.replacement,
            encoding=args.encoding,
        )
    elif args.stdin or not sys.stdin.isatty():
        inputs.append(
            inspect_text(
                sys.stdin.read(),
                source="stdin",
                emit_content=emit_content,
                replacement=args.replacement,
            )
        )
    else:
        errors.append(
            {"source": "arguments", "error": "provide file(s), --stdin, or --json-text"}
        )

    report = _report(inputs, errors)
    stream = sys.stdout if report["ok"] else sys.stderr
    print(
        json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty),
        file=stream,
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
