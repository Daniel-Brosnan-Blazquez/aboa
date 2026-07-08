"""
Tests for archive inventory SQLAlchemy models and JSON serialization.
"""

import datetime
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from aboa.datamodel.archived_files import ArchiveConfiguration, ArchivedFile, ArchiveOperation, ArchiveRootDirectory
from aboa.engine.query import Query


class TestDatamodel(unittest.TestCase):
    """
    Unit and persistence tests for archived file, root, and operation models.
    """

    def setUp(self):
        """
        Prepare a clean inventory and a reusable root-directory model.
        """
        query = Query()
        query.clear_db()
        query.close_session()
        # Most model tests can serialize objects without persistence, but they all
        # need a root-directory relationship object to mirror production rows.
        self.test_root = Path(tempfile.mkdtemp(prefix="aboa_test_"))
        self.root_directory = ArchiveRootDirectory(uuid.uuid4(), "/tmp/archive", datetime.datetime(2026, 7, 2), active=True)
        self.archive_configuration = ArchiveConfiguration(
            uuid.uuid4(),
            "/tmp/config/archive_configurations.xml",
            datetime.datetime(2026, 7, 2, 9, 0, 0),
            """<archive_configurations root_directory="/tmp/archive"/>""",
        )
        self.delete_archive_configuration = ArchiveConfiguration(
            uuid.uuid4(),
            "/tmp/config/delete_archive_configurations.xml",
            datetime.datetime(2026, 7, 3, 9, 0, 0),
            """<archive_configurations root_directory="/tmp/archive"><retention_policies/></archive_configurations>""",
        )

    def tearDown(self):
        """
        Clear persisted rows and remove temporary filesystem state.
        """
        self.root_directory = None
        query = Query()
        query.clear_db()
        query.close_session()
        shutil.rmtree(str(self.test_root), ignore_errors=True)

    def test_archived_file_jsonify(self):
        """
        Serialize all archived-file fields into JSON-ready values.
        """
        query = Query()
        file_uuid = uuid.uuid4()
        archived_file = ArchivedFile(
            file_uuid,
            "sample.txt",
            "/tmp/archive/texts/2026/07/02/sample.txt",
            datetime.datetime(2026, 7, 2, 10, 0, 0),
            datetime.datetime(2026, 7, 2, 10, 1, 0),
            10,
            self.root_directory,
            archive_configuration=self.archive_configuration,
            delete_archive_configuration=self.delete_archive_configuration,
            available=False,
            last_access_date=datetime.datetime(2026, 7, 2, 10, 2, 0),
            file_group="group_a",
            file_type="text",
            file_class="AUX",
            file_version="1.0",
            validity_start_date=datetime.datetime(2026, 7, 2, 0, 0, 0),
            validity_stop_date=datetime.datetime(2026, 7, 3, 0, 0, 0),
            generation_date=datetime.datetime(2026, 7, 1, 12, 0, 0),
            expiration_date=datetime.datetime(2026, 7, 10, 0, 0, 0),
            removal_date=datetime.datetime(2026, 7, 4, 0, 0, 0),
            removal_justification="retention:default",
            checksum="abc123",
        )

        query.session.add(self.root_directory)
        query.session.add(self.archive_configuration)
        query.session.add(self.delete_archive_configuration)
        query.session.add(archived_file)
        query.session.commit()

        structure = archived_file.jsonify()

        # Datetimes are expected as ISO strings and identifiers as text so the CLI
        # can emit JSON directly from jsonify results.
        assert structure["file_uuid"] == str(file_uuid)
        assert structure["name"] == "sample.txt"
        assert structure["path"] == "/tmp/archive/texts/2026/07/02/sample.txt"
        assert structure["reception_date"] == "2026-07-02T10:00:00"
        assert structure["file_group"] == "group_a"
        assert structure["file_type"] == "text"
        assert structure["archive_date"] == "2026-07-02T10:01:00"
        assert structure["file_size"] == 10
        assert structure["available"] is False
        assert structure["archive_configuration_uuid"] == str(self.archive_configuration.archive_configuration_uuid)
        assert structure["delete_archive_configuration_uuid"] == str(self.delete_archive_configuration.archive_configuration_uuid)
        assert structure["last_access_date"] == "2026-07-02T10:02:00"
        assert structure["file_class"] == "AUX"
        assert structure["file_version"] == "1.0"
        assert structure["validity_start_date"] == "2026-07-02T00:00:00"
        assert structure["validity_stop_date"] == "2026-07-03T00:00:00"
        assert structure["generation_date"] == "2026-07-01T12:00:00"
        assert structure["expiration_date"] == "2026-07-10T00:00:00"
        assert structure["removal_date"] == "2026-07-04T00:00:00"
        assert structure["removal_justification"] == "retention:default"
        assert structure["checksum"] == "abc123"
        
        query.close_session()

    def test_archived_file_jsonify_handles_optional_values(self):
        """
        Serialize missing optional archived-file metadata as null values.
        """
        archived_file = ArchivedFile(
            uuid.uuid4(),
            "sample.txt",
            "/tmp/archive/texts/2026/07/02/sample.txt",
            datetime.datetime(2026, 7, 2, 10, 0, 0),
            datetime.datetime(2026, 7, 2, 10, 1, 0),
            10,
            self.root_directory,
        )

        structure = archived_file.jsonify()

        assert structure["available"] is True
        assert structure["archive_configuration_uuid"] is None
        assert structure["delete_archive_configuration_uuid"] is None
        assert structure["last_access_date"] is None
        assert structure["file_group"] is None
        assert structure["file_type"] is None
        assert structure["file_class"] is None
        assert structure["file_version"] is None
        assert structure["validity_start_date"] is None
        assert structure["validity_stop_date"] is None
        assert structure["generation_date"] is None
        assert structure["expiration_date"] is None
        assert structure["removal_date"] is None
        assert structure["removal_justification"] is None
        assert structure["checksum"] is None

    def test_archive_root_directory_jsonify(self):
        """
        Serialize archive root-directory history rows.
        """
        root_uuid = uuid.uuid4()
        root_directory = ArchiveRootDirectory(
            root_uuid,
            "/tmp/archive",
            datetime.datetime(2026, 7, 2, 9, 0, 0),
            active_until=datetime.datetime(2026, 7, 3, 9, 0, 0),
            active=False,
        )

        structure = root_directory.jsonify()

        assert structure == {
            "root_directory_uuid": str(root_uuid),
            "path": "/tmp/archive",
            "active_from": "2026-07-02T09:00:00",
            "active_until": "2026-07-03T09:00:00",
            "active": False,
        }

    def test_archive_configuration_jsonify(self):
        """
        Serialize archive-configuration history rows.
        """
        configuration_uuid = uuid.uuid4()
        content = """<archive_configurations root_directory="/tmp/archive"/>"""
        archive_configuration = ArchiveConfiguration(
            configuration_uuid,
            "/tmp/config/archive_configurations.xml",
            datetime.datetime(2026, 7, 2, 9, 0, 0),
            content,
            active_until=datetime.datetime(2026, 7, 3, 9, 0, 0),
            active=False,
        )

        structure = archive_configuration.jsonify()

        assert structure == {
            "archive_configuration_uuid": str(configuration_uuid),
            "path": "/tmp/config/archive_configurations.xml",
            "active_from": "2026-07-02T09:00:00",
            "active_until": "2026-07-03T09:00:00",
            "active": False,
            "content": content,
        }

    def test_archive_operation_jsonify(self):
        """
        Serialize an archive operation without an attached file.
        """
        operation_uuid = uuid.uuid4()
        operation = ArchiveOperation(
            operation_uuid,
            "archive",
            datetime.datetime(2026, 7, 2, 10, 5, 0),
            1,
            message="processor failed",
        )

        structure = operation.jsonify()

        assert structure == {
            "operation_uuid": str(operation_uuid),
            "operation": "archive",
            "time_stamp": "2026-07-02T10:05:00",
            "status": 1,
            "message": "processor failed",
            "file_uuid": "",
        }

    def test_retrieve_archive_operation_can_be_persisted_without_archived_file(self):
        """
        Persist retrieve failures that are not tied to an archived-file row.
        """
        query = Query()
        operation_uuid = uuid.uuid4()
        operation = ArchiveOperation(
            operation_uuid,
            "retrieve",
            datetime.datetime(2026, 7, 2, 10, 5, 0),
            1,
            message="requested file was not found",
        )

        try:
            # Retrieval can fail before a concrete ArchivedFile is available, so
            # the nullable relationship must survive a database round trip.
            query.session.add(operation)
            query.session.commit()

            persisted = query.session.query(ArchiveOperation).filter_by(operation_uuid=str(operation_uuid)).one()

            assert persisted.operation == "retrieve"
            assert persisted.file_uuid is None
            assert persisted.archivedFile is None
            assert persisted.jsonify()["file_uuid"] == ""
        finally:
            query.close_session()

    def test_relationship_foreign_keys_are_serialized_after_persistence(self):
        """
        Serialize foreign keys populated through SQLAlchemy relationships.
        """
        query = Query()
        file_uuid = uuid.uuid4()
        archived_file = ArchivedFile(
            file_uuid,
            "sample.txt",
            "/tmp/archive/texts/2026/07/02/sample.txt",
            datetime.datetime(2026, 7, 2, 10, 0, 0),
            datetime.datetime(2026, 7, 2, 10, 1, 0),
            10,
            self.root_directory,
            archive_configuration=self.archive_configuration,
            delete_archive_configuration=self.delete_archive_configuration,
        )
        operation = ArchiveOperation(
            uuid.uuid4(),
            "archive",
            datetime.datetime(2026, 7, 2, 10, 5, 0),
            1,
            archived_file=archived_file,
        )

        try:
            # Persist the full relationship graph so SQLAlchemy fills the foreign
            # key columns that jsonify exposes to API and CLI callers.
            query.session.add(self.root_directory)
            query.session.add(self.archive_configuration)
            query.session.add(self.delete_archive_configuration)
            query.session.add(archived_file)
            query.session.add(operation)
            query.session.commit()

            assert archived_file.jsonify()["root_directory_uuid"] == str(self.root_directory.root_directory_uuid)
            assert archived_file.jsonify()["archive_configuration_uuid"] == str(self.archive_configuration.archive_configuration_uuid)
            assert archived_file.jsonify()["delete_archive_configuration_uuid"] == str(self.delete_archive_configuration.archive_configuration_uuid)
            assert archived_file.file_uuid in [file.file_uuid for file in self.archive_configuration.archivedFiles]
            assert archived_file.file_uuid in [file.file_uuid for file in self.delete_archive_configuration.deletedArchivedFiles]
            assert operation.jsonify()["file_uuid"] == str(file_uuid)
        finally:
            query.close_session()
