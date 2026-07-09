"""
Tests for cleanup workflows built on archived-file expiration dates.
"""

import datetime
import shutil
import unittest
from pathlib import Path

from aboa.engine.engine import Engine
from aboa.engine.query import Query
from aboa.engine.retention import apply_retention


class TestCleanUp(unittest.TestCase):
    """
    Integration tests for cleanup candidate selection.
    """

    def setUp(self):
        """
        Prepare a clean inventory and fixture-backed archive root.
        """
        # Cleanup is driven by stored expiration dates, so this fixture creates an
        # isolated archive configuration without runtime retention policies.
        query = Query()
        query.clear_db()
        query.close_session()
        self.inputs_path = Path(__file__).parent / "inputs"
        self.archive_root = Path("/tmp/aboa_test_clean_up_archive")
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        self.configuration_file = str(self.inputs_path / "clean_up_archive_configuration.xml")
        self.engine = Engine()
        self.engine.set_configuration_path(self.configuration_file)

    def tearDown(self):
        """
        Close sessions, clear rows, and remove temporary archive files.
        """
        self.engine.close_session()
        query = Query()
        query.clear_db()
        query.close_session()
        shutil.rmtree(str(self.archive_root), ignore_errors=True)

    def input_file(self, name):
        """
        Return a fixture input path by file name.
        """
        return self.inputs_path / name

    def archive_file(self, input_file, **metadata):
        """
        Archive a fixture with optional metadata and return the inventory row.
        """
        assert self.engine.archive_file(str(input_file), metadata=metadata) is None
        return self.engine.query.get_archived_files(
            names={"filter": [Path(input_file).name], "op": "in"},
            selection="last",
        )[0]

    def test_clean_up_dry_run_returns_candidates(self):
        """
        Return expired archive files as cleanup candidates in dry-run mode.
        """
        input_file = self.input_file("sample.txt")
        # Set expiration in the past so the file qualifies immediately.
        archived_file = self.archive_file(
            input_file,
            file_type="text",
            expiration_date=datetime.datetime.utcnow() - datetime.timedelta(days=1),
        )

        candidates = apply_retention(self.engine, dry_run=True)

        assert candidates[0].file_uuid == archived_file.file_uuid
