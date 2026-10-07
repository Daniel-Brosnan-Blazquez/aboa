# ABOA Archive Component Development Plan

This plan describes how to develop the ABOA Archive component from the requirements in
`ABOA_requirements.md`, defining the code style, package layout, and operational
patterns for the component.

ABOA stands for Archive for Business Operations Analysis. Its responsibility is to
archive files on a POSIX file system, keep a PostgreSQL inventory of archived files,
and expose archive, retrieval, delete, configuration, and retention capabilities
through command line and REST APIs.

## 1. Target Architecture

Use this architecture for the first ABOA version:

- Package source under `src/aboa`, separated into concerns: `datamodel`, `engine`,
  `processors`, and `api`.
- SQLAlchemy declarative model in `aboa.datamodel`, with `Base`, `Session`, and
  `engine` initialized from a JSON configuration file.
- A high-level `Engine` class for mutating operations.
- A `Query` class for read operations and inventory filtering.
- Project-wide logging through `aboa.logging.Log`, using a rotating file handler,
  log format, environment-variable overrides, and custom log-level pattern.
- JSON configuration files in `src/aboa/config`, XSD files in `src/aboa/schemas`, database
  model artifacts in `src/aboa/datamodel`, scripts in `src/aboa/scripts`, and tests in
  `src/tests`.
- Test structure based on `unittest` style and database lifecycle: instantiate
  `Query`, instantiate `Engine`, clear tables in `setUp`, and close
  sessions in `tearDown`.

## 2. Target Repository Layout

Create the following structure:

```text
aboa/
  LICENSE
  README.md
  AUTHORS
  src/
    setup.py
    MANIFEST.in
    __init__.py
    aboa/
      __init__.py
      logging.py
      datamodel/
        __init__.py
        base.py
        errors.py
        functions.py
        archived_files.py
      engine/
        __init__.py
        engine.py
        query.py
        errors.py
        functions.py
        parsing.py
        commands.py
        retention.py
      processors/
        __init__.py
        base_processor.py
      api/
        __init__.py
        rest.py
        schemas.py
    config/
      datamodel.json
      engine.json
      archive_configurations.xml
    schemas/
      aboa_archive_configurations.xsd
    datamodel/
      aboa_data_model.dbm
      aboa_data_model.sql
    scripts/
      aboa_init.py
      aboa_init_ddbb.sh
      aboa_clean_up.py
    tests/
      test_datamodel.py
      test_engine.py
      test_query.py
      test_configuration.py
      test_archive_filesystem.py
      test_processors.py
      test_clean_up.py
      test_cli.py
      test_rest.py
      inputs/
```

## 3. Data Model Plan

Design the PostgreSQL model in pgModeler and export both:

- `src/aboa/datamodel/aboa_data_model.dbm`
- `src/aboa/datamodel/aboa_data_model.sql`

Implement matching SQLAlchemy entities under `aboa.datamodel`.

### 3.1 Core Tables

`archived_files`

- `file_uuid`: UUID primary key.
- `name`: text, original file name.
- `path`: text, full archived POSIX path.
- `reception_date`: timestamp, when ABOA received the archive request.
- `archive_date`: timestamp, when the file was stored.
- `file_size`: bigint.
- `available`: boolean, true until deleted or removed by retention.
- `root_directory_uuid`: FK to `archive_root_directories`.
- `last_access_date`: nullable timestamp.
- `file_group`: nullable text.
- `file_type`: nullable text.
- `file_class`: nullable text.
- `file_version`: nullable text.
- `validity_start_date`: nullable timestamp.
- `validity_stop_date`: nullable timestamp.
- `generation_date`: nullable timestamp.
- `expiration_date`: nullable timestamp.
- `removal_date`: nullable timestamp.
- `checksum`: nullable text, recommended for integrity verification.

`archive_root_directories`

- `root_directory_uuid`: UUID primary key.
- `path`: text.
- `active_from`: timestamp.
- `active_until`: nullable timestamp.
- `active`: boolean.

`archive_operations`

- `operation_uuid`: UUID primary key.
- `operation`: text, values `archive`, `retrieve`, `delete`, `configure`,
  `retention`.
- `time_stamp`: timestamp.
- `status`: integer or text.
- `message`: nullable text.
- `file_uuid`: nullable FK to `archived_files`.

### 3.2 Model Conventions

- Use SQLAlchemy classes with explicit `__tablename__`, typed columns, constructors,
  and `jsonify()` methods, with consistent entity APIs.
- Keep database access centralized through `aboa.datamodel.base.Session`.
- Keep database configuration in `src/aboa/config/datamodel.json`, using the
  `DDBB_CONFIGURATION` structure with ABOA-specific defaults.
