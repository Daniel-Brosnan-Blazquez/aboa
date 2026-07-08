"""
Tests for retention cleanup execution.
"""

import datetime
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from aboa.engine.engine import Engine
from aboa.engine.query import Query
from aboa.engine.retention import RETENTION_REMOVAL_JUSTIFICATION, apply_retention


class TestRetention(unittest.TestCase):
    """
    Integration tests for retention dry-run and deletion behavior.
    """

    def setUp(self):
        """
        Prepare a clean inventory with one temporary archive configuration.
        """
        # Retention cleanup reads only archived-file expiration_date values; the
        # archive configuration deliberately has no runtime retention policy.
        query = Query()
        query.clear_db()
        query.close_session()
        self.test_root = Path(tempfile.mkdtemp(prefix="aboa_test_"))
        self.archive_root = self.test_root / "archive"
        self.archive_root.mkdir()
        self.input_root = self.test_root / "inputs"
        self.input_root.mkdir()
        self.configuration_file = str(self.write_archive_configuration(
            "archive_configuration.xml",
            """<archive_configurations root_directory="{}">
  <archive_configuration file_group="group_a">
    <file_mask>*.txt</file_mask>
    <file_directory>texts</file_directory>
  </archive_configuration>
</archive_configurations>""".format(self.archive_root),
        ))
        self.engine = Engine()
        self.engine._load_archive_configuration(self.configuration_file)

    def tearDown(self):
        """
        Close sessions, clear rows, and remove temporary files.
        """
        self.engine.close_session()
        query = Query()
        query.clear_db()
        query.close_session()
        shutil.rmtree(str(self.test_root), ignore_errors=True)

    def make_file(self, name, content="hello"):
        """
        Create an input fixture file inside the test input root.
        """
        path = self.input_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def write_archive_configuration(self, name, content):
        """
        Write an archive configuration fixture inside the test root.
        """
        path = self.test_root / name
        path.write_text(content)
        return path

    def test_retention_dry_run_and_execution(self):
        """
        Return retention candidates in dry-run and delete them on execution.
        """
        input_file = self.make_file("sample.txt")
        future_file = self.make_file("future.txt")
        no_expiration_file = self.make_file("no_expiration.txt")
        # Expiration is in the past, making the file eligible without consulting
        # any runtime retention policy configuration.
        assert self.engine.archive_file(str(input_file), metadata={"file_type": "text", "expiration_date": datetime.datetime.utcnow() - datetime.timedelta(days=1)}) is None
        assert self.engine.archive_file(str(future_file), metadata={"file_type": "text", "expiration_date": datetime.datetime.utcnow() + datetime.timedelta(days=1)}) is None
        assert self.engine.archive_file(str(no_expiration_file), metadata={"file_type": "text"}) is None
        archived_file = self.engine.query.get_archived_files(
            names={"filter": [input_file.name], "op": "in"},
            selection="last",
        )[0]
        assert archived_file.deleteArchiveConfiguration is not None
        assert archived_file.deleteArchiveConfiguration.path == self.configuration_file

        dry_run = apply_retention(self.engine, dry_run=True)
        executed = apply_retention(self.engine, dry_run=False)

        assert len(dry_run) == 1
        assert len(executed) == 1
        assert dry_run[0].file_uuid == archived_file.file_uuid
        assert executed[0].available is False
        assert executed[0].deleteArchiveConfiguration is not None
        assert executed[0].deleteArchiveConfiguration.path == self.configuration_file
        assert executed[0].removal_justification == RETENTION_REMOVAL_JUSTIFICATION
        assert not os.path.exists(executed[0].path)
