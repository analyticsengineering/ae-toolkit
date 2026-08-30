#!/usr/bin/env python3
"""Deterministically profile CSV, JSON, and JSON Lines datasets."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


NULL_STRINGS = {"", "null", "none", "nil", "n/a", "na", "nan"}
PII_NAME_PATTERNS = {
    "email": re.compile(r"(?:^|_)(?:e_?mail|email_address)(?:$|_)", re.I),
    "phone": re.compile(r"(?:^|_)(?:phone|mobile|telephone)(?:$|_)", re.I),
    "ssn": re.compile(r"(?:^|_)(?:ssn|social_security)(?:$|_)", re.I),
    "credit_card": re.compile(r"(?:^|_)(?:credit_card|card_number|pan)(?:$|_)", re.I),
    "ip_address": re.compile(r"(?:^|_)(?:ip|ip_address)(?:$|_)", re.I),
    "person_name": re.compile(r"(?:^|_)(?:first_name|last_name|full_name|given_name|surname)(?:$|_)", re.I),
    "address": re.compile(r"(?:^|_)(?:street_address|postal_address|home_address)(?:$|_)", re.I),
    "date_of_birth": re.compile(r"(?:^|_)(?:dob|date_of_birth|birth_date)(?:$|_)", re.I),
}
PII_VALUE_PATTERNS = {
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "phone": re.compile(r"^\+?[\d(). -]{7,20}$"),
    "ssn": re.compile(r"^\d{3}-?\d{2}-?\d{4}$"),
    "credit_card": re.compile(r"^(?:\d[ -]?){13,19}$"),
    "ip_address": re.compile(
        r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$"
    ),
}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INTEGER = re.compile(r"^[+-]?(?:0|[1-9]\d*)$")
NUMBER = re.compile(r"^[+-]?(?:(?:\d+\.\d*)|(?:\d*\.\d+)|\d+)(?:[eE][+-]?\d+)?$")


class ProfileError(ValueError):
    """Raised for expected input and parsing errors."""


class JsonArgumentParser(argparse.ArgumentParser):
    """Emit parse failures as JSON for automation-friendly CLIs."""

    def error(self, message: str) -> None:
        print(
            json.dumps({"ok": False, "error": message, "error_type": "ArgumentError"}),
            file=sys.stderr,
        )
        raise SystemExit(2)


def _is_null(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().lower() in NULL_STRINGS
    )


def _parse_datetime(value: str) -> tuple[str, dt.datetime | dt.date] | None:
    text = value.strip()
    try:
        if ISO_DATE.fullmatch(text):
            return "date", dt.date.fromisoformat(text)
        candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
        if "T" in candidate or " " in candidate:
            return "datetime", dt.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return None


def _scalar_type(value: Any) -> str:
    if _is_null(value):
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    text = str(value).strip()
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return "boolean"
    # Preserve identifiers such as 00123 as strings.
    if INTEGER.fullmatch(text) and not (
        len(text.lstrip("+-")) > 1 and text.lstrip("+-").startswith("0")
    ):
        return "integer"
    if NUMBER.fullmatch(text):
        return "number"
    parsed_date = _parse_datetime(text)
    if parsed_date:
        return parsed_date[0]
    return "string"


def _inferred_type(values: Iterable[Any]) -> str:
    types = {_scalar_type(value) for value in values} - {"null"}
    if not types:
        return "null"
    if types <= {"integer"}:
        return "integer"
    if types <= {"integer", "number"}:
        return "number"
    if types <= {"date"}:
        return "date"
    if types <= {"date", "datetime"}:
        return "datetime"
    if len(types) == 1:
        return next(iter(types))
    return "mixed"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, bool) or _is_null(value):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif NUMBER.fullmatch(str(value).strip()):
        result = float(str(value).strip())
    else:
        return None
    return result if math.isfinite(result) else None


def _percent(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


def _quartiles(values: Sequence[float]) -> tuple[float, float]:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    lower = ordered[:midpoint]
    upper = ordered[midpoint + (len(ordered) % 2) :]
    return statistics.median(lower), statistics.median(upper)


def _pii_warnings(name: str, values: Sequence[Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    kinds = {kind for kind, pattern in PII_NAME_PATTERNS.items() if pattern.search(name)}
    sampled = [str(value).strip() for value in values if not _is_null(value)][:200]
    identifier_column = bool(
        re.search(r"(?:^|_)(?:id|key|code)(?:$|_)", name, re.IGNORECASE)
    )
    for kind, pattern in PII_VALUE_PATTERNS.items():
        if identifier_column and kind in {"phone", "ssn", "credit_card"}:
            continue
        matches = sum(bool(pattern.fullmatch(value)) for value in sampled)
        threshold = max(2, math.ceil(len(sampled) * 0.5))
        if matches >= threshold:
            kinds.add(kind)
    for kind in sorted(kinds):
        warnings.append(
            {
                "column": name,
                "kind": kind,
                "reason": "column_name_or_value_pattern",
                "sample_values_emitted": False,
            }
        )
    return warnings


def _variant_findings(name: str, values: Sequence[Any]) -> list[dict[str, Any]]:
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for value in values:
        if _is_null(value) or not isinstance(value, str):
            continue
        display = value.strip()
        normalized = re.sub(r"[\W_]+", "", display.casefold())
        if normalized:
            groups[normalized][display] += 1
    findings = []
    for counter in groups.values():
        if len(counter) > 1:
            findings.append(
                {
                    "column": name,
                    "distinct_variants": len(counter),
                    "occurrences": sum(counter.values()),
                    "values_emitted": False,
                }
            )
    return sorted(
        findings,
        key=lambda item: (-item["occurrences"], -item["distinct_variants"]),
    )[:20]


def profile_records(
    records: Sequence[dict[str, Any]],
    *,
    source: str | None = None,
    source_format: str | None = None,
    column_order: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Profile object-like records and return a JSON-serializable report."""
    if any(not isinstance(record, dict) for record in records):
        raise ProfileError("All records must be JSON objects or tabular rows")

    discovered: list[str] = list(column_order or [])
    seen_columns = set(discovered)
    for record in records:
        for name in record:
            text_name = str(name)
            if text_name not in seen_columns:
                discovered.append(text_name)
                seen_columns.add(text_name)

    row_count = len(records)
    row_fingerprints = Counter(
        _canonical([record.get(column) for column in discovered]) for record in records
    )
    duplicate_groups = sum(1 for count in row_fingerprints.values() if count > 1)
    duplicate_rows = sum(count - 1 for count in row_fingerprints.values() if count > 1)

    columns: list[dict[str, Any]] = []
    possible_keys: list[str] = []
    constants: list[str] = []
    all_pii: list[dict[str, Any]] = []
    all_variants: list[dict[str, Any]] = []
    outliers: list[dict[str, Any]] = []

    for name in discovered:
        values = [record.get(name) for record in records]
        non_null = [value for value in values if not _is_null(value)]
        null_count = row_count - len(non_null)
        unique_count = len({_canonical(value) for value in non_null})
        inferred = _inferred_type(values)
        pii = _pii_warnings(name, non_null)
        is_possible_key = bool(
            row_count and null_count == 0 and unique_count == row_count
        )
        normalized_distinct = {
            _canonical(None if _is_null(value) else value) for value in values
        }
        is_constant = bool(row_count) and len(normalized_distinct) == 1
        if is_possible_key:
            possible_keys.append(name)
        if is_constant:
            constants.append(name)
        all_pii.extend(pii)

        column: dict[str, Any] = {
            "name": name,
            "inferred_type": inferred,
            "null_count": null_count,
            "null_percent": _percent(null_count, row_count),
            "non_null_count": len(non_null),
            "unique_count": unique_count,
            "cardinality": unique_count,
            "unique_percent": _percent(unique_count, len(non_null)),
            "possible_key": is_possible_key,
            "constant": is_constant,
            "potential_pii": bool(pii),
        }

        if inferred in {"integer", "number"}:
            numbers = [
                number
                for value in non_null
                if (number := _numeric_value(value)) is not None
            ]
            if numbers:
                column["numeric_min"] = min(numbers)
                column["numeric_max"] = max(numbers)
            if len(numbers) >= 8 and len(set(numbers)) >= 4:
                q1, q3 = _quartiles(numbers)
                iqr = q3 - q1
                if iqr > 0:
                    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                    count = sum(value < lower or value > upper for value in numbers)
                    if count:
                        finding = {
                            "column": name,
                            "method": "1.5_iqr",
                            "count": count,
                            "percent_of_numeric": _percent(count, len(numbers)),
                            "lower_bound": lower,
                            "upper_bound": upper,
                            "values_emitted": False,
                        }
                        outliers.append(finding)
                        column["outliers"] = finding

        if inferred in {"date", "datetime"} and not pii:
            parsed = [
                parsed_value[1]
                for value in non_null
                if (parsed_value := _parse_datetime(str(value))) is not None
            ]
            if parsed:
                column["date_min"] = min(parsed).isoformat()
                column["date_max"] = max(parsed).isoformat()

        variants = _variant_findings(name, non_null)
        if variants:
            column["suspicious_variant_groups"] = len(variants)
            all_variants.extend(variants)
        columns.append(column)

    return {
        "ok": True,
        "source": source,
        "format": source_format,
        "row_count": row_count,
        "column_count": len(discovered),
        "columns": columns,
        "duplicate_rows": duplicate_rows,
        "duplicate_row_groups": duplicate_groups,
        "possible_keys": possible_keys,
        "constants": constants,
        "suspicious_categorical_variants": all_variants,
        "outliers": outliers,
        "potential_pii_warnings": all_pii,
        "privacy_note": "Potentially sensitive sample values are never included.",
    }