- Add indexes for common retrieval filters: `name`, `path`, `archive_date`,
  `generation_date`, `validity_start_date`, `validity_stop_date`, `file_group`,
  `file_type`, `file_class`, `file_version`, `available`, `expiration_date`, and
  `removal_date`.

## 4. Archive Engine Plan

Implement `aboa.engine.engine.Engine` as the main mutation interface.

### 4.1 Public Methods

- `archive_file(file_path, reception_date=None, metadata=None)`: copy or move the
  input file into the managed POSIX archive, record the inventory row, run a matching
  processor if configured, and return the archived file entity.
- `retrieve_files(filters=None, order_by=None, group_by=None, selection="all",
  limit=None, offset=None)`: delegate to `Query` and update `last_access_date` for
  returned files when appropriate.
- `delete_files(filters=None, file_uuids=None, physical_delete=False)`: mark files
  removed and optionally remove the physical POSIX file.
- `configure_archive(configuration_path)`: validate XML through XSD, reject invalid
  configurations, store new configuration and root directory history.
- `apply_retention(policy_names=None, dry_run=False)`: evaluate retention policies,
  mark matching files removed, and optionally delete physical files.
- `close_session()`: close the SQLAlchemy session and keep session lifecycle explicit.

### 4.2 Archive Behavior

- Resolve the active root directory from the latest valid configuration.
- Match files against `archive_configuration.file_mask`.
- Archive matched files under:

```text
<root_directory>/<file_directory>/<YEAR>/<MONTH>/<DAY>/<file_name>
```

- Archive unmatched files under:

```text
<root_directory>/unknown/<YEAR>/<MONTH>/<DAY>/<file_name>
```

- Reject any configuration where `file_directory` is `unknown`.
- Create directories with POSIX-safe permissions.
- Archive files in the `error` folder when any recoverable archive error happens,
  such as a repeated file reception or a processor failure. Metadata will be filled
  with default values when extraction is not possible.
- Log every operation start, success, failure, and relevant decision.
- Operation failures must be logged and recorded in `archive_operations`.
- Operation successes must be logged but not recorded in `archive_operations`.
- Archive operations will store files using POSIX hard links by default. The input
  file and archive root therefore need to be on the same filesystem for the normal
  path. If hard-link creation fails, the operation follows the error-folder path and
  records the failure.
- The archive command includes a delete flag. When enabled, the original input file is
  deleted only after ABOA has stored a managed copy or link in either the final
  archive path or the error folder.

### 4.3 Processor Behavior

- Implement a processor contract in `aboa.processors.base_processor`.
- Load configured processors dynamically using an import-module pattern.
- A processor receives the input file path, and returns
  extracted metadata such as `file_type`, `file_class`, `file_version`,
  `validity_start_date`, `validity_stop_date`, `expiration_date`, and
  `generation_date`.

## 5. Query Plan

Implement `aboa.engine.query.Query` as the read and delete-query builder.

### 5.1 Retrieval Filters

Support filters for all inventory metadata:

- `file_uuids`
- `names`
- `paths`
- `reception_date_filters`
- `archive_date_filters`
- `file_size_filters`
- `available`
- `last_access_date_filters`
- `file_group`
- `file_type`
- `file_class`
- `file_version`
- `validity_start_date_filters`
- `validity_stop_date_filters`
- `generation_date_filters`
- `expiration_date_filters`
- `removal_date_filters`

Use structured filter dictionaries:

```python
{"filter": "S2%", "op": "like"}
{"filter": ["AUX", "RAW"], "op": "in"}
{"date": "2026-07-01T00:00:00", "op": ">="}
```

### 5.2 Selection Rules

Support the required retrieval rules:

- `order_by`: validate field name and direction.
- `group_by`: validate the metadata field, initially returning grouped rows or
  grouped lists depending on API surface.
- `first`: return the first row after filtering and ordering.
- `last`: return the last row after filtering and ordering.
- `all`: return all matching rows after pagination.
- `limit` and `offset`: implement pagination with positive integer validation.

Avoid `eval()` for new ABOA query code. Keep the dictionary-based filter API shape
while mapping fields and operators through explicit dictionaries for safer code.

## 6. Configuration XML and XSD Plan

Create `src/aboa/schemas/aboa_archive_configurations.xsd` for:

```xml
<archive_configurations root_directory="">
  <archive_configuration file_group="">
    <file_mask></file_mask>
    <file_directory></file_directory>
    <file_processor></file_processor>
    <retention_policy active="" key=""></retention_policy>
  </archive_configuration>
  <retention_policies>
    <retention_policy active="" key=""></retention_policy>
  </retention_policies>
</archive_configurations>
```

