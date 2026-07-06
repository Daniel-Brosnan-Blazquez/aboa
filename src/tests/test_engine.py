import os
import shutil
import sys
import unittest
from pathlib import Path

from aboa.datamodel.archived_files import ArchivedFile, ArchiveOperation, ArchiveRootDirectory
from aboa.engine.engine import Engine
from aboa.engine.errors import ArchiveFileError
from aboa.engine.query import Query


class TestEngine(unittest.TestCase):
    def setUp(self):
        query = Query()
        query.clear_db()
        query.close_session()
        self.inputs_path = Path(__file__).parent / "inputs"
        self.archive_root = Path("/tmp/aboa_test_engine_archive")
        self.second_archive_root = Path("/tmp/aboa_test_engine_archive_changed")
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        shutil.rmtree(str(self.second_archive_root), ignore_errors=True)
        self.archive_root.mkdir()
        self.second_archive_root.mkdir()
        self.configuration_file = str(self.inputs_path / "engine_archive_configuration.xml")
        self.engine = Engine()
        self.engine._load_archive_configuration(self.configuration_file)

    def tearDown(self):
        self.engine.close_session()
        query = Query()
        query.close_session()
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        shutil.rmtree(str(self.second_archive_root), ignore_errors=True)

    def input_file(self, name):
        return self.inputs_path / name

    def test_archive_matching_file(self):
        input_file = self.input_file("sample.txt")

        archived_file = self.engine.archive_file(str(input_file))

        assert archived_file.file_group == "group_a"
        assert os.path.exists(archived_file.path)
        path_parts = archived_file.path.split(os.sep)
        assert "texts" in path_parts
        assert path_parts[-4:-1] == [
            archived_file.archive_date.strftime("%Y"),
            archived_file.archive_date.strftime("%m"),
            archived_file.archive_date.strftime("%d"),
        ]
        assert archived_file.file_size == os.path.getsize(input_file)

    def test_archive_unmatched_file_goes_to_unknown(self):
        input_file = self.input_file("sample.bin")

        archived_file = self.engine.archive_file(str(input_file))

        assert archived_file.file_group == "unknown"
        assert "unknown" in archived_file.path.split(os.sep)

    def test_changing_root_directory_archives_without_restart(self):
        first_input = self.input_file("root_change_first.txt")
        second_input = self.input_file("root_change_second.txt")
        second_configuration = self.input_file("engine_archive_changed_root_configuration.xml")

        first_archive = self.engine.archive_file(str(first_input))
        self.engine._load_archive_configuration(str(second_configuration))
        second_archive = self.engine.archive_file(str(second_input))

        assert os.path.exists(first_archive.path)
        assert os.path.exists(second_archive.path)
        assert os.path.commonpath([str(self.archive_root), first_archive.path]) == str(self.archive_root)
        assert os.path.commonpath([str(self.second_archive_root), second_archive.path]) == str(self.second_archive_root)
        assert os.path.commonpath([str(self.second_archive_root), first_archive.path]) != str(self.second_archive_root)
        assert os.path.commonpath([str(self.archive_root), second_archive.path]) != str(self.archive_root)

    def test_archive_file_reloads_configuration_and_repairs_stale_root_directory(self):
        input_file = self.input_file("root_change_first.txt")
        stale_root_directory = self.engine.query.get_active_root_directory()
        stale_root_directory.path = str(self.second_archive_root)
        self.engine.archive_xpath = None
        self.engine.session.commit()

        archived_file = self.engine.archive_file(str(input_file))
        active_root_directory = self.engine.query.get_active_root_directory()
        active_root_directories = self.engine.session.query(ArchiveRootDirectory).filter(ArchiveRootDirectory.active == True).all()

        assert active_root_directory.path == str(self.archive_root)
        assert archived_file.rootDirectory.path == str(self.archive_root)
        assert os.path.commonpath([str(self.archive_root), archived_file.path]) == str(self.archive_root)
        assert len(active_root_directories) == 1

    def test_archive_processor_metadata(self):
        inputs_path = str(self.inputs_path)
        if inputs_path not in sys.path:
            sys.path.insert(0, inputs_path)
        configuration = self.inputs_path / "engine_metadata_configuration.xml"
        engine = Engine()
        engine._load_archive_configuration(str(configuration))
        input_file = self.input_file("sample.txt")

        archived_file = engine.archive_file(str(input_file))

        assert archived_file.file_type == "text"
        assert archived_file.file_class == "AUX"
        assert archived_file.file_version == "1.0"
        assert archived_file.generation_date.isoformat() == "2026-07-01T12:00:00"
        engine.close_session()

    def test_archive_processor_failure_goes_to_error(self):
        inputs_path = str(self.inputs_path)
        if inputs_path not in sys.path:
            sys.path.insert(0, inputs_path)
        configuration = self.inputs_path / "engine_failure_configuration.xml"
        engine = Engine()
        engine._load_archive_configuration(str(configuration))
        input_file = self.input_file("sample.txt")

        archived_file = engine.archive_file(str(input_file))
        operations = engine.session.query(ArchiveOperation).all()

        assert "error" in archived_file.path.split(os.sep)
        assert len(operations) == 1
        assert operations[0].file_uuid == archived_file.file_uuid
        engine.close_session()

    def test_archive_missing_file_records_failure_with_archived_file(self):
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

    def test_delete_logical_and_physical(self):
        input_file = self.input_file("sample.txt")
        archived_file = self.engine.archive_file(str(input_file))

        deleted = self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)

        assert deleted[0].available is False
        assert deleted[0].removal_date is not None
        assert not os.path.exists(deleted[0].path)
