#!/usr/bin/env python3
"""Infer a dbt project's own conventions from the models it already contains.

Every convention is reported with the evidence behind it and a strength rating,
so a workflow can act silently on a well-supported pattern and ask a human only
where the repository genuinely disagrees with itself.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inspect_dbt  # noqa: E402  (local sibling script, not an installed package)


# A pattern is only acted on silently when it is both dominant and repeated.
STRONG_RATIO = 0.8
STRONG_INSTANCES = 5
WEAK_RATIO = 0.5
MAX_EXAMPLES = 3
# How large a directory-partitioned minority must be before it is treated as a
# competing convention rather than a stray file.
MINORITY_SHARE = 0.25

# Installed packages and build output are somebody else's code. Counting them
# would report a vendored project's style as the team's own.
VENDORED_DIRECTORIES = {"dbt_packages", "dbt_modules", "target", "logs"}

LAYER_SYNONYMS = {
    "staging": ("stg", "staging", "stage", "base", "src"),
    "intermediate": ("int", "intermediate", "inter", "xf"),
    "fact": ("fct", "fact", "f"),
    "dimension": ("dim", "dimension", "d"),
}

# A pinned adapter package names the warehouse even when no profile is committed.
ADAPTER_REQUIREMENT = re.compile(r"\bdbt[-_]([a-z][a-z0-9]+)\b", re.I)
NON_ADAPTER_PACKAGES = {"core", "common", "adapters", "extractor", "artifacts", "semantic", "metadata"}

# Configuration keys only one warehouse accepts. Weaker than a pinned adapter,
# since a key can survive a migration, so this is consulted last.
#
# `partition_by` and `cluster_by` are deliberately absent. Snowflake, Databricks,
# Spark, and Athena all accept one or both, so naming BigQuery from them was a
# guess dressed as evidence, and a wrong warehouse produces SQL that cannot run.
DIALECT_FINGERPRINTS = (
    ("snowflake", re.compile(r"(?m)^\s*\+?(?:snowflake_warehouse|query_tag|transient)\s*:", re.I)),
    ("bigquery", re.compile(r"(?m)^\s*\+?(?:require_partition_filter|hours_to_expiration|kms_key_name)\s*:", re.I)),
    ("databricks", re.compile(r"(?m)^\s*\+?(?:liquid_clustered_by|databricks_compute|tblproperties)\s*:", re.I)),
    ("redshift", re.compile(r"(?m)^\s*\+?(?:dist|sort_type|bind)\s*:", re.I)),
)
# Column-name shapes that identify a row rather than describe it. A unique test
# on anything else is a constraint, not a declaration of grain.
KEY_COLUMN = re.compile(r"(?:^id$|_id$|_key$|_sk$|_pk$|^sk_|^pk_)", re.I)

SURROGATE_KEY_PATTERNS = (
    ("dbt_utils.generate_surrogate_key", re.compile(r"dbt_utils\s*\.\s*generate_surrogate_key", re.I)),
    ("dbt_utils.surrogate_key", re.compile(r"dbt_utils\s*\.\s*surrogate_key", re.I)),
)
INLINE_HASH = re.compile(r"\b(?:md5|sha256|farm_fingerprint)\s*\(", re.I)
MACRO_DEFINITION = re.compile(r"\{%-?\s*macro\s+([A-Za-z_]\w*)\s*\(")
TEST_KEYS = ("data_tests", "tests")
KEY_LINE = re.compile(r"^([^:]+):(?:\s+(.*))?$")
BLOCK_SCALARS = {">", "|", ">-", "|-", ">+", "|+"}

# dbt documents anchors, aliases, and merge keys, including a dedicated
# top-level `anchors:` property, so the reader has to understand them.
ANCHOR_VALUE = re.compile(r"^&(?P<name>[^\s\[\]{},]+)\s*(?P<rest>.*)$", re.S)
ALIAS_VALUE = re.compile(r"^\*(?P<name>[^\s\[\]{},]+)\s*$")


class ConventionInferenceError(ValueError):
    """Raised for expected convention inference errors."""


# --- Minimal YAML reader -----------------------------------------------------
#
# dbt schema files are a narrow slice of YAML: nested mappings, sequences of
# mappings, scalars, and folded descriptions. Parsing that slice directly keeps
# this script dependency-free, which matters because it runs in whatever
# interpreter the user already has.


def _significant_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw in text.replace("\t", "    ").splitlines():
        stripped = raw.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        lines.append((len(raw) - len(stripped), stripped.rstrip()))
    return lines


def _children(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[tuple[int, str]], int]:
    child: list[tuple[int, str]] = []
    end = index + 1
    while end < len(lines) and lines[end][0] > indent:
        child.append(lines[end])
        end += 1
    return child, end


class _Anchors:
    """Anchors seen so far, plus anything that made the document unreadable.

    dbt documents anchors, aliases, and merge keys, and its own examples use
    them, so refusing to read them turned healthy repositories into "unknown".
    Resolution is strictly backwards -- an alias can only name an anchor already
    parsed -- which makes a cycle unrepresentable rather than a case to detect.
    """

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.problems: list[str] = []

    def define(self, name: str, value: Any) -> Any:
        self.values[name] = value
        return value

    def resolve(self, name: str) -> Any:
        if name not in self.values:
            self.problems.append(f"unresolved_alias: {name}")
            return None
        return copy.deepcopy(self.values[name])


def _split_anchor(raw: str) -> tuple[str | None, str]:
    match = ANCHOR_VALUE.match(raw)
    if not match:
        return None, raw
    return match.group("name"), (match.group("rest") or "").strip()


def _alias_name(raw: str) -> str | None:
    match = ALIAS_VALUE.match(raw)
    return match.group("name") if match else None


def _merge_sources(raw: str, anchors: _Anchors) -> list[dict[str, Any]]:
    """The mappings a `<<:` line pulls in, highest precedence first."""
    text = raw.strip()
    names: list[str] = []
    if text.startswith("[") and text.endswith("]"):
        names = [
            item
            for part in inspect_dbt._split_flow(text[1:-1])
            if (item := _alias_name(part.strip()))
        ]
    elif (single := _alias_name(text)) is not None:
        names = [single]
    else:
        anchors.problems.append("merge_key: the merged value is not an alias")
        return []
    merged: list[dict[str, Any]] = []
    for name in names:
        value = anchors.resolve(name)
        if isinstance(value, dict):
            merged.append(value)
        elif value is not None:
            anchors.problems.append(f"merge_key: {name} is not a mapping")
    return merged


def _parse_block(lines: list[tuple[int, str]], indent: int, anchors: _Anchors) -> Any:
    if not lines:
        return None
    if lines[0][1].startswith("-"):
        return _parse_sequence(lines, indent, anchors)
    return _parse_mapping(lines, indent, anchors)


def _parse_mapping(
    lines: list[tuple[int, str]], indent: int, anchors: _Anchors
) -> dict[str, Any]:
    explicit: dict[str, Any] = {}
    merges: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        current_indent, line = lines[index]
        if current_indent != indent or line.startswith("- "):
            index += 1
            continue
        match = KEY_LINE.match(line)
        if not match:
            index += 1
            continue
        key = match.group(1).strip()
        raw = (match.group(2) or "").strip()
        child, end = _children(lines, index, indent)
        index = end

        if key == "<<":
            merges.extend(_merge_sources(raw, anchors))
            continue

        anchor, raw = _split_anchor(raw)
        alias = _alias_name(raw) if raw else None
        if alias is not None:
            value: Any = anchors.resolve(alias)
        elif raw in BLOCK_SCALARS:
            value = " ".join(text for _, text in child).strip()
        elif raw:
            value = inspect_dbt._yaml_scalar(raw)
        elif child:
            value = _parse_block(child, child[0][0], anchors)
        else:
            value = None
        if anchor:
            anchors.define(anchor, value)
        explicit[key] = value

    if not merges:
        return explicit
    # YAML merge precedence: the mapping's own keys win, and among several
    # merged mappings the first named wins.
    result: dict[str, Any] = {}
    for source in reversed(merges):
        result.update(source)
    result.update(explicit)
    return result


def _parse_sequence(lines: list[tuple[int, str]], indent: int, anchors: _Anchors) -> list[Any]:
    items: list[Any] = []
    index = 0
    while index < len(lines):
        current_indent, line = lines[index]
        if current_indent != indent or not line.startswith("-"):
            index += 1
            continue
        remainder = line[1:].strip()
        child, end = _children(lines, index, indent)
        index = end

        anchor, remainder = _split_anchor(remainder)
        alias = _alias_name(remainder) if remainder else None
        if alias is not None:
            value: Any = anchors.resolve(alias)
        elif remainder and KEY_LINE.match(remainder):
            # The key on a dash line belongs at its own textual column. Aligning
            # it with the child lines instead would flatten a nested block, so
            # `- relationships:` would absorb `to:` and `field:` as siblings.
            offset = len(line) - len(line[1:].lstrip())
            key_indent = current_indent + offset
            value = _parse_mapping([(key_indent, remainder), *child], key_indent, anchors)
        elif remainder:
            value = inspect_dbt._yaml_scalar(remainder)
        elif child:
            value = _parse_block(child, child[0][0], anchors)
        else:
            value = None
        if anchor:
            anchors.define(anchor, value)
        items.append(value)
    return items


def parse_yaml_with_diagnostics(text: str) -> tuple[Any, list[str]]:
    """Parse a dbt YAML document and report anything that made it unreliable."""
    anchors = _Anchors()
    lines = _significant_lines(text)
    document = {} if not lines else _parse_block(lines, lines[0][0], anchors)
    return document, sorted(set(anchors.problems))


def parse_yaml(text: str) -> Any:
    """Parse the subset of YAML that dbt configuration files actually use."""
    document, _problems = parse_yaml_with_diagnostics(text)
    return document


# --- Evidence ----------------------------------------------------------------


def _directories_for(examples: dict[str, list[str]], label: str) -> set[str]:
    return {Path(path).parent.as_posix() for path in examples.get(label, [])}


def _partitioned_by_directory(
    examples: dict[str, list[str]], first: str, second: str
) -> bool:
    """True when two competing patterns never appear in the same directory.

    A clean directory split is a migration or a legacy boundary, not a majority
    opinion. Counting files would hand the answer to whichever side happens to
    be larger, which is usually the side being retired.
    """
    left = _directories_for(examples, first)
    right = _directories_for(examples, second)
    return bool(left) and bool(right) and left.isdisjoint(right)


def conclude(
    counts: Counter[str],
    examples: dict[str, list[str]] | None = None,
    minimum: int = STRONG_INSTANCES,
    decode: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Turn a tally of observed patterns into a convention plus its strength."""
    total = sum(counts.values())
    if not total:
        return {
            "value": None,
            "strength": "absent",
            "confidence": 0.0,
            "supporting": 0,
            "contradicting": 0,
            "total": 0,
            "candidates": {},
            "examples": [],
            "partitioned": False,
        }

    seen = examples or {}
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    label, supporting = ranked[0]
    tied = len(ranked) > 1 and ranked[1][1] == supporting
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    partitioned = (
        len(ranked) > 1
        and (runner_up >= 2 or runner_up / total >= MINORITY_SHARE)
        and _partitioned_by_directory(seen, label, ranked[1][0])
    )
    ratio = supporting / total

    if tied or partitioned:
        strength = "split"
    elif ratio >= STRONG_RATIO and total >= minimum:
        strength = "strong"
    elif ratio >= WEAK_RATIO:
        strength = "weak"
    else:
        strength = "split"

    # A split tally has no usable answer; exposing the alphabetical winner would
    # invite a caller to treat an arbitrary tie-break as the team's convention.
    return {
        "value": None if strength == "split" else (decode(label) if decode else label),
        "strength": strength,
        "confidence": round(ratio, 3),
        "supporting": supporting,
        "contradicting": total - supporting,
        "total": total,
        "candidates": {key: value for key, value in ranked},
        "examples": sorted(set(seen.get(label, [])))[:MAX_EXAMPLES],
        "partitioned": partitioned,
    }


