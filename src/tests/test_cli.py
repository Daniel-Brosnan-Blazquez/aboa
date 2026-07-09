"""
Tests for command-line archive and retrieve entry points.
"""

import contextlib
import io
import json
import shutil
import sys
import unittest
from pathlib import Path

from aboa.engine.commands import aboa_archive, aboa_delete, aboa_recover, aboa_retrieve
from aboa.engine.engine import Engine
from aboa.engine.query import Query


class TestCli(unittest.TestCase):
    """
    Integration tests for CLI commands using captured stdout.
    """

    def setUp(self):
        """
        Prepare a clean inventory and fixture-backed CLI archive roots.
        """
        # CLI commands read sys.argv directly, so each test stores and restores
        # the original arguments to avoid leaking state across the test process.
        query = Query()
        query.clear_db()
        query.close_session()
        self.inputs_path = Path(__file__).parent / "inputs"
        self.archive_root = Path("/tmp/aboa_test_cli_archive")
        self.default_archive_root = Path("/tmp/aboa_archive")
        self.retrieval_root = Path("/tmp/aboa_test_cli_retrieved")
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        shutil.rmtree(str(self.default_archive_root), ignore_errors=True)
        shutil.rmtree(str(self.retrieval_root), ignore_errors=True)
        self.configuration_file = str(self.inputs_path / "cli_archive_configuration.xml")
        self.engine = Engine()
        self.engine.set_configuration_path(self.configuration_file)
        self.argv = sys.argv[:]

    def tearDown(self):
        """
        Restore argv, close sessions, clear rows, and remove temporary files.
        """
        sys.argv = self.argv
        self.engine.close_session()
        query = Query()
        query.clear_db()
        query.close_session()
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        shutil.rmtree(str(self.default_archive_root), ignore_errors=True)
        shutil.rmtree(str(self.retrieval_root), ignore_errors=True)

    def input_file(self, name):
        """
        Return a fixture input path by file name.
        """
        return self.inputs_path / name

    def archive_and_get(self, input_file, **kwargs):
        """
        Archive a fixture and return the persisted inventory row.
        """
        assert self.engine.archive_file(str(input_file), **kwargs) is None
        return self.engine.query.get_archived_files(
            names={"filter": [Path(input_file).name], "op": "in"},
            selection="last",
        )[0]

    def test_cli_archive_and_retrieve(self):
        """
        Archive a file through the CLI and retrieve it through the CLI.
        """
        input_file = self.input_file("sample.txt")

        sys.argv = ["aboa_archive", "--file", str(input_file)]
        archive_stdout = io.StringIO()
        # Commands print JSON to stdout, so the test captures and decodes the
        # command output instead of reading internal engine state directly.
        with contextlib.redirect_stdout(archive_stdout):
            aboa_archive()
        archive_output = json.loads(archive_stdout.getvalue())

        sys.argv = ["aboa_retrieve", "--name", "%.txt"]
        retrieve_stdout = io.StringIO()
        with contextlib.redirect_stdout(retrieve_stdout):
            aboa_retrieve()
        retrieve_output = json.loads(retrieve_stdout.getvalue())

        assert archive_output["name"] == "sample.txt"
        assert len(retrieve_output) == 1

    def test_cli_retrieve_can_list_and_copy_to_destination(self):
        """
        List retrieval candidates without access updates, then copy them to a folder.
        """
        input_file = self.input_file("sample.txt")

        sys.argv = ["aboa_archive", "-f", str(input_file)]
        with contextlib.redirect_stdout(io.StringIO()):
            aboa_archive()

        sys.argv = ["aboa_retrieve", "-n", "%.txt", "-l"]
        list_stdout = io.StringIO()
        with contextlib.redirect_stdout(list_stdout):
            aboa_retrieve()
        list_output = json.loads(list_stdout.getvalue())
        query = Query()
        listed_file = query.get_archived_files(names={"filter": "sample.txt", "op": "like"})[0]
        query.close_session()

        sys.argv = ["aboa_retrieve", "-n", "%.txt", "-d", str(self.retrieval_root)]
        retrieve_stdout = io.StringIO()
        with contextlib.redirect_stdout(retrieve_stdout):
            aboa_retrieve()
        retrieve_output = json.loads(retrieve_stdout.getvalue())
        query = Query()
        retrieved_file = query.get_archived_files(names={"filter": "sample.txt", "op": "like"})[0]
        query.close_session()

        assert len(list_output) == 1
        assert listed_file.last_access_date is None
        assert len(retrieve_output) == 1
        assert (self.retrieval_root / "sample.txt").read_text() == input_file.read_text()
        assert retrieved_file.last_access_date is not None

    def test_cli_delete_can_list_candidates_before_deleting(self):
        """
        List deletion candidates with metadata filters before applying deletion.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)

        sys.argv = ["aboa_delete", "--file-group", "group_a", "--list"]
        list_stdout = io.StringIO()
        with contextlib.redirect_stdout(list_stdout):
            aboa_delete()
        list_output = json.loads(list_stdout.getvalue())
        query = Query()
        listed_file = query.get_archived_files(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]
        query.close_session()

        sys.argv = ["aboa_delete", "--file-group", "group_a", "--reason", "operator_request"]
        delete_stdout = io.StringIO()
        with contextlib.redirect_stdout(delete_stdout):
            aboa_delete()
        delete_output = json.loads(delete_stdout.getvalue())
        query = Query()
        deleted_file = query.get_archived_files(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]
        query.close_session()

        assert len(list_output) == 1
        assert listed_file.available is True
        assert len(delete_output) == 1
        assert deleted_file.available is False
        assert deleted_file.removal_justification == "operator_request"

    def test_cli_recover_from_trash(self):
        """
        Recover a physically deleted file through the CLI.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        file_uuid = archived_file.file_uuid
        archive_path = archived_file.path
        self.engine.delete_files(file_uuids=[file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [file_uuid], "op": "in"})[0]
        trash_path = queued.path
        trash_uuid = queued.file_to_remove_uuid

        sys.argv = ["aboa_recover", "--trash-uuid", str(trash_uuid)]
        recover_stdout = io.StringIO()
        with contextlib.redirect_stdout(recover_stdout):
            aboa_recover()
        recover_output = json.loads(recover_stdout.getvalue())

        assert len(recover_output) == 1
        assert recover_output[0]["file_uuid"] == str(file_uuid)
        assert recover_output[0]["available"] is True
        assert Path(archive_path).exists()
        assert not Path(trash_path).exists()

    def test_cli_recover_can_list_and_filter_by_archived_metadata(self):
        """
        Recover command accepts archived-file metadata filters for candidate lookup.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        archive_path = archived_file.path
        self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]
        trash_path = queued.path

        sys.argv = ["aboa_recover", "--file-group", "group_a", "--list"]
        list_stdout = io.StringIO()
        with contextlib.redirect_stdout(list_stdout):
            aboa_recover()
        list_output = json.loads(list_stdout.getvalue())
        assert Path(trash_path).exists()

        sys.argv = ["aboa_recover", "--file-group", "group_a"]
        recover_stdout = io.StringIO()
        with contextlib.redirect_stdout(recover_stdout):
            aboa_recover()
        recover_output = json.loads(recover_stdout.getvalue())

        assert len(list_output) == 1
        assert list_output[0]["file_uuid"] == str(archived_file.file_uuid)
        assert not Path(trash_path).exists()
        assert len(recover_output) == 1
        assert recover_output[0]["file_uuid"] == str(archived_file.file_uuid)
        assert Path(archive_path).exists()
