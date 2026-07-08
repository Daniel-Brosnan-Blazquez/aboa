"""
Retention cleanup execution.

module aboa
"""

import datetime
import os

from aboa.datamodel.archived_files import ArchivedFile


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
            if os.path.exists(archived_file.path):
                os.unlink(archived_file.path)

        engine.session.commit()
        return candidates
    except Exception as exc:
        engine.session.rollback()
        if hasattr(engine, "get_exit_code") and hasattr(engine, "record_failure"):
            exit_code = engine.get_exit_code("RETENTION_FAILED")
            message = exit_code["message"].format(exc)
            engine.record_failure("retention", exit_code["status"], message)
            engine.session.commit()
        raise


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
