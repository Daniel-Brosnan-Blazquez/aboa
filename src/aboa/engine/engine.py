"""
Engine definition for archive operations.

module aboa
"""

import datetime
import fnmatch
import hashlib
import importlib
import os
import shutil
import uuid

from lxml import etree
from sqlalchemy.orm import scoped_session

from aboa.datamodel.archived_files import (
    ArchivedFile,
    ArchiveOperation,
    ArchiveRootDirectory,
)
from aboa.datamodel.base import Base, Session, engine as sqlalchemy_engine
from aboa.engine.errors import ArchiveConfigurationError, ArchiveFileError, ProcessorError
from aboa.engine.functions import get_resources_path, parse_datetime
from aboa.engine.parsing import get_archive_configuration
from aboa.engine.query import Query
from aboa.logging import Log

logging = Log(name=__name__)
logger = logging.logger


def _xpath_match(context, source_mask, file_name):
    """
    XPath extension function to match file names against configured masks.
    """
    if isinstance(file_name, list):
        file_name = file_name[0] if file_name else ""
    masks = source_mask if isinstance(source_mask, list) else [source_mask]
    for mask in masks:
        if hasattr(mask, "text"):
            mask = mask.text
        if mask is not None and fnmatch.fnmatch(str(file_name), str(mask)):
            return True
    return False


xpath_namespace = etree.FunctionNamespace(None)
xpath_namespace["match"] = _xpath_match


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
        "message": "The delete operation ended unexpectedly with the error {}",
    },
    "RETRIEVE_FAILED": {
        "status": 9,
        "message": "The retrieve operation ended unexpectedly with the error {}",
    },
    "RETENTION_FAILED": {
        "status": 10,
        "message": "The retention operation ended unexpectedly with the error {}",
    },
    "ARCHIVE_FAILED": {
        "status": 11,
        "message": "The archive operation for file {} ended unexpectedly with the error {}",
    },
}


