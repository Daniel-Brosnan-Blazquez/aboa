"""
Command line utilities for ABOA.

module aboa
"""

import argparse
import datetime
import json
import os

from aboa.engine.errors import ArchiveDeletionError, ArchiveFileError, ArchiveRecoveryError
from aboa.engine.engine import Engine
from aboa.engine.functions import parse_datetime
from aboa.engine.operators import arithmetic_operators, text_operators
from aboa.engine.query import Query
from aboa.engine.retention import apply_final_removal, apply_retention
from aboa.logging import Log

logging = Log(name=__name__)
logger = logging.logger

TEXT_OPERATOR_NAMES = sorted(text_operators.keys())
ARITHMETIC_OPERATOR_NAMES = sorted(arithmetic_operators.keys(), key=len, reverse=True)

ARCHIVED_FILE_TEXT_FILTERS = (
    {
        "dest": "file_uuids",
        "long": "--uuid",
        "short": "-u",
        "default_op": "in",
        "help": "archived file UUID; repeat to match several UUIDs",
    },
    {
        "dest": "names",
        "long": "--name",
        "short": "-n",
        "default_op": "like",
        "help": "file name filter",
    },
    {
        "dest": "paths",
        "long": "--path",
        "short": "-p",
        "default_op": "like",
        "help": "archive path filter",
    },
    {
        "dest": "root_directory_uuids",
        "long": "--root-directory-uuid",
        "short": "-r",
        "default_op": "in",
        "help": "archive root-directory UUID; repeat to match several UUIDs",
    },
    {
        "dest": "file_group",
        "long": "--file-group",
        "short": "-g",
        "default_op": "like",
        "help": "file group metadata filter",
    },
    {
        "dest": "file_type",
        "long": "--file-type",
        "short": "-t",
        "default_op": "like",
        "help": "file type metadata filter",
    },
    {
        "dest": "file_class",
        "long": "--file-class",
        "short": "-c",
        "default_op": "like",
        "help": "file class metadata filter",
    },
    {
        "dest": "file_version",
        "long": "--file-version",
        "short": "-v",
        "default_op": "like",
        "help": "file version metadata filter",
    },
    {
        "dest": "archive_configuration_uuids",
        "long": "--archive-configuration-uuid",
        "short": "-a",
        "default_op": "in",
        "help": "archive-configuration UUID; repeat to match several UUIDs",
    },
    {
        "dest": "delete_archive_configuration_uuids",
        "long": "--delete-archive-configuration-uuid",
        "short": "-q",
        "default_op": "in",
        "help": "delete archive-configuration UUID; repeat to match several UUIDs",
    },
    {
        "dest": "removal_justification",
        "long": "--removal-justification",
        "short": "-j",
        "default_op": "like",
        "help": "logical removal justification filter",
    },
    {
        "dest": "checksum",
        "long": "--checksum",
        "short": "-k",
        "default_op": "like",
        "help": "checksum metadata filter",
    },
)

ARCHIVED_FILE_DATE_FILTERS = (
    {
        "dest": "reception_date_filters",
        "long": "--reception-date",
        "short": "-R",
        "help": "reception date filter",
    },
    {
        "dest": "archive_date_filters",
        "long": "--archive-date",
        "short": "-A",
        "help": "archive date filter",
    },
    {
        "dest": "last_access_date_filters",
        "long": "--last-access-date",
        "short": "-L",
        "help": "last access date filter",
    },
    {
        "dest": "validity_start_date_filters",
        "long": "--validity-start-date",
        "short": "-S",
        "help": "validity start date filter",
    },
    {
        "dest": "validity_stop_date_filters",
        "long": "--validity-stop-date",
        "short": "-T",
        "help": "validity stop date filter",
    },
    {
        "dest": "generation_date_filters",
        "long": "--generation-date",
        "short": "-G",
        "help": "generation date filter",
    },
    {
        "dest": "expiration_date_filters",
        "long": "--expiration-date",
        "short": "-E",
        "help": "expiration date filter",
    },
    {
        "dest": "removal_date_filters",
        "long": "--removal-date",
        "short": "-M",
        "help": "logical removal date filter",
    },
)

TRASH_TEXT_FILTERS = (
    {
        "dest": "trash_file_to_remove_uuids",
        "query_dest": "file_to_remove_uuids",
        "long": "--trash-uuid",
        "short": "-U",
        "default_op": "in",
        "help": "trash queue UUID; repeat to match several UUIDs",
    },
    {
        "dest": "trash_paths",
        "query_dest": "paths",
        "long": "--trash-path",
        "short": "-w",
        "default_op": "like",
        "help": "trash payload path filter",
    },
    {
        "dest": "trash_root_directory_uuids",
        "query_dest": "root_directory_uuids",
        "long": "--trash-root-directory-uuid",
        "short": "-W",
        "default_op": "in",
        "help": "trash root-directory UUID; repeat to match several UUIDs",
    },
)