def _unique_headers(headers: Sequence[str]) -> list[str]:
    result: list[str] = []
    counts: Counter[str] = Counter()
    for index, raw in enumerate(headers, 1):
        base = raw.strip() or f"column_{index}"
        counts[base] += 1
        result.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return result


def load_dataset(
    path: str | Path,
    *,
    input_format: str | None = None,
    encoding: str = "utf-8-sig",
    delimiter: str | None = None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """Load a supported dataset without modifying it."""
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise ProfileError(f"Input file does not exist or is not a file: {file_path}")
    fmt = (input_format or file_path.suffix.lstrip(".")).lower()
    if fmt == "ndjson":
        fmt = "jsonl"
    if fmt not in {"csv", "json", "jsonl"}:
        raise ProfileError("Unsupported format; use csv, json, jsonl, or ndjson")

    try:
        if fmt == "csv":
            with file_path.open("r", encoding=encoding, newline="") as handle:
                if delimiter is None:
                    sample = handle.read(65536)
                    handle.seek(0)
                    try:
                        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
                    except csv.Error:
                        dialect = csv.excel
                    reader = csv.reader(handle, dialect)
                else:
                    reader = csv.reader(handle, delimiter=delimiter)
                try:
                    headers = _unique_headers(next(reader))
                except StopIteration:
                    return [], [], fmt
                records = []
                for row_number, row in enumerate(reader, 2):
                    if not row and not headers:
                        continue
                    if len(row) > len(headers):
                        raise ProfileError(
                            f"CSV row {row_number} has {len(row)} fields; expected {len(headers)}"
                        )
                    padded = row + [None] * (len(headers) - len(row))
                    records.append(dict(zip(headers, padded)))
                return records, headers, fmt

        text = file_path.read_text(encoding=encoding)
        if fmt == "jsonl":
            records = []
            for line_number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ProfileError(f"JSONL line {line_number} is not an object")
                records.append(value)
            return records, [], fmt

        value = json.loads(text)
        if isinstance(value, list):
            records = value
        elif isinstance(value, dict) and isinstance(value.get("records"), list):
            records = value["records"]
        elif isinstance(value, dict):
            record_arrays = [
                (key, child)
                for key, child in value.items()
                if isinstance(child, list)
                and all(isinstance(record, dict) for record in child)
            ]
            records = record_arrays[0][1] if len(record_arrays) == 1 else [value]
        else:
            raise ProfileError(
                "JSON input must be an object, an array of objects, or contain a record array"
            )
        if any(not isinstance(record, dict) for record in records):
            raise ProfileError("JSON records must all be objects")
        return records, [], fmt
    except UnicodeError as exc:
        raise ProfileError(f"Could not decode input using {encoding}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}") from exc
    except OSError as exc:
        raise ProfileError(f"Could not read input: {exc}") from exc


def profile_dataset(
    path: str | Path,
    *,
    input_format: str | None = None,
    encoding: str = "utf-8-sig",
    delimiter: str | None = None,
) -> dict[str, Any]:
    """Load and profile a dataset path."""
    records, columns, fmt = load_dataset(
        path, input_format=input_format, encoding=encoding, delimiter=delimiter
    )
    return profile_records(
        records,
        source=str(Path(path).expanduser().resolve()),
        source_format=fmt,
        column_order=columns,
    )


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("path", help="CSV, JSON, JSONL, or NDJSON file")
    parser.add_argument("--format", choices=("csv", "json", "jsonl", "ndjson"))
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--delimiter", help="Explicit single-character CSV delimiter")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.delimiter is not None and len(args.delimiter) != 1:
        print(
            json.dumps({"ok": False, "error": "--delimiter must be one character"}),
            file=sys.stderr,
        )
        return 2
    try:
        report = profile_dataset(
            args.path,
            input_format=args.format,
            encoding=args.encoding,
            delimiter=args.delimiter,
        )
    except (ProfileError, OSError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
