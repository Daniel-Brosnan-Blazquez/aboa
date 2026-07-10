"""
Engine definition for archive operations.

module aboa
"""

import datetime
import hashlib
import importlib
import os
import re
import shutil
import uuid

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import scoped_session

from aboa.datamodel.archived_files import (
    ArchiveConfiguration,
    ArchivedFile,
    ArchiveOperation,
    ArchiveRootDirectory,
    FileToBeRemoved,
)
from aboa.datamodel.base import Base, Session, engine as sqlalchemy_engine
from aboa.engine.errors import (
    ArchiveConfigurationError,
    ArchiveDeletionError,
    ArchiveFileError,
    ArchiveRecoveryError,
    ArchiveRetrievalError,
    ProcessorError,
)
from aboa.engine.functions import get_resources_path, parse_datetime, read_configuration
from aboa.engine.parsing import get_archive_configuration
from aboa.engine.query import Query
from aboa.engine.xpath_functions import register_xpath_functions
from aboa.logging import Log

logging = Log(name=__name__)
logger = logging.logger

XML_DURATION_PATTERN = re.compile(
    r"^(?P<sign>-)?P"
    r"(?:(?P<years>\d+)Y)?"
    r"(?:(?P<months>\d+)M)?"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)

# Register custom XPath functions for ABOA archive configuration XML.
register_xpath_functions()

# Declare exit codes
exit_codes = {
    "OK": {
        "status": 0,
        "message": "The archive operation {} has finished correctly",
    },
    "CONFIGURATION_FAILED": {
        "status": 1,
        "message": "The archive configuration with path {} could not be loaded. The error was: {}",
    },
    "FILE_DOES_NOT_EXIST": {
        "status": 2,
        "message": "The file {} does not exist",
    },
    "ROOT_DIRECTORY_NOT_CONFIGURED": {
        "status": 3,
        "message": "There is no active archive root directory",
    },
    "PROCESSOR_FAILED": {
        "status": 4,
        "message": "The file {} was going to be processed by {} but the processing ended unexpectedly with the error: {}",
    },
    "FILE_ALREADY_ARCHIVED": {
        "status": 5,
        "message": "The file {} has been received already",
    },
    "FILE_STORAGE_FAILED": {
        "status": 6,
        "message": "The file {} could not be stored in the archive. The error was: {}",
    },
    "INPUT_DELETE_FAILED": {
        "status": 7,
        "message": "The archived input file {} could not be deleted. The error was: {}",
    },
    "DELETE_FAILED": {
        "status": 8,
        "message": "The delete operation ended unexpectedly with the error: {}",
    },
    "RETRIEVE_FAILED": {
        "status": 9,
        "message": "The retrieve operation ended unexpectedly with the error: {}",
    },
    "RETENTION_FAILED": {
        "status": 10,
        "message": "The retention operation ended unexpectedly with the error: {}",
    },
    "ARCHIVE_FAILED": {
        "status": 11,
        "message": "The archive operation for file {} ended unexpectedly with the error: {}",
    },
    "FINAL_REMOVAL_FAILED": {
        "status": 12,
        "message": "The final removal operation for file {} ended unexpectedly with the error: {}",
    },
    "RECOVERY_FAILED": {
        "status": 13,
        "message": "The recovery operation ended unexpectedly with the error: {}",
    },
}

DEFAULT_TRASH_DIRECTORY_NAME = "trash"
DEFAULT_FINAL_REMOVAL_DELAY_DAYS = 30


