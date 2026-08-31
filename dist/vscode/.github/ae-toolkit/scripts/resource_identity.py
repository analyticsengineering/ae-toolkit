#!/usr/bin/env python3
"""Give dbt resources a typed identity instead of a bare name string.

A file stem is not an identity. `orders` can be a model in this project, a model
in an installed package, a v2 of a versioned model, a seed, and the subject of a
generic test, all at once. Passing the string around meant every consumer
re-guessed which one was meant, and a selector built from the wrong guess either
validates nothing or validates the whole warehouse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


MODEL = "model"
SEED = "seed"
SNAPSHOT = "snapshot"
ANALYSIS = "analysis"
MACRO = "macro"
SINGULAR_TEST = "singular_test"
GENERIC_TEST = "generic_test"
UNIT_TEST = "unit_test"
SOURCE = "source"
EXPOSURE = "exposure"
SEMANTIC_MODEL = "semantic_model"
METRIC = "metric"
SAVED_QUERY = "saved_query"

SQL = "sql"
PYTHON = "python"

MODEL_SUFFIXES = {".sql": SQL, ".py": PYTHON}

# A generic test is a macro named `test_*` or declared with `{% test %}`. Only
# the latter is unambiguous, so both are recognized but reported distinctly.
GENERIC_TEST_BLOCK = re.compile(r"\{%-?\s*test\s+([A-Za-z_][\w]*)\s*\(", re.I)
MACRO_BLOCK = re.compile(r"\{%-?\s*macro\s+([A-Za-z_][\w]*)\s*\(", re.I)

# `ref` in every shape dbt accepts: one argument, package-qualified two
# arguments, and either form with `version=`/`v=`.
REF_CALL = re.compile(
    r"""\bref\s*\(\s*
        (?P<first>['"][^'"]+['"])
        (?:\s*,\s*(?P<second>['"][^'"]+['"]))?
        (?P<rest>(?:\s*,\s*[^)]*?)?)
        \s*\)""",
    re.I | re.X,
)
SOURCE_CALL = re.compile(
    r"""\bsource\s*\(\s*
        (?P<source>['"][^'"]+['"])\s*,\s*
        (?P<table>['"][^'"]+['"])\s*\)""",
    re.I | re.X,
)
VERSION_KWARG = re.compile(r"\b(?:version|v)\s*=\s*['\"]?([\w.]+)['\"]?", re.I)


def _unquote(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().strip("'\"")


@dataclass(frozen=True)
class ResourceRef:
    """A reference one resource makes to another."""

    resource_type: str
    name: str
    package: str | None = None
    source_name: str | None = None
    version: str | None = None

    @property
    def key(self) -> tuple[str, str, str | None, str | None]:
        return (self.resource_type, self.name, self.package, self.source_name)

    def selector(self) -> str:
        if self.resource_type == SOURCE:
            return f"source:{self.source_name}.{self.name}"
        if self.version:
            return f"{self.name}.v{self.version}"
        return self.name

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"resource_type": self.resource_type, "name": self.name}
        if self.package:
            payload["package"] = self.package
        if self.source_name:
            payload["source"] = self.source_name
        if self.version:
            payload["version"] = self.version
        return payload


@dataclass
class Resource:
    """One addressable dbt resource, with everything a selector needs."""

    resource_type: str
    name: str
    path: str | None = None
    package: str | None = None
    language: str | None = None
    version: str | None = None
    source_name: str | None = None
    unique_id: str | None = None
    refs: tuple[ResourceRef, ...] = ()
    definition: str | None = None
    attached_to: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str, str | None]:
        return (self.resource_type, self.qualified_name, self.package)

    @property
    def qualified_name(self) -> str:
        if self.resource_type == SOURCE and self.source_name:
            return f"{self.source_name}.{self.name}"
        return self.name

    def selector(self) -> str:
        if self.resource_type == SOURCE:
            return f"source:{self.source_name}.{self.name}"
        if self.resource_type == UNIT_TEST:
            return f"unit_test:{self.name}"
        if self.version:
            return f"{self.name}.v{self.version}"
        return self.name

    def manifest_unique_id(self, project_name: str | None) -> str | None:
        if self.unique_id:
            return self.unique_id
        package = self.package or project_name
        if not package:
            return None
        if self.resource_type == SOURCE:
            return f"source.{package}.{self.source_name}.{self.name}"
        prefix = {
            MODEL: "model",
            SEED: "seed",
            SNAPSHOT: "snapshot",
            ANALYSIS: "analysis",
            SINGULAR_TEST: "test",
            GENERIC_TEST: "macro",
            UNIT_TEST: "unit_test",
            MACRO: "macro",
            EXPOSURE: "exposure",
            SEMANTIC_MODEL: "semantic_model",
            METRIC: "metric",
            SAVED_QUERY: "saved_query",
        }.get(self.resource_type)
        if prefix is None:
            return None
        name = f"{self.name}.v{self.version}" if self.version else self.name
        return f"{prefix}.{package}.{name}"

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "resource_type": self.resource_type,
            "name": self.name,
        }
        for key, value in (
            ("path", self.path),
            ("package", self.package),
            ("language", self.language),
            ("version", self.version),
            ("source", self.source_name),
            ("unique_id", self.unique_id),
            ("definition", self.definition),
        ):
            if value:
                payload[key] = value
        if self.attached_to:
            payload["attached_to"] = list(self.attached_to)
        if self.refs:
            payload["refs"] = [ref.as_dict() for ref in self.refs]
        return payload


def parse_refs(text: str) -> tuple[ResourceRef, ...]:
    """Extract every `ref` and `source` call, keeping package and version.

    A bare-name regex treated `ref('finance', 'orders')` as a model called
    `finance`, which selects the wrong node or nothing at all.
    """
    found: list[ResourceRef] = []
    seen: set[tuple[Any, ...]] = set()
    for match in REF_CALL.finditer(text):
        first = _unquote(match.group("first"))
        second = _unquote(match.group("second"))
        rest = match.group("rest") or ""
        package, name = (first, second) if second else (None, first)
        if not name:
            continue
        version_match = VERSION_KWARG.search(rest) or VERSION_KWARG.search(
            match.group("second") or ""
        )
        version = version_match.group(1) if version_match else None
        ref = ResourceRef(MODEL, name, package=package, version=version)
        if ref.key + (version,) not in seen:
            seen.add(ref.key + (version,))
            found.append(ref)
    for match in SOURCE_CALL.finditer(text):
        source_name = _unquote(match.group("source"))
        table = _unquote(match.group("table"))
        if not source_name or not table:
            continue
        ref = ResourceRef(SOURCE, table, source_name=source_name)
        if ref.key + (None,) not in seen:
            seen.add(ref.key + (None,))
            found.append(ref)
    return tuple(found)


def parse_versioned_model_name(stem: str) -> tuple[str, str | None]:
    """Split `orders_v2` into its base name and version, as dbt files are named."""
    match = re.fullmatch(r"(?P<base>.+?)_v(?P<version>\d+(?:_\d+)?)", stem)
    if not match:
        return stem, None
    return match.group("base"), match.group("version").replace("_", ".")


def macro_definitions(text: str) -> tuple[list[str], list[str]]:
    """Return (generic test names, plain macro names) defined in a macro file.

    dbt's `{% test %}` block is the only definitive marker. A `test_`-prefixed
    macro is the legacy spelling and is reported as a generic test too, but the
    caller can tell them apart because only block-defined names appear first.
    """
    generic = [match.group(1) for match in GENERIC_TEST_BLOCK.finditer(text)]
    macros: list[str] = []
    for match in MACRO_BLOCK.finditer(text):
        name = match.group(1)
        if name.startswith("test_"):
            generic.append(name[len("test_"):])
        else:
            macros.append(name)
    return sorted(set(generic)), sorted(set(macros))


def classify_model_file(relative: str) -> tuple[str, str | None, str | None]:
    """Return (name, version, language) for a model file path."""
    path = Path(relative)
    language = MODEL_SUFFIXES.get(path.suffix.lower())
    base, version = parse_versioned_model_name(path.stem)
    return base, version, language


def resource_for_path(
    context: Any,
    relative: str,
    *,
    text: str | None = None,
) -> Resource | None:
    """Build a typed resource from a project-relative file path.

    Returns None for files that are not addressable dbt resources, which is the
    honest answer for a README under `models/`.
    """
    layout = getattr(context, "layout", None)
    if layout is None:
        return None
    if not layout.is_own_code(relative):
        return None
    kind = layout.kind_of(relative)
    suffix = Path(relative).suffix.lower()
    package = layout.name

    if kind == "model" and suffix in MODEL_SUFFIXES:
        name, version, language = classify_model_file(relative)
        refs = parse_refs(text) if text else ()
        return Resource(
            MODEL,
            name,
            path=relative,
            package=package,
            language=language,
            version=version,
            refs=refs,
        )
    if kind == "test" and suffix == ".sql":
        return Resource(
            SINGULAR_TEST,
            Path(relative).stem,
            path=relative,
            package=package,
            language=SQL,
            refs=parse_refs(text) if text else (),
        )
    if kind == "test" and suffix == ".py":
        return Resource(
            SINGULAR_TEST,
            Path(relative).stem,
            path=relative,
            package=package,
            language=PYTHON,
            refs=parse_refs(text) if text else (),
        )
    if kind == "snapshot" and suffix == ".sql":
        return Resource(
            SNAPSHOT,
            Path(relative).stem,
            path=relative,
            package=package,
            language=SQL,
            refs=parse_refs(text) if text else (),
        )
    if kind == "seed" and suffix == ".csv":
        return Resource(SEED, Path(relative).stem, path=relative, package=package)
    if kind == "analysis" and suffix in MODEL_SUFFIXES:
        return Resource(
            ANALYSIS,
            Path(relative).stem,
            path=relative,
            package=package,
            language=MODEL_SUFFIXES[suffix],
            refs=parse_refs(text) if text else (),
        )
    if kind == "macro" and suffix == ".sql":
        generic, _macros = macro_definitions(text or "")
        if generic:
            return Resource(
                GENERIC_TEST,
                generic[0],
                path=relative,
                package=package,
                language=SQL,
                definition="macro",
            )
        return Resource(MACRO, Path(relative).stem, path=relative, package=package, language=SQL)
    return None


@dataclass
class ResourceIndex:
    """Every typed resource this project defines, addressable several ways."""

    resources: list[Resource] = field(default_factory=list)
    generic_test_usages: dict[str, list[str]] = field(default_factory=dict)
    unsupported_yaml: dict[str, list[str]] = field(default_factory=dict)

    def add(self, resource: Resource) -> None:
        self.resources.append(resource)

    def by_type(self, resource_type: str) -> list[Resource]:
        return [item for item in self.resources if item.resource_type == resource_type]

    def by_path(self, relative: str) -> Resource | None:
        for item in self.resources:
            if item.path == relative:
                return item
        return None

    def models_named(self, name: str) -> list[Resource]:
        return [item for item in self.by_type(MODEL) if item.name == name]

    def consumers_of(self, refs: Iterable[ResourceRef]) -> list[Resource]:
        """Direct consumers of the given resources, by declared ref/source calls."""
        wanted = {ref.key for ref in refs}
        if not wanted:
            return []
        return [
            resource
            for resource in self.resources
            if any(ref.key in wanted for ref in resource.refs)
        ]

    def downstream_of(self, refs: Sequence[ResourceRef]) -> list[Resource]:
        """Transitive consumers, so a contract change reaches the whole subtree."""
        frontier = list(refs)
        collected: dict[tuple[str, str, str | None], Resource] = {}
        while frontier:
            direct = self.consumers_of(frontier)
            frontier = []
            for resource in direct:
                if resource.key in collected:
                    continue
                collected[resource.key] = resource
                frontier.append(
                    ResourceRef(
                        resource.resource_type,
                        resource.name,
                        package=None,
                        version=resource.version,
                    )
                )
        return sorted(collected.values(), key=lambda item: (item.resource_type, item.name))


def build_index(context: Any) -> ResourceIndex:
    """Inventory the project's own resources from configured directories."""
    import project_context as _context  # deferred; keeps import order simple

    index = ResourceIndex()
    if not getattr(context, "is_dbt_project", False):
        return index
    root = context.dbt_root
    layout = context.layout

    for path in context.iter_files():
        relative = path.relative_to(root).as_posix()
        if not layout.is_own_code(relative):
            continue
        suffix = path.suffix.lower()
        if suffix in {".sql", ".py"}:
            text = _safe_read(path)
            resource = resource_for_path(context, relative, text=text)
            if resource is not None:
                index.add(resource)
            if layout.kind_of(relative) == "macro" and text:
                generic, macros = macro_definitions(text)
                for extra in generic[1:]:
                    index.add(
                        Resource(
                            GENERIC_TEST,
                            extra,
                            path=relative,
                            package=layout.name,
                            language="sql",
                            definition="macro",
                        )
                    )
                for macro in macros:
                    if index.by_path(relative) and index.by_path(relative).name == macro:
                        continue
                    index.add(
                        Resource(MACRO, macro, path=relative, package=layout.name, language="sql")
                    )
        elif suffix == ".csv":
            resource = resource_for_path(context, relative)
            if resource is not None:
                index.add(resource)
        elif suffix in {".yml", ".yaml"}:
            text = _safe_read(path)
            if text is None:
                continue
            document, unsupported = _context.parse_yaml_checked(text)
            if unsupported:
                index.unsupported_yaml[relative] = unsupported
            _index_yaml(index, relative, document, layout.name)
    return index