TRASH_DATE_FILTERS = (
    {
        "dest": "trash_removal_date_filters",
        "query_dest": "removal_date_filters",
        "long": "--trash-removal-date",
        "short": "-Q",
        "help": "scheduled final-removal date filter",
    },
)


def _print_json(payload):
    """
    Print a JSON payload using the formatting expected by ABOA commands.
    """
    print(json.dumps(payload, indent=2, sort_keys=True))


def _exit_with_error(parser, message):
    """
    Exit a command cleanly for an expected engine-domain error.
    """
    parser.exit(status=1, message="error: {}\n".format(message))


def _jsonify_rows(rows):
    """
    Serialize a list or grouped dictionary of SQLAlchemy entities.
    """
    if isinstance(rows, dict):
        return {
            str(group): [row.jsonify() for row in group_rows]
            for group, group_rows in rows.items()
        }
    return [row.jsonify() for row in rows]


def _parse_arithmetic_filter(raw_value, value_key):
    """
    Parse CLI arithmetic filters written as VALUE or OP:VALUE.
    """
    value = str(raw_value).strip()
    for operator_name in ARITHMETIC_OPERATOR_NAMES:
        if value.startswith(operator_name):
            filter_value = value[len(operator_name):]
            if filter_value.startswith(":"):
                filter_value = filter_value[1:]
            if filter_value == "":
                raise argparse.ArgumentTypeError("missing value after operator {}".format(operator_name))
            return {"op": operator_name, value_key: filter_value}
    return {"op": "==", value_key: value}