class Engine():
    """
    Class for managing ABOA archive mutations.

    The engine owns the write-side operations for the archive inventory. It stores
    metadata of archived files, status of failed archive operations and root-directory history in the database.
    Archive matching rules and retention policy keys remain runtime configuration loaded from XML.
    """

    def __init__(self, session=None):
        """
        Instantiate an archive engine.

        :param session: optional SQLAlchemy session supplied by tests or callers
        :type session: sqlalchemy.orm.session.Session or None
        """
        if session is None:
            Scoped_session = scoped_session(Session)
            self.session = Scoped_session()
        else:
            self.session = session
        self.query = Query(session=self.session)
        self.archive_xpath = None
        self._load_default_configuration()

    def close_session(self):
        """
        Close the underlying SQLAlchemy session.
        """
        self.session.close()

    def configure_archive(self, configuration_path):
        """
        Load and activate an archive configuration.

        The consolidated parser returns an XPath evaluator. The engine keeps that
        evaluator as runtime configuration and selects archive rules directly with
        XPath expressions, following the EBOA triggering pattern.

        :param configuration_path: XML archive configuration path
        :type configuration_path: str

        :return: active root-directory history entity
        :rtype: aboa.datamodel.archived_files.ArchiveRootDirectory

        :raises ArchiveConfigurationError: when the configuration is invalid
        """
        logger.info("Archive configuration request received for file {}".format(configuration_path))
        try:
            configuration_xpath = get_archive_configuration(configuration_path)
            root_directory_path = configuration_xpath("string(/archive_configurations/@root_directory)")
            now = datetime.datetime.utcnow()
            for root_directory in self.session.query(ArchiveRootDirectory).filter(ArchiveRootDirectory.active == True).all():
                root_directory.active = False
                root_directory.active_until = now
            root_directory = ArchiveRootDirectory(uuid.uuid4(), root_directory_path, now)
            self.session.add(root_directory)
            self.archive_xpath = configuration_xpath
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            message = exit_codes["CONFIGURATION_FAILED"]["message"].format(configuration_path, exc)
            logger.error(message)
            self._record_failure("configure", exit_codes["CONFIGURATION_FAILED"]["status"], message)
            self.session.commit()
            if isinstance(exc, ArchiveConfigurationError):
                raise
            raise ArchiveConfigurationError(message)

        logger.info("Archive configuration request performed for file {}".format(configuration_path))
        return root_directory

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

        :return: archived file inventory entity
        :rtype: aboa.datamodel.archived_files.ArchivedFile

        :raises ArchiveFileError: when the input file does not exist
        :raises ArchiveConfigurationError: when no active root directory is configured
        """
        logger.info("Archive request received for file {}".format(file_path))
        metadata = dict(metadata or {})
        reception_date = parse_datetime(reception_date) or datetime.datetime.utcnow()
        archive_date = datetime.datetime.utcnow()

        if not os.path.exists(file_path):
            message = exit_codes["FILE_DOES_NOT_EXIST"]["message"].format(file_path)
            logger.error(message)
            self._record_failure("archive", exit_codes["FILE_DOES_NOT_EXIST"]["status"], message)
            self.session.commit()
            raise ArchiveFileError(message)

        root_directory = self.query.get_active_root_directory()
        if root_directory is None:
            message = exit_codes["ROOT_DIRECTORY_NOT_CONFIGURED"]["message"]
            logger.error(message)
            self._record_failure("archive", exit_codes["ROOT_DIRECTORY_NOT_CONFIGURED"]["status"], message)
            self.session.commit()
            raise ArchiveConfigurationError(message)

        configuration = self._match_configuration(file_path)
        failures = []
        if configuration is None:
            # Requirement: files without a matching rule must still be archived.
            target_directory = "unknown"
            metadata.setdefault("file_group", "unknown")
            processor = None
        else:
            target_directory = self._configuration_node_text(configuration, "file_directory")
            metadata.setdefault("file_group", configuration.get("file_group"))
            processor = self._configuration_node_text(configuration, "file_processor", empty_as_none=True)

        try:
            if processor is not None:
                metadata.update(self._execute_processor(processor, file_path))
        except Exception as exc:
            # Processor failures are recoverable business failures: archive the file
            # in the error area and persist the failure operation.
            error_message = exit_codes["PROCESSOR_FAILED"]["message"].format(file_path, processor, exc)
            failures.append((exit_codes["PROCESSOR_FAILED"]["status"], error_message))
            target_directory = "error"
            logger.error(error_message)

        try:
            checksum = self._checksum(file_path)
        except Exception as exc:
            message = exit_codes["ARCHIVE_FAILED"]["message"].format(file_path, exc)
            logger.error(message)
            self._record_failure("archive", exit_codes["ARCHIVE_FAILED"]["status"], message)
            self.session.commit()
            raise ArchiveFileError(message)

        if self.session.query(ArchivedFile).filter(ArchivedFile.checksum == checksum, ArchivedFile.available == True).first() is not None:
            # Duplicate reception follows the same recoverable path as processor
            # failures so the received file remains under ABOA control.
            error_message = exit_codes["FILE_ALREADY_ARCHIVED"]["message"].format(file_path)
            failures.append((exit_codes["FILE_ALREADY_ARCHIVED"]["status"], error_message))
            target_directory = "error"
            logger.error(error_message)

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
                self._record_failure("archive", exit_codes["FILE_STORAGE_FAILED"]["status"], message)
                self.session.commit()
                raise ArchiveFileError(message)

        archived_file = ArchivedFile(
            uuid.uuid4(),
            os.path.basename(file_path),
            destination_path,
            reception_date,
            archive_date,
            os.path.getsize(destination_path),
            root_directory,
            file_group=metadata.get("file_group"),
            file_type=metadata.get("file_type"),
            file_class=metadata.get("file_class"),
            file_version=metadata.get("file_version"),
            validity_start_date=parse_datetime(metadata.get("validity_start_date")),
            validity_stop_date=parse_datetime(metadata.get("validity_stop_date")),
            generation_date=parse_datetime(metadata.get("generation_date")),
            expiration_date=parse_datetime(metadata.get("expiration_date")),
            checksum=checksum,
        )
        self.session.add(archived_file)
        for status, message in failures:
            self._record_failure("archive", status, message, archived_file)
        self.session.commit()

        if delete:
            # The input is removed only after the file has been stored under ABOA
            # management and the inventory transaction has committed.
            try:
                os.unlink(file_path)
            except Exception as exc:
                message = exit_codes["INPUT_DELETE_FAILED"]["message"].format(file_path, exc)
                logger.error(message)
                self._record_failure("archive", exit_codes["INPUT_DELETE_FAILED"]["status"], message, archived_file)
                self.session.commit()
                raise ArchiveFileError(message)

        logger.info("Archive request performed for file {}".format(file_path))
        return archived_file

    def retrieve_files(self, filters=None, order_by=None, group_by=None, selection="all", limit=None, offset=None):
        """
        Retrieve archived file inventory entries and update last-access metadata.

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

        :return: list of archived files, or grouped dictionary when ``group_by`` is set
        :rtype: list or dict
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
            now = datetime.datetime.utcnow()
            for archived_file in iterable:
                archived_file.last_access_date = now
            self.session.commit()
            return files
        except Exception as exc:
            self.session.rollback()
            message = exit_codes["RETRIEVE_FAILED"]["message"].format(exc)
            logger.error(message)
            self._record_failure("retrieve", exit_codes["RETRIEVE_FAILED"]["status"], message)
            self.session.commit()
            raise

    def delete_files(self, filters=None, file_uuids=None, physical_delete=False):
        """
        Delete archived files logically and optionally remove physical payloads.

        :param filters: query filters accepted by ``Query.get_archived_files``
        :type filters: dict or None
        :param file_uuids: optional list of file UUIDs to delete
        :type file_uuids: list or None
        :param physical_delete: remove files from the POSIX archive when true
        :type physical_delete: bool

        :return: deleted archive inventory entities
        :rtype: list
        """
        try:
            filters = dict(filters or {})
            if file_uuids is not None:
                filters["file_uuids"] = {"filter": file_uuids, "op": "in"}
            files = self.query.get_archived_files(**filters)
            now = datetime.datetime.utcnow()
            for archived_file in files:
                # Logical deletion is the default behavior. Physical deletion is an
                # explicit caller choice and still leaves the inventory row for trace.
                archived_file.available = False
                archived_file.removal_date = now
                if physical_delete and os.path.exists(archived_file.path):
                    os.unlink(archived_file.path)
            self.session.commit()
            logger.info("Delete request performed on {} file/s".format(len(files)))
            return files
        except Exception as exc:
            self.session.rollback()
            message = exit_codes["DELETE_FAILED"]["message"].format(exc)
            logger.error(message)
            self._record_failure("delete", exit_codes["DELETE_FAILED"]["status"], message)
            self.session.commit()
            raise

    def apply_retention(self, policy_names=None, dry_run=False):
        """
        Apply runtime XML retention policies to archived files.

        :param policy_names: optional policy keys to execute
        :type policy_names: list or None
        :param dry_run: return candidates without changing inventory or filesystem
        :type dry_run: bool

        :return: retention candidate or affected archived files
        :rtype: list
        """
        # Imported lazily to avoid a module cycle: retention works on Engine and
        # Engine exposes this convenience wrapper.
        from aboa.engine.retention import apply_retention
        try:
            return apply_retention(self, policy_names=policy_names, dry_run=dry_run)
        except Exception as exc:
            self.session.rollback()
            message = exit_codes["RETENTION_FAILED"]["message"].format(exc)
            logger.error(message)
            self._record_failure("retention", exit_codes["RETENTION_FAILED"]["status"], message)
            self.session.commit()
            raise

    def _match_configuration(self, file_path):
        """
        Find the first archive rule matching a file name.

        :param file_path: path to the received file
        :type file_path: str

        :return: matching XML archive rule or None
        :rtype: lxml.etree._Element or None
        """
        if self.archive_xpath is None:
            return None
        file_name = os.path.basename(file_path)
        matching_configurations = self.archive_xpath(
            "/archive_configurations/archive_configuration[match(file_mask, $file_name)]",
            file_name=file_name,
        )
        if len(matching_configurations) == 0:
            return None
        return matching_configurations[0]

    def get_active_retention_policies(self, policy_names=None):
        """
        Select active retention policies directly from the archive configuration XML.

        :param policy_names: optional list of policy keys to select
        :type policy_names: list or None

        :return: active retention policy XML nodes
        :rtype: list
        """
        if self.archive_xpath is None:
            return []
        policies = self.archive_xpath(
            "/archive_configurations/retention_policies/retention_policy[@active='true' or @active='1'] | "
            "/archive_configurations/archive_configuration/retention_policy[@active='true' or @active='1']"
        )
        if policy_names is not None:
            policies = [policy for policy in policies if policy.get("key") in policy_names]
        return policies

    def _configuration_node_text(self, configuration_node, child_name, empty_as_none=False):
        """
        Return stripped child text from an archive configuration XML node.
        """
        text = configuration_node.xpath("string({})".format(child_name)).strip()
        if empty_as_none and text == "":
            return None
        return text

    def _load_default_configuration(self):
        """
        Load ``archive_configurations.xml`` from ``ABOA_RESOURCES_PATH`` if present.
        """
        # Loading the default XML is best-effort so tests and scripts can construct
        # an engine before a configuration file exists.
        try:
            configuration_path = os.path.join(get_resources_path(), "archive_configurations.xml")
        except Exception:
            return
        if not os.path.exists(configuration_path):
            return
        try:
            self.archive_xpath = get_archive_configuration(configuration_path)
        except Exception:
            return

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

    def _store_file(self, source_path, destination_path):
        """
        Store a file in the archive using a hard link with copy fallback.

        :param source_path: source file path
        :type source_path: str
        :param destination_path: archive destination path
        :type destination_path: str
        """
        # Hard links are preferred because they are cheap on POSIX filesystems. The
        # copy fallback handles cross-device archives and filesystems without links.
        try:
            os.link(source_path, destination_path)
        except OSError:
            shutil.copy2(source_path, destination_path)

    def _checksum(self, file_path):
        """
        Calculate an MD5 checksum for a file.

        :param file_path: path to the file to hash
        :type file_path: str

        :return: hexadecimal MD5 checksum
        :rtype: str
        """
        # Stream large files instead of reading them fully into memory.
        digest = hashlib.md5()
        with open(file_path, "rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _record_failure(self, operation, status, message, archived_file=None):
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
        """
        operation_row = ArchiveOperation(uuid.uuid4(), operation, datetime.datetime.utcnow(), status, message=message, archived_file=archived_file)
        self.session.add(operation_row)
