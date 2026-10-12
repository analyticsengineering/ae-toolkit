"""Shared standard-library helpers for toolkit tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


TESTS_ROOT = Path(__file__).resolve().parent
PLUGIN_ROOT = TESTS_ROOT.parent
FIXTURES = TESTS_ROOT / "fixtures"


def load_module(relative_path: str, module_name: str | None = None) -> ModuleType:
    """Import a plugin Python file directly from its source path."""
    path = PLUGIN_ROOT / relative_path
    name = module_name or f"toolkit_test_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_python(
    relative_path: str, *args: str, stdin: str | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Invoke a plugin Python entry point with the active interpreter."""
    return subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / relative_path), *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=PLUGIN_ROOT,
        env={**os.environ, **env} if env else None,
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Parse the flat frontmatter used by plugin component files."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} has no opening frontmatter delimiter")
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return result
        if ":" not in line:
            raise ValueError(f"Unsupported frontmatter line in {path}: {line!r}")
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    raise ValueError(f"{path} has no closing frontmatter delimiter")
