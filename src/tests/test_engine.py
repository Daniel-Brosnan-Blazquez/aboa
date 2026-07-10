"""
Tests for archive engine configuration, storage, and failure handling.
"""

import datetime
import os
import shutil
import sys
import unittest
from pathlib import Path

from aboa.datamodel.archived_files import ArchiveConfiguration, ArchivedFile, ArchiveOperation, ArchiveRootDirectory, FileToBeRemoved
from aboa.engine import engine as engine_module
from aboa.engine.engine import Engine
from aboa.engine.errors import (
    ArchiveConfigurationError,
    ArchiveDeletionError,
    ArchiveFileError,
    ArchiveRecoveryError,
    ArchiveRetrievalError,
)
from aboa.engine.query import Query


class TestEngine(unittest.TestCase):
    """
    Integration-style tests for archive engine mutations and failure recording.
    """

    def setUp(self):
        """
        Prepare a clean inventory and filesystem roots for each engine test.
        """
        # Engine tests share the configured database, so each test starts from an
        # empty inventory and recreates the POSIX archive roots it needs.
        query = Query()
        query.clear_db()
        query.close_session()
        self.inputs_path = Path(__file__).parent / "inputs"
        self.archive_root = Path("/tmp/aboa_test_engine_archive")
        self.second_archive_root = Path("/tmp/aboa_test_engine_archive_changed")
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        shutil.rmtree(str(self.second_archive_root), ignore_errors=True)
        self.configuration_file = str(self.inputs_path / "engine_archive_configuration.xml")
        self.engine = Engine()
        self.engine.set_configuration_path(self.configuration_file)

    def tearDown(self):
        """
        Close sessions and remove test archive roots.
        """
        self.engine.close_session()
        query = Query()
        query.close_session()
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        shutil.rmtree(str(self.second_archive_root), ignore_errors=True)

    def input_file(self, name):
        """
        Return a fixture input path by file name.
        """
        return self.inputs_path / name

    def archive_and_get(self, input_file, engine=None, **kwargs):
        """
        Archive a fixture and return the persisted inventory row.
        """
        engine = engine or self.engine
        assert engine.archive_file(str(input_file), **kwargs) is None
        return engine.query.get_archived_files(
            names={"filter": [Path(input_file).name], "op": "in"},
            selection="last",
        )[0]

    def test_set_configuration_path(self):
        """
        Store a custom configuration path for future archive operations.
        """
        configuration_path = str(self.inputs_path / "engine_archive_changed_root_configuration.xml")

        self.engine.set_configuration_path(configuration_path)

        assert self.engine.configuration_path == configuration_path

    def test_get_exit_code_returns_copy(self):
        """
        Expose engine exit-code descriptors without sharing mutable state.
        """
        exit_code = self.engine.get_exit_code("RETENTION_FAILED")
        exit_code["status"] = -1

        assert self.engine.get_exit_code("RETENTION_FAILED")["status"] == 10
        assert "retention operation" in self.engine.get_exit_code("RETENTION_FAILED")["message"]

    def test_archive_matching_file(self):
        """
        Archive a file that matches the configured text rule.
        """
        input_file = self.input_file("sample.txt")

        archived_file = self.archive_and_get(input_file)

        assert archived_file.file_group == "group_a"
        assert archived_file.archiveConfiguration is not None
        assert archived_file.archiveConfiguration.path == self.configuration_file
        assert os.path.exists(archived_file.path)
        path_parts = archived_file.path.split(os.sep)
        assert "texts" in path_parts
        assert path_parts[-4:-1] == [
            archived_file.archive_date.strftime("%Y"),
            archived_file.archive_date.strftime("%m"),
            archived_file.archive_date.strftime("%d"),
        ]
        assert archived_file.file_size == os.path.getsize(input_file)
        assert archived_file.expiration_date == archived_file.archive_date + datetime.timedelta(days=1)
        assert archived_file.deleteArchiveConfiguration is not None
        assert archived_file.deleteArchiveConfiguration.path == self.configuration_file

    def test_archive_unmatched_file_goes_to_unknown(self):
        """
        Archive unmatched files under the unknown fallback directory.
        """
        input_file = self.input_file("sample.bin")

        archived_file = self.archive_and_get(input_file)

        assert archived_file.file_group == "unknown"
        assert "unknown" in archived_file.path.split(os.sep)

    def test_changing_root_directory_archives_without_restart(self):
        """
        Use a reloaded XML configuration root without recreating the engine.
        """
        first_input = self.input_file("root_change_first.txt")
        second_input = self.input_file("root_change_second.txt")
        second_configuration = self.input_file("engine_archive_changed_root_configuration.xml")

        first_archive = self.archive_and_get(first_input)
        # Changing configuration should deactivate the first root and make
        # subsequent archives land below the new root directory.
        self.engine.set_configuration_path(str(second_configuration))
        second_archive = self.archive_and_get(second_input)

        assert os.path.exists(first_archive.path)
        assert os.path.exists(second_archive.path)
        assert os.path.commonpath([str(self.archive_root), first_archive.path]) == str(self.archive_root)
        assert os.path.commonpath([str(self.second_archive_root), second_archive.path]) == str(self.second_archive_root)

    def test_load_archive_configuration_tracks_history_by_content_checksum(self):
        """
        Persist a new archive-configuration row only when XML content changes.
        """
        second_configuration = self.input_file("engine_archive_changed_root_configuration.xml")

        self.engine._load_archive_configuration(self.configuration_file)
        self.engine._load_archive_configuration(self.configuration_file)
        first_rows = self.engine.session.query(ArchiveConfiguration).all()

        self.engine._load_archive_configuration(str(second_configuration))
        rows = self.engine.query.get_archive_configurations(order_by={"field": "active_from", "descending": False})
        active_rows = self.engine.query.get_archive_configurations(active={"filter": True, "op": "=="})
        inactive_rows = self.engine.query.get_archive_configurations(active={"filter": False, "op": "=="})

        assert len(first_rows) == 1
        assert len(rows) == 2
        assert len(active_rows) == 1
        assert len(inactive_rows) == 1
        assert inactive_rows[0].active_until is not None
        assert active_rows[0].path == str(second_configuration)
        assert active_rows[0].content == second_configuration.read_text(encoding="utf-8")

    def test_archive_file_reloads_configuration_and_repairs_stale_root_directory(self):
        """
        Repair stale active root-directory metadata before archiving.
        """
        input_file = self.input_file("root_change_first.txt")
        self.archive_and_get(self.input_file("root_change_second.txt"))
        # Simulate a database row that no longer matches the XML configuration;
        # archive_file reloads the configuration and restores a single active root.
        stale_root_directory = self.engine.query.get_active_root_directory()
        stale_root_directory.path = str(self.second_archive_root)
        self.engine.session.commit()

        archived_file = self.archive_and_get(input_file)
        active_root_directory = self.engine.query.get_active_root_directory()
        active_root_directories = self.engine.session.query(ArchiveRootDirectory).filter(ArchiveRootDirectory.active == True).all()

        assert active_root_directory.path == str(self.archive_root)
        assert archived_file.rootDirectory.path == str(self.archive_root)
        assert os.path.commonpath([str(self.archive_root), archived_file.path]) == str(self.archive_root)
        assert len(active_root_directories) == 1

    def test_archive_file_records_failure_and_raises_when_configuration_reload_fails(self):
        """
        Record archive failure metadata when configuration reload fails.
        """
        default_archive_root = Path("/tmp/aboa_test_engine_default_archive")
        shutil.rmtree(str(default_archive_root), ignore_errors=True)
        previous_default_archive_path = os.environ.get("ABOA_DEFAULT_ARCHIVE_PATH")
        os.environ["ABOA_DEFAULT_ARCHIVE_PATH"] = str(default_archive_root)
        try:
            self.engine.set_configuration_path(str(self.inputs_path / "does_not_exist.xml"))
            # archive_file converts the configuration failure into a persisted
            # failed operation associated with an unavailable archived-file row.
            with self.assertRaises(ArchiveConfigurationError):
                self.engine.archive_file(str(self.input_file("sample.txt")))
            active_root_directory = self.engine.query.get_active_root_directory()
            archived_files = self.engine.session.query(ArchivedFile).all()
            operations = self.engine.session.query(ArchiveOperation).all()

            assert active_root_directory.path == str(default_archive_root)
            assert default_archive_root.exists()
            assert len(archived_files) == 1
            assert archived_files[0].path == str(self.input_file("sample.txt"))
            assert archived_files[0].available is False
            assert archived_files[0].rootDirectory.path == str(default_archive_root)
            assert archived_files[0].archive_configuration_uuid is None
            assert len(operations) == 1
            assert operations[0].file_uuid == archived_files[0].file_uuid
        finally:
            if previous_default_archive_path is None:
                os.environ.pop("ABOA_DEFAULT_ARCHIVE_PATH", None)
            else:
                os.environ["ABOA_DEFAULT_ARCHIVE_PATH"] = previous_default_archive_path
            shutil.rmtree(str(default_archive_root), ignore_errors=True)

    def test_archive_processor_metadata(self):
        """
        Merge processor-produced metadata into the archived-file inventory row.
        """
        inputs_path = str(self.inputs_path)
        # Processor fixtures are plain modules in the inputs directory.
        if inputs_path not in sys.path:
            sys.path.insert(0, inputs_path)
        configuration = self.inputs_path / "engine_metadata_configuration.xml"
        engine = Engine()
        engine.set_configuration_path(str(configuration))
        input_file = self.input_file("sample.txt")

        archived_file = self.archive_and_get(input_file, engine=engine)

        assert archived_file.file_type == "text"
        assert archived_file.file_class == "AUX"
        assert archived_file.file_version == "1.0"
        assert archived_file.generation_date.isoformat() == "2026-07-01T12:00:00"
        engine.close_session()

    def test_archive_processor_failure_goes_to_error(self):
        """
        Archive files in the error area when their configured processor fails.
        """
        inputs_path = str(self.inputs_path)
        # Processor fixtures are plain modules in the inputs directory.
        if inputs_path not in sys.path:
            sys.path.insert(0, inputs_path)
        configuration = self.inputs_path / "engine_failure_configuration.xml"
        engine = Engine()
        engine.set_configuration_path(str(configuration))
        input_file = self.input_file("sample.txt")

        archived_file = self.archive_and_get(input_file, engine=engine)
        operations = engine.session.query(ArchiveOperation).all()

        assert "error" in archived_file.path.split(os.sep)
        assert len(operations) == 1
        assert operations[0].file_uuid == archived_file.file_uuid
        engine.close_session()

    def test_archive_checksum_failure_goes_to_error(self):
        """
        Archive files in the error area when checksum calculation fails.
        """
        input_file = self.input_file("sample.txt")
        original_checksum = self.engine._checksum

        def fail_checksum(file_path):
            raise OSError("checksum read failed")

        try:
            self.engine._checksum = fail_checksum
            archived_file = self.archive_and_get(input_file)
        finally:
            self.engine._checksum = original_checksum
        operations = self.engine.session.query(ArchiveOperation).all()

        assert "error" in archived_file.path.split(os.sep)
        assert archived_file.checksum is None
        assert len(operations) == 1
        assert operations[0].file_uuid == archived_file.file_uuid

    def test_archive_missing_file_records_failure_with_archived_file(self):
        """
        Persist failure context when the requested input file does not exist.
        """
        missing_file = self.input_file("missing.txt")

        with self.assertRaises(ArchiveFileError):
            self.engine.archive_file(str(missing_file))

        archived_files = self.engine.session.query(ArchivedFile).all()
        operations = self.engine.session.query(ArchiveOperation).all()

        assert len(archived_files) == 1
        assert len(operations) == 1
        assert archived_files[0].path == str(missing_file)
        assert archived_files[0].available is False
        assert archived_files[0].file_size == 0
        assert operations[0].file_uuid == archived_files[0].file_uuid

    def test_retrieve_files_raises_archive_retrieval_error_on_failure(self):
        """
        Convert retrieval failures into ArchiveRetrievalError.
        """
        original_get_archived_files = self.engine.query.get_archived_files

        def fail_get_archived_files(**kwargs):
            raise ValueError("retrieval failed")

        try:
            self.engine.query.get_archived_files = fail_get_archived_files
            with self.assertRaises(ArchiveRetrievalError):
                self.engine.retrieve_files()
        finally:
            self.engine.query.get_archived_files = original_get_archived_files
        operations = self.engine.session.query(ArchiveOperation).all()

        assert len(operations) == 1
        assert operations[0].operation == "retrieve"
        assert operations[0].status == 9
        assert "retrieval failed" in operations[0].message

    def test_delete_logical_and_physical(self):
        """
        Mark an archived file unavailable and move its physical payload to trash.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)

        deleted = self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert deleted[0].available is False
        assert deleted[0].physically_available is True
        assert deleted[0].removal_date is not None
        assert deleted[0].removal_justification == "manual_delete"
        assert deleted[0].delete_archive_configuration_uuid is None
        assert not os.path.exists(deleted[0].path)
        assert len(queued) == 1
        assert isinstance(queued[0], FileToBeRemoved)
        assert queued[0].file_to_remove_uuid is not None
        assert queued[0].file_uuid == deleted[0].file_uuid
        assert queued[0].root_directory_uuid == deleted[0].root_directory_uuid
        assert queued[0].removal_date == deleted[0].removal_date + datetime.timedelta(days=self.engine.final_removal_delay_days)
        assert os.path.exists(queued[0].path)
        assert "trash" in queued[0].path.split(os.sep)

    def test_delete_physical_is_idempotent_when_payload_is_already_in_trash(self):
        """
        Repeating a physical delete keeps the original removal metadata and trash row.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)

        first_delete = self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)[0]
        first_removal_date = first_delete.removal_date
        first_queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]
        second_delete = self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)[0]
        second_queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert second_delete.available is False
        assert second_delete.physically_available is True
        assert second_delete.removal_date == first_removal_date
        assert len(second_queued) == 1
        assert second_queued[0].file_to_remove_uuid == first_queued.file_to_remove_uuid
        assert second_queued[0].path == first_queued.path
        assert os.path.exists(first_queued.path)

    def test_delete_physical_marks_missing_payload_not_physically_available(self):
        """
        Physical deletion notices when the archive payload has already disappeared.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        os.unlink(archived_file.path)

        deleted = self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert deleted[0].available is False
        assert deleted[0].physically_available is False
        assert queued == []

    def test_delete_permanently_bypasses_trash(self):
        """
        Permanent deletion removes the payload immediately and leaves no trash row.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        archive_path = archived_file.path

        deleted = self.engine.delete_files(file_uuids=[archived_file.file_uuid], permanent_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert deleted[0].available is False
        assert deleted[0].physically_available is False
        assert not os.path.exists(archive_path)
        assert queued == []

    def test_delete_archived_file_entry_requires_no_physical_payload(self):
        """
        Purge archived_files rows only after the managed payload has gone.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        file_uuid = archived_file.file_uuid

        with self.assertRaises(ArchiveDeletionError):
            self.engine.delete_archived_file_entries(file_uuids=[file_uuid])
        self.engine.delete_files(file_uuids=[file_uuid], permanent_delete=True)
        self.engine.record_failure("archive", 5, "duplicate reception", archived_file)
        self.engine.session.commit()

        purged = self.engine.delete_archived_file_entries(file_uuids=[file_uuid])
        remaining = self.engine.query.get_archived_files(file_uuids={"filter": [file_uuid], "op": "in"})
        remaining_operations = self.engine.query.get_archive_operations(file_uuids={"filter": [file_uuid], "op": "in"})

        assert len(purged) == 1
        assert purged[0].file_uuid == file_uuid
        assert remaining == []
        assert remaining_operations == []

    def test_repeated_duplicate_reception_reuses_existing_error_payload(self):
        """
        Do not create another error-folder copy for the same duplicate checksum.
        """
        input_file = self.input_file("sample.txt")
        self.archive_and_get(input_file)

        self.engine.archive_file(str(input_file))
        first_error_files = list(self.archive_root.glob("error/**/*.txt"))
        self.engine.archive_file(str(input_file))
        second_error_files = list(self.archive_root.glob("error/**/*.txt"))
        error_rows = self.engine.query.get_archived_files(paths={"filter": "%/error/%", "op": "like"})
        operations = self.engine.query.get_archive_operations(operations={"filter": "archive", "op": "like"})

        assert len(first_error_files) == 1
        assert len(second_error_files) == 1
        assert len(error_rows) == 1
        assert len(operations) == 2

    def test_recover_files_from_trash(self):
        """
        Move a trashed payload back to its archive path and clear trash metadata.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        archive_path = archived_file.path
        self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})
        trash_path = queued[0].path

        recovered = self.engine.recover_files_from_trash(file_uuids=[archived_file.file_uuid])
        remaining = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert len(recovered) == 1
        assert recovered[0].file_uuid == archived_file.file_uuid
        assert recovered[0].available is True
        assert recovered[0].physically_available is True
        assert recovered[0].removal_date is None
        assert recovered[0].removal_justification is None
        assert recovered[0].path == archive_path
        assert os.path.exists(archive_path)
        assert not os.path.exists(trash_path)
        assert remaining == []

    def test_recover_files_from_trash_failure_is_recorded(self):
        """
        Record a recovery failure and leave the trash row queued for inspection.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})
        trash_path = queued[0].path
        os.unlink(trash_path)

        with self.assertRaises(ArchiveRecoveryError):
            self.engine.recover_files_from_trash(file_uuids=[archived_file.file_uuid])
        remaining = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})
        operations = self.engine.query.get_archive_operations(operations={"filter": "recover", "op": "like"})

        assert len(remaining) == 1
        assert remaining[0].path == trash_path
        assert archived_file.available is False
        assert len(operations) == 1
        assert operations[0].status == 13
        assert operations[0].file_uuid == archived_file.file_uuid
        assert trash_path in operations[0].message

    def test_trash_configuration_is_loaded_from_engine_configuration(self):
        """
        Move physical deletions using trash settings configured in engine.json.
        """
        original_read_configuration = engine_module.read_configuration
        engine = None

        def read_custom_configuration():
            configuration = original_read_configuration()
            configuration.setdefault("ARCHIVE", {})["TRASH_DIRECTORY"] = "custom_trash"
            configuration["ARCHIVE"]["FINAL_REMOVAL_DELAY_DAYS"] = 7
            return configuration

        try:
            engine_module.read_configuration = read_custom_configuration
            engine = Engine()
            engine.set_configuration_path(self.configuration_file)
            archived_file = self.archive_and_get(self.input_file("sample.txt"), engine=engine)
            deleted = engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
            queued = engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

            assert engine.trash_directory == "custom_trash"
            assert engine.final_removal_delay_days == 7
            assert len(queued) == 1
            assert queued[0].removal_date == deleted[0].removal_date + datetime.timedelta(days=7)
            assert "custom_trash" in queued[0].path.split(os.sep)
            assert not os.path.exists(deleted[0].path)
            assert os.path.exists(queued[0].path)
        finally:
            engine_module.read_configuration = original_read_configuration
            if engine is not None:
                engine.close_session()

    def test_delete_files_raises_archive_deletion_error_on_failure(self):
        """
        Convert deletion failures into ArchiveDeletionError.
        """
        original_get_archived_files = self.engine.query.get_archived_files

        def fail_get_archived_files(**kwargs):
            raise ValueError("deletion failed")

        try:
            self.engine.query.get_archived_files = fail_get_archived_files
            with self.assertRaises(ArchiveDeletionError):
                self.engine.delete_files()
        finally:
            self.engine.query.get_archived_files = original_get_archived_files
        operations = self.engine.session.query(ArchiveOperation).all()

        assert len(operations) == 1
        assert operations[0].operation == "delete"
        assert operations[0].status == 8
        assert "deletion failed" in operations[0].message
