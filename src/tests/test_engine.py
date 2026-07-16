"""
Tests for archive engine configuration, storage, and failure handling.
"""

import datetime
import importlib
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from lxml import etree

from aboa.datamodel.archived_files import ArchiveConfiguration, ArchivedFile, ArchiveOperation, ArchiveRootDirectory, FileToBeRemoved
from aboa.engine import engine as engine_module
from aboa.engine.engine import Engine
from aboa.engine.errors import (
    ArchiveConfigurationError,
    ArchiveDeletionError,
    ArchiveFileError,
    ArchiveRecoveryError,
    ArchiveRetrievalError,
    ProcessorError,
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

    def test_engine_accepts_supplied_session_and_validates_final_removal_delay(self):
        """
        Accept caller-owned sessions and validate cleanup delay configuration.
        """
        query = Query()
        engine = None
        try:
            engine = Engine(session=query.session)
            assert engine.session is query.session
            assert engine.query.session is query.session
        finally:
            if engine is not None:
                engine.close_session()

        self.engine.engine_configuration = {"ARCHIVE": {"FINAL_REMOVAL_DELAY_DAYS": None}}
        assert self.engine._configured_final_removal_delay_days() == 30
        self.engine.engine_configuration = {"ARCHIVE": {"FINAL_REMOVAL_DELAY_DAYS": " "}}
        assert self.engine._configured_final_removal_delay_days() == 30
        self.engine.engine_configuration = {"ARCHIVE": {"FINAL_REMOVAL_DELAY_DAYS": "many"}}
        with self.assertRaises(ArchiveConfigurationError):
            self.engine._configured_final_removal_delay_days()
        self.engine.engine_configuration = {"ARCHIVE": {"FINAL_REMOVAL_DELAY_DAYS": -1}}
        with self.assertRaises(ArchiveConfigurationError):
            self.engine._configured_final_removal_delay_days()

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

    def test_delete_does_not_select_already_deleted_files_by_default(self):
        """
        Repeating a delete skips files already marked unavailable.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)

        first_delete = self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)[0]
        first_removal_date = first_delete.removal_date
        first_queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]
        second_delete = self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        second_queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert second_delete == []
        assert archived_file.available is False
        assert archived_file.physically_available is True
        assert archived_file.removal_date == first_removal_date
        assert len(second_queued) == 1
        assert second_queued[0].file_to_remove_uuid == first_queued.file_to_remove_uuid
        assert second_queued[0].path == first_queued.path
        assert os.path.exists(first_queued.path)

    def test_physical_delete_can_process_logically_unavailable_file(self):
        """
        Physical deletion can move a logically deleted payload to trash later.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        archive_path = archived_file.path
        first_delete = self.engine.delete_files(file_uuids=[archived_file.file_uuid])[0]

        physical_delete = self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert first_delete.available is False
        assert os.path.exists(archive_path) is False
        assert len(physical_delete) == 1
        assert physical_delete[0].file_uuid == archived_file.file_uuid
        assert len(queued) == 1
        assert os.path.exists(queued[0].path)
        assert "trash" in queued[0].path.split(os.sep)

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

    def test_delete_permanently_can_purge_inventory_in_same_request(self):
        """
        Permanent deletion can remove payload, inventory, and operations together.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        file_uuid = archived_file.file_uuid
        archive_path = archived_file.path
        self.engine.record_failure("archive", 5, "duplicate reception", archived_file)
        self.engine.session.commit()

        deleted = self.engine.delete_files(
            file_uuids=[file_uuid],
            permanent_delete=True,
            purge_entries=True,
        )
        remaining = self.engine.query.get_archived_files(file_uuids={"filter": [file_uuid], "op": "in"})
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [file_uuid], "op": "in"})
        remaining_operations = self.engine.query.get_archive_operations(file_uuids={"filter": [file_uuid], "op": "in"})

        assert len(deleted) == 1
        assert deleted[0].file_uuid == file_uuid
        assert not os.path.exists(archive_path)
        assert remaining == []
        assert queued == []
        assert remaining_operations == []

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

    def test_duplicate_reception_reuse_can_delete_input_file(self):
        """
        Delete a duplicate input after reusing an existing error payload.
        """
        temp_root = Path(tempfile.mkdtemp(prefix="aboa_engine_duplicate_delete_"))
        duplicate_input = temp_root / "sample.txt"
        shutil.copy2(str(self.input_file("sample.txt")), str(duplicate_input))
        try:
            self.archive_and_get(self.input_file("sample.txt"))
            self.engine.archive_file(str(duplicate_input))
            assert duplicate_input.exists()

            self.engine.archive_file(str(duplicate_input), delete=True)

            assert not duplicate_input.exists()
            assert len(list(self.archive_root.glob("error/**/*.txt"))) == 1
        finally:
            shutil.rmtree(str(temp_root), ignore_errors=True)

    def test_archive_storage_failure_records_normal_and_error_storage_failures(self):
        """
        Record archive failures when normal and error-area storage both fail.
        """
        original_store_file = self.engine._store_file

        def fail_store_file(source_path, destination_path):
            raise OSError("storage unavailable")

        try:
            self.engine._store_file = fail_store_file
            with self.assertRaises(ArchiveFileError):
                self.engine.archive_file(str(self.input_file("sample.txt")))
        finally:
            self.engine._store_file = original_store_file
        operations = self.engine.query.get_archive_operations(operations={"filter": "archive", "op": "like"})

        assert len(operations) == 2
        assert all(operation.status == 6 for operation in operations)
        assert all("storage unavailable" in operation.message for operation in operations)

    def test_archive_delete_removes_successfully_archived_input(self):
        """
        Remove a caller-owned input file after a successful archive.
        """
        temp_root = Path(tempfile.mkdtemp(prefix="aboa_engine_archive_delete_"))
        input_file = temp_root / "delete_me.txt"
        shutil.copy2(str(self.input_file("delete_me.txt")), str(input_file))
        try:
            self.engine.archive_file(str(input_file), delete=True)
            archived_file = self.engine.query.get_archived_files(names={"filter": "delete_me.txt", "op": "like"})[0]

            assert not input_file.exists()
            assert os.path.exists(archived_file.path)
        finally:
            shutil.rmtree(str(temp_root), ignore_errors=True)

    def test_retrieve_grouped_files_updates_last_access_dates(self):
        """
        Flatten grouped retrieval results for access-date bookkeeping.
        """
        self.archive_and_get(self.input_file("sample.txt"))
        self.archive_and_get(self.input_file("sample.bin"))

        grouped = self.engine.retrieve_files(group_by="file_group")
        accessed_files = [archived_file for group in grouped.values() for archived_file in group]

        assert "group_a" in grouped
        assert "unknown" in grouped
        assert all(archived_file.last_access_date is not None for archived_file in accessed_files)

    def test_copy_retrieved_files_rejects_bad_destinations_and_missing_payloads(self):
        """
        Reject retrieval destinations that are files and selected payloads that are missing.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        destination_file = self.archive_root / "not_a_directory"
        destination_file.write_text("not a directory")

        with self.assertRaises(ValueError):
            self.engine._copy_retrieved_files([archived_file], str(destination_file))

        destination_directory = self.archive_root / "retrieved"
        os.unlink(archived_file.path)
        with self.assertRaises(ValueError):
            self.engine._copy_retrieved_files([archived_file], str(destination_directory))

    def test_retrieval_destination_path_avoids_name_collisions(self):
        """
        Build unique retrieval output names without overwriting existing files.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        destination_directory = Path(tempfile.mkdtemp(prefix="aboa_engine_retrieve_collision_"))
        try:
            (destination_directory / "sample.txt").write_text("existing")
            unique_path = self.engine._build_retrieval_destination_path(str(destination_directory), archived_file)
            Path(unique_path).write_text("existing unique")

            numbered_path = self.engine._build_retrieval_destination_path(
                str(destination_directory),
                archived_file,
                copied_paths={unique_path},
            )
            Path(numbered_path).write_text("existing numbered")
            second_numbered_path = self.engine._build_retrieval_destination_path(
                str(destination_directory),
                archived_file,
                copied_paths={unique_path},
            )

            assert unique_path.endswith("sample_{}.txt".format(archived_file.file_uuid))
            assert numbered_path.endswith("sample_{}_1.txt".format(archived_file.file_uuid))
            assert second_numbered_path.endswith("sample_{}_2.txt".format(archived_file.file_uuid))
        finally:
            shutil.rmtree(str(destination_directory), ignore_errors=True)

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

    def test_recover_logically_deleted_file_without_trash(self):
        """
        Mark a logical-only deleted file available again without moving bytes.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        archive_path = archived_file.path
        self.engine.delete_files(file_uuids=[archived_file.file_uuid])
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        recovered = self.engine.recover_files_from_trash(file_uuids=[archived_file.file_uuid])
        remaining = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert queued == []
        assert len(recovered) == 1
        assert recovered[0].file_uuid == archived_file.file_uuid
        assert recovered[0].available is True
        assert recovered[0].physically_available is True
        assert recovered[0].removal_date is None
        assert recovered[0].removal_justification is None
        assert recovered[0].path == archive_path
        assert os.path.exists(archive_path)
        assert remaining == []

    def test_recover_recalculates_expiration_from_current_configuration(self):
        """
        Recovery applies the active retention policy like a fresh archive.
        """
        input_file = self.input_file("sample.txt")
        recovery_configuration = str(self.inputs_path / "engine_archive_recovery_future_configuration.xml")
        original_expiration_date = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        archived_file = self.archive_and_get(input_file, metadata={"expiration_date": original_expiration_date})
        self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        self.engine.set_configuration_path(recovery_configuration)

        before_recovery = datetime.datetime.utcnow()
        recovered = self.engine.recover_files_from_trash(file_uuids=[archived_file.file_uuid])
        after_recovery = datetime.datetime.utcnow()

        assert len(recovered) == 1
        assert recovered[0].expiration_date > original_expiration_date
        assert before_recovery + datetime.timedelta(days=2) <= recovered[0].expiration_date
        assert recovered[0].expiration_date <= after_recovery + datetime.timedelta(days=2)
        assert recovered[0].deleteArchiveConfiguration is not None
        assert recovered[0].deleteArchiveConfiguration.path == recovery_configuration

    def test_recover_keeps_existing_future_expiration(self):
        """
        Recovery preserves a previous expiration date that is still in the future.
        """
        input_file = self.input_file("sample.txt")
        recovery_configuration = str(self.inputs_path / "engine_archive_recovery_past_generation_configuration.xml")
        future_expiration_date = datetime.datetime(2099, 12, 31, 23, 59, 59)
        old_generation_date = datetime.datetime.utcnow() - datetime.timedelta(days=10)
        archived_file = self.archive_and_get(
            input_file,
            metadata={
                "expiration_date": future_expiration_date,
                "generation_date": old_generation_date,
            },
        )
        self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        self.engine.set_configuration_path(recovery_configuration)

        recovered = self.engine.recover_files_from_trash(file_uuids=[archived_file.file_uuid])

        assert len(recovered) == 1
        assert recovered[0].expiration_date == future_expiration_date
        assert recovered[0].deleteArchiveConfiguration is not None
        assert recovered[0].deleteArchiveConfiguration.path == self.configuration_file

    def test_recover_clears_expiration_when_current_retention_is_not_future(self):
        """
        Recovery leaves expiration empty when current retention has already expired.
        """
        input_file = self.input_file("sample.txt")
        recovery_configuration = str(self.inputs_path / "engine_archive_recovery_past_generation_configuration.xml")
        old_generation_date = datetime.datetime.utcnow() - datetime.timedelta(days=10)
        old_expiration_date = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        archived_file = self.archive_and_get(
            input_file,
            metadata={
                "expiration_date": old_expiration_date,
                "generation_date": old_generation_date,
            },
        )
        self.engine.delete_files(file_uuids=[archived_file.file_uuid])
        self.engine.set_configuration_path(recovery_configuration)

        recovered = self.engine.recover_files_from_trash(file_uuids=[archived_file.file_uuid])

        assert len(recovered) == 1
        assert recovered[0].expiration_date is None
        assert recovered[0].deleteArchiveConfiguration is None

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

    def test_final_removal_delay_is_loaded_from_engine_configuration(self):
        """
        Move physical deletions using cleanup delay configured in engine.json.
        """
        original_read_configuration = engine_module.read_configuration
        engine = None

        def read_custom_configuration():
            configuration = original_read_configuration()
            configuration.setdefault("ARCHIVE", {})["FINAL_REMOVAL_DELAY_DAYS"] = 7
            return configuration

        try:
            engine_module.read_configuration = read_custom_configuration
            engine = Engine()
            engine.set_configuration_path(self.configuration_file)
            archived_file = self.archive_and_get(self.input_file("sample.txt"), engine=engine)
            deleted = engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
            queued = engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

            assert engine.final_removal_delay_days == 7
            assert len(queued) == 1
            assert queued[0].removal_date == deleted[0].removal_date + datetime.timedelta(days=7)
            assert "trash" in queued[0].path.split(os.sep)
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

    def test_delete_rejects_purge_entries_while_moving_to_trash(self):
        """
        Reject incompatible physical deletion and purge-entry options.
        """
        with self.assertRaises(ArchiveDeletionError):
            self.engine.delete_files(physical_delete=True, purge_entries=True)
        operations = self.engine.query.get_archive_operations(operations={"filter": "delete", "op": "like"})

        assert len(operations) == 1
        assert "cannot be purged while moving payloads to trash" in operations[0].message

    def test_recover_files_from_trash_can_select_by_trash_uuid(self):
        """
        Recover a trashed file by the pending-removal row UUID.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]

        recovered = self.engine.recover_files_from_trash(file_to_remove_uuids=[queued.file_to_remove_uuid])

        assert len(recovered) == 1
        assert recovered[0].file_uuid == archived_file.file_uuid

    def test_recover_logically_deleted_file_failure_is_recorded(self):
        """
        Record recovery failures for logical-only rows whose payload is missing.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        self.engine.delete_files(file_uuids=[archived_file.file_uuid])
        os.unlink(archived_file.path)

        with self.assertRaises(ArchiveRecoveryError):
            self.engine.recover_files_from_trash(file_uuids=[archived_file.file_uuid])
        operations = self.engine.query.get_archive_operations(operations={"filter": "recover", "op": "like"})

        assert len(operations) == 1
        assert operations[0].status == 13
        assert archived_file.path in operations[0].message

    def test_recover_files_from_trash_records_lookup_failures(self):
        """
        Convert unexpected recovery setup failures into ArchiveRecoveryError.
        """
        original_load_archive_configuration = self.engine._load_archive_configuration

        def fail_load_archive_configuration(configuration_path=None):
            raise ValueError("configuration lookup failed")

        try:
            self.engine._load_archive_configuration = fail_load_archive_configuration
            with self.assertRaises(ArchiveRecoveryError):
                self.engine.recover_files_from_trash()
        finally:
            self.engine._load_archive_configuration = original_load_archive_configuration
        operations = self.engine.query.get_archive_operations(operations={"filter": "recover", "op": "like"})

        assert len(operations) == 1
        assert "configuration lookup failed" in operations[0].message

    def test_record_archive_failures_without_active_root_records_operation_only(self):
        """
        Record archive failures even when no root directory row is available.
        """
        self.engine._record_archive_failures(
            str(self.input_file("sample.txt")),
            str(self.input_file("sample.txt")),
            datetime.datetime.utcnow(),
            datetime.datetime.utcnow(),
            {},
            None,
            [(5, "archive failed without root")],
            None,
        )

        archived_files = self.engine.query.get_archived_files()
        operations = self.engine.query.get_archive_operations(operations={"filter": "archive", "op": "like"})

        assert archived_files == []
        assert len(operations) == 1
        assert operations[0].file_uuid is None

    def test_configuration_and_retention_helper_edge_cases(self):
        """
        Exercise configuration fallback, matching, retention, and duration guards.
        """
        previous_default_archive_path = os.environ.pop("ABOA_DEFAULT_ARCHIVE_PATH", None)
        try:
            with self.assertRaises(ArchiveConfigurationError):
                self.engine._load_archive_configuration(str(self.inputs_path / "does_not_exist.xml"))
        finally:
            if previous_default_archive_path is not None:
                os.environ["ABOA_DEFAULT_ARCHIVE_PATH"] = previous_default_archive_path

        with self.assertRaises(ArchiveConfigurationError):
            self.engine._activate_root_directory(" ")
        assert self.engine._match_configuration("sample.txt") is None
        assert self.engine._retention_policy_for_configuration(None) is None
        with self.assertRaises(ArchiveConfigurationError):
            self.engine._parse_retention_duration("not-a-duration")
        with self.assertRaises(ArchiveConfigurationError):
            self.engine._parse_retention_duration("P")

        reception_date = datetime.datetime(2026, 7, 1, 0, 0, 0)
        archive_date = datetime.datetime(2026, 7, 2, 0, 0, 0)
        retention_nodes = etree.parse(str(self.input_file("engine_retention_policy_nodes.xml")))
        reception_node = retention_nodes.xpath("/archive_configurations/archive_configuration[@file_group='reception_policy']")[0]
        validity_node = retention_nodes.xpath("/archive_configurations/archive_configuration[@file_group='validity_policy']")[0]
        generation_node = retention_nodes.xpath("/archive_configurations/archive_configuration[@file_group='generation_policy']")[0]
        unknown_node = retention_nodes.xpath("/archive_configurations/archive_configuration[@file_group='unknown_policy']")[0]

        assert self.engine._calculate_expiration_date(reception_node, reception_date, archive_date, {}) == reception_date + datetime.timedelta(days=2)
        assert self.engine._calculate_expiration_date(
            validity_node,
            reception_date,
            archive_date,
            {"validity_stop_date": "2026-07-10T00:00:00"},
        ) == datetime.datetime(2026, 7, 13, 0, 0, 0)
        assert self.engine._calculate_expiration_date(generation_node, reception_date, archive_date, {}) is None
        assert self.engine._calculate_expiration_date(unknown_node, reception_date, archive_date, {}) is None

    def test_processor_execution_edge_cases(self):
        """
        Validate processor import, contract, and empty-result behavior.
        """
        inputs_path = str(self.inputs_path)
        inserted_inputs_path = inputs_path not in sys.path
        module_names = ["processor_without_process", "processor_returns_none", "processor_returns_list"]
        try:
            if inserted_inputs_path:
                sys.path.insert(0, inputs_path)
            importlib.invalidate_caches()

            with self.assertRaises(ProcessorError):
                self.engine._execute_processor("processor_does_not_exist", str(self.input_file("sample.txt")))
            with self.assertRaises(ProcessorError):
                self.engine._execute_processor("processor_without_process", str(self.input_file("sample.txt")))
            assert self.engine._execute_processor("processor_returns_none", str(self.input_file("sample.txt"))) == {}
            with self.assertRaises(ProcessorError):
                self.engine._execute_processor("processor_returns_list", str(self.input_file("sample.txt")))
        finally:
            if inserted_inputs_path and inputs_path in sys.path:
                sys.path.remove(inputs_path)
            for module_name in module_names:
                sys.modules.pop(module_name, None)

    def test_archive_path_and_duplicate_helper_edge_cases(self):
        """
        Build collision-safe archive paths and ignore stale duplicate error rows.
        """
        archive_date = datetime.datetime(2026, 7, 16, 9, 0, 0)
        destination_path = self.engine._build_destination_path(str(self.archive_root), "texts", archive_date, "sample.txt")
        Path(destination_path).write_text("existing")
        collision_path = self.engine._build_destination_path(str(self.archive_root), "texts", archive_date, "sample.txt")
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        stale_error_file = ArchivedFile(
            uuid.uuid4(),
            "sample.txt",
            str(self.archive_root / "error" / "missing.txt"),
            datetime.datetime.utcnow(),
            datetime.datetime.utcnow(),
            0,
            archived_file.rootDirectory,
            available=False,
            physically_available=True,
            checksum="abc123",
        )
        self.engine.session.add(stale_error_file)
        self.engine.session.commit()

        assert collision_path != destination_path
        assert Path(collision_path).name.startswith("sample_")
        assert self.engine._find_existing_duplicate_error_file("sample.txt", None) is None
        assert self.engine._find_existing_duplicate_error_file("sample.txt", "abc123") is None

    def test_delete_input_file_success_noop_and_failure(self):
        """
        Skip deleting archive payloads and record input deletion failures.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        self.engine._delete_input_file(archived_file.path, archived_file)
        original_unlink = engine_module.os.unlink

        def fail_unlink(path):
            raise OSError("cannot delete input")

        try:
            engine_module.os.unlink = fail_unlink
            with self.assertRaises(ArchiveFileError):
                self.engine._delete_input_file(str(self.input_file("sample.txt")), archived_file)
        finally:
            engine_module.os.unlink = original_unlink
        operations = self.engine.query.get_archive_operations(operations={"filter": "archive", "op": "like"})

        assert len(operations) == 1
        assert operations[0].status == 7
        assert "cannot delete input" in operations[0].message

    def test_trash_and_permanent_delete_helper_edge_cases(self):
        """
        Update existing trash rows and delete queued trash payloads permanently.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        root_directory = archived_file.rootDirectory
        old_trash_path = str(self.archive_root / "trash" / "old" / "sample.txt")
        existing_row = FileToBeRemoved(
            uuid.uuid4(),
            archived_file,
            old_trash_path,
            root_directory,
            datetime.datetime.utcnow(),
        )
        self.engine.session.add(existing_row)
        self.engine.session.commit()

        updated_row = self.engine.move_archived_file_to_trash(
            archived_file,
            datetime.datetime(2026, 7, 16, 9, 0, 0),
        )

        assert updated_row.file_to_remove_uuid == existing_row.file_to_remove_uuid
        assert updated_row.path != old_trash_path
        assert os.path.exists(updated_row.path)

        deleted_payload = self.engine.delete_archived_file_permanently(archived_file)
        remaining = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert deleted_payload is True
        assert remaining == []
        assert archived_file.physically_available is False

    def test_permanent_delete_removes_stale_trash_rows_without_payload(self):
        """
        Delete stale trash rows even when the queued trash payload is already gone.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]
        os.unlink(queued.path)

        deleted_payload = self.engine.delete_archived_file_permanently(archived_file)
        remaining = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})

        assert deleted_payload is False
        assert remaining == []
        assert archived_file.physically_available is False

    def test_logical_recovery_filters_and_stale_payloads(self):
        """
        Build logical recovery filters and skip logical rows with missing payloads.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        self.engine.delete_files(file_uuids=[archived_file.file_uuid])
        os.unlink(archived_file.path)

        assert self.engine._build_logical_recovery_filters(file_uuids=[archived_file.file_uuid]) == {
            "available": {"filter": False, "op": "=="},
            "file_uuids": {"filter": [archived_file.file_uuid], "op": "in"},
        }
        assert self.engine._build_logical_recovery_filters() == {
            "available": {"filter": False, "op": "=="},
        }
        assert self.engine._build_logical_recovery_filters(filters={"paths": {"filter": "%", "op": "like"}}) is None
        assert self.engine.get_logically_deleted_recoverable_files(file_uuids=[archived_file.file_uuid]) == []

    def test_recovered_future_expiration_keeps_existing_delete_configuration(self):
        """
        Preserve an already assigned delete configuration for future expirations.
        """
        future_expiration = datetime.datetime(2099, 12, 31, 23, 59, 59)
        archived_file = self.archive_and_get(
            self.input_file("sample.txt"),
            metadata={"expiration_date": future_expiration},
        )
        delete_configuration = archived_file.deleteArchiveConfiguration

        self.engine._refresh_recovered_file_expiration(archived_file, datetime.datetime.utcnow())

        assert archived_file.expiration_date == future_expiration
        assert archived_file.deleteArchiveConfiguration is delete_configuration

    def test_delete_archived_entry_removes_stale_trash_rows(self):
        """
        Purge inventory rows when only stale trash metadata remains.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        file_uuid = archived_file.file_uuid
        self.engine.delete_files(file_uuids=[file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [file_uuid], "op": "in"})[0]
        os.unlink(queued.path)

        purged = self.engine.delete_archived_file_entries(file_uuids=[file_uuid])
        remaining_files = self.engine.query.get_archived_files(file_uuids={"filter": [file_uuid], "op": "in"})
        remaining_trash = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [file_uuid], "op": "in"})

        assert len(purged) == 1
        assert remaining_files == []
        assert remaining_trash == []

    def test_trash_path_and_recovery_guard_edge_cases(self):
        """
        Build collision-safe trash paths and reject unsafe recovery inputs.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        removal_date = datetime.datetime(2026, 7, 16, 9, 0, 0)
        trash_path = self.engine._build_trash_path(str(self.archive_root), removal_date, archived_file)
        Path(trash_path).write_text("existing")
        collision_path = self.engine._build_trash_path(str(self.archive_root), removal_date, archived_file)

        assert collision_path.endswith("sample_{}.txt".format(archived_file.file_uuid))

        self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]
        Path(archived_file.path).parent.mkdir(parents=True, exist_ok=True)
        Path(archived_file.path).write_text("conflicting archive payload")
        with self.assertRaises(ArchiveRecoveryError):
            self.engine._recover_file_from_trash(queued)

    def test_recover_file_from_trash_handles_flat_archive_path(self):
        """
        Recover a trash payload to an archive path without a directory component.
        """
        self.archive_and_get(self.input_file("sample.txt"))
        root_directory = self.engine.query.get_active_root_directory()
        archive_path = Path("flat_recover.txt")
        trash_root = Path(tempfile.mkdtemp(prefix="aboa_engine_flat_recover_"))
        trash_path = trash_root / "flat_recover.txt"
        shutil.copy2(str(self.input_file("flat_recover.txt")), str(trash_path))
        archived_file = ArchivedFile(
            uuid.uuid4(),
            "flat_recover.txt",
            str(archive_path),
            datetime.datetime.utcnow(),
            datetime.datetime.utcnow(),
            0,
            root_directory,
            available=False,
            physically_available=True,
        )
        trash_row = FileToBeRemoved(uuid.uuid4(), archived_file, str(trash_path), root_directory, datetime.datetime.utcnow())
        self.engine.session.add(archived_file)
        self.engine.session.add(trash_row)
        self.engine.session.commit()
        try:
            recovered = self.engine._recover_file_from_trash(trash_row)

            assert recovered.path == str(archive_path)
            assert archive_path.read_text() == self.input_file("flat_recover.txt").read_text()
            assert recovered.available is True
        finally:
            if archive_path.exists():
                archive_path.unlink()
            shutil.rmtree(str(trash_root), ignore_errors=True)

    def test_logical_recovery_guard_edge_cases(self):
        """
        Reject invalid logical recovery requests before mutating inventory.
        """
        available_file = self.archive_and_get(self.input_file("sample.txt"))
        with self.assertRaises(ArchiveRecoveryError):
            self.engine._recover_logically_deleted_file(available_file)

        self.engine.delete_files(file_uuids=[available_file.file_uuid], physical_delete=True)
        with self.assertRaises(ArchiveRecoveryError):
            self.engine._recover_logically_deleted_file(available_file)

        missing_payload_file = self.archive_and_get(self.input_file("query_a.txt"))
        self.engine.delete_files(file_uuids=[missing_payload_file.file_uuid])
        os.unlink(missing_payload_file.path)
        with self.assertRaises(ArchiveRecoveryError):
            self.engine._recover_logically_deleted_file(missing_payload_file)