def _parse_number_filter(raw_value):
    """
    Parse a numeric filter and convert the filter value to a number.
    """
    number_filter = _parse_arithmetic_filter(raw_value, "number")
    number_text = number_filter["number"]
    try:
        if "." in number_text:
            number_filter["number"] = float(number_text)
        else:
            number_filter["number"] = int(number_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("{} is not a valid number".format(number_text)) from exc
    return number_filter


def _parse_bool_filter(raw_value):
    """
    Parse a boolean filter written as VALUE or OP:VALUE.
    """
    bool_filter = _parse_arithmetic_filter(raw_value, "filter")
    value = str(bool_filter["filter"]).strip().lower()
    if value in ("true", "1", "yes", "y"):
        bool_filter["filter"] = True
    elif value in ("false", "0", "no", "n"):
        bool_filter["filter"] = False
    else:
        raise argparse.ArgumentTypeError("{} is not a valid boolean".format(bool_filter["filter"]))
    return bool_filter


def _parse_datetime_argument(raw_value):
    """
    Parse a CLI datetime argument.
    """
    try:
        parsed_datetime = parse_datetime(raw_value)
    except Exception as exc:
        raise argparse.ArgumentTypeError("{} is not a valid datetime".format(raw_value)) from exc
    if parsed_datetime.tzinfo is not None and parsed_datetime.utcoffset() is not None:
        parsed_datetime = parsed_datetime.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed_datetime


def _parse_future_datetime_argument(raw_value):
    """
    Parse a CLI datetime argument that must be in the future.
    """
    parsed_datetime = _parse_datetime_argument(raw_value)
    if parsed_datetime <= datetime.datetime.utcnow():
        raise argparse.ArgumentTypeError("{} must be in the future".format(raw_value))
    return parsed_datetime


def _add_text_filter_arguments(parser, filter_specs):
    """
    Add text-filter options and their operator selectors to a parser.
    """
    for filter_spec in filter_specs:
        parser.add_argument(
            filter_spec["short"],
            filter_spec["long"],
            action="append",
            dest=filter_spec["dest"],
            metavar="VALUE",
            help=filter_spec["help"],
        )
        parser.add_argument(
            "{}-op".format(filter_spec["long"]),
            choices=TEXT_OPERATOR_NAMES,
            default=filter_spec["default_op"],
            dest="{}_op".format(filter_spec["dest"]),
            help="operator for {} (default: {})".format(filter_spec["long"], filter_spec["default_op"]),
        )


def _add_date_filter_arguments(parser, filter_specs):
    """
    Add date-filter options. Values may be prefixed with an arithmetic operator.
    """
    for filter_spec in filter_specs:
        parser.add_argument(
            filter_spec["short"],
            filter_spec["long"],
            action="append",
            type=lambda value: _parse_arithmetic_filter(value, "date"),
            dest=filter_spec["dest"],
            metavar="FILTER",
            help="{}; use VALUE or OP:VALUE".format(filter_spec["help"]),
        )


def _build_text_filter(args, parser, filter_spec):
    """
    Build one query text-filter dictionary from parsed CLI arguments.
    """
    values = getattr(args, filter_spec["dest"])
    if values is None:
        return None

    op = getattr(args, "{}_op".format(filter_spec["dest"]))
    if op in ("in", "notin"):
        return {"filter": values, "op": op}

    if len(values) > 1:
        parser.error("{} can be repeated only when its operator is in or notin".format(filter_spec["long"]))
    return {"filter": values[0], "op": op}


def _build_text_filters(args, parser, filter_specs):
    """
    Build text filters for all supplied text-filter arguments.
    """
    filters = {}
    for filter_spec in filter_specs:
        text_filter = _build_text_filter(args, parser, filter_spec)
        if text_filter is not None:
            filters[filter_spec.get("query_dest", filter_spec["dest"])] = text_filter
    return filters


def _add_archived_file_filter_arguments(parser):
    """
    Add all filters supported by the archived-file inventory query.
    """
    _add_text_filter_arguments(parser, ARCHIVED_FILE_TEXT_FILTERS)
    _add_date_filter_arguments(parser, ARCHIVED_FILE_DATE_FILTERS)
    parser.add_argument(
        "-z",
        "--file-size",
        action="append",
        type=_parse_number_filter,
        dest="file_size_filters",
        metavar="FILTER",
        help="file size filter; use VALUE or OP:VALUE",
    )
    parser.add_argument(
        "-b",
        "--available",
        type=_parse_bool_filter,
        dest="available_filter",
        metavar="FILTER",
        help="availability filter; use VALUE or OP:VALUE",
    )
    parser.add_argument(
        "-B",
        "--physically-available",
        type=_parse_bool_filter,
        dest="physically_available_filter",
        metavar="FILTER",
        help="physical payload availability filter; use VALUE or OP:VALUE",
    )


def _build_archived_file_filters(args, parser):
    """
    Build filters accepted by ``Query.get_archived_files``.
    """
    filters = _build_text_filters(args, parser, ARCHIVED_FILE_TEXT_FILTERS)
    for filter_spec in ARCHIVED_FILE_DATE_FILTERS:
        date_filters = getattr(args, filter_spec["dest"])
        if date_filters is not None:
            filters[filter_spec["dest"]] = date_filters
    if getattr(args, "file_size_filters", None) is not None:
        filters["file_size_filters"] = args.file_size_filters
    if getattr(args, "available_filter", None) is not None:
        filters["available"] = args.available_filter
    if getattr(args, "physically_available_filter", None) is not None:
        filters["physically_available"] = args.physically_available_filter
    return filters


def _add_trash_filter_arguments(parser):
    """
    Add filters supported by the pending-final-removal inventory query.
    """
    _add_text_filter_arguments(parser, TRASH_TEXT_FILTERS)
    _add_date_filter_arguments(parser, TRASH_DATE_FILTERS)


def _build_trash_filters(args, parser):
    """
    Build filters accepted by ``Query.get_files_to_be_removed``.
    """
    filters = _build_text_filters(args, parser, TRASH_TEXT_FILTERS)
    for filter_spec in TRASH_DATE_FILTERS:
        date_filters = getattr(args, filter_spec["dest"])
        if date_filters is not None:
            filters[filter_spec.get("query_dest", filter_spec["dest"])] = date_filters
    return filters


def _add_retrieve_arguments(parser):
    """
    Add retrieval selection, sorting, pagination, and destination options.
    """
    parser.add_argument(
        "-s",
        "--selection",
        choices=["all", "first", "last"],
        default="all",
        help="select all matching files, only the first match, or only the last match",
    )
    parser.add_argument(
        "-o",
        "--order-by",
        dest="order_by",
        help="inventory metadata field used to order matching files",
    )
    parser.add_argument(
        "-x",
        "--descending",
        action="store_true",
        help="sort matching files in descending order when --order-by is provided",
    )
    parser.add_argument(
        "-m",
        "--limit",
        type=int,
        help="maximum number of matching files to return",
    )
    parser.add_argument(
        "-i",
        "--offset",
        type=int,
        help="number of matching files to skip before returning results",
    )
    parser.add_argument(
        "-Y",
        "--group-by",
        dest="group_by",
        help="inventory metadata field used to group matching files",
    )
    parser.add_argument(
        "-d",
        "--destination-path",
        "--destination_path",
        dest="destination_path",
        help="folder where retrieved file payloads are copied",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        dest="list_files",
        help="list matching files without copying payloads or updating access metadata",
    )


def _build_order_by(args):
    """
    Build an order-by descriptor for query and engine calls.
    """
    if args.order_by is None:
        return None
    return {"field": args.order_by, "descending": args.descending}


def _build_recover_filters(args, parser, query):
    """
    Resolve archived-file metadata filters into trash-queue filters.
    """
    archived_file_filters = _build_archived_file_filters(args, parser)
    trash_filters = _build_trash_filters(args, parser)

    if archived_file_filters:
        files = query.get_archived_files(**archived_file_filters)
        trash_filters["file_uuids"] = {
            "filter": [archived_file.file_uuid for archived_file in files],
            "op": "in",
        }
    return trash_filters


def _jsonify_recover_candidates(rows, logical_files=None):
    """
    Serialize archived files that can be recovered from trash or logical delete.
    """
    files = []
    seen_file_uuids = set()
    for row in rows:
        archived_file = row.archivedFile
        if archived_file.file_uuid in seen_file_uuids:
            continue
        files.append(archived_file)
        seen_file_uuids.add(archived_file.file_uuid)
    for archived_file in logical_files or []:
        if archived_file.file_uuid in seen_file_uuids:
            continue
        files.append(archived_file)
        seen_file_uuids.add(archived_file.file_uuid)
    return _jsonify_rows(files)


def aboa_archive():
    """
    Command line entry point for archiving one file.
    """
    parser = argparse.ArgumentParser(description="Archive a file into ABOA")
    parser.add_argument(
        "-f",
        "--file",
        required=True,
        help="path of the input file to archive",
    )
    parser.add_argument(
        "-d",
        "--delete",
        action="store_true",
        help="delete the input file after it has been archived successfully",
    )
    parser.add_argument(
        "-E",
        "--expiration-date",
        type=_parse_future_datetime_argument,
        dest="expiration_date",
        metavar="DATETIME",
        help="explicit archive expiration date; overrides retention-policy calculation",
    )
    args = parser.parse_args()
    logger.info("Archive command received for file {}".format(args.file))
    engine = Engine()
    try:
        archive_kwargs = {"delete": args.delete}
        if args.expiration_date is not None:
            archive_kwargs["metadata"] = {"expiration_date": args.expiration_date}
        engine.archive_file(args.file, **archive_kwargs)
        archived_file = engine.query.get_archived_files(
            names={"filter": [os.path.basename(args.file)], "op": "in"},
            selection="last",
        )[0]
        _print_json(archived_file.jsonify())
        logger.info("Archive command completed for file {}".format(args.file))
    except ArchiveFileError as exc:
        logger.error("Archive command failed for file {}: {}".format(args.file, exc))
        _exit_with_error(parser, exc)
    finally:
        engine.close_session()


def aboa_retrieve():
    """
    Command line entry point for retrieving archive inventory entries.
    """
    parser = argparse.ArgumentParser(description="Retrieve ABOA inventory entries")
    _add_archived_file_filter_arguments(parser)
    _add_retrieve_arguments(parser)
    args = parser.parse_args()
    filters = _build_archived_file_filters(args, parser)
    order_by = _build_order_by(args)
    logger.info("Retrieve command received with filters {}".format(filters))

    if args.list_files:
        query = Query()
        try:
            files = query.get_archived_files(
                selection=args.selection,
                order_by=order_by,
                group_by=args.group_by,
                limit=args.limit,
                offset=args.offset,
                **filters
            )
            _print_json(_jsonify_rows(files))
            logger.info("Retrieve command listed candidate files")
        finally:
            query.close_session()
        return

    engine = Engine()
    try:
        files = engine.retrieve_files(
            filters=filters,
            order_by=order_by,
            group_by=args.group_by,
            selection=args.selection,
            limit=args.limit,
            offset=args.offset,
            destination_path=args.destination_path,
        )
        _print_json(_jsonify_rows(files))
        logger.info("Retrieve command completed")
    finally:
        engine.close_session()


def aboa_delete():
    """
    Command line entry point for logical or physical file deletion.
    """
    parser = argparse.ArgumentParser(description="Delete ABOA inventory entries")
    _add_archived_file_filter_arguments(parser)
    parser.add_argument(
        "-P",
        "--physical",
        action="store_true",
        help="move matching archived payloads to trash in addition to logical deletion",
    )
    parser.add_argument(
        "-D",
        "--permanent",
        action="store_true",
        dest="permanent_delete",
        help="delete matching payloads immediately instead of moving them to trash",
    )
    parser.add_argument(
        "-I",
        "--purge-entry",
        action="store_true",
        dest="purge_entry",
        help="delete matching archived-file rows; combine with --permanent to remove payloads first",
    )
    parser.add_argument(
        "-e",
        "--reason",
        default="manual_delete",
        dest="removal_reason",
        help="removal justification stored on logically deleted files",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        dest="list_files",
        help="list matching files without deleting them",
    )
    args = parser.parse_args()
    filters = _build_archived_file_filters(args, parser)
    if args.physical and args.permanent_delete:
        parser.error("--physical and --permanent cannot be used together")
    if args.physical and args.purge_entry:
        parser.error("--physical and --purge-entry cannot be used together; use --permanent --purge-entry")
    if not filters and not args.list_files:
        parser.error("at least one archived-file filter is required")
    if args.permanent_delete:
        filters.setdefault("physically_available", {"filter": True, "op": "=="})
    elif not args.physical and not args.purge_entry:
        filters.setdefault("available", {"filter": True, "op": "=="})
    logger.info("Delete command received with filters {}".format(filters))

    engine = Engine()
    try:
        if args.list_files:
            files = engine.query.get_archived_files(**filters)
            _print_json(_jsonify_rows(files))
            logger.info("Delete command listed {} candidate file/s".format(len(files)))
            return

        if args.purge_entry and not args.permanent_delete:
            files = engine.delete_archived_file_entries(filters=filters)
        else:
            files = engine.delete_files(
                filters=filters,
                physical_delete=args.physical,
                permanent_delete=args.permanent_delete,
                purge_entries=args.purge_entry,
                removal_justification=args.removal_reason,
            )
        _print_json(_jsonify_rows(files))
        logger.info("Delete command completed on {} file/s".format(len(files)))
    except ArchiveDeletionError as exc:
        logger.error("Delete command failed: {}".format(exc))
        _exit_with_error(parser, exc)
    finally:
        engine.close_session()


def aboa_recover():
    """
    Command line entry point for recovering logically or physically deleted files.
    """
    parser = argparse.ArgumentParser(description="Recover deleted ABOA files")
    _add_archived_file_filter_arguments(parser)
    _add_trash_filter_arguments(parser)
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        dest="list_files",
        help="list matching recoverable files without changing archive payloads",
    )
    args = parser.parse_args()

    engine = Engine()
    try:
        filters = _build_recover_filters(args, parser, engine.query)
        if not filters and not args.list_files:
            parser.error("at least one archived-file or trash filter is required")
        logger.info("Recover command received with filters {}".format(filters))

        if args.list_files:
            rows = engine.query.get_files_to_be_removed(**filters)
            logical_files = engine.get_logically_deleted_recoverable_files(filters=filters)
            _print_json(_jsonify_recover_candidates(rows, logical_files))
            logger.info("Recover command listed {} candidate file/s".format(len(rows) + len(logical_files)))
            return

        files = engine.recover_files_from_trash(filters=filters)
        _print_json(_jsonify_rows(files))
        logger.info("Recover command completed on {} file/s".format(len(files)))
    except ArchiveRecoveryError as exc:
        logger.error("Recover command failed: {}".format(exc))
        _exit_with_error(parser, exc)
    finally:
        engine.close_session()


def aboa_clean_up():
    """
    Command line entry point for retention cleanup.
    """
    parser = argparse.ArgumentParser(description="Remove expired ABOA archive files")
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="show files selected by cleanup without applying changes",
    )
    parser.add_argument(
        "-f",
        "--final-removal",
        action="store_true",
        help="remove expired trash payloads instead of applying retention cleanup",
    )
    parser.add_argument(
        "--empty-trash",
        action="store_true",
        help="remove all trash payloads immediately, ignoring scheduled final-removal dates",
    )
    args = parser.parse_args()
    logger.info("Clean-up command received")
    engine = Engine()
    try:
        if args.final_removal or args.empty_trash:
            rows = apply_final_removal(
                engine,
                dry_run=args.dry_run,
                empty_trash=args.empty_trash,
            )
        else:
            rows = apply_retention(engine, dry_run=args.dry_run)
        _print_json(_jsonify_rows(rows))
        logger.info("Clean-up command completed on {} row/s".format(len(rows)))
    finally:
        engine.close_session()
