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

        assert len(files) == 1
        assert files[0].name == "query_b.txt"
        assert "group_a" in grouped
        assert last[0].name == "query_b.txt"

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