def _as_bool(label: str) -> bool:
    return label == "true"


def _as_int(label: str) -> int:
    return int(label)


def _as_test_list(label: str) -> list[str]:
    return sorted(label.split("+"))


# Where each observation lands in `.ae/project.yml`, and what to ask a human
# when the repository contradicts itself.
OBSERVATION_META: dict[str, dict[str, Any]] = {
    "models.staging_prefix": {"question": "Which prefix should new staging models use?"},
    "models.intermediate_prefix": {"question": "Which prefix should new intermediate models use?"},
    "models.fact_prefix": {"question": "Which prefix should new fact models use?"},
    "models.dimension_prefix": {"question": "Which prefix should new dimension models use?"},
    "models.staging_directory": {"question": "Which directory should new staging models live in?"},
    "models.intermediate_directory": {"question": "Which directory should new intermediate models live in?"},
    "models.fact_directory": {"question": "Which directory should new fact models live in?"},
    "models.dimension_directory": {"question": "Which directory should new dimension models live in?"},
    "models.final_naming": {
        "question": "Do final models use a layer prefix or business names without one?"
    },
    "models.final_directory": {"question": "Which directory should unprefixed final models live in?"},
    "surrogate_key.macro": {"question": "Which surrogate key implementation should new models use?"},
    "yaml.strategy": {"question": "Should new model documentation go in its own file or an existing grouped file?"},
    "yaml.filename_pattern": {"question": "What filename should new documentation files use?"},
    "tests.key": {"question": "Should new YAML use `data_tests` or the legacy `tests` key?"},
    "tests.primary_key": {"question": "Which tests should a primary key carry?", "decode": _as_test_list},
    "tests.relationships": {"question": "Should foreign keys carry relationships tests?", "decode": _as_bool},
    "sql.leading_commas": {"question": "Should generated SQL use leading commas?", "decode": _as_bool},
    "sql.lowercase_keywords": {"question": "Should generated SQL lowercase keywords?", "decode": _as_bool},
    "sql.ctes": {"question": "Should generated models be structured as CTEs?", "decode": _as_bool},
    "sql.indent_width": {"question": "What indent width should generated SQL use?", "decode": _as_int},
    "sources.database": {"question": "What database should new sources declare?"},
    "sources.schema_style": {"question": "Should new source schemas be literal or templated?"},
    "sources.freshness_required": {"question": "Should new sources declare freshness?", "decode": _as_bool},
    "sources.identifier_required": {
        "question": "Should source tables declare warehouse identifiers?",
        "decode": _as_bool,
    },
    # These are observations, not house conventions. Different ingestion
    # systems correctly use different load fields and SLAs. They remain in the
    # evidence report, but never become defaults for an unrelated source.
    "sources.loaded_at_field": {"resource_pattern": True},
    "sources.freshness_warn_after": {"resource_pattern": True},
    "sources.freshness_error_after": {"resource_pattern": True},
    "sources.filename_pattern": {"question": "How should source YAML files be named?"},
    "incremental.strategy": {"question": "Which incremental strategy should new models use?"},
    "incremental.unique_key_style": {"question": "How should incremental unique keys be declared?"},
    "incremental.on_schema_change": {"question": "How should incremental models handle schema changes?"},
    "incremental.filter_timestamp": {"question": "Which timestamp should incremental filters use?"},
    "documentation.model_descriptions_required": {
        "question": "Should every model carry a description?",
        "decode": _as_bool,
    },
    "documentation.column_descriptions_required": {
        "resource_pattern": True,
        "decode": _as_bool,
    },
    "documentation.column_docs_blocks": {
        "question": "Should a column that has a docs block of its name reference it?",
        "decode": _as_bool,
    },
}


