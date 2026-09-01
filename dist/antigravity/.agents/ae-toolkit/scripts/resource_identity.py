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

# Resource types dbt selects by bare name. Everything else carries a prefix
# (`source:`, `unit_test:`) and so cannot collide with these.
BARE_NAME_TYPES = frozenset({MODEL, SEED, SNAPSHOT, ANALYSIS, SINGULAR_TEST})

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

# dbt creates a view named after a versioned model's base name that points at
# whichever version is current. It is a published physical interface, not
# another model, and a rename or version cutover changes what it resolves to.
LATEST_VERSION_POINTER = "latest_version_pointer"


def _unquote(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().strip("'\"")


def version_text(value: Any) -> str | None:
    """Render a declared version the way dbt spells it in a selector.

    dbt accepts integers, floats, and strings, so `2`, `2.1`, and `2026_q3` are
    all legitimate. Rendering a float through `str` would turn a `v: 2` that
    YAML read as a float into `2.0`, which selects nothing.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class PublishedInterface:
    """A relation dbt maintains in addition to the model's own relation."""

    kind: str
    name: str
    enabled: bool
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "enabled": self.enabled,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class VersionDeclaration:
    """One entry under a model's `versions:` list."""

    version: str
    defined_in: str | None = None


@dataclass
class ModelDeclaration:
    """What a YAML `models:` entry says about a model's identity."""

    name: str
    path: str
    versions: tuple[VersionDeclaration, ...] = ()
    latest_version: str | None = None
    pointer_enabled: bool | None = None
    pointer_alias: str | None = None

    def resolved_latest(self) -> str | None:
        if self.latest_version is not None:
            return self.latest_version
        if not self.versions:
            return None
        # dbt treats the highest declared version as latest when none is named.
        return self.versions[-1].version

    def file_stems(self) -> dict[str, VersionDeclaration]:
        """Map each file stem dbt would look for to the version it defines."""
        latest = self.resolved_latest()
        stems: dict[str, VersionDeclaration] = {}
        for entry in self.versions:
            if entry.defined_in:
                stems[entry.defined_in] = entry
                continue
            stems[f"{self.name}_v{entry.version}"] = entry
            if entry.version == latest:
                # dbt allows the latest version to keep the unsuffixed filename.
                stems.setdefault(self.name, entry)
        return stems


@dataclass(frozen=True)
class ResourceRef:
    """A reference one resource makes to another."""

    resource_type: str
    name: str
    package: str | None = None
    source_name: str | None = None
    version: str | None = None

    @property
    def key(self) -> tuple[str, str, str | None, str | None, str | None]:
        """Identity including version, because `v1` and `v2` are two relations.

        Dropping the version here made `ref('orders', v=1)` and `ref('orders',
        v=2)` the same edge, so changing one version resolved consumers of both
        and a versioned deletion found no state node at all.
        """
        return (self.resource_type, self.name, self.package, self.source_name, self.version)

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
    defined_in: str | None = None
    is_latest_version: bool = False
    interfaces: tuple[PublishedInterface, ...] = ()
    identity_evidence: str = "filename"

    @property
    def key(self) -> tuple[str, str, str | None, str | None]:
        return (self.resource_type, self.qualified_name, self.package, self.version)

    @property
    def qualified_name(self) -> str:
        if self.resource_type == SOURCE and self.source_name:
            return f"{self.source_name}.{self.name}"
        return self.name

    def ref(self) -> ResourceRef:
        """This resource expressed as the reference another resource would make."""
        return ResourceRef(
            self.resource_type,
            self.name,
            package=self.package,
            source_name=self.source_name,
            version=self.version,
        )

    def matches_ref(self, ref: ResourceRef) -> bool:
        """Whether an incoming reference resolves to this exact resource.

        An unversioned `ref('orders')` resolves to whichever version is current,
        so it matches an unversioned model or the latest version -- but never an
        older version that merely shares the name.
        """
        if ref.resource_type != self.resource_type or ref.name != self.name:
            return False
        if ref.source_name != self.source_name:
            return False
        if ref.package is not None and self.package is not None and ref.package != self.package:
            return False
        if ref.version is not None:
            return ref.version == self.version
        return self.version is None or self.is_latest_version

    def selector(self) -> str:
        if self.resource_type == SOURCE:
            return f"source:{self.source_name}.{self.name}"
        if self.resource_type == UNIT_TEST:
            return f"unit_test:{self.name}"
        if self.version:
            return f"{self.name}.v{self.version}"
        return self.name

    def path_selector(self) -> str | None:
        """An unambiguous selector for when the name alone addresses two things."""
        return f"path:{self.path}" if self.path else None

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
            ("defined_in", self.defined_in),
        ):
            if value:
                payload[key] = value
        if self.version:
            payload["is_latest_version"] = self.is_latest_version
            payload["identity_evidence"] = self.identity_evidence
        if self.interfaces:
            payload["interfaces"] = [item.as_dict() for item in self.interfaces]
        if self.attached_to:
            payload["attached_to"] = list(self.attached_to)
        if self.refs:
            payload["refs"] = [ref.as_dict() for ref in self.refs]
        return payload