def _safe_read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None


def _index_yaml(index: ResourceIndex, relative: str, document: Any, package: str | None) -> None:
    if not isinstance(document, dict):
        return
    for source in document.get("sources") or []:
        if not isinstance(source, dict) or not source.get("name"):
            continue
        source_name = str(source["name"])
        for table in source.get("tables") or []:
            if isinstance(table, dict) and table.get("name"):
                index.add(
                    Resource(
                        SOURCE,
                        str(table["name"]),
                        path=relative,
                        package=package,
                        source_name=source_name,
                    )
                )
    for unit_test in document.get("unit_tests") or []:
        if isinstance(unit_test, dict) and unit_test.get("name"):
            index.add(
                Resource(
                    UNIT_TEST,
                    str(unit_test["name"]),
                    path=relative,
                    package=package,
                    attached_to=(str(unit_test["model"]),) if unit_test.get("model") else (),
                )
            )
    for key, resource_type in (
        ("exposures", EXPOSURE),
        ("semantic_models", SEMANTIC_MODEL),
        ("metrics", METRIC),
        ("saved_queries", SAVED_QUERY),
    ):
        for entry in document.get(key) or []:
            if isinstance(entry, dict) and entry.get("name"):
                index.add(
                    Resource(resource_type, str(entry["name"]), path=relative, package=package)
                )
    for model in document.get("models") or []:
        if not isinstance(model, dict) or not model.get("name"):
            continue
        for test_name in _generic_tests_in(model):
            index.generic_test_usages.setdefault(test_name, []).append(str(model["name"]))


def _generic_tests_in(node: Any) -> list[str]:
    """Names of generic tests declared anywhere under a YAML node."""
    names: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"tests", "data_tests"} and isinstance(value, list):
                for entry in value:
                    if isinstance(entry, str):
                        names.append(entry)
                    elif isinstance(entry, dict):
                        names.extend(str(item) for item in entry)
            else:
                names.extend(_generic_tests_in(value))
    elif isinstance(node, list):
        for item in node:
            names.extend(_generic_tests_in(item))
    return names
