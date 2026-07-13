"""
Retention cleanup execution.

module aboa
"""

import datetime
import os

from aboa.datamodel.archived_files import ArchivedFile, FileToBeRemoved
from aboa.engine.errors import ArchiveFinalRemovalError, ArchiveRetentionError


RETENTION_REMOVAL_JUSTIFICATION = "retention_policy"


def apply_retention(engine, dry_run=False):
    """
    Remove available archived files whose expiration date has passed.

    Retention policies are applied when files are archived by calculating and
    storing ``ArchivedFile.expiration_date``. Runtime retention cleanup only needs
    to evaluate that timestamp.

    :param engine: archive engine owning the session
    :type engine: aboa.engine.engine.Engine
    :param dry_run: return candidates without changing inventory or filesystem
    :type dry_run: bool

    :return: candidate or affected archived files
    :rtype: list
    """
    now = datetime.datetime.utcnow()
    try:
        candidates = get_expired_files(engine.session, now)
        if dry_run:
            return candidates

        for archived_file in candidates:
            archived_file.available = False
            archived_file.removal_date = now
            archived_file.removal_justification = RETENTION_REMOVAL_JUSTIFICATION
            engine.move_archived_file_to_trash(archived_file, now)

        engine.session.commit()
        return candidates
    except Exception as exc:
        engine.session.rollback()
        exit_code = engine.get_exit_code("RETENTION_FAILED")
        message = exit_code["message"].format(exc)
        engine.record_failure("retention", exit_code["status"], message)
        engine.session.commit()
        raise ArchiveRetentionError(message) from exc


def apply_final_removal(engine, dry_run=False, now=None, empty_trash=False):
    """
    Delete trash-queue payloads whose grace period has elapsed.

    Per-file deletion failures are persisted in ``archive_operations`` and the
    corresponding trash-queue row is left in place for a later retry.

    :param engine: archive engine owning the session
    :type engine: aboa.engine.engine.Engine
    :param dry_run: return candidates without deleting payloads or rows
    :type dry_run: bool
    :param now: evaluation timestamp, defaulting to current UTC time
    :type now: datetime.datetime or None
    :param empty_trash: delete every queued trash payload immediately
    :type empty_trash: bool

    :return: candidate or affected pending-removal rows
    :rtype: list
    """
    now = now or datetime.datetime.utcnow()

    try:
        candidates = get_files_ready_for_final_removal(
            engine.session,
            now,
            empty_trash=empty_trash,
        )
        if dry_run:
            return candidates

        for file_to_be_removed in candidates:
            try:
                archived_file = file_to_be_removed.archivedFile
                if os.path.exists(file_to_be_removed.path):
                    os.unlink(file_to_be_removed.path)
                engine.session.delete(file_to_be_removed)
                if archived_file is not None:
                    engine._sync_physical_availability(archived_file)
            except Exception as exc:
                exit_code = engine.get_exit_code("FINAL_REMOVAL_FAILED")
                message = exit_code["message"].format(file_to_be_removed.path, exc)
                engine.record_failure("final_removal", exit_code["status"], message, file_to_be_removed.archivedFile)
        engine.session.commit()
        return candidates
    except Exception as exc:
        engine.session.rollback()
        exit_code = engine.get_exit_code("FINAL_REMOVAL_FAILED")
        message = exit_code["message"].format("final_removal", exc)
        engine.record_failure("final_removal", exit_code["status"], message)
        engine.session.commit()
        raise ArchiveFinalRemovalError(message) from exc


def get_expired_files(session, now=None):
    """
    Return available archive inventory rows expired at ``now``.

    :param session: SQLAlchemy session
    :type session: sqlalchemy.orm.session.Session
    :param now: evaluation timestamp, defaulting to current UTC time
    :type now: datetime.datetime or None

    :return: expired available archived files
    :rtype: list
    """
    now = now or datetime.datetime.utcnow()
    return (
        session.query(ArchivedFile)
        .filter(ArchivedFile.available == True)
        .filter(ArchivedFile.expiration_date <= now)
        .order_by(
            ArchivedFile.expiration_date.asc(),
            ArchivedFile.archive_date.asc(),
            ArchivedFile.file_uuid.asc(),
        )
        .all()
    )


def get_files_ready_for_final_removal(session, now=None, empty_trash=False):
    """
    Return trash-queue rows selected for final physical deletion.

    :param session: SQLAlchemy session
    :type session: sqlalchemy.orm.session.Session
    :param now: evaluation timestamp, defaulting to current UTC time
    :type now: datetime.datetime or None
    :param empty_trash: include every queued trash payload, ignoring removal_date
    :type empty_trash: bool

    :return: pending-removal rows ready for final deletion
    :rtype: list
    """
    now = now or datetime.datetime.utcnow()
    query = session.query(FileToBeRemoved)
    if not empty_trash:
        query = query.filter(FileToBeRemoved.removal_date <= now)
    return query.order_by(
        FileToBeRemoved.removal_date.asc(),
        FileToBeRemoved.file_to_remove_uuid.asc(),
    ).all()