class Tally:
    """Accumulates counted observations alongside the files that support them."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.examples: dict[str, list[str]] = {}

    def add(self, label: str, example: str | None = None) -> None:
        self.counts[label] += 1
        if example:
            self.examples.setdefault(label, []).append(example)


def _tallies() -> dict[str, Tally]:
    return {key: Tally() for key in OBSERVATION_META}


# --- Inference ---------------------------------------------------------------


def _is_own_code(relative: str) -> bool:
    return not VENDORED_DIRECTORIES.intersection(Path(relative).parts)


def _model_layer(name: str) -> tuple[str, str] | None:
    # Warehouses disagree about identifier case. Snowflake folds unquoted names
    # to upper, so STG_ORDERS is as conventional there as stg_orders is on
    # BigQuery. Match the layer without regard to case, but report the prefix
    # exactly as the repository writes it, so a generated model matches its
    # neighbours instead of the matching table below. A project that mixes
    # STG_ and stg_ therefore yields two candidates and becomes a question,
    # which is the right answer for a genuinely inconsistent repository.
    leading = name.split("_", 1)[0] if "_" in name else name
    for layer, synonyms in LAYER_SYNONYMS.items():
        if leading.lower() in synonyms:
            return layer, f"{leading}_"
    return None


def _macro_names(root: Path) -> set[str]:
    names: set[str] = set()
    for path in inspect_dbt._walk_files(root):
        if path.suffix.lower() != ".sql" or "macros" not in path.parts:
            continue
        names.update(MACRO_DEFINITION.findall(inspect_dbt._read_text(path)))
    return names


def _surrogate_key_label(text: str, local_macros: Iterable[str]) -> str | None:
    for label, pattern in SURROGATE_KEY_PATTERNS:
        if pattern.search(text):
            return label
    for macro in sorted(local_macros):
        if not re.search(r"(surrogate|hash)", macro, re.I):
            continue
        if re.search(rf"\{{\{{-?\s*{re.escape(macro)}\s*\(", text):
            return macro
    if INLINE_HASH.search(text):
        return "inline_hash"
    return None


def _observe_models(root: Path, model_paths: list[str], tallies: dict[str, Tally]) -> None:
    local_macros = _macro_names(root)
    for relative in model_paths:
        path = root / relative
        name = path.stem
        text = inspect_dbt._read_text(path)

        layer = _model_layer(name)
        if layer:
            layer_name, prefix = layer
            tallies[f"models.{layer_name}_prefix"].add(prefix, relative)
            directory = path.parent.relative_to(root).as_posix()
            tallies[f"models.{layer_name}_directory"].add(directory, relative)
        elif _looks_like_unprefixed_final(relative, text):
            # Classic dbt projects often put final models such as orders.sql
            # directly under models/. Absence of fct_/dim_ is itself evidence;
            # it must not be replaced with a fashionable default.
            tallies["models.final_naming"].add("unprefixed", relative)
            directory = path.parent.relative_to(root).as_posix()
            tallies["models.final_directory"].add(directory, relative)

        key_label = _surrogate_key_label(text, local_macros)
        if key_label:
            tallies["surrogate_key.macro"].add(key_label, relative)

        if path.suffix.lower() == ".py":
            # A Python model has no SQL to style and no Jinja incremental block.
            # Measuring it would dilute the SQL evidence with zeros.
            continue
        _observe_incremental(text, relative, tallies)
        _observe_sql_style(text, relative, tallies)


def _looks_like_unprefixed_final(relative: str, text: str) -> bool:
    parts = [part.lower() for part in Path(relative).parts]
    parent_parts = set(parts[:-1])
    if parent_parts & {"staging", "stage", "intermediate", "snapshots", "seeds"}:
        return False
    if parent_parts & {"marts", "mart", "reporting", "analytics", "final"}:
        return True
    # Root-level models that consume a recognized staging model are the common
    # legacy shape (for example Jaffle Shop Classic's orders.sql).
    return len(parts) == 2 and bool(
        re.search(r"\bref\s*\(\s*['\"](?:stg|staging|stage|base|src)_", text, re.I)
    )


def _config_value(text: str, key: str) -> str | None:
    match = re.search(rf"\b{re.escape(key)}\s*=\s*(['\"])(.*?)\1", text, re.I | re.S)
    return match.group(2).strip() if match else None


def _observe_incremental(text: str, relative: str, tallies: dict[str, Tally]) -> None:
    if not re.search(r"materialized\s*=\s*['\"]incremental['\"]|\bis_incremental\s*\(", text, re.I):
        return

    strategy = _config_value(text, "incremental_strategy")
    if strategy:
        tallies["incremental.strategy"].add(strategy, relative)

    unique_key = re.search(r"\bunique_key\s*=\s*(\[[^\]]+\]|['\"][^'\"]+['\"])", text, re.I | re.S)
    if unique_key:
        style = "list" if unique_key.group(1).lstrip().startswith("[") else "single"
        tallies["incremental.unique_key_style"].add(style, relative)

    schema_change = _config_value(text, "on_schema_change")
    if schema_change:
        tallies["incremental.on_schema_change"].add(schema_change, relative)

    incremental_block = re.search(
        r"\{%-?\s*if\s+is_incremental\s*\(\s*\)\s*-?%\}(.*?)\{%-?\s*endif\s*-?%\}",
        text,
        re.I | re.S,
    )
    if incremental_block:
        predicate = incremental_block.group(1)
        timestamp = re.search(
            r"\bwhere\b.*?\b([A-Za-z_][\w]*?(?:_at|_date|_timestamp|_time))\b\s*(?:>|>=|between)",
            predicate,
            re.I | re.S,
        )
        if timestamp:
            tallies["incremental.filter_timestamp"].add(timestamp.group(1), relative)


def _indent_step(lines: Sequence[str]) -> int | None:
    """Infer the indent unit from the widths that actually carry the structure.

    Taking the smallest indented line let one continuation aligned to a single
    space declare the project's indent width as 1. Widths that appear on only a
    handful of lines are dropped, and the unit is the greatest common divisor of
    what remains, so a file indented 4/8/12 reports 4 rather than 12.
    """
    indents = Counter(
        len(line) - len(line.lstrip(" "))
        for line in lines
        if line.startswith(" ") and line.strip()
    )
    positive = {width: count for width, count in indents.items() if width > 0}
    if not positive:
        return None
    total = sum(positive.values())
    dominant = [width for width, count in positive.items() if count / total >= 0.1]
    if not dominant:
        dominant = [max(positive, key=lambda width: (positive[width], -width))]
    step = dominant[0]
    for width in dominant[1:]:
        step = math.gcd(step, width)
    return step or None


def _observe_sql_style(text: str, relative: str, tallies: dict[str, Tally]) -> None:
    lines = text.splitlines()
    leading = sum(1 for line in lines if re.match(r"^\s+,\s*\S", line))
    trailing = sum(1 for line in lines if re.search(r",\s*$", line))
    if leading or trailing:
        tallies["sql.leading_commas"].add("true" if leading > trailing else "false", relative)

    lower = len(re.findall(r"\b(?:select|from|where|join|group by|order by)\b", text))
    upper = len(re.findall(r"\b(?:SELECT|FROM|WHERE|JOIN|GROUP BY|ORDER BY)\b", text))
    if lower or upper:
        tallies["sql.lowercase_keywords"].add("true" if lower >= upper else "false", relative)

    has_cte = bool(re.search(r"(?im)^\s*with\s+[\w`\"]+\s+as\s*\(", text))
    tallies["sql.ctes"].add("true" if has_cte else "false", relative)

    step = _indent_step(lines)
    if step:
        tallies["sql.indent_width"].add(str(step), relative)


def _documented_models(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    models = document.get("models")
    if not isinstance(models, list):
        return []
    return [model for model in models if isinstance(model, dict) and model.get("name")]


def _column_tests(column: dict[str, Any]) -> tuple[list[str], str | None]:
    for key in TEST_KEYS:
        raw = column.get(key)
        if not isinstance(raw, list):
            continue
        names: list[str] = []
        for entry in raw:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict):
                names.extend(str(item) for item in entry)
        return names, key
    return [], None


def _relationship_candidates(
    model_name: str,
    columns: Sequence[Any],
) -> list[tuple[str, list[str]]]:
    """Foreign-key columns that could carry a relationships test.

    Coverage was previously measured per model: one model with three untested
    foreign keys counted the same as one with a single tested key. Measuring per
    candidate column is what makes the resulting percentage mean anything.
    """
    candidates: list[tuple[str, list[str]]] = []
    for column in columns:
        if not isinstance(column, dict) or not column.get("name"):
            continue
        name = str(column["name"])
        if not KEY_COLUMN.search(name):
            continue
        tests, _key = _column_tests(column)
        # The model's own key is not a foreign key into anything.
        if "unique" in tests:
            continue
        entity = re.sub(r"^(?:stg|int|fct|dim|f|d)_", "", model_name, flags=re.I).rstrip("s")
        if name.lower() in {f"{entity.lower()}_id", f"{entity.lower()}_key", "id"}:
            continue
        candidates.append((name, tests))
    return candidates


DOC_CALL = re.compile(r"\bdoc\(\s*['\"]")
DOCS_BLOCK = re.compile(r"{%-?\s*docs\s+([A-Za-z0-9_]+)\s*-?%}")
MAX_DOCS_BLOCK_NAMES = 300


def _docs_blocks(root: Path, is_own_code: Callable[[str], bool]) -> dict[str, Any]:
    """Name the shared docs blocks, so new columns reuse them instead of new prose."""
    names: dict[str, str] = {}
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        if not is_own_code(relative) or set(Path(relative).parts) & {"target", "dbt_packages", "logs", ".git"}:
            continue
        for name in DOCS_BLOCK.findall(inspect_dbt._read_text(path)):
            names.setdefault(name, relative)
    listed = sorted(names)[:MAX_DOCS_BLOCK_NAMES]
    return {
        "count": len(names),
        "files": sorted(set(names.values())),
        "names": {name: names[name] for name in listed},
        "truncated": len(names) > MAX_DOCS_BLOCK_NAMES,
    }


CONVENTION_HEADING = re.compile(
    r"(?im)^\s{0,3}#{1,4}\s+([^\n]*\b(?:conventions?|style(?:\s+guide)?|standards|naming|guidelines|how\s+we\s+(?:model|build|write))\b[^\n]*)$"
)
CONVENTION_FILE = re.compile(r"(?i)(?:^|/)(?:readme|contributing|style|styleguide|conventions|standards)[^/]*\.md$")
MAX_WRITTEN_CONVENTION_FILES = 20


def _written_conventions(root: Path, is_own_code: Callable[[str], bool]) -> list[dict[str, Any]]:
    """Files where the team writes its conventions down, which outrank anything inferred."""
    found: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        parts = Path(relative).parts
        if len(parts) > 3 or not is_own_code(relative) or set(parts) & {"target", "dbt_packages", "logs", ".git", "node_modules"}:
            continue
        headings = [heading.strip() for heading in CONVENTION_HEADING.findall(inspect_dbt._read_text(path))]
        if headings or (CONVENTION_FILE.search(relative) and len(parts) == 1 and not relative.lower().startswith("readme")):
            found.append({"path": relative, "headings": headings[:10]})
        if len(found) >= MAX_WRITTEN_CONVENTION_FILES:
            break
    return found


def _observe_yaml(
    root: Path,
    yaml_paths: list[str],
    model_paths: list[str],
    tallies: dict[str, Tally],
    docs_block_names: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    yaml_model_entries = 0
    declared_columns = 0
    described_columns = 0
    sources: list[dict[str, Any]] = []
    source_contracts: list[dict[str, Any]] = []
    grouped_files: list[tuple[str, list[str]]] = []
    model_documentation: dict[str, tuple[bool, str]] = {}

    for relative in yaml_paths:
        document = parse_yaml(inspect_dbt._read_text(root / relative))
        models = _documented_models(document)
        if models:
            grouped_files.append((relative, [str(model["name"]) for model in models]))
        for model in models:
            yaml_model_entries += 1
            description = model.get("description")
            model_name = str(model["name"])
            described_here = bool(isinstance(description, str) and description.strip())
            described_before, previous_path = model_documentation.get(
                model_name, (False, relative)
            )
            model_documentation[model_name] = (
                described_before or described_here,
                relative if described_here else previous_path,
            )
            columns = model.get("columns") if isinstance(model.get("columns"), list) else []
            unique_columns: list[tuple[str, list[str]]] = []
            for column in columns:
                if not isinstance(column, dict) or not column.get("name"):
                    continue
                declared_columns += 1
                column_name = str(column["name"])
                column_description = column.get("description")
                if isinstance(column_description, str) and column_description.strip():
                    described_columns += 1
                if column_name in docs_block_names:
                    tallies["documentation.column_docs_blocks"].add(
                        "true" if isinstance(column_description, str) and DOC_CALL.search(column_description)
                        else "false",
                        relative,
                    )
                tallies["documentation.column_descriptions_required"].add(
                    "true" if isinstance(column_description, str) and column_description.strip() else "false",
                    relative,
                )
                tests, key_name = _column_tests(column)
                if key_name:
                    tallies["tests.key"].add(key_name, relative)
                if "unique" in tests:
                    unique_columns.append((column_name, tests))

            for column_name, tests in _relationship_candidates(model_name, columns):
                tallies["tests.relationships"].add(
                    "true" if "relationships" in tests else "false",
                    f"{relative}#{model_name}.{column_name}",
                )

            # A unique test states a constraint. It states the grain only when
            # exactly one key-shaped column carries it; two unique columns mean
            # the file has not said which one identifies a row.
            if len(unique_columns) == 1 and KEY_COLUMN.search(unique_columns[0][0]):
                tests = unique_columns[0][1]
                label = "not_null+unique" if "not_null" in tests else "unique"
                tallies["tests.primary_key"].add(label, relative)

        if isinstance(document, dict) and isinstance(document.get("sources"), list):
            for source in document["sources"]:
                if isinstance(source, dict) and source.get("name"):
                    sources.append(source)
                    source_contracts.extend(_observe_source(source, relative, tallies))
                    tallies["sources.filename_pattern"].add(
                        _source_filename_pattern(Path(relative), str(source["name"])),
                        relative,
                    )

    # The denominator is every project-owned SQL model, not only the subset
    # already present in YAML. Sparse YAML must never look like a strong
    # documentation convention.
    for model_path in model_paths:
        model_name = Path(model_path).stem
        described, example = model_documentation.get(model_name, (False, model_path))
        tallies["documentation.model_descriptions_required"].add(
            "true" if described else "false",
            example,
        )
    project_model_names = {Path(path).stem for path in model_paths}
    described_models = sum(
        1
        for name, (described, _) in model_documentation.items()
        if name in project_model_names and described
    )

    _observe_yaml_strategy(grouped_files, tallies)
    return {
        "yaml_model_entry_count": yaml_model_entries,
        "documented_model_count": described_models,
        "declared_column_count": declared_columns,
        "documented_column_count": described_columns,
        "source_count": len(sources),
        "source_contracts": source_contracts,
    }


def _configured(resource: dict[str, Any], key: str) -> Any:
    """Read both legacy direct properties and modern dbt `config:` placement."""
    config = resource.get("config")
    if isinstance(config, dict) and key in config:
        return config.get(key)
    return resource.get(key)


def _freshness_value(resource: dict[str, Any]) -> dict[str, Any] | None:
    value = _configured(resource, "freshness")
    return value if isinstance(value, dict) else None


def _thresholds(freshness: dict[str, Any] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for level in ("warn_after", "error_after"):
        threshold = freshness.get(level) if freshness else None
        if not isinstance(threshold, dict):
            continue
        count, period = threshold.get("count"), threshold.get("period")
        if count is not None and period:
            result[level] = f"{count} {period}"
    return result


def _observe_source(
    source: dict[str, Any],
    relative: str,
    tallies: dict[str, Tally],
) -> list[dict[str, Any]]:
    database = source.get("database")
    if database is not None:
        tallies["sources.database"].add(str(database), relative)

    schema = source.get("schema")
    if schema is not None:
        style = "templated" if "{{" in str(schema) else "literal"
        tallies["sources.schema_style"].add(style, relative)

    tables = source.get("tables") if isinstance(source.get("tables"), list) else []
    source_freshness = _freshness_value(source)
    has_freshness = bool(source_freshness) or any(
        isinstance(table, dict) and _freshness_value(table) for table in tables
    )
    tallies["sources.freshness_required"].add("true" if has_freshness else "false", relative)
    identifiers = [
        table
        for table in tables
        if isinstance(table, dict) and isinstance(table.get("identifier"), str)
    ]
    if tables:
        tallies["sources.identifier_required"].add(
            "true" if len(identifiers) == len(tables) else "false",
            relative,
        )

    loaded_at = _configured(source, "loaded_at_field")
    if isinstance(loaded_at, str) and loaded_at.strip():
        tallies["sources.loaded_at_field"].add(loaded_at.strip(), relative)

    freshness_blocks = [source_freshness]
    freshness_blocks.extend(_freshness_value(table) for table in tables if isinstance(table, dict))
    for freshness in freshness_blocks:
        for level, threshold in _thresholds(freshness).items():
            tallies[f"sources.freshness_{level}"].add(threshold, relative)

    source_name = str(source["name"])
    contracts: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict) or not table.get("name"):
            continue
        table_loaded_at = _configured(table, "loaded_at_field")
        table_freshness = _freshness_value(table)
        effective_loaded_at = table_loaded_at if table_loaded_at is not None else loaded_at
        effective_freshness = table_freshness if table_freshness is not None else source_freshness
        contracts.append(
            {
                "source": source_name,
                "table": str(table["name"]),
                "loaded_at_field": effective_loaded_at,
                "freshness": _thresholds(effective_freshness),
                "declared_in": relative,
            }
        )
        if isinstance(table_loaded_at, str) and table_loaded_at.strip():
            tallies["sources.loaded_at_field"].add(table_loaded_at.strip(), relative)
    return contracts


def _source_filename_pattern(path: Path, source_name: str) -> str:
    if path.stem == source_name:
        return f"{{source}}{path.suffix}"
    if path.stem == f"_{source_name}":
        return f"_{{source}}{path.suffix}"
    return path.name


def _filename_pattern(path: Path, model: str) -> str:
    """Describe how a single-model documentation file is named."""
    if path.stem == model:
        return f"{{model}}{path.suffix}"
    if path.stem == f"_{model}":
        return f"_{{model}}{path.suffix}"
    return path.name


def _observe_yaml_strategy(
    grouped_files: list[tuple[str, list[str]]], tallies: dict[str, Tally]
) -> None:
    for relative, names in grouped_files:
        path = Path(relative)
        if len(names) == 1:
            tallies["yaml.strategy"].add("model_level", relative)
            tallies["yaml.filename_pattern"].add(_filename_pattern(path, names[0]), relative)
            continue
        strategy = "project_level" if len(grouped_files) == 1 else "directory_level"
        tallies["yaml.strategy"].add(strategy, relative)
        tallies["yaml.filename_pattern"].add(path.name, relative)


def _detect_adapter(root: Path) -> tuple[str | None, str | None]:
    """Return the warehouse this project targets and how that was determined.

    A committed repository usually does not contain `profiles.yml`: dbt keeps it
    in `~/.dbt`, dbt Cloud supplies it, and teams gitignore it because it holds
    credentials. Reading only that file therefore leaves the warehouse unknown
    on most real projects, so fall back to signals a repository does commit.
    Each source is weaker than the last, and the caller reports which one
    answered, because a wrong warehouse is more harmful than an unknown one.
    """
    profiles = root / "profiles.yml"
    if profiles.is_file():
        match = re.search(r"(?m)^\s+type:\s*([A-Za-z_]+)\s*$", inspect_dbt._read_text(profiles))
        if match:
            return match.group(1), "profiles.yml"

    for candidate in ("requirements.txt", "pyproject.toml", "setup.py", "requirements-dev.txt"):
        path = root / candidate
        if not path.is_file():
            continue
        found = ADAPTER_REQUIREMENT.findall(inspect_dbt._read_text(path))
        # dbt-core and dbt-common are not warehouses.
        adapters = sorted({name.lower() for name in found} - NON_ADAPTER_PACKAGES)
        if len(adapters) == 1:
            return adapters[0], candidate
        if len(adapters) > 1:
            return None, f"{candidate} names more than one adapter: {', '.join(adapters)}"

    project_file = root / "dbt_project.yml"
    if project_file.is_file():
        text = inspect_dbt._read_text(project_file)
        matched = sorted({name for name, pattern in DIALECT_FINGERPRINTS if pattern.search(text)})
        if len(matched) == 1:
            return matched[0], "dbt_project.yml configuration keys"
        if len(matched) > 1:
            return None, (
                "dbt_project.yml configuration keys point at more than one warehouse: "
                + ", ".join(matched)
            )

    return None, None


def _adapter_confidence(source: str | None) -> str:
    """How much weight the adapter evidence can carry.

    A committed profile or a pinned adapter package states the warehouse. A
    configuration key only suggests it, because keys outlive the migrations that
    left them behind, so downstream SQL generation must treat it as provisional.
    """
    if not source:
        return "none"
    if "more than one" in source:
        return "none"
    if source == "profiles.yml":
        return "high"
    if source.endswith((".txt", ".toml", ".py")):
        return "high"
    return "medium"


def _profile_fingerprint(root: Path, paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(set(paths)):
        path = root / relative
        if not path.is_file():
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _repository_context(
    root: Path,
    yaml_paths: list[str],
    is_own_code: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    own = is_own_code or _is_own_code
    lookml_files = [
        path
        for path in inspect_dbt._walk_files(root)
        if path.suffix.lower() == ".lkml" and own(path.relative_to(root).as_posix())
    ]
    semantic_files = 0
    metric_files = 0
    saved_query_files = 0
    for relative in yaml_paths:
        declared = inspect_dbt._semantic_declarations(
            inspect_dbt._read_text(root / relative)
        )
        semantic_files += int(declared["semantic_models"])
        metric_files += int(declared["metrics"])
        saved_query_files += int(declared["saved_queries"])

    orchestration: list[str] = []
    for path in inspect_dbt._walk_files(root):
        relative = path.relative_to(root).as_posix()
        if not own(relative):
            continue
        lowered = relative.lower()
        if lowered in {"dbt_cloud.yml", "dbt_cloud.yaml"}:
            orchestration.append("dbt-cloud")
        elif path.suffix.lower() == ".py":
            text = inspect_dbt._read_text(path)
            if re.search(r"\bDAG\s*\(", text) and re.search(r"\bdbt\b", text, re.I):
                orchestration.append("airflow")
    workflows = root / ".github" / "workflows"
    if workflows.is_dir() and any(
        "dbt" in inspect_dbt._read_text(path).lower()
        for path in workflows.glob("*.y*ml")
        if path.is_file()
    ):
        orchestration.append("github-actions")

    return {
        "semantic_layer": {
            "detected": bool(semantic_files or metric_files or saved_query_files),
            "semantic_model_file_count": semantic_files,
            "metric_file_count": metric_files,
            "saved_query_file_count": saved_query_files,
        },
        "bi": {
            "looker_detected": bool(lookml_files),
            "lookml_file_count": len(lookml_files),
        },
        "orchestration": sorted(set(orchestration)),
    }


def _stored_profile_state(root: Path, current_fingerprint: str) -> dict[str, Any]:
    path = root / ".ae" / "project.yml"
    if not path.is_file():
        return {
            "present": False,
            "path": ".ae/project.yml",
            "stale": None,
            "stored_fingerprint": None,
            "current_fingerprint": current_fingerprint,
        }
    document = parse_yaml(inspect_dbt._read_text(path))
    project = document.get("project") if isinstance(document, dict) else None
    stored = project.get("profile_fingerprint") if isinstance(project, dict) else None
    return {
        "present": True,
        "path": ".ae/project.yml",
        "stale": None if not stored else stored != current_fingerprint,
        "stored_fingerprint": stored,
        "current_fingerprint": current_fingerprint,
    }


def _project_facts(
    root: Path,
    report: dict[str, Any],
    model_paths: list[str],
    yaml_paths: list[str],
    is_own_code: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    project = report.get("project") if isinstance(report.get("project"), dict) else {}
    adapter, adapter_source = _detect_adapter(root)

    packages: list[str] = []
    for candidate in ("packages.yml", "dependencies.yml"):
        path = root / candidate
        if not path.is_file():
            continue
        document = parse_yaml(inspect_dbt._read_text(path))
        entries = document.get("packages") if isinstance(document, dict) else None
        for entry in entries or []:
            if isinstance(entry, dict):
                name = entry.get("package") or entry.get("git") or entry.get("local")
                if name:
                    packages.append(str(name))

    fingerprint_inputs = [
        *model_paths,
        *yaml_paths,
        *[
            candidate
            for candidate in ("dbt_project.yml", "dbt_project.yaml", "packages.yml", "dependencies.yml")
            if (root / candidate).is_file()
        ],
    ]
    import project_context as _context

    layout = _context.DbtProjectLayout(root, project)
    engine, engine_evidence = _context.infer_engine(
        root,
        _context.git_root_for(root),
        require_dbt_version=layout.require_dbt_version,
        target_dir=root / layout.target_path,
    )
    facts = {
        "name": project.get("name"),
        "transformation": "dbt",
        "adapter": adapter,
        "adapter_source": adapter_source,
        "adapter_confidence": _adapter_confidence(adapter_source),
        # Which engine runs matters for defaults that differ between Core and
        # Fusion, and static inference can only report what is written down.
        "engine": engine,
        "engine_evidence": engine_evidence,
        "packages": sorted(set(packages)),
        "profile_fingerprint": _profile_fingerprint(root, fingerprint_inputs),
    }
    facts.update(_repository_context(root, yaml_paths, is_own_code))
    return facts


def infer_conventions(path: str | Path) -> dict[str, Any]:
    """Return this project's conventions, each with the evidence supporting it."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ConventionInferenceError(f"Project path is not a directory: {root}")

    report = inspect_dbt.inspect_dbt(root)
    if not report.get("is_dbt_project"):
        return {
            "ok": True,
            "root": str(root),
            "is_dbt_project": False,
            "project": {},
            "conventions": {},
            "open_questions": [],
            "evidence": {},
            "inference_note": "No dbt_project.yml found; no conventions were inferred.",
        }

    import project_context

    layout = project_context.DbtProjectLayout(root, report.get("project"))
    own = layout.is_own_code
    model_paths = [path for path in report["model_tree"]["files"] if own(path)]
    yaml_paths = [detail["path"] for detail in report["yaml_files"] if own(detail["path"])]
    vendored_count = report.get("excluded_vendored_file_count", 0) + (
        (len(report["model_tree"]["files"]) + len(report["yaml_files"]))
        - (len(model_paths) + len(yaml_paths))
    )

    tallies = _tallies()
    _observe_models(root, model_paths, tallies)
    docs_blocks = _docs_blocks(root, own)
    documentation = _observe_yaml(root, yaml_paths, model_paths, tallies, frozenset(docs_blocks["names"]))

    evidence: dict[str, Any] = {}
    conventions: dict[str, Any] = {}
    open_questions: list[dict[str, Any]] = []

    for key in sorted(OBSERVATION_META):
        meta = OBSERVATION_META[key]
        tally = tallies[key]
        observation = conclude(tally.counts, tally.examples, decode=meta.get("decode"))
        evidence[key] = observation
        section, _, leaf = key.partition(".")
        if meta.get("resource_pattern"):
            continue
        if observation["strength"] in {"strong", "weak"}:
            conventions.setdefault(section, {})[leaf] = observation["value"]
        elif observation["strength"] == "split":
            open_questions.append(
                {
                    "convention": key,
                    "question": meta["question"],
                    "candidates": observation["candidates"],
                    "reason": (
                        "Separate directories follow different patterns, so the file"
                        " counts cannot say which one governs new work."
                        if observation["partitioned"]
                        else "The repository uses more than one pattern, so it cannot answer this."
                    ),
                }
            )

    facts = _project_facts(root, report, model_paths, yaml_paths, own)
    facts.update(
        {
            "model_count": len(model_paths),
            "excluded_vendored_files": vendored_count,
            "documented_model_count": documentation["documented_model_count"],
            "yaml_model_entry_count": documentation["yaml_model_entry_count"],
            "declared_column_count": documentation["declared_column_count"],
            "documented_column_count": documentation["documented_column_count"],
            "source_count": documentation["source_count"],
            "docs_blocks": docs_blocks,
            "written_conventions": _written_conventions(root, own),
        }
    )

    return {
        "ok": True,
        "root": str(root),
        "is_dbt_project": True,
        "project": facts,
        "profile": _stored_profile_state(root, facts["profile_fingerprint"]),
        "resource_patterns": {
            "sources": documentation["source_contracts"],
            "note": (
                "Loaded-at fields and freshness thresholds are resource contracts, "
                "not global house conventions."
            ),
        },
        "conventions": {section: conventions[section] for section in sorted(conventions)},
        "open_questions": open_questions,
        "evidence": evidence,
        "thresholds": {
            "strong_ratio": STRONG_RATIO,
            "strong_instances": STRONG_INSTANCES,
            "weak_ratio": WEAK_RATIO,
        },
        "inference_note": "Static inference only; dbt was not executed and no warehouse was contacted."
        + (
            " Conventions are written down in "
            + ", ".join(entry["path"] for entry in facts["written_conventions"])
            + "; read them first. A written rule outranks any value inferred here."
            if facts["written_conventions"]
            else ""
        ),
    }


