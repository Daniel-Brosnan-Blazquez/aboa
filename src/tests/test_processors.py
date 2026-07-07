"""
Tests for processor interface defaults.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from aboa.processors.base_processor import BaseProcessor, process


class TestProcessors(unittest.TestCase):
    """
    Unit tests for the base processor contract.
    """

    def setUp(self):
        """
        Create a temporary folder for processor input fixtures.
        """
        self.test_root = Path(tempfile.mkdtemp(prefix="aboa_processor_test_"))

    def tearDown(self):
        """
        Remove temporary processor input fixtures.
        """
        shutil.rmtree(str(self.test_root), ignore_errors=True)

    def test_base_processor_contract(self):
        """
        Return empty metadata from the default processor implementations.
        """
        input_file = self.test_root / "sample.txt"
        input_file.write_text("hello")

        # Both the class method and module-level convenience function are valid
        # processor entry points for configured archive processors.
        assert BaseProcessor().process(str(input_file)) == {}
        assert process(str(input_file)) == {}