def parse_refs(text: str, *, language: str | None = None) -> tuple[ResourceRef, ...]:
    """Extract every `ref` and `source` call, keeping package and version.

    A bare-name regex treated `ref('finance', 'orders')` as a model called
    `finance`, which selects the wrong node or nothing at all.
    """
    refs, _unknown = parse_refs_checked(text, language=language)
    return refs


def _parse_refs_regex(text: str) -> tuple[ResourceRef, ...]:
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


def strip_sql_comments(text: str) -> str:
    """Blank out SQL and Jinja comments without disturbing string literals.

    A `ref` inside `-- ref('legacy_orders')` is a note to a human. Treating it
    as an edge invented a dependency, which then widened a bounded selector to
    include a model the code never reads.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        pair = text[index : index + 2]
        if char in "'\"":
            quote = char
            out.append(char)
            index += 1
            while index < length:
                out.append(text[index])
                if text[index] == "\\" and index + 1 < length:
                    out.append(text[index + 1])
                    index += 2
                    continue
                if text[index] == quote:
                    index += 1
                    break
                index += 1
            continue
        if pair == "--":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if pair == "/*":
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        if pair == "{#":
            end = text.find("#}", index + 2)
            index = length if end == -1 else end + 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _python_refs(text: str) -> tuple[tuple[ResourceRef, ...], list[str]]:
    """Extract `dbt.ref` and `dbt.source` calls using the Python grammar itself.

    Regex matching found calls in docstrings, comments, and example strings. The
    parser only sees calls the interpreter would actually make.
    """
    import ast

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return (), [f"Python could not be parsed ({exc.msg}); dependencies are unknown."]

    found: list[ResourceRef] = []
    seen: set[tuple[Any, ...]] = set()
    unknown: list[str] = []

    def literal(node: Any) -> str | None:
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in {"ref", "source"}:
            continue
        base = func.value
        if not isinstance(base, ast.Name) or base.id != "dbt":
            continue
        positional = [literal(arg) for arg in node.args]
        if any(value is None for value in positional):
            unknown.append(
                f"dbt.{func.attr}() on line {node.lineno} is built from a computed value."
            )
            continue
        version = None
        for keyword in node.keywords:
            if keyword.arg in {"v", "version"}:
                literal_value = keyword.value
                if isinstance(literal_value, ast.Constant):
                    version = version_text(literal_value.value)
        if func.attr == "source":
            if len(positional) != 2:
                continue
            ref = ResourceRef(SOURCE, positional[1], source_name=positional[0])
        elif len(positional) == 2:
            ref = ResourceRef(MODEL, positional[1], package=positional[0], version=version)
        elif len(positional) == 1:
            ref = ResourceRef(MODEL, positional[0], version=version)
        else:
            continue
        if ref.key in seen:
            continue
        seen.add(ref.key)
        found.append(ref)
    return tuple(found), unknown


def parse_refs_checked(
    text: str,
    *,
    language: str | None = None,
) -> tuple[tuple[ResourceRef, ...], list[str]]:
    """Dependencies plus anything the reader could not resolve confidently."""
    if language == PYTHON:
        return _python_refs(text)
    return _parse_refs_regex(strip_sql_comments(text)), []


def parse_versioned_model_name(stem: str) -> tuple[str, str | None]:
    """Split `orders_v2` into its base name and version, as dbt files are named.

    Deliberately numeric only. dbt allows a version to be any string, but a
    filename cannot distinguish `orders_v2026_q3` from `customer_verified`, so
    a non-numeric version has to come from YAML or the manifest. This is the
    last-resort reading, used only when neither authority describes the file.
    """
    match = re.fullmatch(r"(?P<base>.+?)_v(?P<version>\d+(?:_\d+)?)", stem)
    if not match:
        return stem, None
    return match.group("base"), match.group("version").replace("_", ".")


def model_declarations(document: Any, relative: str) -> list[ModelDeclaration]:
    """Read model identity out of a YAML document, versions included."""
    models = document.get("models") if isinstance(document, dict) else None
    if not isinstance(models, list):
        return []
    declarations: list[ModelDeclaration] = []
    for entry in models:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        versions: list[VersionDeclaration] = []
        for item in entry.get("versions") or []:
            if not isinstance(item, dict):
                continue
            version = version_text(item.get("v"))
            if version is None:
                continue
            defined_in = item.get("defined_in")
            versions.append(
                VersionDeclaration(version, str(defined_in) if defined_in else None)
            )
        pointer_enabled, pointer_alias = _pointer_config(entry)
        declarations.append(
            ModelDeclaration(
                name=str(entry["name"]),
                path=relative,
                versions=tuple(versions),
                latest_version=version_text(entry.get("latest_version")),
                pointer_enabled=pointer_enabled,
                pointer_alias=pointer_alias,
            )
        )
    return declarations


def _pointer_config(entry: dict[str, Any]) -> tuple[bool | None, str | None]:
    config = entry.get("config")
    pointer = config.get(LATEST_VERSION_POINTER) if isinstance(config, dict) else None
    if isinstance(pointer, bool):
        return pointer, None
    if not isinstance(pointer, dict):
        return None, None
    enabled = pointer.get("enabled")
    alias = pointer.get("alias")
    return (
        enabled if isinstance(enabled, bool) else None,
        str(alias) if alias else None,
    )


class ModelRegistry:
    """Resolve a model file to the identity YAML and the manifest agree on.

    Order matters. The manifest is what dbt itself built, YAML is what the team
    declared, and the filename is a guess. Reading them in that order is what
    lets `orders_current_rebuild.sql` be version `2026_q3` of `orders` instead
    of a model nobody references.
    """

    def __init__(
        self,
        *,
        declarations: Sequence[ModelDeclaration] = (),
        manifest: Any = None,
        project: str | None = None,
        pointer_default: bool = False,
    ) -> None:
        self.project = project
        self.pointer_default = pointer_default
        self.declarations = list(declarations)
        self._by_stem: dict[str, tuple[ModelDeclaration, VersionDeclaration]] = {}
        for declaration in self.declarations:
            for stem, entry in declaration.file_stems().items():
                self._by_stem.setdefault(stem, (declaration, entry))
        self._by_path = _manifest_models_by_path(manifest)

    def identify(self, relative: str) -> dict[str, Any]:
        """Return the name, version, and provenance for one model file."""
        stem = Path(relative).stem

        node = self._by_path.get(relative)
        if node is not None:
            name = str(node.get("name") or stem)
            version = version_text(node.get("version"))
            latest = version_text(node.get("latest_version"))
            declared = self._by_stem.get(stem)
            return {
                "name": name,
                "version": version,
                "defined_in": declared[1].defined_in if declared else None,
                "is_latest_version": bool(version and latest == version),
                "unique_id": str(node.get("unique_id")) if node.get("unique_id") else None,
                "evidence": "manifest",
                "interfaces": self._interfaces(name, version, latest),
            }

        declared = self._by_stem.get(stem)
        if declared is not None:
            declaration, entry = declared
            latest = declaration.resolved_latest()
            return {
                "name": declaration.name,
                "version": entry.version,
                "defined_in": entry.defined_in,
                "is_latest_version": entry.version == latest,
                "unique_id": None,
                "evidence": "yaml",
                "interfaces": self._interfaces(
                    declaration.name,
                    entry.version,
                    latest,
                    declaration=declaration,
                ),
            }

        name, version = parse_versioned_model_name(stem)
        return {
            "name": name,
            "version": version,
            "defined_in": None,
            # Nothing contradicts it, so a lone versioned file is its own latest.
            "is_latest_version": bool(version),
            "unique_id": None,
            "evidence": "filename",
            "interfaces": (),
        }

    def _interfaces(
        self,
        name: str,
        version: str | None,
        latest: str | None,
        *,
        declaration: ModelDeclaration | None = None,
    ) -> tuple[PublishedInterface, ...]:
        if not version or latest != version:
            return ()
        source = declaration or next(
            (item for item in self.declarations if item.name == name), None
        )
        enabled = source.pointer_enabled if source else None
        evidence = "model config"
        if enabled is None:
            enabled = self.pointer_default
            evidence = "project flag" if self.pointer_default else "project default"
        alias = (source.pointer_alias if source else None) or name
        return (
            PublishedInterface(LATEST_VERSION_POINTER, alias, bool(enabled), evidence),
        )


def _manifest_models_by_path(manifest: Any) -> dict[str, dict[str, Any]]:
    """Index manifest model nodes by the project-relative file that defines them."""
    if not isinstance(manifest, dict):
        return {}
    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        return {}
    latest_by_name: dict[str, str] = {}
    for node in nodes.values():
        if not isinstance(node, dict) or node.get("resource_type") != MODEL:
            continue
        latest = version_text(node.get("latest_version"))
        if latest is not None and node.get("name"):
            latest_by_name[str(node["name"])] = latest

    indexed: dict[str, dict[str, Any]] = {}
    for unique_id, node in nodes.items():
        if not isinstance(node, dict) or node.get("resource_type") != MODEL:
            continue
        location = node.get("original_file_path") or node.get("path")
        if not location:
            continue
        name = str(node.get("name") or "")
        indexed[Path(str(location)).as_posix()] = {
            **node,
            "unique_id": unique_id,
            "latest_version": version_text(node.get("latest_version"))
            or latest_by_name.get(name),
        }
    return indexed


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
    registry: ModelRegistry | None = None,
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
        language = MODEL_SUFFIXES[suffix]
        identity = (registry or ModelRegistry()).identify(relative)
        return Resource(
            MODEL,
            identity["name"],
            path=relative,
            package=package,
            language=language,
            version=identity["version"],
            unique_id=identity["unique_id"],
            refs=parse_refs(text, language=language) if text else (),
            defined_in=identity["defined_in"],
            is_latest_version=identity["is_latest_version"],
            interfaces=tuple(identity["interfaces"]),
            identity_evidence=identity["evidence"],
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
            refs=parse_refs(text, language=PYTHON) if text else (),
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
            refs=parse_refs(text, language=MODEL_SUFFIXES[suffix]) if text else (),
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
    generic_test_usages: dict[str, list[ResourceRef]] = field(default_factory=dict)
    unsupported_yaml: dict[str, list[str]] = field(default_factory=dict)
    unknown_dependencies: dict[str, list[str]] = field(default_factory=dict)
    registry: ModelRegistry | None = None

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

    def named(self, name: str) -> list[Resource]:
        """Every resource a bare selector of this name would reach.

        Sources and unit tests are excluded because their selectors carry a
        prefix, so a `raw.orders` source never contends with an `orders` model.
        """
        return [
            item
            for item in self.resources
            if item.name == name and item.resource_type in BARE_NAME_TYPES
        ]

    def is_ambiguous(self, resource: Resource) -> bool:
        """Whether the bare name would address more than one kind of thing.

        A project with a `customers` model and a `customers` seed cannot be
        validated by name: `--select customers` reaches both, and building the
        seed was never part of the change.
        """
        types = {item.resource_type for item in self.named(resource.name)}
        return len(types) > 1

    def consumers_of(self, refs: Iterable[ResourceRef]) -> list[Resource]:
        """Direct consumers of the given resources, by declared ref/source calls."""
        wanted = list(refs)
        if not wanted:
            return []
        targets = [
            item for item in self.resources if any(item.matches_ref(ref) for ref in wanted)
        ]
        if not targets:
            targets = []
        found: list[Resource] = []
        for resource in self.resources:
            for outgoing in resource.refs:
                if any(target.matches_ref(outgoing) for target in targets) or any(
                    outgoing.key == ref.key for ref in wanted
                ):
                    found.append(resource)
                    break
        return found

    def downstream_of(self, refs: Sequence[ResourceRef]) -> list[Resource]:
        """Transitive consumers, so a contract change reaches the whole subtree."""
        frontier = list(refs)
        collected: dict[tuple[str, str, str | None, str | None], Resource] = {}
        while frontier:
            direct = self.consumers_of(frontier)
            frontier = []
            for resource in direct:
                if resource.key in collected:
                    continue
                collected[resource.key] = resource
                frontier.append(resource.ref())
        return sorted(
            collected.values(),
            key=lambda item: (item.resource_type, item.name, item.version or ""),
        )


def build_index(context: Any) -> ResourceIndex:
    """Inventory the project's own resources from configured directories."""
    import artifact_inventory as _artifacts  # deferred; keeps import order simple
    import project_context as _context

    index = ResourceIndex()
    if not getattr(context, "is_dbt_project", False):
        return index
    root = context.dbt_root
    layout = context.layout

    declarations: list[ModelDeclaration] = []
    yaml_documents: list[tuple[str, Any]] = []
    for path in context.iter_files():
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() not in {".yml", ".yaml"} or not layout.is_own_code(relative):
            continue
        text = _safe_read(path)
        if text is None:
            continue
        document, unsupported = _context.parse_yaml_checked(text)
        if unsupported:
            index.unsupported_yaml[relative] = unsupported
        yaml_documents.append((relative, document))
        declarations.extend(model_declarations(document, relative))

    manifest = None
    try:
        manifest = _artifacts.inventory_artifacts(context).manifest_document()
    except (OSError, ValueError):
        manifest = None
    index.registry = ModelRegistry(
        declarations=declarations,
        manifest=manifest,
        project=layout.name,
        pointer_default=bool(getattr(context, "latest_version_pointer_default", False)),
    )

    for path in context.iter_files():
        relative = path.relative_to(root).as_posix()
        if not layout.is_own_code(relative):
            continue
        suffix = path.suffix.lower()
        if suffix in {".sql", ".py"}:
            text = _safe_read(path)
            resource = resource_for_path(context, relative, text=text, registry=index.registry)
            if resource is not None:
                index.add(resource)
            if text is not None:
                _unknown, notes = parse_refs_checked(
                    text, language=PYTHON if suffix == ".py" else SQL
                )
                if notes:
                    index.unknown_dependencies[relative] = notes
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

    for relative, document in yaml_documents:
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
                for test_name in _generic_tests_in(table):
                    index.generic_test_usages.setdefault(test_name, []).append(
                        ResourceRef(SOURCE, str(table["name"]), source_name=source_name)
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
            index.generic_test_usages.setdefault(test_name, []).append(
                ResourceRef(MODEL, str(model["name"]))
            )


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
