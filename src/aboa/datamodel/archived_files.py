"""
Archive data model definition.

module aboa
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, BigInteger, Text
from sqlalchemy.orm import relationship

from aboa.datamodel.base import Base


def _isoformat(value):
    """
    Format optional datetime values for JSON serialization.

    :param value: datetime value to format
    :type value: datetime.datetime or None

    :return: ISO-8601 text or None
    :rtype: str or None
    """
    if value is None:
        return None
    return value.isoformat()


class ArchiveRootDirectory(Base):
    """
    Persisted history entry for an archive root directory.

    Root directories are stored as a timeline so archived files keep the exact
    root that was active when they were managed.
    """

    __tablename__ = "archive_root_directories"

    root_directory_uuid = Column(Text, primary_key=True)
    path = Column(Text, nullable=False)
    active_from = Column(DateTime, nullable=False)
    active_until = Column(DateTime)
    active = Column(Boolean, nullable=False, default=True)

    def __init__(self, root_directory_uuid, path, active_from, active_until=None, active=True):
        """
        Build a root-directory history entity.

        :param root_directory_uuid: root directory UUID
        :param path: POSIX root directory path
        :param active_from: activation timestamp
        :param active_until: deactivation timestamp, if any
        :param active: flag indicating whether this root directory is active
        """
        self.root_directory_uuid = str(root_directory_uuid)
        self.path = path
        self.active_from = active_from
        self.active_until = active_until
        self.active = active

    def jsonify(self):
        """
        Serialize the root-directory history entry.

        :return: JSON-ready dictionary
        :rtype: dict
        """
        return {
            "root_directory_uuid": str(self.root_directory_uuid),
            "path": self.path,
            "active_from": _isoformat(self.active_from),
            "active_until": _isoformat(self.active_until),
            "active": self.active,
        }


class ArchiveConfiguration(Base):
    """
    Persisted history entry for an archive XML configuration.

    The full XML content is stored so configuration changes can be detected by
    checksum without adding another persisted column.
    """

    __tablename__ = "archive_configurations"

    archive_configuration_uuid = Column(Text, primary_key=True)
    path = Column(Text, nullable=False)
    active_from = Column(DateTime, nullable=False)
    active_until = Column(DateTime)
    active = Column(Boolean, nullable=False, default=True)
    content = Column(Text, nullable=False)
    archivedFiles = relationship(
        "ArchivedFile",
        foreign_keys="ArchivedFile.archive_configuration_uuid",
        back_populates="archiveConfiguration",
    )
    deletedArchivedFiles = relationship(
        "ArchivedFile",
        foreign_keys="ArchivedFile.delete_archive_configuration_uuid",
        back_populates="deleteArchiveConfiguration",
    )

    def __init__(self, archive_configuration_uuid, path, active_from, content, active_until=None, active=True):
        """
        Build an archive-configuration history entity.

        :param archive_configuration_uuid: archive configuration UUID
        :param path: source XML configuration path
        :param active_from: activation timestamp
        :param content: raw XML configuration content
        :param active_until: deactivation timestamp, if any
        :param active: flag indicating whether this configuration is active
        """
        self.archive_configuration_uuid = str(archive_configuration_uuid)
        self.path = path
        self.active_from = active_from
        self.active_until = active_until
        self.active = active
        self.content = content

    def jsonify(self):
        """
        Serialize the archive-configuration history entry.

        :return: JSON-ready dictionary
        :rtype: dict
        """
        return {
            "archive_configuration_uuid": str(self.archive_configuration_uuid),
            "path": self.path,
            "active_from": _isoformat(self.active_from),
            "active_until": _isoformat(self.active_until),
            "active": self.active,
            "content": self.content,
        }


class ArchivedFile(Base):
    """
    Inventory row for a file managed by ABOA.

    The row stores the POSIX archive path, lifecycle timestamps, optional file
    metadata extracted by processors, and logical availability state.
    """

    # Main inventory row for a file stored in the POSIX archive.
    __tablename__ = "archived_files"

    file_uuid = Column(Text, primary_key=True)
    name = Column(Text, index=True, nullable=False)
    path = Column(Text, index=True, nullable=False)
    reception_date = Column(DateTime, index=True, nullable=False)
    archive_date = Column(DateTime, index=True, nullable=False)
    file_size = Column(BigInteger, nullable=False)
    available = Column(Boolean, index=True, nullable=False, default=True)
    root_directory_uuid = Column(Text, ForeignKey("archive_root_directories.root_directory_uuid"), nullable=False)
    rootDirectory = relationship("ArchiveRootDirectory", backref="archived_files")
    archive_configuration_uuid = Column(Text, ForeignKey("archive_configurations.archive_configuration_uuid"), nullable=True)
    archiveConfiguration = relationship(
        "ArchiveConfiguration",
        foreign_keys=[archive_configuration_uuid],
        back_populates="archivedFiles",
    )
    delete_archive_configuration_uuid = Column(Text, ForeignKey("archive_configurations.archive_configuration_uuid"), nullable=True)
    deleteArchiveConfiguration = relationship(
        "ArchiveConfiguration",
        foreign_keys=[delete_archive_configuration_uuid],
        back_populates="deletedArchivedFiles",
    )
    last_access_date = Column(DateTime, index=True)
    file_group = Column(Text, index=True)
    file_type = Column(Text, index=True)
    file_class = Column(Text, index=True)
    file_version = Column(Text, index=True)
    validity_start_date = Column(DateTime, index=True)
    validity_stop_date = Column(DateTime, index=True)
    generation_date = Column(DateTime, index=True)
    expiration_date = Column(DateTime, index=True)
    removal_date = Column(DateTime, index=True)
    removal_justification = Column(Text, index=True)
    checksum = Column(Text)

    def __init__(self, file_uuid, name, path, reception_date, archive_date, file_size, root_directory,
                 archive_configuration=None, delete_archive_configuration=None,
                 available=True, last_access_date=None, file_group=None, file_type=None,
                 file_class=None, file_version=None, validity_start_date=None,
                 validity_stop_date=None, generation_date=None, expiration_date=None,
                 removal_date=None, removal_justification=None, checksum=None):
        """
        Build an archived-file inventory entity.

        :param file_uuid: file UUID
        :param name: original file name
        :param path: full archived POSIX path
        :param reception_date: reception timestamp
        :param archive_date: archive timestamp
        :param file_size: archived file size in bytes
        :param root_directory: associated root-directory history entity
        :param archive_configuration: associated archive configuration used to archive
        :param delete_archive_configuration: associated archive configuration used to delete
        :param available: logical availability flag
        :param last_access_date: last retrieval timestamp
        :param file_group: optional configured file group
        :param file_type: optional file type
        :param file_class: optional file class
        :param file_version: optional file version
        :param validity_start_date: optional validity start timestamp
        :param validity_stop_date: optional validity stop timestamp
        :param generation_date: optional generation timestamp
        :param expiration_date: optional expiration timestamp
        :param removal_date: optional logical removal timestamp
        :param removal_justification: optional logical removal reason
        :param checksum: optional SHA-256 checksum
        """
        self.file_uuid = str(file_uuid)
        self.name = name
        self.path = path
        self.reception_date = reception_date
        self.archive_date = archive_date
        self.file_size = file_size
        self.available = available
        self.rootDirectory = root_directory
        self.archiveConfiguration = archive_configuration
        self.deleteArchiveConfiguration = delete_archive_configuration
        self.last_access_date = last_access_date
        self.file_group = file_group
        self.file_type = file_type
        self.file_class = file_class
        self.file_version = file_version
        self.validity_start_date = validity_start_date
        self.validity_stop_date = validity_stop_date
        self.generation_date = generation_date
        self.expiration_date = expiration_date
        self.removal_date = removal_date
        self.removal_justification = removal_justification
        self.checksum = checksum

    def jsonify(self):
        """
        Serialize the archived-file inventory row.

        :return: JSON-ready dictionary
        :rtype: dict
        """
        return {
            "file_uuid": str(self.file_uuid),
            "name": self.name,
            "path": self.path,
            "reception_date": _isoformat(self.reception_date),
            "archive_date": _isoformat(self.archive_date),
            "file_size": self.file_size,
            "available": self.available,
            "root_directory_uuid": str(self.root_directory_uuid),
            "archive_configuration_uuid": str(self.archive_configuration_uuid) if self.archive_configuration_uuid else None,
            "delete_archive_configuration_uuid": str(self.delete_archive_configuration_uuid) if self.delete_archive_configuration_uuid else None,
            "last_access_date": _isoformat(self.last_access_date),
            "file_group": self.file_group,
            "file_type": self.file_type,
            "file_class": self.file_class,
            "file_version": self.file_version,
            "validity_start_date": _isoformat(self.validity_start_date),
            "validity_stop_date": _isoformat(self.validity_stop_date),
            "generation_date": _isoformat(self.generation_date),
            "expiration_date": _isoformat(self.expiration_date),
            "removal_date": _isoformat(self.removal_date),
            "removal_justification": self.removal_justification,
            "checksum": self.checksum,
        }


class FileToBeRemoved(Base):
    """
    Trash-queue row for an archived file awaiting final physical removal.

    Physical removals first move archive payloads to a trash directory. This row
    records the trash path and the scheduled final deletion timestamp.
    """

    __tablename__ = "files_to_be_removed"

    file_uuid = Column(Text, ForeignKey("archived_files.file_uuid"), nullable=False)
    file_to_remove_uuid = Column(Text, primary_key=True)
    root_directory_uuid = Column(Text, ForeignKey("archive_root_directories.root_directory_uuid"), nullable=False)
    path = Column(Text, index=True, nullable=False)
    removal_date = Column(DateTime, index=True, nullable=False)
    archivedFile = relationship("ArchivedFile", backref="filesToBeRemoved")
    rootDirectory = relationship("ArchiveRootDirectory", backref="files_to_be_removed")

    def __init__(self, file_to_remove_uuid, archived_file, path, root_directory, removal_date):
        """
        Build a pending final-removal row.

        :param file_to_remove_uuid: pending-removal UUID
        :type file_to_remove_uuid: uuid.UUID or str
        :param archived_file: archived-file inventory row being removed
        :type archived_file: aboa.datamodel.archived_files.ArchivedFile
        :param path: payload path inside the trash directory
        :type path: str
        :param root_directory: root-directory history row that owns the trash path
        :type root_directory: aboa.datamodel.archived_files.ArchiveRootDirectory
        :param removal_date: scheduled final-removal timestamp
        :type removal_date: datetime.datetime
        """
        self.file_to_remove_uuid = str(file_to_remove_uuid)
        self.archivedFile = archived_file
        self.path = path
        self.rootDirectory = root_directory
        self.removal_date = removal_date

    def jsonify(self):
        """
        Serialize the pending final-removal row.

        :return: JSON-ready dictionary
        :rtype: dict
        """
        return {
            "file_to_remove_uuid": str(self.file_to_remove_uuid),
            "file_uuid": str(self.file_uuid),
            "path": self.path,
            "root_directory_uuid": str(self.root_directory_uuid),
            "removal_date": _isoformat(self.removal_date),
        }


class ArchiveOperation(Base):
    """
    Failure trace for archive operations.

    Successful operations are log-only. Rows in this table represent failures that
    need durable operator visibility.
    """

    # Only failed operations are stored here; successful operations are log-only.
    __tablename__ = "archive_operations"

    operation_uuid = Column(Text, primary_key=True)
    operation = Column(Text, nullable=False)
    time_stamp = Column(DateTime, nullable=False)
    status = Column(Integer, nullable=False)
    message = Column(Text)
    file_uuid = Column(Text, ForeignKey("archived_files.file_uuid"))
    archivedFile = relationship("ArchivedFile", backref="operations")

    def __init__(self, operation_uuid, operation, time_stamp, status, message=None, archived_file=None):
        """
        Build an operation failure entity.

        :param operation_uuid: operation UUID
        :param operation: operation name
        :param time_stamp: failure timestamp
        :param status: numeric status code
        :param message: optional failure message
        :param archived_file: optional related archived file
        """
        self.operation_uuid = str(operation_uuid)
        self.operation = operation
        self.time_stamp = time_stamp
        self.status = status
        self.message = message
        self.archivedFile = archived_file

    def jsonify(self):
        """
        Serialize the operation row.

        :return: JSON-ready dictionary
        :rtype: dict
        """
        return {
            "operation_uuid": str(self.operation_uuid),
            "operation": self.operation,
            "time_stamp": _isoformat(self.time_stamp),
            "status": self.status,
            "message": self.message,
            "file_uuid": str(self.file_uuid) if self.file_uuid else "",
        }
