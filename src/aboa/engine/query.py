"""
Query interface for the ABOA inventory.

module aboa
"""

import datetime

from sqlalchemy.orm import scoped_session

from aboa.datamodel.archived_files import (
    ArchiveConfiguration,
    ArchivedFile,
    ArchiveOperation,
    ArchiveRootDirectory,
)
from aboa.datamodel.base import Base, Session, engine
from aboa.engine import functions
from aboa.engine.errors import InputError
from aboa.engine.operators import arithmetic_operators, text_operators


class Query():
    """
    Class for querying data stored in the ABOA inventory.

    The query interface accepts ABOA filter dictionaries while mapping all
    fields and operators explicitly to SQLAlchemy expressions.
    """

    # Public filter names map to SQLAlchemy columns explicitly. This keeps the public
    # filter API shape while avoiding eval-based query construction.
    text_fields = {
        "file_uuids": ArchivedFile.file_uuid,
        "names": ArchivedFile.name,
        "paths": ArchivedFile.path,
        "file_group": ArchivedFile.file_group,
        "file_type": ArchivedFile.file_type,
        "file_class": ArchivedFile.file_class,
        "file_version": ArchivedFile.file_version,
        "archive_configuration_uuids": ArchivedFile.archive_configuration_uuid,
        "delete_archive_configuration_uuids": ArchivedFile.delete_archive_configuration_uuid,
        "removal_justification": ArchivedFile.removal_justification,
    }
    date_fields = {
        "reception_date_filters": ArchivedFile.reception_date,
        "archive_date_filters": ArchivedFile.archive_date,
        "last_access_date_filters": ArchivedFile.last_access_date,
        "validity_start_date_filters": ArchivedFile.validity_start_date,
        "validity_stop_date_filters": ArchivedFile.validity_stop_date,
        "generation_date_filters": ArchivedFile.generation_date,
        "expiration_date_filters": ArchivedFile.expiration_date,
        "removal_date_filters": ArchivedFile.removal_date,
    }
    order_fields = {
        "file_uuid": ArchivedFile.file_uuid,
        "name": ArchivedFile.name,
        "path": ArchivedFile.path,
        "reception_date": ArchivedFile.reception_date,
        "archive_date": ArchivedFile.archive_date,
        "file_size": ArchivedFile.file_size,
        "available": ArchivedFile.available,
        "last_access_date": ArchivedFile.last_access_date,
        "file_group": ArchivedFile.file_group,
        "file_type": ArchivedFile.file_type,
        "file_class": ArchivedFile.file_class,
        "file_version": ArchivedFile.file_version,
        "validity_start_date": ArchivedFile.validity_start_date,
        "validity_stop_date": ArchivedFile.validity_stop_date,
        "generation_date": ArchivedFile.generation_date,
        "expiration_date": ArchivedFile.expiration_date,
        "removal_date": ArchivedFile.removal_date,
        "removal_justification": ArchivedFile.removal_justification,
        "archive_configuration_uuid": ArchivedFile.archive_configuration_uuid,
        "delete_archive_configuration_uuid": ArchivedFile.delete_archive_configuration_uuid,
    }
    archive_root_directory_text_fields = {
        "root_directory_uuids": ArchiveRootDirectory.root_directory_uuid,
        "paths": ArchiveRootDirectory.path,
    }
    archive_root_directory_date_fields = {
        "active_from_date_filters": ArchiveRootDirectory.active_from,
        "active_until_date_filters": ArchiveRootDirectory.active_until,
    }
    archive_root_directory_order_fields = {
        "root_directory_uuid": ArchiveRootDirectory.root_directory_uuid,
        "path": ArchiveRootDirectory.path,
        "active_from": ArchiveRootDirectory.active_from,
        "active_until": ArchiveRootDirectory.active_until,
        "active": ArchiveRootDirectory.active,
    }
    archive_configuration_text_fields = {
        "archive_configuration_uuids": ArchiveConfiguration.archive_configuration_uuid,
        "paths": ArchiveConfiguration.path,
        "contents": ArchiveConfiguration.content,
    }
    archive_configuration_date_fields = {
        "active_from_date_filters": ArchiveConfiguration.active_from,
        "active_until_date_filters": ArchiveConfiguration.active_until,
    }
    archive_configuration_order_fields = {
        "archive_configuration_uuid": ArchiveConfiguration.archive_configuration_uuid,
        "path": ArchiveConfiguration.path,
        "active_from": ArchiveConfiguration.active_from,
        "active_until": ArchiveConfiguration.active_until,
        "active": ArchiveConfiguration.active,
        "content": ArchiveConfiguration.content,
    }
    archive_operation_text_fields = {
        "operation_uuids": ArchiveOperation.operation_uuid,
        "operations": ArchiveOperation.operation,
        "messages": ArchiveOperation.message,
        "file_uuids": ArchiveOperation.file_uuid,
    }
    archive_operation_date_fields = {
        "time_stamp_filters": ArchiveOperation.time_stamp,
    }
    archive_operation_number_fields = {
        "status_filters": ArchiveOperation.status,
    }
    archive_operation_order_fields = {
        "operation_uuid": ArchiveOperation.operation_uuid,
        "operation": ArchiveOperation.operation,
        "time_stamp": ArchiveOperation.time_stamp,
        "status": ArchiveOperation.status,
        "message": ArchiveOperation.message,
        "file_uuid": ArchiveOperation.file_uuid,
    }

    def __init__(self, session=None):
        """
        Instantiate a query interface.

        :param session: optional SQLAlchemy session supplied by callers or tests
        :type session: sqlalchemy.orm.session.Session or None
        """
        if session is None:
            Scoped_session = scoped_session(Session)
            self.session = Scoped_session()
        else:
            self.session = session

    def clear_db(self):
        """
        Delete all ABOA inventory rows.

        This helper is intended for tests and initialization workflows.
        """
        for table in reversed(Base.metadata.sorted_tables):
            self.session.execute(table.delete())
        self.session.commit()

    def close_session(self):
        """
        Close the underlying SQLAlchemy session.
        """
        self.session.close()

    def get_active_root_directory(self):
        """
        Return the most recently activated root directory.

        :return: active root directory entity or None
        :rtype: aboa.datamodel.archived_files.ArchiveRootDirectory or None
        """
        return self.session.query(ArchiveRootDirectory).filter(ArchiveRootDirectory.active == True).order_by(ArchiveRootDirectory.active_from.desc()).first()

    def get_active_archive_configuration(self):
        """
        Return the most recently activated archive configuration.

        :return: active archive configuration entity or None
        :rtype: aboa.datamodel.archived_files.ArchiveConfiguration or None
        """
        return self.session.query(ArchiveConfiguration).filter(ArchiveConfiguration.active == True).order_by(ArchiveConfiguration.active_from.desc()).first()

    def get_archived_files(self, file_uuids=None, names=None, paths=None,
                           reception_date_filters=None, archive_date_filters=None,
                           file_size_filters=None, available=None,
                           last_access_date_filters=None, file_group=None,
                           file_type=None, file_class=None, file_version=None,
                           archive_configuration_uuids=None,
                           delete_archive_configuration_uuids=None,
                           validity_start_date_filters=None, validity_stop_date_filters=None,
                           generation_date_filters=None, expiration_date_filters=None,
                           removal_date_filters=None, removal_justification=None,
                           order_by=None, group_by=None,
                           selection="all", limit=None, offset=None):
        """
        Query archived files by metadata filters.

        :param file_uuids: UUID text filter
        :param names: file name text filter
        :param paths: archive path text filter
        :param reception_date_filters: reception date filters
        :param archive_date_filters: archive date filters
        :param file_size_filters: file size numeric filters
        :param available: availability boolean filter
        :param last_access_date_filters: last access date filters
        :param file_group: file group text filter
        :param file_type: file type text filter
        :param file_class: file class text filter
        :param file_version: file version text filter
        :param archive_configuration_uuids: archive-configuration UUID text filter
        :param delete_archive_configuration_uuids: delete archive-configuration UUID text filter
        :param validity_start_date_filters: validity start date filters
        :param validity_stop_date_filters: validity stop date filters
        :param generation_date_filters: generation date filters
        :param expiration_date_filters: expiration date filters
        :param removal_date_filters: removal date filters
        :param removal_justification: removal reason text filter
        :param order_by: ordering descriptor with field and descending keys
        :param group_by: field used to group complete entity results
        :param selection: selection rule: all, first, or last
        :param limit: maximum number of rows
        :param offset: result offset

        :return: list of archived files, or grouped dictionary when group_by is set
        :rtype: list or dict

        :raises InputError: when filters, ordering, grouping, or selection are invalid
        """
        params = []
        values = locals()

        # Build filter predicates from the supported metadata groups.
        for argument_name, column in self.text_fields.items():
            value = values[argument_name]
            if value is not None:
                functions.is_valid_text_filter(value)
                params.append(self._build_text_filter(column, value))

        for argument_name, column in self.date_fields.items():
            value = values[argument_name]
            if value is not None:
                functions.is_valid_date_filters(value)
                for date_filter in value:
                    params.append(arithmetic_operators[date_filter["op"]](column, functions.parse_datetime(date_filter["date"])))

        if file_size_filters is not None:
            functions.is_valid_number_filters(file_size_filters)
            for number_filter in file_size_filters:
                params.append(arithmetic_operators[number_filter["op"]](ArchivedFile.file_size, number_filter["number"]))

        if available is not None:
            functions.is_valid_bool_filter(available)
            params.append(arithmetic_operators[available["op"]](ArchivedFile.available, available["filter"]))

        query = self.session.query(ArchivedFile).filter(*params)

        return self._finish_query(
            query,
            self.order_fields,
            ArchivedFile.archive_date.desc(),
            group_by=group_by,
            order_by=order_by,
            selection=selection,
            limit=limit,
            offset=offset,
        )

    def get_archive_root_directories(self, root_directory_uuids=None, paths=None,
                                     active_from_date_filters=None,
                                     active_until_date_filters=None, active=None,
                                     order_by=None, group_by=None, selection="all",
                                     limit=None, offset=None):
        """
        Query archive root-directory history rows.

        :param root_directory_uuids: root-directory UUID text filter
        :param paths: POSIX path text filter
        :param active_from_date_filters: activation date filters
        :param active_until_date_filters: deactivation date filters
        :param active: active boolean filter
        :param order_by: ordering descriptor with field and descending keys
        :param group_by: field used to group complete entity results
        :param selection: selection rule: all, first, or last
        :param limit: maximum number of rows
        :param offset: result offset

        :return: list of archive root directories, or grouped dictionary
        :rtype: list or dict

        :raises InputError: when filters, ordering, grouping, or selection are invalid
        """
        params = []
        values = locals()

        for argument_name, column in self.archive_root_directory_text_fields.items():
            value = values[argument_name]
            if value is not None:
                functions.is_valid_text_filter(value)
                params.append(self._build_text_filter(column, value))

        for argument_name, column in self.archive_root_directory_date_fields.items():
            value = values[argument_name]
            if value is not None:
                functions.is_valid_date_filters(value)
                for date_filter in value:
                    params.append(arithmetic_operators[date_filter["op"]](column, functions.parse_datetime(date_filter["date"])))

        if active is not None:
            functions.is_valid_bool_filter(active)
            params.append(arithmetic_operators[active["op"]](ArchiveRootDirectory.active, active["filter"]))

        query = self.session.query(ArchiveRootDirectory).filter(*params)
        return self._finish_query(
            query,
            self.archive_root_directory_order_fields,
            ArchiveRootDirectory.active_from.desc(),
            group_by=group_by,
            order_by=order_by,
            selection=selection,
            limit=limit,
            offset=offset,
        )

    def get_archive_configurations(self, archive_configuration_uuids=None,
                                   paths=None, contents=None,
                                   active_from_date_filters=None,
                                   active_until_date_filters=None, active=None,
                                   order_by=None, group_by=None, selection="all",
                                   limit=None, offset=None):
        """
        Query archive-configuration history rows.

        :param archive_configuration_uuids: archive-configuration UUID text filter
        :param paths: source XML path text filter
        :param contents: raw XML content text filter
        :param active_from_date_filters: activation date filters
        :param active_until_date_filters: deactivation date filters
        :param active: active boolean filter
        :param order_by: ordering descriptor with field and descending keys
        :param group_by: field used to group complete entity results
        :param selection: selection rule: all, first, or last
        :param limit: maximum number of rows
        :param offset: result offset

        :return: list of archive configurations, or grouped dictionary
        :rtype: list or dict

        :raises InputError: when filters, ordering, grouping, or selection are invalid
        """
        params = []
        values = locals()

        for argument_name, column in self.archive_configuration_text_fields.items():
            value = values[argument_name]
            if value is not None:
                functions.is_valid_text_filter(value)
                params.append(self._build_text_filter(column, value))

        for argument_name, column in self.archive_configuration_date_fields.items():
            value = values[argument_name]
            if value is not None:
                functions.is_valid_date_filters(value)
                for date_filter in value:
                    params.append(arithmetic_operators[date_filter["op"]](column, functions.parse_datetime(date_filter["date"])))

        if active is not None:
            functions.is_valid_bool_filter(active)
            params.append(arithmetic_operators[active["op"]](ArchiveConfiguration.active, active["filter"]))

        query = self.session.query(ArchiveConfiguration).filter(*params)
        return self._finish_query(
            query,
            self.archive_configuration_order_fields,
            ArchiveConfiguration.active_from.desc(),
            group_by=group_by,
            order_by=order_by,
            selection=selection,
            limit=limit,
            offset=offset,
        )

    def get_archive_operations(self, operation_uuids=None, operations=None,
                               time_stamp_filters=None, status_filters=None,
                               messages=None, file_uuids=None, order_by=None,
                               group_by=None, selection="all", limit=None,
                               offset=None):
        """
        Query persisted archive operation failures.

        Successful operations are log-only, so this method returns rows for failed
        archive, retrieve, delete, configure, and retention operations.

        :param operation_uuids: operation UUID text filter
        :param operations: operation-name text filter
        :param time_stamp_filters: operation timestamp filters
        :param status_filters: status numeric filters
        :param messages: failure message text filter
        :param file_uuids: related archived-file UUID text filter
        :param order_by: ordering descriptor with field and descending keys
        :param group_by: field used to group complete entity results
        :param selection: selection rule: all, first, or last
        :param limit: maximum number of rows
        :param offset: result offset

        :return: list of archive operations, or grouped dictionary
        :rtype: list or dict

        :raises InputError: when filters, ordering, grouping, or selection are invalid
        """
        params = []
        values = locals()

        for argument_name, column in self.archive_operation_text_fields.items():
            value = values[argument_name]
            if value is not None:
                functions.is_valid_text_filter(value)
                params.append(self._build_text_filter(column, value))

        for argument_name, column in self.archive_operation_date_fields.items():
            value = values[argument_name]
            if value is not None:
                functions.is_valid_date_filters(value)
                for date_filter in value:
                    params.append(arithmetic_operators[date_filter["op"]](column, functions.parse_datetime(date_filter["date"])))

        for argument_name, column in self.archive_operation_number_fields.items():
            value = values[argument_name]
            if value is not None:
                functions.is_valid_number_filters(value)
                for number_filter in value:
                    params.append(arithmetic_operators[number_filter["op"]](column, number_filter["number"]))

        query = self.session.query(ArchiveOperation).filter(*params)
        return self._finish_query(
            query,
            self.archive_operation_order_fields,
            ArchiveOperation.time_stamp.desc(),
            group_by=group_by,
            order_by=order_by,
            selection=selection,
            limit=limit,
            offset=offset,
        )

    def _finish_query(self, query, order_fields, default_last_order,
                      group_by=None, order_by=None, selection="all", limit=None,
                      offset=None):
        """
        Apply grouping, ordering, selection, and pagination to an entity query.

        :param query: SQLAlchemy query to modify
        :param order_fields: fields accepted by order_by and group_by
        :type order_fields: dict
        :param default_last_order: default descending order for last selection
        :param group_by: optional entity field used to group full entity rows
        :param order_by: optional ordering descriptor
        :param selection: selection rule: all, first, or last
        :param limit: maximum number of rows
        :param offset: result offset

        :return: list of entities, or grouped dictionary when group_by is set
        :rtype: list or dict
        """
        if group_by is not None:
            if group_by not in order_fields:
                raise InputError("The group_by field {} is not valid".format(group_by))
            rows = query.all()
            grouped = {}
            for row in rows:
                # Grouping is performed in Python so callers receive complete entity
                # objects instead of aggregate rows.
                grouped.setdefault(getattr(row, group_by), []).append(row)
            return grouped

        if order_by is not None:
            functions.is_valid_order_by(order_by)
            if order_by["field"] not in order_fields:
                raise InputError("The order_by field {} is not valid".format(order_by["field"]))
            order_statement = order_fields[order_by["field"]]
            if order_by["descending"]:
                order_statement = order_statement.desc()
            query = query.order_by(order_statement)

        if selection not in ("all", "first", "last"):
            raise InputError("The selection parameter must be all, first or last")
        if selection == "last":
            # "last" is defined relative to the caller's ordering. Reverse that
            # ordering and reuse first() to avoid loading the full result set.
            query = self._reverse_query_order(query, order_by, order_fields, default_last_order)

        if limit is not None:
            functions.is_valid_positive_integer(limit)
            query = query.limit(limit)
        if offset is not None:
            functions.is_valid_positive_integer(offset)
            query = query.offset(offset)

        if selection in ("first", "last"):
            result = query.first()
            return [] if result is None else [result]
        return query.all()

    def _build_text_filter(self, column, text_filter):
        """
        Build a SQLAlchemy predicate from an ABOA text filter.

        :param column: SQLAlchemy column to filter
        :param text_filter: filter dictionary with filter and op keys
        :type text_filter: dict

        :return: SQLAlchemy predicate
        """
        op = text_filter["op"]
        if op in ("in", "notin"):
            return getattr(column, text_operators[op])(text_filter["filter"])
        return getattr(column, text_operators[op])(text_filter["filter"])

    def _reverse_query_order(self, query, order_by, order_fields=None, default_order=None):
        """
        Reverse query ordering for the ``last`` selection rule.

        :param query: SQLAlchemy query to modify
        :param order_by: original order descriptor
        :type order_by: dict or None
        :param order_fields: fields accepted by order_by
        :type order_fields: dict or None
        :param default_order: default ordering when no order_by is supplied

        :return: query with reversed order
        """
        if order_fields is None:
            order_fields = self.order_fields
        if default_order is None:
            default_order = ArchivedFile.archive_date.desc()
        if order_by is None:
            return query.order_by(default_order)
        reverse_order_by = {"field": order_by["field"], "descending": not order_by["descending"]}
        order_statement = order_fields[reverse_order_by["field"]]
        if reverse_order_by["descending"]:
            order_statement = order_statement.desc()
        return query.order_by(None).order_by(order_statement)
