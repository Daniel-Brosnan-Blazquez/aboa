# ABOA operations flow

This document describes the runtime flow for the ABOA archive, retrieve, delete,
recovery, and cleanup operations. The database inventory is the source of truth for
metadata and operation failures. Successful operations are written to the log only;
failed operations are written to both the log and `archive_operations`.

## Shared rules

1. Every mutating operation owns one database transaction per request.
2. Successful operations commit their metadata changes before returning.
3. Failed operations roll back incomplete changes, record a failure row when enough
   context exists, commit that failure row, and raise the corresponding engine
   exception.
4. Archive payloads are stored below the active root directory using this layout:

   ```text
   <root_directory>/<target_directory>/<YEAR>/<MONTH>/<DAY>/<file_name>
   ```

5. The reserved target directories are `unknown`, `error`, and the configured trash
   directory. User archive configuration files cannot route normal files into these
   internal areas.
6. A file is logically available when `archived_files.available` is true.
7. A file is physically available when its payload exists either at
   `archived_files.path` or in a queued trash path.

## Load archive configuration flow

1. Resolve the configuration path.
   1. If the caller provided a path, use it.
   2. Otherwise build `<ABOA_RESOURCES_PATH>/archive_configurations.xml`.
   3. If the path cannot be resolved, raise `ArchiveConfigurationError` and record
      `CONFIGURATION_FAILED` from the archive operation that requested the load.
2. Check that the configuration file exists.
   1. If it does not exist, raise `ArchiveConfigurationError`.
   2. The archive operation records `CONFIGURATION_FAILED` against an unavailable
      archived-file row with minimum metadata when a root directory is available.
3. Parse the XML configuration.
   1. Reject invalid XML.
   2. Validate the XML against `aboa_archive_configurations.xsd`.
   3. Reject archive rules whose `file_directory` is reserved.
   4. Warn, but do not reject, duplicated routing values.
4. Read `/archive_configurations/@root_directory`.
   1. If the root directory is missing, raise `ArchiveConfigurationError`.
   2. If no active root directory exists, create the configured path if needed and
      insert a new active `archive_root_directories` row.
   3. If the configured root changed, mark all previous active root rows inactive,
      set their `active_until`, create the new root path if needed, and insert a new
      active root row.
   4. If the configured root is already active, leave root history unchanged.
5. Store archive-configuration history.
   1. Read the configuration XML content.
   2. Compare the active configuration checksum with the new content checksum.
   3. If the content changed, mark previous active configuration rows inactive,
      set their `active_until`, and insert a new active `archive_configurations`
      row with the source path and XML content.
   4. If the content did not change, leave configuration history unchanged.
6. Save the parsed XPath evaluator and the effective configuration path in the
   engine instance.
7. If configuration loading fails, try to activate `ABOA_DEFAULT_ARCHIVE_PATH` as a
   fallback root. The original configuration error is still raised and recorded by
   the requesting archive operation.

## ABOA archive operation flow

1. Log the archive request.
2. Normalize request inputs.
   1. Copy caller-provided metadata into a request-local dictionary.
   2. Parse the supplied reception date, or use the current UTC time.
   3. Capture the current UTC archive date.
3. Load the archive configuration. This may refresh the active root directory and
   archive-configuration history.
4. Resolve the active root directory and active archive-configuration row.
5. Check that the input file path exists.
   1. If it does not exist, record `FILE_DOES_NOT_EXIST` against an unavailable
      archived-file row with minimum metadata.
   2. Raise `ArchiveFileError`.
6. Match the file name against the first configured archive rule whose `file_mask`
   matches.
   1. If a rule matches, use its `file_directory`, `file_group`, and optional
      `file_processor`.
   2. If no rule matches, set `target_directory` to `unknown`, set `file_group` to
      `unknown`, and continue without a processor.
7. Execute the configured processor when present.
   1. Merge returned metadata into the request metadata.
   2. If the processor fails, record `PROCESSOR_FAILED`, switch
      `target_directory` to `error`, and continue so the received file remains under
      ABOA control.
8. Calculate `expiration_date` from the active retention policy when metadata did
   not already provide one.
9. Generate the SHA-256 checksum.
   1. If checksum generation fails, record `ARCHIVE_FAILED`, set checksum to null,
      switch `target_directory` to `error`, and continue.
10. Check duplicate reception.
    1. If an available archived-file row already has the same file name, record
       `FILE_ALREADY_ARCHIVED` and switch `target_directory` to `error`.
    2. If the duplicate file name and checksum already have an available error-area
       copy, reuse that existing error row, record the new failure against it, delete
       the input if requested, and finish.
11. Build the destination path below the active root, target directory, and archive
    date tree. If the expected path already exists, append a generated UUID to keep
    the stored payload collision-safe.
12. Store the payload.
    1. Try to create a hard link from the input path to the destination path.
    2. If hard-link creation fails, copy the file to the destination path.
    3. If normal storage fails, record `FILE_STORAGE_FAILED` and retry once in the
       `error` directory.
    4. If error-area storage also fails, record the failure context and raise
       `ArchiveFileError`.
13. Insert the `archived_files` row with file metadata, root-directory history,
    archive-configuration history, checksum, availability, physical availability,
    and delete-configuration linkage when the file has an expiration date.
14. Insert one `archive_operations` row for each recorded archive failure.
15. Commit the inventory transaction.
16. If input deletion was requested, delete the original input path only after the
    managed archive payload and inventory row have been committed.
    1. If input deletion fails, record `INPUT_DELETE_FAILED` and raise
       `ArchiveFileError`.
