#!/usr/bin/env python3
"""Run the toolkit's dependency-free unittest suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def main() -> int:
    tests_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(tests_dir))
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(tests_dir),
        pattern="test_*.py",
        top_level_dir=str(tests_dir),
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
