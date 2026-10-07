"""
Tests for command-line archive and retrieve entry points.
"""

import contextlib
import argparse
import datetime
import io
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

from aboa.datamodel.archived_files import ArchivedFile, ArchiveRootDirectory, FileToBeRemoved
from aboa.engine import commands as commands_module
from aboa.engine.commands import aboa_archive, aboa_clean_up, aboa_delete, aboa_recover, aboa_retrieve
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

    def test_cli_archive_handles_archive_file_error_without_traceback(self):
        """
        Convert expected archive failures into clean CLI errors.
        """
        missing_file = self.input_file("missing.txt")
        sys.argv = ["aboa_archive.py", "--file", str(missing_file)]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as context:
                aboa_archive()

        assert context.exception.code == 1
        assert str(missing_file) in stderr.getvalue()
        assert "Traceback" not in stderr.getvalue()

    def test_cli_delete_handles_archive_deletion_error_without_traceback(self):
        """
        Convert expected delete failures into clean CLI errors.
        """
        archived_file = self.archive_and_get(self.input_file("sample.txt"))
        sys.argv = ["aboa_delete.py", "--uuid", str(archived_file.file_uuid), "--purge-entry"]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as context:
                aboa_delete()

        assert context.exception.code == 1
        assert "cannot be deleted because its payload is still physically available" in stderr.getvalue()
        assert "Traceback" not in stderr.getvalue()

    def test_cli_archive_and_retrieve(self):
        """
        Archive a file through the CLI and retrieve it through the CLI.
        """
        input_file = self.input_file("sample.txt")

        sys.argv = ["aboa_archive.py", "--file", str(input_file)]
        archive_stdout = io.StringIO()
        # Commands print JSON to stdout, so the test captures and decodes the
        # command output instead of reading internal engine state directly.
        with contextlib.redirect_stdout(archive_stdout):
            aboa_archive()
        archive_output = json.loads(archive_stdout.getvalue())

        sys.argv = ["aboa_retrieve.py", "--name", "%.txt"]
        retrieve_stdout = io.StringIO()
        with contextlib.redirect_stdout(retrieve_stdout):
            aboa_retrieve()
        retrieve_output = json.loads(retrieve_stdout.getvalue())

        assert archive_output["name"] == "sample.txt"
        assert len(retrieve_output) == 1

    def test_cli_archive_accepts_expiration_date(self):
        """
        Archive command accepts an explicit expiration date metadata value.
        """
        input_file = self.input_file("sample.txt")

        sys.argv = [
            "aboa_archive.py",
            "--file",
            str(input_file),
            "--expiration-date",
            "2099-12-31T23:59:59",
        ]
        archive_stdout = io.StringIO()
        with contextlib.redirect_stdout(archive_stdout):
            aboa_archive()
        archive_output = json.loads(archive_stdout.getvalue())

        assert archive_output["expiration_date"] == "2099-12-31T23:59:59"
        assert archive_output["delete_archive_configuration_uuid"] is not None

    def test_cli_archive_rejects_non_future_expiration_date(self):
        """
        Archive command rejects explicit expiration dates that are not future.
        """
        input_file = self.input_file("sample.txt")

        sys.argv = [
            "aboa_archive.py",
            "--file",
            str(input_file),
            "--expiration-date",
            "2000-01-01T00:00:00",
        ]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as context:
                aboa_archive()
        archived_files = self.engine.query.get_archived_files()

        assert context.exception.code == 2
        assert "must be in the future" in stderr.getvalue()
        assert archived_files == []

    def test_cli_retrieve_can_list_and_copy_to_destination(self):
        """
        List retrieval candidates without access updates, then copy them to a folder.
        """
        input_file = self.input_file("sample.txt")

        sys.argv = ["aboa_archive.py", "-f", str(input_file)]
        with contextlib.redirect_stdout(io.StringIO()):
            aboa_archive()

        sys.argv = ["aboa_retrieve.py", "-n", "%.txt", "-l"]
        list_stdout = io.StringIO()
        with contextlib.redirect_stdout(list_stdout):
            aboa_retrieve()
        list_output = json.loads(list_stdout.getvalue())
        query = Query()
        listed_file = query.get_archived_files(names={"filter": "sample.txt", "op": "like"})[0]
        query.close_session()

        sys.argv = ["aboa_retrieve.py", "-n", "%.txt", "-d", str(self.retrieval_root)]
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

        sys.argv = ["aboa_delete.py", "--file-group", "group_a", "--list"]
        list_stdout = io.StringIO()
        with contextlib.redirect_stdout(list_stdout):
            aboa_delete()
        list_output = json.loads(list_stdout.getvalue())
        query = Query()
        listed_file = query.get_archived_files(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]
        query.close_session()

        sys.argv = ["aboa_delete.py", "--file-group", "group_a", "--reason", "operator_request"]
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

    def test_cli_short_aliases_cover_physical_availability_and_permanent_purge(self):
        """
        Use short aliases for physical availability, permanent delete, and purge.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        file_uuid = archived_file.file_uuid
        archive_path = archived_file.path

        sys.argv = ["aboa_retrieve.py", "-u", str(file_uuid), "-B", "true", "-l"]
        list_stdout = io.StringIO()
        with contextlib.redirect_stdout(list_stdout):
            aboa_retrieve()
        list_output = json.loads(list_stdout.getvalue())

        sys.argv = ["aboa_delete.py", "-u", str(file_uuid), "-D", "-I"]
        delete_stdout = io.StringIO()
        with contextlib.redirect_stdout(delete_stdout):
            aboa_delete()
        delete_output = json.loads(delete_stdout.getvalue())
        remaining = self.engine.query.get_archived_files(file_uuids={"filter": [file_uuid], "op": "in"})

        assert len(list_output) == 1
        assert list_output[0]["file_uuid"] == str(file_uuid)
        assert len(delete_output) == 1
        assert delete_output[0]["file_uuid"] == str(file_uuid)
        assert remaining == []
        assert not Path(archive_path).exists()

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

        sys.argv = ["aboa_recover.py", "--trash-uuid", str(trash_uuid)]
        recover_stdout = io.StringIO()
        with contextlib.redirect_stdout(recover_stdout):
            aboa_recover()
        recover_output = json.loads(recover_stdout.getvalue())

        assert len(recover_output) == 1
        assert recover_output[0]["file_uuid"] == str(file_uuid)
        assert recover_output[0]["available"] == "True"
        assert Path(archive_path).exists()
        assert not Path(trash_path).exists()

    def test_cli_recover_logically_deleted_file(self):
        """
        Recover a logical-only deleted file through the CLI.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        file_uuid = archived_file.file_uuid
        archive_path = archived_file.path
        self.engine.delete_files(file_uuids=[file_uuid])

        sys.argv = ["aboa_recover.py", "--uuid", str(file_uuid), "--list"]
        list_stdout = io.StringIO()
        with contextlib.redirect_stdout(list_stdout):
            aboa_recover()
        list_output = json.loads(list_stdout.getvalue())

        sys.argv = ["aboa_recover.py", "--uuid", str(file_uuid)]
        recover_stdout = io.StringIO()
        with contextlib.redirect_stdout(recover_stdout):
            aboa_recover()
        recover_output = json.loads(recover_stdout.getvalue())
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [file_uuid], "op": "in"})

        assert len(list_output) == 1
        assert list_output[0]["file_uuid"] == str(file_uuid)
        assert list_output[0]["available"] == "False"
        assert len(recover_output) == 1
        assert recover_output[0]["file_uuid"] == str(file_uuid)
        assert recover_output[0]["available"] == "True"
        assert Path(archive_path).exists()
        assert queued == []

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

        sys.argv = ["aboa_recover.py", "--file-group", "group_a", "--list"]
        list_stdout = io.StringIO()
        with contextlib.redirect_stdout(list_stdout):
            aboa_recover()
        list_output = json.loads(list_stdout.getvalue())
        assert Path(trash_path).exists()

        sys.argv = ["aboa_recover.py", "--file-group", "group_a"]
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

    def test_cli_clean_up_can_empty_trash_immediately(self):
        """
        Empty all queued trash payloads through the clean-up CLI.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        file_uuid = archived_file.file_uuid
        self.engine.delete_files(file_uuids=[file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [file_uuid], "op": "in"})[0]
        trash_path = queued.path
        trash_uuid = queued.file_to_remove_uuid

        sys.argv = ["aboa_clean_up.py", "--empty-trash"]
        cleanup_stdout = io.StringIO()
        with contextlib.redirect_stdout(cleanup_stdout):
            aboa_clean_up()
        cleanup_output = json.loads(cleanup_stdout.getvalue())
        query = Query()
        remaining = query.get_files_to_be_removed(file_uuids={"filter": [file_uuid], "op": "in"})
        refreshed_file = query.get_archived_files(file_uuids={"filter": [file_uuid], "op": "in"})[0]
        query.close_session()

        assert len(cleanup_output) == 1
        assert cleanup_output[0]["file_to_remove_uuid"] == str(trash_uuid)
        assert remaining == []
        assert refreshed_file.physically_available is False
        assert not Path(trash_path).exists()

    def test_cli_clean_up_runs_retention_when_final_removal_is_not_requested(self):
        """
        Run normal retention cleanup through the clean-up CLI.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(
            input_file,
            metadata={"expiration_date": datetime.datetime.utcnow() - datetime.timedelta(days=1)},
        )

        sys.argv = ["aboa_clean_up.py"]
        cleanup_stdout = io.StringIO()
        with contextlib.redirect_stdout(cleanup_stdout):
            aboa_clean_up()
        cleanup_output = json.loads(cleanup_stdout.getvalue())
        query = Query()
        refreshed_file = query.get_archived_files(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]
        query.close_session()

        assert len(cleanup_output) == 1
        assert cleanup_output[0]["file_uuid"] == str(archived_file.file_uuid)
        assert refreshed_file.available is False
        assert refreshed_file.removal_justification == "retention_policy"

    def test_cli_helper_parsers_build_filters_and_json_payloads(self):
        """
        Exercise CLI parser helpers for typed filters and grouped JSON output.
        """
        class JsonifiableRow:
            def __init__(self, file_uuid):
                self.file_uuid = file_uuid

            def jsonify(self):
                return {"file_uuid": self.file_uuid}

        grouped_rows = {"group_a": [JsonifiableRow("file-1")]}
        archived_parser = argparse.ArgumentParser()
        commands_module._add_archived_file_filter_arguments(archived_parser)
        archived_args = archived_parser.parse_args([
            "--reception-date",
            ">=:2026-07-16T00:00:00",
            "--file-size",
            "<:10.5",
            "--available",
            "false",
        ])
        trash_parser = argparse.ArgumentParser()
        commands_module._add_trash_filter_arguments(trash_parser)
        trash_args = trash_parser.parse_args(["--trash-removal-date", "<=:2026-07-17T00:00:00"])
        order_args = argparse.Namespace(order_by="archive_date", descending=True)
        aware_datetime = commands_module._parse_datetime_argument("2026-07-16T12:30:00+02:00")

        assert commands_module._jsonify_rows(grouped_rows) == {"group_a": [{"file_uuid": "file-1"}]}
        assert commands_module._parse_arithmetic_filter(">=:2026-07-16", "date") == {
            "op": ">=",
            "date": "2026-07-16",
        }
        assert commands_module._parse_number_filter("42") == {"op": "==", "number": 42}
        assert commands_module._parse_number_filter("<:10.5") == {"op": "<", "number": 10.5}
        assert commands_module._parse_bool_filter("!=:no") == {"op": "!=", "filter": False}
        assert aware_datetime == datetime.datetime(2026, 7, 16, 10, 30, 0)
        assert commands_module._build_archived_file_filters(archived_args, archived_parser) == {
            "reception_date_filters": [{"op": ">=", "date": "2026-07-16T00:00:00"}],
            "file_size_filters": [{"op": "<", "number": 10.5}],
            "available": {"op": "==", "filter": False},
        }
        assert commands_module._build_trash_filters(trash_args, trash_parser) == {
            "removal_date_filters": [{"op": "<=", "date": "2026-07-17T00:00:00"}],
        }
        assert commands_module._build_order_by(order_args) == {"field": "archive_date", "descending": True}

        with self.assertRaises(argparse.ArgumentTypeError):
            commands_module._parse_arithmetic_filter(">=", "date")
        with self.assertRaises(argparse.ArgumentTypeError):
            commands_module._parse_number_filter("not-a-number")
        with self.assertRaises(argparse.ArgumentTypeError):
            commands_module._parse_bool_filter("maybe")
        with self.assertRaises(argparse.ArgumentTypeError):
            commands_module._parse_datetime_argument("not-a-date")

    def test_cli_text_filter_rejects_repeated_values_for_scalar_operator(self):
        """
        Reject repeated text filters unless the operator accepts lists.
        """
        parser = argparse.ArgumentParser()
        commands_module._add_archived_file_filter_arguments(parser)
        args = parser.parse_args(["--name", "a.txt", "--name", "b.txt", "--name-op", "like"])

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                commands_module._build_archived_file_filters(args, parser)

    def test_recover_candidate_json_deduplicates_archived_files(self):
        """
        Serialize each recoverable archived file only once.
        """
        now = datetime.datetime.utcnow()
        root_directory = ArchiveRootDirectory(uuid.uuid4(), str(self.archive_root), now)
        first = ArchivedFile(uuid.uuid4(), "file-1.txt", "/tmp/file-1.txt", now, now, 1, root_directory)
        second = ArchivedFile(uuid.uuid4(), "file-2.txt", "/tmp/file-2.txt", now, now, 1, root_directory)

        payload = commands_module._jsonify_recover_candidates(
            [
                FileToBeRemoved(uuid.uuid4(), first, "/tmp/trash/file-1.txt", root_directory, now),
                FileToBeRemoved(uuid.uuid4(), first, "/tmp/trash/file-1-copy.txt", root_directory, now),
            ],
            logical_files=[first, second],
        )

        assert payload == [first.jsonify(), second.jsonify()]

    def test_cli_delete_rejects_conflicting_or_missing_filters(self):
        """
        Reject delete invocations with conflicting modes or no selector.
        """
        for argv, message in (
            (["aboa_delete.py", "--uuid", "file-1", "--physical", "--permanent"], "--physical and --permanent"),
            (["aboa_delete.py", "--uuid", "file-1", "--physical", "--purge-entry"], "--physical and --purge-entry"),
            (["aboa_delete.py"], "at least one archived-file filter is required"),
        ):
            with self.subTest(argv=argv):
                sys.argv = argv
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as context:
                        aboa_delete()

                assert context.exception.code == 2
                assert message in stderr.getvalue()

    def test_cli_recover_rejects_missing_filters(self):
        """
        Require a recover selector unless listing candidates.
        """
        sys.argv = ["aboa_recover.py"]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as context:
                aboa_recover()

        assert context.exception.code == 2
        assert "at least one archived-file or trash filter is required" in stderr.getvalue()

    def test_cli_recover_handles_recovery_error_without_traceback(self):
        """
        Convert expected recovery failures into clean CLI errors.
        """
        input_file = self.input_file("sample.txt")
        archived_file = self.archive_and_get(input_file)
        self.engine.delete_files(file_uuids=[archived_file.file_uuid])
        Path(archived_file.path).unlink()

        sys.argv = ["aboa_recover.py", "--uuid", str(archived_file.file_uuid)]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as context:
                aboa_recover()

        assert context.exception.code == 1
        assert "does not exist" in stderr.getvalue()
        assert "Traceback" not in stderr.getvalue()