17. Log successful completion.

## ABOA retrieve operation flow

1. Build archived-file query filters from the caller or CLI arguments.
2. Query `archived_files` with the requested filters, ordering, grouping,
   selection, limit, and offset.
3. If `group_by` was requested, keep the grouped response shape for the caller and
   flatten the selected rows only for bookkeeping.
4. If a destination path was provided:
   1. Create the destination directory when needed.
   2. Check that every selected archive payload still exists.
   3. Copy each payload to the destination without overwriting an existing file.
5. Set `last_access_date` to the current UTC time for every selected row.
6. Commit the transaction and return the selected rows.
7. If anything fails, roll back partial changes, record `RETRIEVE_FAILED`, commit
   the failure row, and raise `ArchiveRetrievalError`.

## ABOA delete operation flow

1. Build archived-file query filters from the caller or CLI arguments.
2. Add default safety filters.
   1. Logical deletion defaults to currently available rows.
   2. Permanent deletion defaults to physically available rows.
   3. Physical deletion can include already logically unavailable rows when their
      payload is still at the archive path.
3. Reject requests that would purge inventory entries while moving payloads to
   trash.
4. Query the matching archived-file rows.
5. For each selected row:
   1. Preserve the first logical deletion timestamp when one already exists.
   2. Preserve the first removal justification when one already exists.
   3. Set `available` to false.
   4. Clear the pending `delete_archive_configuration_uuid` association from the
      manually deleted file.
   5. Apply the requested physical action.
6. For logical-only deletion, refresh `physically_available` based on whether the
   payload exists at the archive path or in trash.
7. For physical deletion, move the payload to trash and queue final removal.
8. For permanent deletion, delete the payload immediately and remove any queued
   trash rows for the same archived file.
9. If inventory purge was requested, delete the archived-file row only after no
   managed payload remains. Delete associated operation rows with the inventory row.
10. Commit the transaction and return the deleted rows.
11. If anything fails, roll back partial changes, record `DELETE_FAILED`, commit the
    failure row, and raise `ArchiveDeletionError`.

## ABOA physical deletion and trash flow

1. If the archived payload no longer exists at `archived_files.path`, refresh
   `physically_available` from any existing trash row and return.
2. Calculate the scheduled final-removal date from the logical removal date plus
   `FINAL_REMOVAL_DELAY_DAYS`.
3. Build a trash path using this layout:

   ```text
   <root_directory>/<trash_directory>/<YEAR>/<MONTH>/<DAY>/<file_name>
   ```

4. If the trash path already exists, append the archived-file UUID to avoid
   overwriting an existing payload.
5. Move the archive payload to the trash path.
6. Insert or update a `files_to_be_removed` row with the archived-file UUID,
   trash path, root-directory UUID, and scheduled final-removal date.
7. Keep `physically_available` true while the payload exists in trash.

## ABOA recovery operation flow

1. Build recovery filters from archived-file metadata filters and trash-specific
   filters.
2. Query `files_to_be_removed` for physical trash recovery candidates.
3. For each trash candidate:
   1. Check that the trash row is linked to an archived-file row.
   2. Check that the trash payload exists.
   3. Check that the original archive path is free.
   4. Recreate the original archive directory if needed.
   5. Move the payload from trash back to the archived path.
   6. Set `available` and `physically_available` to true.
   7. Clear `removal_date` and `removal_justification`.
   8. Refresh `file_size`.
   9. Restore delete-configuration linkage when the file still has an expiration
      date.
   10. Delete the trash row.
4. Query logical-only recovery candidates when the filters can be mapped to
   archived-file UUIDs.
5. For each logical-only candidate:
   1. Check that it is unavailable.
   2. Check that it is not queued for trash recovery.
   3. Check that the payload still exists at the archive path.
   4. Set `available` and `physically_available` to true.
   5. Clear `removal_date` and `removal_justification`.
   6. Refresh `file_size`.
   7. Restore delete-configuration linkage when the file still has an expiration
      date.
6. Commit successful recoveries.
7. If one or more candidates fail, record `RECOVERY_FAILED` for each failed file,
   commit the failure rows, and raise `ArchiveRecoveryError`.
8. If the operation fails before per-file handling, roll back partial changes,
   record `RECOVERY_FAILED`, commit the failure row, and raise
   `ArchiveRecoveryError`.

## ABOA retention cleanup flow

1. Query archived files where `available` is true and `expiration_date` is earlier
   than or equal to the cleanup time.
2. If dry-run mode is enabled, return the selected rows without changing inventory
   or payloads.
3. Otherwise mark each selected file unavailable, set its removal date, set the
   retention removal justification, move its payload to trash, and queue final
   removal.
4. If anything fails, record `RETENTION_FAILED` and raise the retention cleanup
   error.

## ABOA final removal cleanup flow

1. Query `files_to_be_removed` rows whose scheduled `removal_date` has passed.
   If immediate trash emptying was requested, query all `files_to_be_removed` rows.
2. If dry-run mode is enabled, return the selected rows without changing inventory
   or payloads.
3. Otherwise delete each queued trash payload from the filesystem.
4. Mark the related archived file as no longer physically available.
5. Delete the processed `files_to_be_removed` row.
6. Commit the transaction.
7. If anything fails, record `FINAL_REMOVAL_FAILED` and raise the final-removal
   cleanup error.
