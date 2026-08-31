"""Tests that this repository is a self-contained, publishable plugin package.

The plugin was extracted from a larger project. These tests fail if a path
dependency on that project survives or generated runtime debris becomes tracked
content.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

from test_support import PLUGIN_ROOT, read_json


TEXT_SUFFIXES = {".md", ".mdc", ".json", ".yml", ".yaml", ".py", ".sql", ".txt", ".jsonl"}
SKIPPED_DIRS = {".git", "__pycache__"}

# An absolute home path in shipped content means the extraction left a local
# reference behind.
ABSOLUTE_LOCAL_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/")
PARENT_PROJECT_PATH = re.compile(r"analytics-engineering-toolkit/(?!\.cursor-plugin)")


def _tracked_files() -> list[str] | None:
    if shutil.which("git") is None or not (PLUGIN_ROOT / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def _shipped_files() -> list[str] | None:
    """Tracked plus non-ignored new files that would enter the package."""
    if shutil.which("git") is None or not (PLUGIN_ROOT / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def _repository_text_files() -> list[Path]:
    """Shipped text files, excluding this module, whose patterns would self-match."""
    this_file = Path(__file__).resolve()
    files: list[Path] = []
    tracked = _shipped_files()
    candidates = (
        [PLUGIN_ROOT / relative for relative in tracked]
        if tracked is not None
        else list(PLUGIN_ROOT.rglob("*"))
    )
    for path in sorted(candidates):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if SKIPPED_DIRS.intersection(path.parts):
            continue
        if path.resolve() == this_file:
            continue
        files.append(path)
    return files


class PackageIndependenceTests(unittest.TestCase):
    def test_no_shipped_file_references_an_absolute_local_path(self) -> None:
        offenders = []
        for path in _repository_text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if ABSOLUTE_LOCAL_PATH.search(text):
                offenders.append(path.relative_to(PLUGIN_ROOT).as_posix())
        self.assertEqual(offenders, [], f"Absolute local paths found in {offenders}")

    def test_no_shipped_file_expects_the_plugin_to_live_in_a_subdirectory(self) -> None:
        offenders = []
        for path in _repository_text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for match in PARENT_PROJECT_PATH.finditer(text):
                # The install directory legitimately carries the plugin name.
                window = text[max(0, match.start() - 40): match.start()]
                if "plugins/local" in window:
                    continue
                offenders.append(path.relative_to(PLUGIN_ROOT).as_posix())
                break
        self.assertEqual(offenders, [], f"Subdirectory install assumptions in {offenders}")

    def test_manifest_points_at_this_repository(self) -> None:
        manifest = read_json(PLUGIN_ROOT / ".cursor-plugin" / "plugin.json")
        self.assertEqual(
            manifest["repository"], "https://github.com/analyticsengineering/ae-toolkit"
        )

    def test_plugin_manifest_sits_at_the_repository_root(self) -> None:
        self.assertTrue((PLUGIN_ROOT / ".cursor-plugin" / "plugin.json").is_file())
        self.assertFalse((PLUGIN_ROOT / ".cursor-plugin" / "marketplace.json").exists())

    def test_continuous_integration_runs_the_suite_and_target_drift_check(self) -> None:
        workflow = (PLUGIN_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("tests/run_tests.py", workflow)
        self.assertIn("scripts/build_targets.py --check", workflow)


class TrackedContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tracked = _tracked_files()
        if self.tracked is None:
            self.skipTest("git is unavailable")

    def test_bytecode_is_not_tracked(self) -> None:
        leaked = [
            path for path in self.tracked if "__pycache__" in path or path.endswith(".pyc")
        ]
        self.assertEqual(leaked, [], f"Bytecode is tracked: {leaked}")


if __name__ == "__main__":
    unittest.main()
