"""
Tests for retention cleanup execution.
"""

import datetime
import os
import shutil
import unittest
from pathlib import Path

from aboa.engine.engine import Engine
from aboa.engine.query import Query
from aboa.engine import retention as retention_module
from aboa.engine.errors import ArchiveRetentionError
from aboa.engine.retention import RETENTION_REMOVAL_JUSTIFICATION, apply_final_removal, apply_retention


class TestRetention(unittest.TestCase):
    """
    Integration tests for retention dry-run and deletion behavior.
    """

    def setUp(self):
        """
        Prepare a clean inventory and fixture-backed archive root.
        """
        # Retention cleanup reads only archived-file expiration_date values; the
        # archive configuration fixture deliberately has no runtime retention policy.
        query = Query()
        query.clear_db()
        query.close_session()
        self.inputs_path = Path(__file__).parent / "inputs"
        self.archive_root = Path("/tmp/aboa_test_retention_archive")
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        self.configuration_file = str(self.inputs_path / "retention_archive_configuration.xml")
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

    def test_retention_dry_run_and_execution(self):
        """
        Return retention candidates in dry-run and delete them on execution.
        """
        input_file = self.input_file("sample.txt")
        future_file = self.input_file("query_a.txt")
        no_expiration_file = self.input_file("query_b.txt")
        # Expiration is in the past, making the file eligible without consulting
        # any runtime retention policy configuration.
        archived_file = self.archive_file(
            input_file,
            file_type="text",
            expiration_date=datetime.datetime.utcnow() - datetime.timedelta(days=1),
        )
        self.archive_file(
            future_file,
            file_type="text",
            expiration_date=datetime.datetime.utcnow() + datetime.timedelta(days=1),
        )
        self.archive_file(no_expiration_file, file_type="text")
        assert archived_file.deleteArchiveConfiguration is not None
        assert archived_file.deleteArchiveConfiguration.path == self.configuration_file

        dry_run = apply_retention(self.engine, dry_run=True)
        executed = apply_retention(self.engine, dry_run=False)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert len(dry_run) == 1
        assert len(executed) == 1
        assert dry_run[0].file_uuid == archived_file.file_uuid
        assert executed[0].available is False
        assert executed[0].deleteArchiveConfiguration is not None
        assert executed[0].deleteArchiveConfiguration.path == self.configuration_file
        assert executed[0].removal_justification == RETENTION_REMOVAL_JUSTIFICATION
        assert not os.path.exists(executed[0].path)
        assert len(queued) == 1
        assert queued[0].removal_date == executed[0].removal_date + datetime.timedelta(days=self.engine.final_removal_delay_days)
        assert os.path.exists(queued[0].path)
        assert "trash" in queued[0].path.split(os.sep)

    def test_final_removal_deletes_eligible_trash_rows(self):
        """
        Permanently delete trash payloads after the 30-day grace period.
        """
        input_file = self.input_file("sample.txt")
        self.archive_file(
            input_file,
            file_type="text",
            expiration_date=datetime.datetime.utcnow() - datetime.timedelta(days=1),
        )
        apply_retention(self.engine, dry_run=False)
        queued = self.engine.query.get_files_to_be_removed()[0]
        queued.removal_date = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        trash_path = queued.path
        self.engine.session.commit()

        removed = apply_final_removal(self.engine)
        remaining = self.engine.query.get_files_to_be_removed()

        assert len(removed) == 1
        assert removed[0].file_uuid == queued.file_uuid
        assert queued.archivedFile.physically_available is False
        assert not os.path.exists(trash_path)
        assert remaining == []

    def test_final_removal_can_empty_trash_immediately(self):
        """
        Delete queued trash payloads before their scheduled final-removal date.
        """
        input_file = self.input_file("sample.txt")
        self.archive_file(
            input_file,
            file_type="text",
            expiration_date=datetime.datetime.utcnow() - datetime.timedelta(days=1),
        )
        apply_retention(self.engine, dry_run=False)
        queued = self.engine.query.get_files_to_be_removed()[0]
        trash_path = queued.path

        scheduled_dry_run = apply_final_removal(self.engine, dry_run=True)
        immediate_dry_run = apply_final_removal(self.engine, dry_run=True, empty_trash=True)
        removed = apply_final_removal(self.engine, empty_trash=True)
        remaining = self.engine.query.get_files_to_be_removed()

        assert scheduled_dry_run == []
        assert len(immediate_dry_run) == 1
        assert immediate_dry_run[0].file_uuid == queued.file_uuid
        assert len(removed) == 1
        assert removed[0].file_uuid == queued.file_uuid
        assert queued.archivedFile.physically_available is False
        assert not os.path.exists(trash_path)
        assert remaining == []

    def test_final_removal_failure_is_registered_for_retry(self):
        """
        Register final-removal failures and keep the queue row for retry.
        """
        input_file = self.input_file("sample.txt")
        self.archive_file(
            input_file,
            file_type="text",
            expiration_date=datetime.datetime.utcnow() - datetime.timedelta(days=1),
        )
        apply_retention(self.engine, dry_run=False)
        queued = self.engine.query.get_files_to_be_removed()[0]
        queued.removal_date = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        trash_path = queued.path
        self.engine.session.commit()
        original_unlink = retention_module.os.unlink

        def fail_unlink(path):
            if path == trash_path:
                raise OSError("permission denied")
            return original_unlink(path)

        try:
            retention_module.os.unlink = fail_unlink
            removed = apply_final_removal(self.engine)
        finally:
            retention_module.os.unlink = original_unlink
        remaining = self.engine.query.get_files_to_be_removed()
        operations = self.engine.query.get_archive_operations(operations={"filter": "final_removal", "op": "like"})

        assert len(removed) == 1
        assert len(remaining) == 1
        assert remaining[0].path == trash_path
        assert os.path.exists(trash_path)
        assert len(operations) == 1
        assert operations[0].status == 12
        assert operations[0].file_uuid == queued.file_uuid
        assert "permission denied" in operations[0].message

    def test_retention_failure_raises_specific_exception(self):
        """
        Convert retention cleanup failures into ArchiveRetentionError.
        """
        original_get_expired_files = retention_module.get_expired_files

        def fail_get_expired_files(session, now=None):
            raise ValueError("retention query failed")

        try:
            retention_module.get_expired_files = fail_get_expired_files
            with self.assertRaises(ArchiveRetentionError):
                apply_retention(self.engine)
        finally:
            retention_module.get_expired_files = original_get_expired_files
        operations = self.engine.query.get_archive_operations(operations={"filter": "retention", "op": "like"})

        assert len(operations) == 1
        assert operations[0].status == 10
        assert "retention query failed" in operations[0].message