Validation rules:

- `root_directory` is required and must not be empty.
- At least one `archive_configuration` can be present, but zero should also be
  considered if the system must allow only the `unknown` fallback.
- `file_group` attribute inside archive_configuration is required.
- `file_mask` is required.
- `file_directory` is required and must not equal `unknown`.
- `file_processor` is optional.
- `retention_policy` is optional inside each `archive_configuration`.
- `active` and `key` attributes are required for each `retention_policy`.

Implement XML parsing in `aboa.engine.parsing`, using `lxml` and `xmlschema`/XSD
validation before storing or activating configurations.

## 7. CLI API Plan

Implement command line entry points through `setup.py` and/or scripts:

- `aboa_archive.py --file <path> [--delete]`
- `aboa_retrieve.py [filters] [--order-by field:asc|desc] [--selection all|first|last]
  [--limit N] [--offset N]`
- `aboa_delete.py --uuid <uuid> [--physical]`
- `aboa_clean_up.py --policy <name> [--dry-run]`

Use `aboa.engine.commands` for shared argument parsing and output formatting.

## 8. REST API Plan

ABOA must provide a RESTful API in addition to the command line API. Implement the
REST layer in `aboa.api.rest` as a thin adapter over `Engine` and `Query`, so archive
logic remains testable without HTTP.

Initial endpoints:

- `POST /archive/files`: archive a server-local file path or uploaded file.
- `GET /archive/files`: retrieve inventory entries with metadata filters, selection
  rules, and pagination.
- `GET /archive/files/<file_uuid>`: retrieve one inventory entry.
- `GET /archive/files/<file_uuid>/content`: stream file content from the POSIX
  archive.
- `DELETE /archive/files/<file_uuid>`: delete logically or physically.
- `POST /archive/retention/run`: execute clean-up policies, with dry-run support.

Return JSON structures from entity `jsonify()` methods, following the datamodel
conventions. Keep authentication and authorization outside the first ABOA
implementation unless a wider BOA service layer provides it.

## 9. Retention Policy Plan

Implement retention in `aboa.engine.retention`.

Policy matching must support:

- File type.
- Last access date.
- Validity stop date.
- Reception date.
- Generation date.
- Archive date.
- Expiration date.

Execution rules:

- Retention can run in dry-run mode and return candidate files without changing
  inventory or POSIX files.
- Physical deletion removes the POSIX file and records the operation.
- Every retention action creates a log entry. If the operation fails, an
  `archive_operations` row will be created.

## 10. Logging and Error Handling Plan

Create:

- `aboa.logging.Log`
- `aboa.engine.errors`
- `aboa.datamodel.errors`

Follow these logging conventions:

- Rotating file logs under the configured log path.
- Log level from config and environment variable overrides.
- Domain-specific exceptions for invalid filters, invalid configuration, missing
  files, archive collisions, processor failures, and retention failures.
- Explicit operation status messages for archive, retrieval, deletion, configuration,
  and retention.

Recommended environment variables:

- `ABOA_RESOURCES_PATH`
- `ABOA_LOG_LEVEL`
- `ABOA_STREAM_LOG`
- `ABOA_DDBB_HOST`

## 11. Testing Plan

ABOA requirement 20 requires tests covering all component code. Build the test suite
alongside implementation.

### 11.1 Unit Tests

- Datamodel entity construction and `jsonify()`.
- Configuration parsing and XSD validation.
- Rejection of `file_directory="unknown"`.
- Query filter validation and query composition.
- Selection rules: `first`, `last`, `all`.
- Pagination: valid and invalid `limit`/`offset`.
- Archive path generation and unknown fallback routing.
- Processor loading, successful metadata extraction, and failure handling.
- Retention candidate selection and execution behavior.

### 11.2 Integration Tests

- Initialize PostgreSQL test database from `aboa_data_model.sql`.
- Configure archive root directory in a temporary POSIX path.
- Archive a matching file and verify physical file plus inventory metadata.
- Archive an unmatched file and verify `unknown/YEAR/MONTH/DAY`.
- Retrieve by every metadata field.
- Delete logically and physically.
- Run retention dry-run and real execution.
- Exercise CLI commands.
- Exercise REST endpoints with Flask test client.

### 11.3 Coverage Gate

- Configure coverage through `pytest-cov` or the project's test conventions.
- Set a project coverage target near 100 percent for ABOA-owned modules.
- Keep tests deterministic by using temporary directories, controlled timestamps,
  and isolated database state.