class Engine():
    """
    Class for managing ABOA archive mutations.

    The engine owns the write-side operations for the archive inventory. It stores
    metadata of archived files, status of failed archive operations, root-directory history,
    and archive-configuration history in the database. Archive matching rules and
    retention policy definitions remain runtime configuration loaded from XML and
    are applied while archiving files.
    """

    def __init__(self, session=None):
        """
        Instantiate an archive engine.

        :param session: optional SQLAlchemy session supplied by tests or callers
        :type session: sqlalchemy.orm.session.Session or None

        :return: None
        :rtype: None
        """
        if session is None:
            Scoped_session = scoped_session(Session)
            self.session = Scoped_session()
        else:
            self.session = session
        self.query = Query(session=self.session)
        self.configuration_xpath = None
        self.configuration_path = None
        self.engine_configuration = read_configuration()
        self.trash_directory = self._configured_trash_directory()
        self.final_removal_delay_days = self._configured_final_removal_delay_days()

    def get_exit_codes(self):
        """
        Return engine exit-code descriptors.

        :return: copy of the exit-code table keyed by code name
        :rtype: dict
        """
        return {key: dict(value) for key, value in exit_codes.items()}

    def get_exit_code(self, name):
        """
        Return one engine exit-code descriptor by name.

        :param name: exit-code key, such as ``RETENTION_FAILED``
        :type name: str

        :return: copy of the exit-code descriptor
        :rtype: dict

        :raises KeyError: when the exit-code key is unknown
        """
        return self.get_exit_codes()[name]

    def _configured_trash_directory(self):
        """
        Return the trash directory name configured for archived payload removal.

        :return: configured trash directory name, or default ``trash``
        :rtype: str
        """
        archive_configuration = self.engine_configuration.get("ARCHIVE", {})
        trash_directory = archive_configuration.get("TRASH_DIRECTORY", DEFAULT_TRASH_DIRECTORY_NAME)
        if trash_directory is None or str(trash_directory).strip() == "":
            return DEFAULT_TRASH_DIRECTORY_NAME
        return str(trash_directory).strip()

    def _configured_final_removal_delay_days(self):
        """
        Return how many days trashed payloads wait before final removal.

        :return: configured delay in days, or default ``30``
        :rtype: int

        :raises ArchiveConfigurationError: when the configured value is invalid
        """
        archive_configuration = self.engine_configuration.get("ARCHIVE", {})
        delay_days = archive_configuration.get("FINAL_REMOVAL_DELAY_DAYS", DEFAULT_FINAL_REMOVAL_DELAY_DAYS)
        if delay_days is None or str(delay_days).strip() == "":
            return DEFAULT_FINAL_REMOVAL_DELAY_DAYS
        try:
            delay_days = int(delay_days)
        except (TypeError, ValueError) as exc:
            raise ArchiveConfigurationError("The final removal delay days must be an integer") from exc
        if delay_days < 0:
            raise ArchiveConfigurationError("The final removal delay days must be positive")
        return delay_days

    def set_configuration_path(self, configuration_path):
        """
        Set the archive configuration XML path used by archive operations.

        :param configuration_path: archive configuration XML path, or None to use
            the default ``ABOA_RESOURCES_PATH`` configuration
        :type configuration_path: str or None

        :return: None
        :rtype: None
        """
        self.configuration_path = configuration_path

    def close_session(self):
        """
        Close the underlying SQLAlchemy session.

        :return: None
        :rtype: None
        """
        self.session.close()

    def archive_file(self, file_path, reception_date=None, metadata=None, delete=False):
        """
        Archive a file into the managed POSIX archive and inventory it.

        Files are routed through the first matching XML rule. Unmatched files go to
        ``unknown``. Recoverable failures, such as processor failure or duplicate
        reception, go to ``error`` and create an ``ArchiveOperation`` failure row.

        :param file_path: path to the file to archive
        :type file_path: str
        :param reception_date: optional reception timestamp
        :type reception_date: str or datetime.datetime or None
        :param metadata: optional metadata overriding or complementing processor data
        :type metadata: dict or None
        :param delete: remove the input file after successful archive management
        :type delete: bool

        :return: None
        :rtype: None

        :raises ArchiveFileError: when the input file does not exist
        :raises ArchiveConfigurationError: when no active root directory is configured
        """
        logger.info("Archive request received for file {}".format(file_path))
        metadata = dict(metadata or {})
        reception_date = parse_datetime(reception_date) or datetime.datetime.utcnow()
        archive_date = datetime.datetime.utcnow()
        failures = []
        root_directory = None
        archive_configuration = None

        # Load the archive configuration XML and synchronize the root-directory.
        try:
            self._load_archive_configuration(self.configuration_path)
        except ArchiveConfigurationError as exc:
            message = exit_codes["CONFIGURATION_FAILED"]["message"].format(self.configuration_path, exc)
            logger.error(message)
            failures.append((exit_codes["CONFIGURATION_FAILED"]["status"], message))
            self._record_archive_failures(file_path, file_path, reception_date, archive_date, metadata, None, failures, root_directory, archive_configuration)
            raise ArchiveConfigurationError(message)

        # Get the active root directory for the archive.
        root_directory = self.query.get_active_root_directory()
        archive_configuration = self.query.get_active_archive_configuration()

        # Check that the file exists
        if not os.path.exists(file_path):
            message = exit_codes["FILE_DOES_NOT_EXIST"]["message"].format(file_path)
            logger.error(message)
            failures.append((exit_codes["FILE_DOES_NOT_EXIST"]["status"], message))
            self._record_archive_failures(file_path, file_path, reception_date, archive_date, metadata, None, failures, root_directory, archive_configuration)
            raise ArchiveFileError(message)

        # Find the matching archiving configuration
        configuration = self._match_configuration(file_path)
        if configuration is None:
            # Requirement: files without a matching rule must still be archived.
            target_directory = "unknown"
            metadata.setdefault("file_group", "unknown")
            processor = None
        else:
            target_directory = self._configuration_node_text(configuration, "file_directory")
            metadata.setdefault("file_group", configuration.get("file_group"))
            processor = self._configuration_node_text(configuration, "file_processor", empty_as_none=True)

        # Execute the configured processor, if any, and update metadata with its output.
        # Processor failure is registered as an archive error.
        try:
            if processor is not None:
                metadata.update(self._execute_processor(processor, file_path))
        except Exception as exc:
            error_message = exit_codes["PROCESSOR_FAILED"]["message"].format(file_path, processor, exc)
            failures.append((exit_codes["PROCESSOR_FAILED"]["status"], error_message))
            target_directory = "error"
            logger.error(error_message)

        if metadata.get("expiration_date") is None:
            expiration_date = self._calculate_expiration_date(configuration, reception_date, archive_date, metadata)
            if expiration_date is not None:
                metadata["expiration_date"] = expiration_date

        # Calculate the checksum of the file to be archived.
        # Checksum failure is registered as an archive error.
        try:
            checksum = self._checksum(file_path)
        except Exception as exc:
            message = exit_codes["ARCHIVE_FAILED"]["message"].format(file_path, exc)
            logger.error(message)
            failures.append((exit_codes["ARCHIVE_FAILED"]["status"], message))
            checksum = None
            target_directory = "error"

        # Check duplication
        is_duplicate_reception = False
        if self.session.query(ArchivedFile).filter(ArchivedFile.name == os.path.basename(file_path), ArchivedFile.available == True).first() is not None:
            # Duplicate reception follows the same recoverable path as processor
            # failures so the received file remains under ABOA control.
            is_duplicate_reception = True
            error_message = exit_codes["FILE_ALREADY_ARCHIVED"]["message"].format(file_path)
            failures.append((exit_codes["FILE_ALREADY_ARCHIVED"]["status"], error_message))
            target_directory = "error"
            logger.error(error_message)

        if target_directory == "error" and is_duplicate_reception:
            existing_error_file = self._find_existing_duplicate_error_file(
                root_directory.path,
                archive_date,
                os.path.basename(file_path),
                checksum,
            )
            if existing_error_file is not None:
                for status, message in failures:
                    self.record_failure("archive", status, message, existing_error_file)
                self.session.commit()
                if delete:
                    self._delete_input_file(file_path, existing_error_file)
                logger.info("Archive request reused existing duplicate error file {}".format(existing_error_file.path))
                return None

        # Store file in the archive, first trying a hard link and falling back to a copy.
        try:
            destination_path = self._build_destination_path(root_directory.path, target_directory, archive_date, os.path.basename(file_path))
            self._store_file(file_path, destination_path)
        except Exception as exc:
            # If both the normal path and copy fallback fail, try once more in the
            # error area so operators can inspect the received file later.
            error_message = exit_codes["FILE_STORAGE_FAILED"]["message"].format(file_path, exc)
            failures.append((exit_codes["FILE_STORAGE_FAILED"]["status"], error_message))
            logger.error(error_message)
            try:
                destination_path = self._build_destination_path(root_directory.path, "error", archive_date, os.path.basename(file_path))
                self._store_file(file_path, destination_path)
            except Exception as second_exc:
                message = exit_codes["FILE_STORAGE_FAILED"]["message"].format(file_path, second_exc)
                logger.error(message)
                failures.append((exit_codes["FILE_STORAGE_FAILED"]["status"], message))
                self._record_archive_failures(file_path, destination_path, reception_date, archive_date, metadata, checksum, failures, root_directory, archive_configuration)
                raise ArchiveFileError(message)

        # Store metadata in the database and record any failures.
        archived_file = self._build_archived_file(file_path, destination_path, reception_date, archive_date, metadata, checksum, root_directory, archive_configuration)
        self.session.add(archived_file)
        for status, message in failures:
            self.record_failure("archive", status, message, archived_file)
        self.session.commit()

        # Check deletion
        if delete:
            # The input is removed only after the file has been stored under ABOA
            # management and the inventory transaction has committed.
            self._delete_input_file(file_path, archived_file)

        logger.info("Archive request performed for file {}".format(file_path))
        return None

    def retrieve_files(self, filters=None, order_by=None, group_by=None, selection="all", limit=None, offset=None, destination_path=None):
        """
        Retrieve archived file inventory entries, optionally copying payloads.

        :param filters: query filters accepted by ``Query.get_archived_files``
        :type filters: dict or None
        :param order_by: ordering descriptor with ``field`` and ``descending``
        :type order_by: dict or None
        :param group_by: optional metadata field used to group results
        :type group_by: str or None
        :param selection: selection rule: ``all``, ``first``, or ``last``
        :type selection: str
        :param limit: maximum number of rows
        :type limit: int or None
        :param offset: result offset
        :type offset: int or None
        :param destination_path: optional folder where selected payloads are copied
        :type destination_path: str or None

        :return: list of archived files, or grouped dictionary when ``group_by`` is set
        :rtype: list or dict

        :raises ArchiveRetrievalError: when inventory retrieval or last-access
            update fails
        """
        try:
            filters = filters or {}
            files = self.query.get_archived_files(order_by=order_by, group_by=group_by, selection=selection, limit=limit, offset=offset, **filters)
            if group_by is not None:
                # Grouped retrieval returns a dictionary, while normal retrieval returns
                # a list; flatten it only for last-access bookkeeping.
                iterable = [item for group in files.values() for item in group]
            else:
                iterable = files
            self._copy_retrieved_files(iterable, destination_path)
            now = datetime.datetime.utcnow()
            for archived_file in iterable:
                archived_file.last_access_date = now
            self.session.commit()
            logger.info("Retrieve request performed on {} file/s".format(len(iterable)))
            return files
        except Exception as exc:
            self.session.rollback()
            message = exit_codes["RETRIEVE_FAILED"]["message"].format(exc)
            logger.error(message)
            self.record_failure("retrieve", exit_codes["RETRIEVE_FAILED"]["status"], message)
            self.session.commit()
            raise ArchiveRetrievalError(message) from exc

    def _copy_retrieved_files(self, archived_files, destination_path=None):
        """
        Copy retrieved payloads into a user-supplied destination folder.

        :param archived_files: archived-file rows selected for retrieval
        :type archived_files: list
        :param destination_path: folder where payloads are copied
        :type destination_path: str or None

        :return: None
        :rtype: None
        """
        if destination_path is None:
            return

        if os.path.exists(destination_path) and not os.path.isdir(destination_path):
            raise ValueError("The destination path {} is not a directory".format(destination_path))
        os.makedirs(destination_path, exist_ok=True)

        copied_paths = set()
        for archived_file in archived_files:
            if not os.path.exists(archived_file.path):
                raise ValueError("The archived payload {} does not exist".format(archived_file.path))

            destination_file = self._build_retrieval_destination_path(destination_path, archived_file, copied_paths)
            shutil.copy2(archived_file.path, destination_file)
            copied_paths.add(destination_file)
            logger.info("Retrieved file {} copied to {}".format(archived_file.file_uuid, destination_file))

    def _build_retrieval_destination_path(self, destination_path, archived_file, copied_paths=None):
        """
        Build a destination path for a retrieved payload without overwriting files.

        :param destination_path: retrieval destination folder
        :type destination_path: str
        :param archived_file: archived-file row selected for retrieval
        :type archived_file: aboa.datamodel.archived_files.ArchivedFile
        :param copied_paths: paths already used by this retrieval batch
        :type copied_paths: set or None

        :return: collision-safe retrieval destination path
        :rtype: str
        """
        copied_paths = copied_paths or set()
        file_name = archived_file.name or os.path.basename(archived_file.path)
        candidate = os.path.join(destination_path, file_name)
        if not os.path.exists(candidate) and candidate not in copied_paths:
            return candidate

        base, extension = os.path.splitext(file_name)
        unique_name = "{}_{}{}".format(base, archived_file.file_uuid, extension)
        candidate = os.path.join(destination_path, unique_name)
        if not os.path.exists(candidate) and candidate not in copied_paths:
            return candidate

        counter = 1
        while True:
            numbered_name = "{}_{}_{}{}".format(base, archived_file.file_uuid, counter, extension)
            candidate = os.path.join(destination_path, numbered_name)
            if not os.path.exists(candidate) and candidate not in copied_paths:
                return candidate
            counter += 1

    def delete_files(self, filters=None, file_uuids=None, physical_delete=False, permanent_delete=False, removal_justification="manual_delete"):
        """
        Delete archived files logically and optionally remove their payloads.

        :param filters: query filters accepted by ``Query.get_archived_files``
        :type filters: dict or None
        :param file_uuids: optional list of file UUIDs to delete
        :type file_uuids: list or None
        :param physical_delete: move files from the POSIX archive to trash when true
        :type physical_delete: bool
        :param permanent_delete: delete physical payloads immediately, bypassing trash
        :type permanent_delete: bool
        :param removal_justification: reason stored on logically removed files
        :type removal_justification: str or None

        :return: deleted archive inventory entities
        :rtype: list

        :raises ArchiveDeletionError: when lookup, inventory update, or physical
            deletion fails
        """
        try:
            filters = dict(filters or {})
            if file_uuids is not None:
                filters["file_uuids"] = {"filter": file_uuids, "op": "in"}
            files = self.query.get_archived_files(**filters)
            now = datetime.datetime.utcnow()
            for archived_file in files:
                # Preserve the first logical deletion timestamp. A repeated delete
                # can still perform a requested physical/permanent cleanup.
                if archived_file.available or archived_file.removal_date is None:
                    archived_file.removal_date = now
                if archived_file.available or archived_file.removal_justification is None:
                    archived_file.removal_justification = removal_justification
                archived_file.available = False
                archived_file.deleteArchiveConfiguration = None
                if permanent_delete:
                    self.delete_archived_file_permanently(archived_file)
                elif physical_delete:
                    self.move_archived_file_to_trash(archived_file, archived_file.removal_date)
                else:
                    self._sync_physical_availability(archived_file)
            self.session.commit()
            logger.info("Delete request performed on {} file/s".format(len(files)))
            return files
        except Exception as exc:
            self.session.rollback()
            message = exit_codes["DELETE_FAILED"]["message"].format(exc)
            logger.error(message)
            self.record_failure("delete", exit_codes["DELETE_FAILED"]["status"], message)
            self.session.commit()
            raise ArchiveDeletionError(message) from exc

    def delete_archived_file_entries(self, filters=None, file_uuids=None):
        """
        Remove archived-file inventory rows only when no managed payload remains.

        :param filters: query filters accepted by ``Query.get_archived_files``
        :type filters: dict or None
        :param file_uuids: optional list of file UUIDs to purge from inventory
        :type file_uuids: list or None

        :return: removed archived-file entities
        :rtype: list

        :raises ArchiveDeletionError: when any selected file still has bytes in
            the archive path or trash, or when the inventory update fails
        """
        try:
            filters = dict(filters or {})
            if file_uuids is not None:
                filters["file_uuids"] = {"filter": file_uuids, "op": "in"}
            files = self.query.get_archived_files(**filters)
            for archived_file in files:
                if self._sync_physical_availability(archived_file):
                    raise ArchiveDeletionError(
                        "The archived-file entry {} cannot be deleted because its payload is still physically available".format(
                            archived_file.file_uuid
                        )
                    )
                self._detach_archive_operations(archived_file)
                for file_to_be_removed in self._get_files_to_be_removed(archived_file):
                    self.session.delete(file_to_be_removed)
                self.session.delete(archived_file)
            self.session.commit()
            logger.info("Archived-file entry deletion request performed on {} file/s".format(len(files)))
            return files
        except Exception as exc:
            self.session.rollback()
            message = exit_codes["DELETE_FAILED"]["message"].format(exc)
            logger.error(message)
            self.record_failure("delete", exit_codes["DELETE_FAILED"]["status"], message)
            self.session.commit()
            raise ArchiveDeletionError(message) from exc

    def recover_files_from_trash(self, filters=None, file_uuids=None, file_to_remove_uuids=None):
        """
        Recover physically deleted archive payloads from trash.

        Recovery moves each queued trash payload back to its original archive
        path, marks the archived file available again, and removes the pending
        final-removal row. Existing archive-path payloads are never overwritten.

        :param filters: query filters accepted by ``Query.get_files_to_be_removed``
        :type filters: dict or None
        :param file_uuids: optional archived-file UUIDs to recover
        :type file_uuids: list or None
        :param file_to_remove_uuids: optional trash-queue UUIDs to recover
        :type file_to_remove_uuids: list or None

        :return: recovered archive inventory entities
        :rtype: list

        :raises ArchiveRecoveryError: when lookup or filesystem recovery fails
        """
        try:
            filters = dict(filters or {})
            if file_uuids is not None:
                filters["file_uuids"] = {"filter": file_uuids, "op": "in"}
            if file_to_remove_uuids is not None:
                filters["file_to_remove_uuids"] = {"filter": file_to_remove_uuids, "op": "in"}

            rows = self.query.get_files_to_be_removed(**filters)
            recovered_files = []
            failures = []
            for file_to_be_removed in rows:
                try:
                    recovered_files.append(self._recover_file_from_trash(file_to_be_removed))
                except Exception as exc:
                    message = "file {}: {}".format(file_to_be_removed.path, exc)
                    logger.error(message)
                    self.record_failure(
                        "recover",
                        exit_codes["RECOVERY_FAILED"]["status"],
                        exit_codes["RECOVERY_FAILED"]["message"].format(message),
                        file_to_be_removed.archivedFile,
                    )
                    failures.append(message)

            self.session.commit()
            if len(failures) > 0:
                raise ArchiveRecoveryError(exit_codes["RECOVERY_FAILED"]["message"].format("; ".join(failures)))

            logger.info("Recovery request performed on {} file/s".format(len(recovered_files)))
            return recovered_files
        except ArchiveRecoveryError:
            raise
        except Exception as exc:
            self.session.rollback()
            message = exit_codes["RECOVERY_FAILED"]["message"].format(exc)
            logger.error(message)
            self.record_failure("recover", exit_codes["RECOVERY_FAILED"]["status"], message)
            self.session.commit()
            raise ArchiveRecoveryError(message) from exc

    def _match_configuration(self, file_path):
        """
        Find the first archive rule matching a file name.

        :param file_path: path to the received file
        :type file_path: str

        :return: matching XML archive rule or None
        :rtype: lxml.etree._Element or None
        """
        if self.configuration_xpath is None:
            return None
        file_name = os.path.basename(file_path)
        matching_configurations = self.configuration_xpath(
            "/archive_configurations/archive_configuration[match(file_mask, $file_name)]",
            file_name=file_name,
        )
        if len(matching_configurations) == 0:
            return None
        return matching_configurations[0]

    def _configuration_node_text(self, configuration_node, child_name, empty_as_none=False):
        """
        Return stripped child text from an archive configuration XML node.

        :param configuration_node: XML archive configuration node
        :type configuration_node: lxml.etree._Element
        :param child_name: child element name to read
        :type child_name: str
        :param empty_as_none: return None instead of an empty string
        :type empty_as_none: bool

        :return: stripped child text, or None when requested for empty values
        :rtype: str or None
        """
        text = configuration_node.xpath("string({})".format(child_name)).strip()
        if empty_as_none and text == "":
            return None
        return text

    def _calculate_expiration_date(self, configuration_node, reception_date, archive_date, metadata):
        """
        Calculate expiration from the applicable XML retention policy.

        Rule-specific policies take precedence over global policies. Explicit
        metadata expiration is handled by the caller and is not overridden here.

        :param configuration_node: matching XML archive rule, if any
        :type configuration_node: lxml.etree._Element or None
        :param reception_date: file reception timestamp
        :type reception_date: datetime.datetime
        :param archive_date: archive operation timestamp
        :type archive_date: datetime.datetime
        :param metadata: archive metadata used by date-keyed policies
        :type metadata: dict

        :return: calculated expiration timestamp, or None when no policy applies
        :rtype: datetime.datetime or None

        :raises ArchiveConfigurationError: when the selected retention duration is
            not a valid XML Schema duration
        """
        retention_policy = self._retention_policy_for_configuration(configuration_node)
        if retention_policy is None:
            return None

        retention_key = retention_policy.get("key")
        if retention_key == "archive_date":
            base_date = archive_date
        elif retention_key == "generation_date":
            base_date = parse_datetime(metadata.get("generation_date"))
        elif retention_key == "reception_date":
            base_date = reception_date
        elif retention_key == "validity_stop_date":
            base_date = parse_datetime(metadata.get("validity_stop_date"))
        else:
            return None

        if base_date is None:
            return None
        return base_date + self._parse_retention_duration(retention_policy.text)

    def _retention_policy_for_configuration(self, configuration_node):
        """
        Return the active retention policy for a matched rule or global fallback.

        :param configuration_node: matching XML archive rule, if any
        :type configuration_node: lxml.etree._Element or None

        :return: active retention policy XML node, or None when none is configured
        :rtype: lxml.etree._Element or None
        """
        if configuration_node is not None:
            policies = configuration_node.xpath("retention_policy[@active='true' or @active='1']")
            if len(policies) > 0:
                return policies[0]

        if self.configuration_xpath is None:
            return None

        policies = self.configuration_xpath(
            "/archive_configurations/retention_policies/retention_policy[@active='true' or @active='1']"
        )
        if len(policies) > 0:
            return policies[0]
        return None

    def _parse_retention_duration(self, duration):
        """
        Parse an XML Schema duration into a calendar-aware relativedelta.

        :param duration: XML Schema duration text, such as ``P1D`` or ``P1Y``
        :type duration: str

        :return: calendar-aware relative delta represented by the duration
        :rtype: dateutil.relativedelta.relativedelta

        :raises ArchiveConfigurationError: when the duration is empty or invalid
        """
        duration = (duration or "").strip()
        match = XML_DURATION_PATTERN.match(duration)
        if match is None:
            raise ArchiveConfigurationError("The retention policy duration {} is not valid".format(duration))

        parts = match.groupdict()
        duration_fields = ["years", "months", "days", "hours", "minutes", "seconds"]
        if all(parts[field] is None for field in duration_fields):
            raise ArchiveConfigurationError("The retention policy duration {} is not valid".format(duration))

        sign = -1 if parts["sign"] == "-" else 1
        seconds = sign * float(parts["seconds"]) if parts["seconds"] is not None else 0
        return relativedelta(
            years=sign * int(parts["years"] or 0),
            months=sign * int(parts["months"] or 0),
            days=sign * int(parts["days"] or 0),
            hours=sign * int(parts["hours"] or 0),
            minutes=sign * int(parts["minutes"] or 0),
            seconds=seconds,
        )

    def _load_archive_configuration(self, configuration_path=None):
        """
        Load archive configuration XML and synchronize root-directory metadata.

        :param configuration_path: optional XML archive configuration path. When
            omitted, ``archive_configurations.xml`` is loaded from
            ``ABOA_RESOURCES_PATH``. If the configuration cannot be loaded,
            ``ABOA_DEFAULT_ARCHIVE_PATH`` is used as the active root directory.
        :type configuration_path: str or None

        :raises ArchiveConfigurationError: when neither configuration nor default
            root directory can load

        :return: None
        :rtype: None
        """

        try:
            if configuration_path is None:
                configuration_path = os.path.join(get_resources_path(), "archive_configurations.xml")
            configuration_xpath = get_archive_configuration(configuration_path)
            root_directory_path = configuration_xpath("string(/archive_configurations/@root_directory)").strip()
            self._activate_root_directory(root_directory_path)
            self._activate_archive_configuration(configuration_path)
            self.configuration_xpath = configuration_xpath
            self.configuration_path = configuration_path
        except Exception as exc:
            self.session.rollback()
            logger.error("The archive configuration could not be loaded, using default archive root directory: {}".format(exc))
            try:
                root_directory_path = os.environ.get("ABOA_DEFAULT_ARCHIVE_PATH")
                if root_directory_path is None or root_directory_path.strip() == "":
                    raise ArchiveConfigurationError("The environment variable ABOA_DEFAULT_ARCHIVE_PATH is not defined")
                self._activate_root_directory(root_directory_path.strip())
                self.configuration_xpath = None
                self.configuration_path = configuration_path
            except Exception as fallback_exc:
                self.session.rollback()

            # Raise exception as the configuration could not be loaded
            raise ArchiveConfigurationError(exc)

        return

    def _activate_archive_configuration(self, configuration_path):
        """
        Ensure the supplied XML configuration path is the active configuration.

        A new history row is created only when the active configuration checksum
        differs from the checksum of the XML content at the supplied path.

        :param configuration_path: source XML archive configuration path
        :type configuration_path: str

        :return: None
        :rtype: None
        """
        with open(configuration_path, "r", encoding="utf-8") as configuration_file:
            configuration_content = configuration_file.read()
        active_configuration = self.query.get_active_archive_configuration()
        configuration_checksum = self._configuration_checksum(configuration_content)
        if active_configuration is None or self._configuration_checksum(active_configuration.content) != configuration_checksum:
            now = datetime.datetime.utcnow()
            for configuration in self.session.query(ArchiveConfiguration).filter(ArchiveConfiguration.active == True).all():
                configuration.active = False
                configuration.active_until = now

            archive_configuration = ArchiveConfiguration(uuid.uuid4(), configuration_path, now, configuration_content)
            self.session.add(archive_configuration)
            self.session.commit()

    def _configuration_checksum(self, configuration_content):
        """
        Calculate a SHA-256 checksum for archive configuration text.

        :param configuration_content: raw XML archive configuration content
        :type configuration_content: str

        :return: hexadecimal SHA-256 checksum
        :rtype: str
        """
        return hashlib.sha256(configuration_content.encode("utf-8")).hexdigest()

    def _activate_root_directory(self, root_directory_path):
        """
        Ensure the supplied archive root directory is the only active root.

        :param root_directory_path: POSIX archive root directory path
        :type root_directory_path: str

        :return: None
        :rtype: None

        :raises ArchiveConfigurationError: when the root directory path is empty
        """
        if root_directory_path is None or root_directory_path.strip() == "":
            raise ArchiveConfigurationError("The archive root directory is not configured")

        root_directory_path = root_directory_path.strip()
        root_directory = self.query.get_active_root_directory()
        if root_directory is None or root_directory.path != root_directory_path:
            now = datetime.datetime.utcnow()
            for active_root_directory in self.session.query(ArchiveRootDirectory).filter(ArchiveRootDirectory.active == True).all():
                active_root_directory.active = False
                active_root_directory.active_until = now

            if not os.path.exists(root_directory_path):
                os.makedirs(root_directory_path, exist_ok=True)

            root_directory = ArchiveRootDirectory(uuid.uuid4(), root_directory_path, now)
            self.session.add(root_directory)
            self.session.commit()

    def _build_archived_file(
            self, file_path, archive_path, reception_date, archive_date,
            metadata, checksum, root_directory, archive_configuration=None,
            available=True, physically_available=True):
        """
        Build an archived-file row with the common metadata mapping.

        :param file_path: original input path
        :type file_path: str
        :param archive_path: path recorded in the archive inventory
        :type archive_path: str
        :param reception_date: reception timestamp
        :type reception_date: datetime.datetime
        :param archive_date: archive timestamp
        :type archive_date: datetime.datetime
        :param metadata: archive metadata
        :type metadata: dict
        :param checksum: file checksum, if available
        :type checksum: str or None
        :param root_directory: associated root-directory history entity
        :type root_directory: aboa.datamodel.archived_files.ArchiveRootDirectory
        :param archive_configuration: associated archive-configuration history entity
        :type archive_configuration: aboa.datamodel.archived_files.ArchiveConfiguration or None
        :param available: logical availability flag
        :type available: bool
        :param physically_available: whether the recorded payload exists physically
        :type physically_available: bool

        :return: archived-file inventory entity
        :rtype: aboa.datamodel.archived_files.ArchivedFile
        """
        file_size = os.path.getsize(archive_path) if os.path.exists(archive_path) else 0
        expiration_date = parse_datetime(metadata.get("expiration_date"))
        delete_archive_configuration = archive_configuration if expiration_date is not None else None
        return ArchivedFile(
            uuid.uuid4(),
            os.path.basename(file_path),
            archive_path,
            reception_date,
            archive_date,
            file_size,
            root_directory,
            archive_configuration=archive_configuration,
            delete_archive_configuration=delete_archive_configuration,
            available=available,
            physically_available=physically_available,
            file_group=metadata.get("file_group"),
            file_type=metadata.get("file_type"),
            file_class=metadata.get("file_class"),
            file_version=metadata.get("file_version"),
            validity_start_date=parse_datetime(metadata.get("validity_start_date")),
            validity_stop_date=parse_datetime(metadata.get("validity_stop_date")),
            generation_date=parse_datetime(metadata.get("generation_date")),
            expiration_date=expiration_date,
            checksum=checksum,
        )

    def _record_archive_failures(self, file_path, archive_path, reception_date, archive_date, metadata, checksum, failures, root_directory, archive_configuration=None):
        """
        Persist archive failure rows after creating their archived-file context.

        :param file_path: original input path
        :type file_path: str
        :param archive_path: path recorded in the archive inventory
        :type archive_path: str
        :param reception_date: reception timestamp
        :type reception_date: datetime.datetime
        :param archive_date: archive timestamp
        :type archive_date: datetime.datetime
        :param metadata: archive metadata
        :type metadata: dict
        :param checksum: file checksum, if available
        :type checksum: str or None
        :param failures: failure statuses and messages
        :type failures: list
        :param root_directory: associated root-directory history entity, if known
        :type root_directory: aboa.datamodel.archived_files.ArchiveRootDirectory or None
        :param archive_configuration: associated archive configuration entity, if known
        :type archive_configuration: aboa.datamodel.archived_files.ArchiveConfiguration or None

        :return: None
        :rtype: None
        """
        if root_directory is None:
            root_directory = self.query.get_active_root_directory()

        archived_file = None
        if root_directory is not None:
            archived_file = self._build_archived_file(
                file_path,
                archive_path,
                reception_date,
                archive_date,
                metadata,
                checksum,
                root_directory,
                archive_configuration,
                available=False,
                physically_available=os.path.exists(archive_path),
            )
            self.session.add(archived_file)

        for status, message in failures:
            self.record_failure("archive", status, message, archived_file)
        self.session.commit()

    def _execute_processor(self, processor_name, file_path):
        """
        Execute a configured file processor.

        :param processor_name: importable Python module name exposing ``process``
        :type processor_name: str
        :param file_path: path to the file being archived
        :type file_path: str

        :return: metadata extracted by the processor
        :rtype: dict

        :raises ProcessorError: when the processor cannot be imported or returns an
            unsupported value
        """
        try:
            processor_module = importlib.import_module(processor_name)
        except Exception as exc:
            raise ProcessorError("Processor {} cannot be imported: {}".format(processor_name, exc))
        if not hasattr(processor_module, "process"):
            raise ProcessorError("Processor {} does not expose a process function".format(processor_name))
        metadata = processor_module.process(file_path)
        if metadata is None:
            return {}
        if type(metadata) != dict:
            raise ProcessorError("Processor {} must return a dictionary".format(processor_name))
        return metadata

    def _build_destination_path(self, root_directory, target_directory, archive_date, file_name):
        """
        Build a collision-safe archive destination path.

        :param root_directory: active archive root directory
        :type root_directory: str
        :param target_directory: configured target directory, ``unknown``, or ``error``
        :type target_directory: str
        :param archive_date: archive timestamp used for YEAR/MONTH/DAY folders
        :type archive_date: datetime.datetime
        :param file_name: original file name
        :type file_name: str

        :return: destination file path
        :rtype: str
        """
        # Archive layout required by the plan: <directory>/YEAR/MONTH/DAY/file.
        directory = os.path.join(root_directory, target_directory, archive_date.strftime("%Y"), archive_date.strftime("%m"), archive_date.strftime("%d"))
        os.makedirs(directory, exist_ok=True)
        destination_path = os.path.join(directory, file_name)
        if not os.path.exists(destination_path):
            return destination_path

        # Preserve the original file name in metadata, but avoid overwriting an
        # existing archived payload on disk.
        base, extension = os.path.splitext(file_name)
        return os.path.join(directory, "{}_{}{}".format(base, uuid.uuid4(), extension))

    def _find_existing_duplicate_error_file(self, root_directory, archive_date, file_name, checksum):
        """
        Return an existing error-area copy for a duplicate reception, if present.

        Repeated duplicate inputs with the same file name and checksum should not
        create another physical copy in the same destination error folder.
        """
        if checksum is None:
            return None

        error_directory = os.path.join(
            root_directory,
            "error",
            archive_date.strftime("%Y"),
            archive_date.strftime("%m"),
            archive_date.strftime("%d"),
        )
        candidates = (
            self.session.query(ArchivedFile)
            .filter(ArchivedFile.name == file_name)
            .filter(ArchivedFile.checksum == checksum)
            .filter(ArchivedFile.physically_available == True)
            .order_by(ArchivedFile.archive_date.asc())
            .all()
        )
        for candidate in candidates:
            if not candidate.path.startswith(error_directory + os.sep):
                continue
            if not os.path.exists(candidate.path):
                candidate.physically_available = False
                continue
            try:
                if self._checksum(candidate.path) == checksum:
                    return candidate
            except Exception:
                logger.warning("Could not verify duplicate error payload {}".format(candidate.path))
        return None

    def _delete_input_file(self, file_path, archived_file):
        """
        Delete an input file after ABOA has recorded a managed copy.
        """
        if os.path.abspath(file_path) == os.path.abspath(archived_file.path):
            return
        try:
            os.unlink(file_path)
        except Exception as exc:
            message = exit_codes["INPUT_DELETE_FAILED"]["message"].format(file_path, exc)
            logger.error(message)
            self.record_failure("archive", exit_codes["INPUT_DELETE_FAILED"]["status"], message, archived_file)
            self.session.commit()
            raise ArchiveFileError(message)

    def move_archived_file_to_trash(self, archived_file, removal_date=None):
        """
        Move an archived payload to trash and queue it for final removal.

        :param archived_file: archived-file inventory row to move
        :type archived_file: aboa.datamodel.archived_files.ArchivedFile
        :param removal_date: logical removal timestamp used to schedule final removal
        :type removal_date: datetime.datetime or None

        :return: pending final-removal row, or None when no payload exists
        :rtype: aboa.datamodel.archived_files.FileToBeRemoved or None
        """
        if not os.path.exists(archived_file.path):
            file_to_be_removed = self._get_file_to_be_removed(archived_file)
            archived_file.physically_available = (
                file_to_be_removed is not None
                and os.path.exists(file_to_be_removed.path)
            )
            return file_to_be_removed

        removal_date = removal_date or datetime.datetime.utcnow()
        final_removal_date = removal_date + datetime.timedelta(days=self.final_removal_delay_days)
        root_directory = archived_file.rootDirectory
        if root_directory is None:
            root_directory = self.session.query(ArchiveRootDirectory).filter(
                ArchiveRootDirectory.root_directory_uuid == archived_file.root_directory_uuid
            ).first()
        trash_path = self._build_trash_path(root_directory.path, removal_date, archived_file)
        shutil.move(archived_file.path, trash_path)

        file_to_be_removed = self._get_file_to_be_removed(archived_file)
        if file_to_be_removed is None:
            file_to_be_removed = FileToBeRemoved(uuid.uuid4(), archived_file, trash_path, root_directory, final_removal_date)
            self.session.add(file_to_be_removed)
        else:
            file_to_be_removed.path = trash_path
            file_to_be_removed.rootDirectory = root_directory
            file_to_be_removed.removal_date = final_removal_date
        archived_file.physically_available = True
        return file_to_be_removed

    def delete_archived_file_permanently(self, archived_file):
        """
        Delete a managed payload immediately without moving it through trash.

        The inventory row is retained; callers that also need to remove metadata
        can call ``delete_archived_file_entries`` after this method has made the
        physical payload unavailable.

        :param archived_file: archived-file inventory row whose payload is removed
        :type archived_file: aboa.datamodel.archived_files.ArchivedFile

        :return: True when at least one filesystem payload was deleted
        :rtype: bool
        """
        deleted_payload = False
        if os.path.exists(archived_file.path):
            os.unlink(archived_file.path)
            deleted_payload = True

        for file_to_be_removed in self._get_files_to_be_removed(archived_file):
            if os.path.exists(file_to_be_removed.path):
                os.unlink(file_to_be_removed.path)
                deleted_payload = True
            self.session.delete(file_to_be_removed)

        archived_file.physically_available = False
        return deleted_payload

    def _get_file_to_be_removed(self, archived_file):
        """
        Return the pending final-removal row for an archived file, if present.
        """
        return (
            self.session.query(FileToBeRemoved)
            .filter(FileToBeRemoved.file_uuid == archived_file.file_uuid)
            .order_by(FileToBeRemoved.removal_date.desc())
            .first()
        )

    def _get_files_to_be_removed(self, archived_file):
        """
        Return all pending final-removal rows for an archived file.
        """
        return (
            self.session.query(FileToBeRemoved)
            .filter(FileToBeRemoved.file_uuid == archived_file.file_uuid)
            .order_by(FileToBeRemoved.removal_date.desc())
            .all()
        )

    def _sync_physical_availability(self, archived_file):
        """
        Refresh whether a managed payload exists in the archive path or trash.
        """
        physically_available = os.path.exists(archived_file.path)
        if not physically_available:
            physically_available = any(
                os.path.exists(file_to_be_removed.path)
                for file_to_be_removed in self._get_files_to_be_removed(archived_file)
            )
        archived_file.physically_available = physically_available
        return physically_available

    def _detach_archive_operations(self, archived_file):
        """
        Preserve operation rows while removing their archived-file foreign key.
        """
        for operation in (
            self.session.query(ArchiveOperation)
            .filter(ArchiveOperation.file_uuid == archived_file.file_uuid)
            .all()
        ):
            operation.archivedFile = None
            operation.file_uuid = None

    def _build_trash_path(self, root_directory, removal_date, archived_file):
        """
        Build a collision-safe trash path for an archived payload.

        :param root_directory: archive root directory path
        :type root_directory: str
        :param removal_date: timestamp when the file is moved to trash
        :type removal_date: datetime.datetime
        :param archived_file: archived-file inventory row being moved
        :type archived_file: aboa.datamodel.archived_files.ArchivedFile

        :return: trash destination path
        :rtype: str
        """
        directory = os.path.join(
            root_directory,
            self.trash_directory,
            removal_date.strftime("%Y"),
            removal_date.strftime("%m"),
            removal_date.strftime("%d"),
        )
        os.makedirs(directory, exist_ok=True)
        trash_name = os.path.basename(archived_file.path)
        trash_path = os.path.join(directory, trash_name)
        if not os.path.exists(trash_path):
            return trash_path

        base, extension = os.path.splitext(trash_name)
        return os.path.join(directory, "{}_{}{}".format(base, archived_file.file_uuid, extension))

    def _recover_file_from_trash(self, file_to_be_removed):
        """
        Move one pending trash payload back to its archived path.

        :param file_to_be_removed: trash-queue row to recover
        :type file_to_be_removed: aboa.datamodel.archived_files.FileToBeRemoved

        :return: recovered archived-file entity
        :rtype: aboa.datamodel.archived_files.ArchivedFile

        :raises ArchiveRecoveryError: when recovery would lose data or the trash
            payload is missing
        """
        archived_file = file_to_be_removed.archivedFile
        if archived_file is None:
            raise ArchiveRecoveryError("The trash row is not linked to an archived file")
        if not os.path.exists(file_to_be_removed.path):
            self._sync_physical_availability(archived_file)
            raise ArchiveRecoveryError("The trash payload {} does not exist".format(file_to_be_removed.path))
        if os.path.exists(archived_file.path):
            self._sync_physical_availability(archived_file)
            raise ArchiveRecoveryError("The archive payload {} already exists".format(archived_file.path))

        archive_directory = os.path.dirname(archived_file.path)
        if archive_directory != "":
            os.makedirs(archive_directory, exist_ok=True)
        shutil.move(file_to_be_removed.path, archived_file.path)

        archived_file.available = True
        archived_file.physically_available = True
        archived_file.removal_date = None
        archived_file.removal_justification = None
        archived_file.file_size = os.path.getsize(archived_file.path)
        if archived_file.expiration_date is not None and archived_file.deleteArchiveConfiguration is None:
            archived_file.deleteArchiveConfiguration = archived_file.archiveConfiguration
        self.session.delete(file_to_be_removed)
        return archived_file

    def _store_file(self, source_path, destination_path):
        """
        Store a file in the archive using a hard link with copy fallback.

        :param source_path: source file path
        :type source_path: str
        :param destination_path: archive destination path
        :type destination_path: str

        :return: None
        :rtype: None

        :raises OSError: when neither hard-linking nor copying can store the file
        """
        # Hard links are preferred because they are cheap on POSIX filesystems. The
        # copy fallback handles cross-device archives and filesystems without links.
        try:
            os.link(source_path, destination_path)
        except OSError:
            shutil.copy2(source_path, destination_path)

    def _checksum(self, file_path):
        """
        Calculate a SHA-256 checksum for a file.

        :param file_path: path to the file to hash
        :type file_path: str

        :return: hexadecimal SHA-256 checksum
        :rtype: str
        """
        # Stream large files instead of reading them fully into memory.
        digest = hashlib.sha256()
        with open(file_path, "rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def record_failure(self, operation, status, message, archived_file=None):
        """
        Add a failed operation row to the current session.

        :param operation: operation name, such as ``archive`` or ``retention``
        :type operation: str
        :param status: exit code status
        :type status: int
        :param message: failure details
        :type message: str
        :param archived_file: optional archived file related to the failure
        :type archived_file: aboa.datamodel.archived_files.ArchivedFile or None

        :return: None
        :rtype: None
        """
        operation_row = ArchiveOperation(uuid.uuid4(), operation, datetime.datetime.utcnow(), status, message=message, archived_file=archived_file)
        self.session.add(operation_row)
