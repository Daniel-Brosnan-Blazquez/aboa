"""
Tests for archived-file query filters, ordering, grouping, and validation.
"""

import datetime
import shutil
import unittest
import uuid
from pathlib import Path

from aboa.datamodel.archived_files import ArchiveOperation
from aboa.engine.engine import Engine
from aboa.engine.errors import InputError
from aboa.engine.query import Query


class TestQuery(unittest.TestCase):
    """
    Integration tests for the inventory query facade.
    """

    def setUp(self):
        """
        Prepare a clean inventory and fixture-backed archive roots.
        """
        # Query tests create real archived-file rows through Engine so Query is
        # exercised against the same data shape production code writes.
        query = Query()
        query.clear_db()
        query.close_session()
        self.inputs_path = Path(__file__).parent / "inputs"
        self.archive_root = Path("/tmp/aboa_test_query_archive")
        self.second_archive_root = Path("/tmp/aboa_test_query_archive_changed")
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        shutil.rmtree(str(self.second_archive_root), ignore_errors=True)
        self.configuration_file = str(self.inputs_path / "query_archive_configuration.xml")
        self.engine = Engine()
        self.engine.set_configuration_path(self.configuration_file)

    def tearDown(self):
        """
        Clear persisted rows and remove temporary filesystem state.
        """
        self.engine.close_session()
        query = Query()
        query.clear_db()
        query.close_session()
        shutil.rmtree(str(self.archive_root), ignore_errors=True)
        shutil.rmtree(str(self.second_archive_root), ignore_errors=True)

    def input_file(self, name):
        """
        Return a fixture input path by file name.
        """
        return self.inputs_path / name

    def test_query_archived_files_filters_selection_grouping_and_pagination(self):
        """
        Combine text filters, ordering, grouping, selection, and limits.
        """
        first = self.input_file("query_a.txt")
        second = self.input_file("query_b.txt")
        self.engine.archive_file(str(first), metadata={"file_type": "text"})
        self.engine.archive_file(str(second), metadata={"file_type": "text"})

        query = Query(session=self.engine.session)
        # The two fixtures differ in size, which makes order and selection assertions
        # deterministic without depending on database insertion order.
        files = query.get_archived_files(names={"filter": "%.txt", "op": "like"}, order_by={"field": "file_size", "descending": True}, limit=1)
        grouped = query.get_archived_files(group_by="file_group")
        last = query.get_archived_files(selection="last", order_by={"field": "file_size", "descending": False})
        archive_configuration = query.get_active_archive_configuration()
        configuration_files = query.get_archived_files(archive_configuration_uuids={"filter": [archive_configuration.archive_configuration_uuid], "op": "in"})
        root_directory_files = query.get_archived_files(root_directory_uuids={"filter": [configuration_files[0].root_directory_uuid], "op": "in"})
        checksum_files = query.get_archived_files(checksum={"filter": configuration_files[0].checksum, "op": "like"})
        physical_files = query.get_archived_files(physically_available={"filter": True, "op": "=="})
        self.engine.delete_files(file_uuids=[configuration_files[0].file_uuid])
        removed_files = query.get_archived_files(removal_justification={"filter": "manual_delete", "op": "like"})

        assert len(files) == 1
        assert files[0].name == "query_b.txt"
        assert "group_a" in grouped
        assert last[0].name == "query_b.txt"
        assert len(configuration_files) == 2
        assert len(root_directory_files) == 2
        assert len(checksum_files) == 1
        assert len(physical_files) == 2
        assert len(removed_files) == 1
        assert removed_files[0].removal_justification == "manual_delete"

    def test_query_archived_files_rejects_invalid_order_field(self):
        """
        Reject order descriptors for fields outside the explicit allow-list.
        """
        query = Query(session=self.engine.session)
        with self.assertRaises(InputError):
            query.get_archived_files(order_by={"field": "wrong", "descending": False})

    def test_query_archive_root_directories_filters_selection_grouping_and_pagination(self):
        """
        Query archive root-directory history using the public query facade.
        """
        second_configuration_file = str(self.inputs_path / "query_archive_changed_root_configuration.xml")
        self.engine.archive_file(str(self.input_file("root_change_first.txt")), metadata={"file_type": "text"})
        self.engine.set_configuration_path(second_configuration_file)
        self.engine.archive_file(str(self.input_file("root_change_second.txt")), metadata={"file_type": "text"})

        query = Query(session=self.engine.session)
        active_roots = query.get_archive_root_directories(
            paths={"filter": str(self.second_archive_root), "op": "like"},
            active={"filter": True, "op": "=="},
            limit=1,
        )
        inactive_roots = query.get_archive_root_directories(active={"filter": False, "op": "=="})
        grouped = query.get_archive_root_directories(group_by="active")
        last = query.get_archive_root_directories(selection="last", order_by={"field": "path", "descending": False})

        assert len(active_roots) == 1
        assert active_roots[0].path == str(self.second_archive_root)
        assert len(inactive_roots) == 1
        assert inactive_roots[0].path == str(self.archive_root)
        assert True in grouped
        assert False in grouped
        assert last[0].path == str(self.second_archive_root)

    def test_query_archive_configurations_filters_selection_grouping_and_pagination(self):
        """
        Query archive-configuration history using the public query facade.
        """
        second_configuration_file = str(self.inputs_path / "query_archive_changed_root_configuration.xml")
        self.engine._load_archive_configuration(self.configuration_file)
        self.engine.set_configuration_path(second_configuration_file)
        self.engine._load_archive_configuration(second_configuration_file)

        query = Query(session=self.engine.session)
        active_configurations = query.get_archive_configurations(
            paths={"filter": second_configuration_file, "op": "like"},
            active={"filter": True, "op": "=="},
            limit=1,
        )
        inactive_configurations = query.get_archive_configurations(active={"filter": False, "op": "=="})
        content_matches = query.get_archive_configurations(contents={"filter": "%aboa_test_query_archive_changed%", "op": "like"})
        grouped = query.get_archive_configurations(group_by="active")
        last = query.get_archive_configurations(selection="last", order_by={"field": "active", "descending": False})

        assert len(active_configurations) == 1
        assert active_configurations[0].path == second_configuration_file
        assert len(inactive_configurations) == 1
        assert inactive_configurations[0].path == self.configuration_file
        assert len(content_matches) == 1
        assert True in grouped
        assert False in grouped
        assert last[0].path == second_configuration_file

    def test_query_archive_operations_filters_selection_grouping_and_pagination(self):
        """
        Query persisted archive operation failures using the public query facade.
        """
        input_file = self.input_file("query_operation.txt")
        self.engine.archive_file(str(input_file), metadata={"file_type": "text"})
        archived_file = self.engine.query.get_archived_files(names={"filter": "query_operation.txt", "op": "like"})[0]
        retrieve_operation = ArchiveOperation(
            uuid.uuid4(),
            "retrieve",
            datetime.datetime(2026, 7, 2, 10, 0, 0),
            9,
            message="retrieval failed",
            archived_file=archived_file,
        )
        delete_operation = ArchiveOperation(
            uuid.uuid4(),
            "delete",
            datetime.datetime(2026, 7, 2, 10, 5, 0),
            8,
            message="deletion failed",
        )
        self.engine.session.add(retrieve_operation)
        self.engine.session.add(delete_operation)
        self.engine.session.commit()

        query = Query(session=self.engine.session)
        operations = query.get_archive_operations(
            operations={"filter": "retrieve", "op": "like"},
            messages={"filter": "%failed", "op": "like"},
            file_uuids={"filter": [archived_file.file_uuid], "op": "in"},
            status_filters=[{"number": 9, "op": "=="}],
            order_by={"field": "time_stamp", "descending": True},
            limit=1,
        )
        grouped = query.get_archive_operations(group_by="operation")
        last = query.get_archive_operations(selection="last", order_by={"field": "time_stamp", "descending": False})

        assert len(operations) == 1
        assert operations[0].operation == "retrieve"
        assert operations[0].file_uuid == archived_file.file_uuid
        assert "retrieve" in grouped
        assert "delete" in grouped
        assert last[0].operation == "delete"

    def test_query_files_to_be_removed_filters_selection_grouping_and_pagination(self):
        """
        Query trash-queue rows using the public query facade.
        """
        input_file = self.input_file("query_operation.txt")
        self.engine.archive_file(str(input_file), metadata={"file_type": "text"})
        archived_file = self.engine.query.get_archived_files(names={"filter": "query_operation.txt", "op": "like"})[0]
        self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        queued = self.engine.query.get_files_to_be_removed()[0]

        query = Query(session=self.engine.session)
        rows = query.get_files_to_be_removed(
            file_to_remove_uuids={"filter": [queued.file_to_remove_uuid], "op": "in"},
            paths={"filter": "%trash%", "op": "like"},
            root_directory_uuids={"filter": [queued.root_directory_uuid], "op": "in"},
            removal_date_filters=[{"date": queued.removal_date.isoformat(), "op": "<="}],
            order_by={"field": "file_to_remove_uuid", "descending": False},
            limit=1,
        )
        grouped = query.get_files_to_be_removed(group_by="root_directory_uuid")
        last = query.get_files_to_be_removed(selection="last", order_by={"field": "path", "descending": False})

        assert len(rows) == 1
        assert rows[0].file_uuid == archived_file.file_uuid
        assert queued.root_directory_uuid in grouped
        assert last[0].file_uuid == queued.file_uuid

    def test_query_date_number_offsets_default_ordering_and_invalid_controls(self):
        """
        Exercise date, numeric, offset, default ordering, and invalid query controls.
        """
        first = self.input_file("query_a.txt")
        second = self.input_file("query_b.txt")
        self.engine.archive_file(str(first), metadata={"file_type": "text"})
        self.engine.archive_file(str(second), metadata={"file_type": "text"})
        archived_file = self.engine.query.get_archived_files(names={"filter": "query_a.txt", "op": "like"})[0]
        operation = ArchiveOperation(
            uuid.uuid4(),
            "archive",
            datetime.datetime.utcnow(),
            5,
            message="duplicate",
            archived_file=archived_file,
        )
        self.engine.session.add(operation)
        self.engine.delete_files(file_uuids=[archived_file.file_uuid], physical_delete=True)
        self.engine.session.commit()
        queued = self.engine.query.get_files_to_be_removed(file_uuids={"filter": [archived_file.file_uuid], "op": "in"})[0]
        query = Query(session=self.engine.session)
        future = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).isoformat()

        file_rows = query.get_archived_files(
            reception_date_filters=[{"date": future, "op": "<="}],
            file_size_filters=[{"number": 0, "op": ">="}],
            order_by={"field": "name", "descending": False},
            offset=1,
        )
        default_last = query.get_archived_files(selection="last")
        reversed_last = query.get_archived_files(selection="last", order_by={"field": "file_size", "descending": True})
        root_rows = query.get_archive_root_directories(
            active_from_date_filters=[{"date": future, "op": "<="}],
            offset=0,
        )
        configuration_rows = query.get_archive_configurations(
            active_from_date_filters=[{"date": future, "op": "<="}],
            offset=0,
        )
        operation_rows = query.get_archive_operations(
            time_stamp_filters=[{"date": future, "op": "<="}],
            offset=0,
        )
        trash_rows = query.get_files_to_be_removed(
            removal_date_filters=[{"date": queued.removal_date.isoformat(), "op": "=="}],
            offset=0,
        )
        default_reversed_query = query._reverse_query_order(query.session.query(type(default_last[0])), None)

        assert len(file_rows) == 1
        assert default_last[0].file_uuid is not None
        assert reversed_last[0].file_uuid is not None
        assert default_reversed_query.first().file_uuid is not None
        assert len(root_rows) == 1
        assert len(configuration_rows) == 1
        assert len(operation_rows) == 1
        assert len(trash_rows) == 1
        with self.assertRaises(InputError):
            query.get_archived_files(group_by="not_a_field")
        with self.assertRaises(InputError):
            query.get_archived_files(selection="middle")