## 12. Implementation Phases

### Phase 1: Project Skeleton

- Create `src/setup.py`, package folders, config folder, schema folder, scripts, and
  test folder.
- Add install requirements for SQLAlchemy, psycopg2, lxml, xmlschema,
  python-dateutil, Flask for REST, and pytest/coverage extras.
- Add `ABOA_RESOURCES_PATH`-based configuration loading.

### Phase 2: Database Inventory

- Design pgModeler model.
- Export SQL and DBM files.
- Implement SQLAlchemy entities and tests.
- Add database initialization script.

### Phase 3: Configuration Management

- Implement XSD.
- Implement XML parser and active root directory history.
- Add validation tests, including the `unknown` rejection.

### Phase 4: Archive Operations

- Implement file matching, path generation, directory creation, safe copy/move,
  metadata insertion, and operation logging.
- Add processor plugin contract and dynamic loading.
- Add archive integration tests using temporary directories.

### Phase 5: Query and Retrieval

- Implement `Query.get_archived_files`.
- Add filter validation, ordering, grouping, selection rules, and pagination.
- Update last access date on retrieval where required.
- Add query tests for each metadata field.

### Phase 6: Delete and Retention

- Implement logical delete and optional physical delete.
- Implement retention policy model and evaluator.
- Add dry-run and execution tests.

### Phase 7: APIs

- Implement CLI commands.
- Implement REST endpoints.
- Add CLI and REST tests.

### Phase 8: Documentation and Hardening

- Update `README.md` with setup, database initialization, environment variables,
  CLI examples, REST examples, and development workflow.
- Add examples under `src/examples` if useful.
- Review logs, errors, and edge cases.
- Run full test suite and coverage.

## 13. Consolidated Decisions

The following points are considered closed for the first ABOA implementation:

- Archive storage will use POSIX hard links by default. The delete flag removes the
  original input only after the file has been stored under ABOA management.
- Recoverable archive failures, including duplicate reception and processor failure,
  will store the file in the `error/YEAR/MONTH/DAY` folder with default metadata.
- Successful operations are logged only. Failed operations are logged and persisted in
  `archive_operations`.
- Processor failures do not prevent ABOA from managing the received file; the file is
  routed to the error folder and failure metadata is recorded.
- `group_by` retrieval responses will return grouped inventory lists in Python and
  grouped JSON arrays in REST responses. CLI output will print one group per block.
- Physical deletion is available only through explicit CLI/API flags and retention
  policy actions. Logical deletion remains the default delete behavior.
- Checksums remain part of the inventory model but are optional for the first
  implementation.
- Retention policy configuration is XML-based, using `retention_policy` elements with
  required `active` and `key` attributes.
- REST is part of the first implementation because it is an explicit ABOA
  requirement, but it must remain a thin layer over the engine/query APIs.

## 14. Requirement Traceability

| Requirement | Planned implementation |
| --- | --- |
| 1. Archive, retrieve, delete requests | `Engine.archive_file`, `Query.get_archived_files`, `Engine.delete_files`, CLI and REST endpoints |
| 2. POSIX archive plus database inventory | hard-link filesystem storage plus PostgreSQL SQLAlchemy datamodel |
| 3. POSIX archive | Directory creation and file operations through Python POSIX filesystem APIs |
| 4. PostgreSQL inventory | `datamodel.json`, SQLAlchemy, pgModeler SQL |
| 5. pgModeler design | `src/aboa/datamodel/aboa_data_model.dbm` |
| 6. Metadata fields | `archived_files` table and query filters |
| 7. CLI and REST APIs | `aboa.engine.commands`, scripts, `aboa.api.rest` |
| 8. Metadata retrieval filters | `Query.get_archived_files` |
| 9. Selection rules | `order_by`, `group_by`, `first`, `last`, `all` |
| 10. Pagination | `limit` and `offset` |
| 11. Log levels | `aboa.logging.Log` |
| 12. XML configuration API | `Engine.configure_archive`, XSD, parser |
| 13. Structured directory | `<file_directory>/YEAR/MONTH/DAY` |
| 14. XSD validation | `aboa_archive_configurations.xsd` |
| 15. Unknown fallback | Unmatched files routed to `unknown/YEAR/MONTH/DAY` |
| 16. Reject unknown configuration | Configuration parser validation |
| 17. File processors | `aboa.processors` dynamic contract |
| 18. Root directory history | `archive_root_directories` table |
| 19. Retention policies | `retention_policies` table and evaluator |
| 20. Test coverage | Unit and integration tests for all modules |
