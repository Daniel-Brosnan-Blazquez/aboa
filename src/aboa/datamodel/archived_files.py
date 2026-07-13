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

    :return: ISO-8601 text or empty string
    :rtype: str
    """
    if value is None:
        return ""
    return value.isoformat()


def _stringify(value):
    """
    Format optional scalar values for JSON serialization.

    :param value: scalar value to format

    :return: text value or empty string
    :rtype: str
    """
    if value is None:
        return ""
    return str(value)


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
            "root_directory_uuid": _stringify(self.root_directory_uuid),
            "path": _stringify(self.path),
            "active_from": _isoformat(self.active_from),
            "active_until": _isoformat(self.active_until),
            "active": _stringify(self.active),
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
            "archive_configuration_uuid": _stringify(self.archive_configuration_uuid),
            "path": _stringify(self.path),
            "active_from": _isoformat(self.active_from),
            "active_until": _isoformat(self.active_until),
            "active": _stringify(self.active),
            "content": _stringify(self.content),
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
    physically_available = Column(Boolean, index=True, nullable=False, default=True)
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
                 available=True, physically_available=True, last_access_date=None, file_group=None, file_type=None,
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
        :param physically_available: whether a managed payload exists in the archive path or trash
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
        self.physically_available = physically_available
        self.rootDirectory = root_directory
        if root_directory is not None:
            self.root_directory_uuid = str(root_directory.root_directory_uuid)
        self.archiveConfiguration = archive_configuration
        if archive_configuration is not None:
            self.archive_configuration_uuid = str(archive_configuration.archive_configuration_uuid)
        self.deleteArchiveConfiguration = delete_archive_configuration
        if delete_archive_configuration is not None:
            self.delete_archive_configuration_uuid = str(delete_archive_configuration.archive_configuration_uuid)
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
            "file_uuid": _stringify(self.file_uuid),
            "name": _stringify(self.name),
            "path": _stringify(self.path),
            "reception_date": _isoformat(self.reception_date),
            "archive_date": _isoformat(self.archive_date),
            "file_size": _stringify(self.file_size),
            "available": _stringify(self.available),
            "physically_available": _stringify(self.physically_available),
            "root_directory_uuid": _stringify(self.root_directory_uuid),
            "archive_configuration_uuid": _stringify(self.archive_configuration_uuid),
            "delete_archive_configuration_uuid": _stringify(self.delete_archive_configuration_uuid),
            "last_access_date": _isoformat(self.last_access_date),
            "file_group": _stringify(self.file_group),
            "file_type": _stringify(self.file_type),
            "file_class": _stringify(self.file_class),
            "file_version": _stringify(self.file_version),
            "validity_start_date": _isoformat(self.validity_start_date),
            "validity_stop_date": _isoformat(self.validity_stop_date),
            "generation_date": _isoformat(self.generation_date),
            "expiration_date": _isoformat(self.expiration_date),
            "removal_date": _isoformat(self.removal_date),
            "removal_justification": _stringify(self.removal_justification),
            "checksum": _stringify(self.checksum),
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
        if archived_file is not None:
            self.file_uuid = str(archived_file.file_uuid)
        self.path = path
        self.rootDirectory = root_directory
        if root_directory is not None:
            self.root_directory_uuid = str(root_directory.root_directory_uuid)
        self.removal_date = removal_date

    def jsonify(self):
        """
        Serialize the pending final-removal row.

        :return: JSON-ready dictionary
        :rtype: dict
        """
        return {
            "file_to_remove_uuid": _stringify(self.file_to_remove_uuid),
            "file_uuid": _stringify(self.file_uuid),
            "path": _stringify(self.path),
            "root_directory_uuid": _stringify(self.root_directory_uuid),
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
        if archived_file is not None:
            self.file_uuid = str(archived_file.file_uuid)

    def jsonify(self):
        """
        Serialize the operation row.

        :return: JSON-ready dictionary
        :rtype: dict
        """
        return {
            "operation_uuid": _stringify(self.operation_uuid),
            "operation": _stringify(self.operation),
            "time_stamp": _isoformat(self.time_stamp),
            "status": _stringify(self.status),
            "message": _stringify(self.message),
            "file_uuid": _stringify(self.file_uuid),
        }