# --- Output ------------------------------------------------------------------


def _needs_quotes(text: str) -> bool:
    if not text or text.strip() != text:
        return True
    if text[0] in "{}[]&*!|>%@`#?,":
        return True
    if ":" in text or "#" in text:
        return True
    if text.lower() in {"true", "false", "null", "yes", "no", "on", "off", "~"}:
        return True
    return bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text))


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if _needs_quotes(text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _emit(value: Any, indent: int = 0) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                lines.extend(_emit(item, indent + 2))
            elif isinstance(item, dict):
                lines.append(f"{pad}{key}: {{}}")
            elif isinstance(item, list):
                lines.append(f"{pad}{key}: []")
            else:
                lines.append(f"{pad}{key}: {_scalar(item)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)) and item:
                nested = _emit(item, indent + 2)
                lines.append(f"{pad}- {nested[0].lstrip()}")
                lines.extend(nested[1:])
            else:
                lines.append(f"{pad}- {_scalar(item)}")
    return lines


def to_project_yaml(result: dict[str, Any]) -> str:
    """Render an inference result as the `.ae/project.yml` a team can edit."""
    document: dict[str, Any] = {
        "version": 1,
        "project": result.get("project") or {},
        "conventions": result.get("conventions") or {},
        "resource_patterns": result.get("resource_patterns") or {},
    }
    if result.get("open_questions"):
        document["open_questions"] = [
            {"convention": item["convention"], "question": item["question"], "candidates": item["candidates"]}
            for item in result["open_questions"]
        ]
    document["_evidence"] = {
        key: {
            "value": observation["value"],
            "strength": observation["strength"],
            "confidence": observation["confidence"],
            "supporting": observation["supporting"],
            "contradicting": observation["contradicting"],
            "examples": observation["examples"],
        }
        for key, observation in sorted((result.get("evidence") or {}).items())
        if observation["strength"] != "absent"
    }

    header = [
        "# Conventions inferred by the Analytics Engineering Toolkit.",
        "# Edit any value; edits win over inference on the next run.",
        "# `_evidence` records what the inference was based on.",
    ]
    return "\n".join([*header, *_emit(document)]) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = inspect_dbt.JsonArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="dbt project directory")
    parser.add_argument("--json", action="store_true", help="Emit the full evidence as JSON")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    parser.add_argument("--write", action="store_true", help="Write .ae/project.yml in the project")
    parser.add_argument("--force", action="store_true", help="Allow --write to replace an existing profile")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = infer_conventions(args.path)
    except (ConventionInferenceError, inspect_dbt.DbtInspectionError, OSError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1

    if args.write:
        destination = Path(result["root"]) / ".ae" / "project.yml"
        if destination.exists() and not args.force:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"{destination} already exists; pass --force to replace it",
                        "error_type": "FileExistsError",
                    }
                ),
                file=sys.stderr,
            )
            return 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(to_project_yaml(result), encoding="utf-8")
        print(json.dumps({"ok": True, "written": str(destination)}))
        return 0

    if args.json:
        print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    else:
        print(to_project_yaml(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
