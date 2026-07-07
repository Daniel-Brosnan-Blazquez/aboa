"""
Tests for physical archive path creation on the local filesystem.
"""

import os
import shutil
import unittest
from pathlib import Path

from aboa.engine.engine import Engine
from aboa.engine.query import Query


class TestArchiveFilesystem(unittest.TestCase):
    """
    Filesystem integration tests for archive storage layout.
    """

    def setUp(self):
        """
        Prepare fixture-backed input data and a clean archive root.
        """
        # Archive path assertions use a dedicated /tmp root, while configuration
        # and received files stay in src/tests/inputs with the rest of the suite.
        query = Query()
        query.clear_db()
        query.close_session()
        self.inputs_path = Path(__file__).parent / "inputs"
        self.archive_root = Path("/tmp/aboa_test_archive_filesystem_archive")
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        self.configuration_file = str(self.inputs_path / "archive_filesystem_configuration.xml")
        self.engine = Engine()
        self.engine.set_configuration_path(self.configuration_file)

    def tearDown(self):
        """
        Close the engine session and remove temporary filesystem state.
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

    def test_archive_creates_year_month_day_tree(self):
        """
        Store archived payloads below file group and archive-date folders.
        """
        input_file = self.input_file("archive_filesystem_sample.txt")

        assert self.engine.archive_file(str(input_file), reception_date="2026-07-02T10:00:00") is None
        archived_file = self.engine.query.get_archived_files(
            names={"filter": [input_file.name], "op": "in"},
            selection="last",
        )[0]
        parts = archived_file.path.split(os.sep)

        assert "texts" in parts
        assert "archive_filesystem_sample.txt" == parts[-1]
        # The date tree is based on archive time, not the reception date.
        assert parts[-4:-1] == [
            archived_file.archive_date.strftime("%Y"),
            archived_file.archive_date.strftime("%m"),
            archived_file.archive_date.strftime("%d"),
        ]
