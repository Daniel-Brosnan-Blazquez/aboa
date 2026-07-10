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

-- object: aboa.archive_configurations | type: TABLE --
-- DROP TABLE IF EXISTS aboa.archive_configurations CASCADE;
CREATE TABLE aboa.archive_configurations (
	archive_configuration_uuid uuid NOT NULL,
	path text NOT NULL,
	active_from timestamp NOT NULL,
	active_until timestamp,
	active bool NOT NULL,
	content text NOT NULL,
	CONSTRAINT archive_configurations_pk PRIMARY KEY (archive_configuration_uuid)
);
-- ddl-end --
ALTER TABLE aboa.archive_configurations OWNER TO aboa;
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
	physical_available bool NOT NULL,
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
	removal_justification text,
	checksum text,
	archive_configuration_uuid uuid,
	delete_archive_configuration_uuid uuid,
	root_directory_uuid uuid NOT NULL,
	archive_configuration_uuid1 uuid,
	delete_archive_configuration_uuid1 uuid,
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

-- object: archived_files_archive_configurations_fk | type: CONSTRAINT --
-- ALTER TABLE aboa.archived_files DROP CONSTRAINT IF EXISTS archived_files_archive_configurations_fk CASCADE;
ALTER TABLE aboa.archived_files ADD CONSTRAINT archived_files_archive_configurations_fk FOREIGN KEY (archive_configuration_uuid1)
REFERENCES aboa.archive_configurations (archive_configuration_uuid) MATCH FULL
ON DELETE SET NULL ON UPDATE CASCADE;
-- ddl-end --

-- object: archived_files_delete_archive_configurations_fk | type: CONSTRAINT --
-- ALTER TABLE aboa.archived_files DROP CONSTRAINT IF EXISTS archived_files_delete_archive_configurations_fk CASCADE;
ALTER TABLE aboa.archived_files ADD CONSTRAINT archived_files_delete_archive_configurations_fk FOREIGN KEY (delete_archive_configuration_uuid1)
REFERENCES aboa.archive_configurations (archive_configuration_uuid) MATCH FULL
ON DELETE SET NULL ON UPDATE CASCADE;
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

-- object: aboa.files_to_be_removed | type: TABLE --
-- DROP TABLE IF EXISTS aboa.files_to_be_removed CASCADE;
CREATE TABLE aboa.files_to_be_removed (
	file_uuid uuid NOT NULL,
	file_to_remove_uuid uuid NOT NULL,
	root_directory_uuid uuid NOT NULL,
	path text NOT NULL,
	removal_date timestamp NOT NULL,
	CONSTRAINT files_to_be_removed_pk PRIMARY KEY (file_to_remove_uuid)
);
-- ddl-end --
ALTER TABLE aboa.files_to_be_removed OWNER TO aboa;
-- ddl-end --

-- object: files_to_be_removed_archived_files_fk | type: CONSTRAINT --
-- ALTER TABLE aboa.files_to_be_removed DROP CONSTRAINT IF EXISTS files_to_be_removed_archived_files_fk CASCADE;
ALTER TABLE aboa.files_to_be_removed ADD CONSTRAINT files_to_be_removed_archived_files_fk FOREIGN KEY (file_uuid)
REFERENCES aboa.archived_files (file_uuid) MATCH FULL
ON DELETE CASCADE ON UPDATE CASCADE;
-- ddl-end --

-- object: files_to_be_removed_archive_root_directories_fk | type: CONSTRAINT --
-- ALTER TABLE aboa.files_to_be_removed DROP CONSTRAINT IF EXISTS files_to_be_removed_archive_root_directories_fk CASCADE;
ALTER TABLE aboa.files_to_be_removed ADD CONSTRAINT files_to_be_removed_archive_root_directories_fk FOREIGN KEY (root_directory_uuid)
REFERENCES aboa.archive_root_directories (root_directory_uuid) MATCH FULL
ON DELETE RESTRICT ON UPDATE CASCADE;
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

-- object: idx_archived_files_physical_available | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_physical_available CASCADE;
CREATE INDEX idx_archived_files_physical_available ON aboa.archived_files
USING btree
(
	physical_available
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

-- object: idx_archived_files_removal_justification | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_removal_justification CASCADE;
CREATE INDEX idx_archived_files_removal_justification ON aboa.archived_files
USING btree
(
	removal_justification
);
-- ddl-end --

-- object: idx_archived_files_archive_configuration_uuid | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_archive_configuration_uuid CASCADE;
CREATE INDEX idx_archived_files_archive_configuration_uuid ON aboa.archived_files
USING btree
(
	archive_configuration_uuid
);
-- ddl-end --

-- object: idx_archived_files_delete_archive_configuration_uuid | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archived_files_delete_archive_configuration_uuid CASCADE;
CREATE INDEX idx_archived_files_delete_archive_configuration_uuid ON aboa.archived_files
USING btree
(
	delete_archive_configuration_uuid
);
-- ddl-end --

-- object: idx_files_to_be_removed_path | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_files_to_be_removed_path CASCADE;
CREATE INDEX idx_files_to_be_removed_path ON aboa.files_to_be_removed
USING btree
(
	path
);
-- ddl-end --

-- object: idx_files_to_be_removed_root_directory_uuid | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_files_to_be_removed_root_directory_uuid CASCADE;
CREATE INDEX idx_files_to_be_removed_root_directory_uuid ON aboa.files_to_be_removed
USING btree
(
	root_directory_uuid
);
-- ddl-end --

-- object: idx_files_to_be_removed_removal_date | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_files_to_be_removed_removal_date CASCADE;
CREATE INDEX idx_files_to_be_removed_removal_date ON aboa.files_to_be_removed
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

-- object: idx_archive_configurations_active | type: INDEX --
-- DROP INDEX IF EXISTS aboa.idx_archive_configurations_active CASCADE;
CREATE INDEX idx_archive_configurations_active ON aboa.archive_configurations
USING btree
(
	active
);
-- ddl-end --

