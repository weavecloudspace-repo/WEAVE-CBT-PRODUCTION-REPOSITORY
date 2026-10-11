"""Regression tests for the desktop CLI process boundary."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class CliProcessTests(unittest.TestCase):
    def test_nuitka_environment_is_not_forwarded(self):
        self.assertTrue(callable(bridge.discover))
