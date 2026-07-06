-- ** Database generated with pgModeler (PostgreSQL Database Modeler).
-- ** pgModeler version: 1.2.3
-- ** PostgreSQL version: 18.0
-- ** Project Site: pgmodeler.io
-- ** Model Author: ---
-- object: aboa | type: ROLE --
-- DROP ROLE IF EXISTS aboa;
CREATE ROLE aboa WITH 
	INHERIT
	LOGIN;
-- ddl-end --


-- ** Database creation must be performed outside a multi lined SQL file. 
-- ** These commands were put in this file only as a convenience.

-- object: aboadb | type: DATABASE --
-- DROP DATABASE IF EXISTS aboadb;
CREATE DATABASE aboadb;
-- ddl-end --


-- object: aboa | type: SCHEMA --
-- DROP SCHEMA IF EXISTS aboa CASCADE;
CREATE SCHEMA aboa;
-- ddl-end --
ALTER SCHEMA aboa OWNER TO aboa;
-- ddl-end --

SET search_path TO pg_catalog,public,aboa;
-- ddl-end --

-- object: aboa.archive_root_directories | type: TABLE --
-- DROP TABLE IF EXISTS aboa.archive_root_directories CASCADE;
CREATE TABLE aboa.archive_root_directories (
	root_directory_uuid uuid NOT NULL,
	path text NOT NULL,
	active_from timestamp NOT NULL,
	active_until timestamp,
	active bool NOT NULL,
	CONSTRAINT archive_root_directories_pk PRIMARY KEY (root_directory_uuid)
);
-- ddl-end --
ALTER TABLE aboa.archive_root_directories OWNER TO aboa;
-- ddl-end --

-- object: aboa.archived_files | type: TABLE --
-- DROP TABLE IF EXISTS aboa.archived_files CASCADE;
CREATE TABLE aboa.archived_files (
	file_uuid uuid NOT NULL,
	name text NOT NULL,
	path text NOT NULL,
	reception_date timestamp NOT NULL,
	archive_date timestamp NOT NULL,
	file_size bigint NOT NULL,
	available bool NOT NULL,
	last_access_date timestamp,
	file_group text,
	file_type text,
	file_class text,
	file_version text,
	validity_start_date timestamp,
	validity_stop_date timestamp,
	generation_date timestamp,
	expiration_date timestamp,
	removal_date timestamp,
	checksum text,
	root_directory_uuid uuid NOT NULL,
	CONSTRAINT archived_files_pk PRIMARY KEY (file_uuid)
);
-- ddl-end --
ALTER TABLE aboa.archived_files OWNER TO aboa;
-- ddl-end --

-- object: archive_root_directories_fk | type: CONSTRAINT --
-- ALTER TABLE aboa.archived_files DROP CONSTRAINT IF EXISTS archive_root_directories_fk CASCADE;
ALTER TABLE aboa.archived_files ADD CONSTRAINT archive_root_directories_fk FOREIGN KEY (root_directory_uuid)
REFERENCES aboa.archive_root_directories (root_directory_uuid) MATCH FULL
ON DELETE RESTRICT ON UPDATE CASCADE;
-- ddl-end --

-- object: aboa.archive_operations | type: TABLE --
-- DROP TABLE IF EXISTS aboa.archive_operations CASCADE;
CREATE TABLE aboa.archive_operations (
	operation_uuid uuid NOT NULL,
	operation text NOT NULL,
	time_stamp timestamp NOT NULL,
	status integer NOT NULL,
	message text,
	file_uuid uuid,
	CONSTRAINT archive_operations_pk PRIMARY KEY (operation_uuid)
);
-- ddl-end --
ALTER TABLE aboa.archive_operations OWNER TO aboa;
-- ddl-end --

-- object: archived_files_fk | type: CONSTRAINT --
-- ALTER TABLE aboa.archive_operations DROP CONSTRAINT IF EXISTS archived_files_fk CASCADE;
ALTER TABLE aboa.archive_operations ADD CONSTRAINT archived_files_fk FOREIGN KEY (file_uuid)
REFERENCES aboa.archived_files (file_uuid) MATCH FULL
ON DELETE SET NULL ON UPDATE CASCADE;
-- ddl-end --

-- object: idx_archived_files_name | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_name CASCADE;
CREATE INDEX idx_archived_files_name ON aboa.archived_files
USING btree
(
	name
);
-- ddl-end --

-- object: idx_archived_files_path | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_path CASCADE;
CREATE INDEX idx_archived_files_path ON aboa.archived_files
USING btree
(
	path
);
-- ddl-end --

-- object: idx_archived_files_archive_date | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_archive_date CASCADE;
CREATE INDEX idx_archived_files_archive_date ON aboa.archived_files
USING btree
(
	archive_date
);
-- ddl-end --

-- object: idx_archived_files_generation_date | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_generation_date CASCADE;
CREATE INDEX idx_archived_files_generation_date ON aboa.archived_files
USING btree
(
	generation_date
);
-- ddl-end --

-- object: idx_archived_files_validity_start_date | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_validity_start_date CASCADE;
CREATE INDEX idx_archived_files_validity_start_date ON aboa.archived_files
USING btree
(
	validity_start_date
);
-- ddl-end --

-- object: idx_archived_files_validity_stop_date | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_validity_stop_date CASCADE;
CREATE INDEX idx_archived_files_validity_stop_date ON aboa.archived_files
USING btree
(
	validity_stop_date
);
-- ddl-end --

-- object: idx_archived_files_file_group | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_file_group CASCADE;
CREATE INDEX idx_archived_files_file_group ON aboa.archived_files
USING btree
(
	file_group
);
-- ddl-end --

-- object: idx_archived_files_file_type | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_file_type CASCADE;
CREATE INDEX idx_archived_files_file_type ON aboa.archived_files
USING btree
(
	file_type
);
-- ddl-end --

-- object: idx_archived_files_file_class | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_file_class CASCADE;
CREATE INDEX idx_archived_files_file_class ON aboa.archived_files
USING btree
(
	file_class
);
-- ddl-end --

-- object: idx_archived_files_file_version | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_file_version CASCADE;
CREATE INDEX idx_archived_files_file_version ON aboa.archived_files
USING btree
(
	file_version
);
-- ddl-end --

-- object: idx_archived_files_available | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_available CASCADE;
CREATE INDEX idx_archived_files_available ON aboa.archived_files
USING btree
(
	available
);
-- ddl-end --

-- object: idx_archived_files_expiration_date | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_expiration_date CASCADE;
CREATE INDEX idx_archived_files_expiration_date ON aboa.archived_files
USING btree
(
	expiration_date
);
-- ddl-end --

-- object: idx_archived_files_removal_date | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_removal_date CASCADE;
CREATE INDEX idx_archived_files_removal_date ON aboa.archived_files
USING btree
(
	removal_date
);
-- ddl-end --

-- object: idx_archive_root_directories_active | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archive_root_directories_active CASCADE;
CREATE INDEX idx_archive_root_directories_active ON aboa.archive_root_directories
USING btree
(
	active
);
-- ddl-end --


