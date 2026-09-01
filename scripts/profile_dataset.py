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


# A missing value is missing. A cell containing "NA" is a string that a human
# probably meant as missing, and might equally be Namibia, North America, or a
# product code. Counting them together produced a null rate nobody could act on,
# so they are counted separately and the reader decides.
NULL_SENTINELS = {"null", "none", "nil", "n/a", "na", "nan", "unknown", "-", "?"}
PII_NAME_PATTERNS = {
    "email": re.compile(r"(?:^|_)(?:e_?mail|email_address)(?:$|_)", re.I),
    "phone": re.compile(r"(?:^|_)(?:phone|mobile|telephone)(?:$|_)", re.I),
    "ssn": re.compile(r"(?:^|_)(?:ssn|social_security)(?:$|_)", re.I),
    "credit_card": re.compile(r"(?:^|_)(?:credit_card|card_number|pan)(?:$|_)", re.I),
    "ip_address": re.compile(r"(?:^|_)(?:ip|ip_address)(?:$|_)", re.I),
    "person_name": re.compile(r"(?:^|_)(?:first_name|last_name|full_name|given_name|surname)(?:$|_)", re.I),
    "address": re.compile(r"(?:^|_)(?:street_address|postal_address|home_address)(?:$|_)", re.I),
    "date_of_birth": re.compile(r"(?:^|_)(?:dob|date_of_birth|birth_date)(?:$|_)", re.I),
    # Numeric personal facts are the ones a profile leaks most quietly: a
    # minimum and maximum salary over six rows is close to naming the people.
    "compensation": re.compile(
        r"(?:^|_)(?:salary|compensation|income|wage|wages|net_pay|gross_pay|bonus)(?:$|_)",
        re.I,
    ),
    "financial_account": re.compile(
        r"(?:^|_)(?:account_number|account_balance|balance|iban|routing_number|"
        r"sort_code|tax_id|ein|vat_number)(?:$|_)",
        re.I,
    ),
    "government_id": re.compile(
        r"(?:^|_)(?:passport|passport_number|drivers_license|license_number|"
        r"national_id|nino)(?:$|_)",
        re.I,
    ),
    "precise_location": re.compile(
        r"(?:^|_)(?:latitude|longitude|lat|lon|lng|geo_point)(?:$|_)", re.I
    ),
}
PII_VALUE_PATTERNS = {
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    # A bare seven-digit run is a quantity far more often than a phone number.
    # Requiring a country prefix or punctuation keeps amounts and counts from
    # being reported as contact details.
    "phone": re.compile(r"^\+\d[\d(). -]{6,19}$|^(?=(?:[^\d]*\d){10,})[\d(). -]{10,20}$"),
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
    """True only for values that are genuinely absent."""
    return value is None or (isinstance(value, str) and not value.strip())


def _sentinel_null(value: Any) -> str | None:
    """The sentinel a cell spells, when it looks like a stand-in for missing."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text.lower() in NULL_SENTINELS else None


def _is_missing(value: Any) -> bool:
    """Absent or a recognized stand-in, for type inference and statistics."""
    return _is_null(value) or _sentinel_null(value) is not None


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


def _scalar_type(value: Any, *, treat_sentinels_as_missing: bool = True) -> str:
    if _is_null(value) or (treat_sentinels_as_missing and _is_missing(value)):
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


def _inferred_type(values: Iterable[Any], *, treat_sentinels_as_missing: bool = True) -> str:
    types = {
        _scalar_type(value, treat_sentinels_as_missing=treat_sentinels_as_missing)
        for value in values
    } - {"null"}
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
    if isinstance(value, bool) or _is_missing(value):
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
    sampled = [str(value).strip() for value in values if not _is_missing(value)][:200]
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
        if _is_missing(value) or not isinstance(value, str):
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
        # Two readings of the same column. `observed` is what the file contains,
        # where "NA" is the value Namibia. `sentinel_adjusted` is the hypothesis
        # that "NA" stands for missing. Only the first is established by the
        # file, and reporting only the second erased a real category.
        observed = [value for value in values if not _is_null(value)]
        present = [value for value in values if not _is_missing(value)]
        definite_nulls = sum(1 for value in values if _is_null(value))
        sentinels = Counter(
            sentinel
            for value in values
            if not _is_null(value) and (sentinel := _sentinel_null(value)) is not None
        )
        missing_count = row_count - len(present)
        unique_count = len({_canonical(value) for value in present})
        observed_unique = len({_canonical(value) for value in observed})
        inferred = _inferred_type(values)
        observed_type = _inferred_type(values, treat_sentinels_as_missing=False)
        pii = _pii_warnings(name, present)
        is_possible_key = bool(row_count and missing_count == 0 and unique_count == row_count)
        normalized_distinct = {
            _canonical(None if _is_missing(value) else value) for value in values
        }
        is_constant = bool(row_count) and len(normalized_distinct) == 1
        observed_constant = bool(row_count) and len(
            {_canonical(None if _is_null(value) else value) for value in values}
        ) == 1
        if is_possible_key:
            possible_keys.append(name)
        if is_constant:
            constants.append(name)
        all_pii.extend(pii)

        column: dict[str, Any] = {
            "name": name,
            "inferred_type": inferred,
            "null_count": definite_nulls,
            "null_percent": _percent(definite_nulls, row_count),
            "sentinel_null_count": sum(sentinels.values()),
            "sentinel_null_values": dict(sorted(sentinels.items())),
            "missing_count": missing_count,
            "missing_percent": _percent(missing_count, row_count),
            "non_null_count": len(present),
            "unique_count": unique_count,
            "cardinality": unique_count,
            "unique_percent": _percent(unique_count, len(present)),
            "possible_key": is_possible_key,
            "constant": is_constant,
            "potential_pii": bool(pii),
            "observed": {
                "inferred_type": observed_type,
                "non_null_count": len(observed),
                "unique_count": observed_unique,
                "cardinality": observed_unique,
                "constant": observed_constant,
                "possible_key": bool(
                    row_count
                    and definite_nulls == 0
                    and observed_unique == row_count
                ),
            },
        }
        if sentinels:
            observed_key = bool(
                row_count and definite_nulls == 0 and observed_unique == row_count
            )
            column["null_interpretation_note"] = (
                f"{name} has {observed_unique} observed categories, including "
                + ", ".join(sorted(sentinels))
                + f". If those stand for missing data it has {unique_count} "
                f"substantive categories and {_percent(missing_count, row_count)}% "
                "missingness. The file does not establish which reading is correct."
            )
            if observed_key != is_possible_key:
                column["sentinel_changes_key_candidacy"] = True

        if inferred in {"integer", "number"}:
            numbers = [
                number for value in present if (number := _numeric_value(value)) is not None
            ]
            # A minimum and a maximum are two real values. On a numeric identifier
            # such as a national ID or an account number, publishing them is
            # publishing two records, so the shape is reported without them.
            if numbers and not pii:
                column["numeric_min"] = min(numbers)
                column["numeric_max"] = max(numbers)
            elif numbers:
                column["numeric_range_suppressed"] = "potential_pii"
            if len(numbers) >= 8 and len(set(numbers)) >= 4:
                q1, q3 = _quartiles(numbers)
                iqr = q3 - q1
                if iqr > 0:
                    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                    count = sum(value < lower or value > upper for value in numbers)
                    if count:
                        finding: dict[str, Any] = {
                            "column": name,
                            "method": "1.5_iqr",
                            "count": count,
                            "percent_of_numeric": _percent(count, len(numbers)),
                            "values_emitted": False,
                        }
                        # Outlier bounds are derived from the data, so on a PII
                        # column they narrow the range a reader can guess within.
                        if pii:
                            finding["bounds_suppressed"] = "potential_pii"
                        else:
                            finding["lower_bound"] = lower
                            finding["upper_bound"] = upper
                        outliers.append(finding)
                        column["outliers"] = finding

        if inferred in {"date", "datetime"} and not pii:
            parsed = [
                parsed_value[1]
                for value in present
                if (parsed_value := _parse_datetime(str(value))) is not None
            ]
            if parsed:
                column["date_min"] = min(parsed).isoformat()
                column["date_max"] = max(parsed).isoformat()
        elif inferred in {"date", "datetime"} and pii:
            column["date_range_suppressed"] = "potential_pii"

        variants = _variant_findings(name, present)
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


def _unique_headers(headers: Sequence[str]) -> tuple[list[str], list[dict[str, Any]]]:
    """Make header names usable, and say so when they had to be changed.

    A file with two columns called `amount` silently became `amount` and
    `amount_2`, and every downstream statement about `amount_2` referred to a
    column the user has never heard of.
    """
    result: list[str] = []
    counts: Counter[str] = Counter()
    normalizations: list[dict[str, Any]] = []
    for index, raw in enumerate(headers, 1):
        stripped = raw.strip()
        base = stripped or f"column_{index}"
        counts[base] += 1
        name = base if counts[base] == 1 else f"{base}_{counts[base]}"
        result.append(name)
        if not stripped:
            normalizations.append(
                {"position": index, "original": raw, "renamed_to": name, "reason": "blank_header"}
            )
        elif name != stripped:
            normalizations.append(
                {
                    "position": index,
                    "original": stripped,
                    "renamed_to": name,
                    "reason": "duplicate_header",
                }
            )
        elif name != raw:
            normalizations.append(
                {
                    "position": index,
                    "original": raw,
                    "renamed_to": name,
                    "reason": "surrounding_whitespace",
                }
            )
    return result, normalizations


def _records_from_json(
    value: Any, record_path: str | None, notes: dict[str, Any]
) -> list[Any]:
    """Choose the array of records in a JSON document, or refuse to choose.

    An API payload commonly carries several arrays: the rows, plus errors,
    warnings, or included resources. Picking one at random profiles the wrong
    table; profiling the wrapper object reports one row and no useful column.
    Both were silent, so both looked like a successful profile.
    """
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        raise ProfileError(
            "JSON input must be an object, an array of objects, or contain a record array"
        )

    if record_path:
        selected: Any = value
        for segment in record_path.split("."):
            if not isinstance(selected, dict) or segment not in selected:
                raise ProfileError(f"Record path {record_path!r} does not exist in this document")
            selected = selected[segment]
        if not isinstance(selected, list):
            raise ProfileError(f"Record path {record_path!r} is not an array")
        return selected

    candidates = [
        (key, child)
        for key, child in value.items()
        if isinstance(child, list) and child and all(isinstance(item, dict) for item in child)
    ]
    # An empty array is still a named collection. Ignoring it turned
    # `{"customers": [], "orders": []}` into a one-row profile of the wrapper,
    # which reports two columns that are really two tables.
    empty = [key for key, child in value.items() if isinstance(child, list) and not child]
    if len(candidates) == 1:
        if empty:
            notes["ignored_empty_arrays"] = sorted(empty)
        return candidates[0][1]
    if len(candidates) > 1:
        described = ", ".join(f"{key} ({len(child)} records)" for key, child in candidates)
        raise ProfileError(
            "This JSON document contains more than one plausible record array "
            f"({described}). Choose one with --record-path."
        )
    if len(empty) > 1:
        raise ProfileError(
            "This JSON document contains only empty arrays "
            f"({', '.join(sorted(empty))}), so there is no record array to profile. "
            "Choose one with --record-path to confirm which collection is intended."
        )
    if len(empty) == 1:
        # One named collection and nothing competing with it. An extract that
        # returned no rows is a real and reportable answer; profiling the
        # wrapper instead would claim one row that the file does not contain.
        notes["record_path_inferred"] = empty[0]
        return value[empty[0]]
    if isinstance(value.get("records"), list):
        return value["records"]
    return [value]


def load_dataset(
    path: str | Path,
    *,
    input_format: str | None = None,
    encoding: str = "utf-8-sig",
    delimiter: str | None = None,
    record_path: str | None = None,
) -> tuple[list[dict[str, Any]], list[str], str, list[dict[str, Any]], dict[str, Any]]:
    """Load a supported dataset without modifying it."""
    notes: dict[str, Any] = {}
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
                    headers, normalizations = _unique_headers(next(reader))
                except StopIteration:
                    return [], [], fmt, [], notes
                records = []
                blank_rows = 0
                for row_number, row in enumerate(reader, 2):
                    # A physically blank line is formatting, not a record. Padding
                    # it to the header width added an all-null row that inflated
                    # every missingness percentage in the file.
                    if not row or all(
                        field is None or str(field).strip() == "" for field in row
                    ):
                        blank_rows += 1
                        continue
                    if len(row) > len(headers):
                        raise ProfileError(
                            f"CSV row {row_number} has {len(row)} fields; expected {len(headers)}"
                        )
                    padded = row + [None] * (len(headers) - len(row))
                    records.append(dict(zip(headers, padded)))
                if blank_rows:
                    notes["blank_rows_skipped"] = blank_rows
                return records, headers, fmt, normalizations, notes

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
            return records, [], fmt, [], notes

        records = _records_from_json(json.loads(text), record_path, notes)
        if any(not isinstance(record, dict) for record in records):
            raise ProfileError("JSON records must all be objects")
        return records, [], fmt, [], notes
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
    record_path: str | None = None,
) -> dict[str, Any]:
    """Load and profile a dataset path."""
    records, columns, fmt, normalizations, notes = load_dataset(
        path,
        input_format=input_format,
        encoding=encoding,
        delimiter=delimiter,
        record_path=record_path,
    )
    report = profile_records(
        records,
        source=str(Path(path).expanduser().resolve()),
        source_format=fmt,
        column_order=columns,
    )
    report["header_normalizations"] = normalizations
    report.update(notes)
    if record_path:
        report["record_path"] = record_path
    return report


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("path", help="CSV, JSON, JSONL, or NDJSON file")
    parser.add_argument("--format", choices=("csv", "json", "jsonl", "ndjson"))
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--delimiter", help="Explicit single-character CSV delimiter")
    parser.add_argument(
        "--record-path",
        help="Dotted key naming the record array to profile in a JSON document",
    )
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
            record_path=args.record_path,
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
