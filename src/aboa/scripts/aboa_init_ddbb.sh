#!/bin/bash
#################################################################
#
# Init DDBB of the aboa
#
# module aboa
#################################################################
USAGE="Usage: `basename $0` -f datamodel_file -d ddbb -p port -h host"
DATAMODEL_FILE=""
DDBB="aboadb"
PORT="5432"
HOST="localhost"
DEFAULT_DATAMODEL_FILE="/datamodel/aboa_data_model.sql"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DATAMODEL_FILE="$SCRIPT_DIR/../datamodel/aboa_data_model.sql"

while getopts f:d:p:h: option
do
    case "${option}"
        in
        f) DATAMODEL_FILE=${OPTARG};;
        d) DDBB=${OPTARG};;
        p) PORT=${OPTARG};;
        h) HOST=${OPTARG};;
        ?) echo -e $USAGE
            exit -1
    esac
done

# Check that option -f has been specified
if [ "$DATAMODEL_FILE" == "" ];
then
    echo "ERROR: The option -f has to be provided"
    echo $USAGE
    exit -1
fi

# Check that option -d has been specified
if [ "$DDBB" == "" ];
then
    echo "ERROR: The option -d has to be provided"
    echo $USAGE
    exit -1
fi

# Check that the sql file for filling up the DDBB exists
if [ ! -f "$DATAMODEL_FILE" ];
then
    if [ "$DATAMODEL_FILE" == "$DEFAULT_DATAMODEL_FILE" ] && [ -f "$PACKAGE_DATAMODEL_FILE" ];
    then
        DATAMODEL_FILE="$PACKAGE_DATAMODEL_FILE"
    else
        echo "ERROR: The file $DATAMODEL_FILE provided does not exist"
        exit -1
    fi
fi

# Check that there are no connections to the DDBB if exists
DATABASE=`psql -p "$PORT" -h "$HOST" -t -U postgres -c "SELECT count(*) FROM pg_database WHERE datname='$DDBB';"`
if [ $DATABASE -eq 1 ];
then
    CONNECTIONS=`psql -p "$PORT" -h "$HOST" -U postgres -t -c "SELECT count(*) FROM pg_stat_activity where datname = '$DDBB';"`
    if [ $CONNECTIONS -ne 0 ];
    then
        echo "ERROR: There are $((CONNECTIONS + 0)) active connections to the DDBB"
        exit -1
    fi
fi

# Remove DDBB if it exists
if [ $DATABASE -eq 1 ];
then
    psql -p "$PORT" -h "$HOST" -U postgres -c "DROP DATABASE $DDBB;"
fi

# Drop the aboa role if it exists. The generated datamodel SQL creates it again.
ROLE=`psql -p "$PORT" -h "$HOST" -t -U postgres -c "SELECT count(*) FROM pg_roles WHERE rolname='aboa';"`
if [ $ROLE -eq 1 ];
then
    psql -p "$PORT" -h "$HOST" -U postgres -c "DROP ROLE aboa;"
fi

# Create DDBB
psql -p "$PORT" -h "$HOST" -U postgres -c "CREATE DATABASE $DDBB;"

# Add extension for postgis when the database engine provides it.
psql -p "$PORT" -h "$HOST" -U postgres -d "$DDBB" -c "CREATE EXTENSION IF NOT EXISTS postgis;"

# pgModeler keeps CREATE DATABASE in the generated SQL as a convenience, but the
# database has to be created before the script can connect and load the schema.
TEMP_DATAMODEL_FILE=`mktemp`
sed "/^CREATE DATABASE /d" "$DATAMODEL_FILE" > "$TEMP_DATAMODEL_FILE"

# Fill DDBB
psql -p "$PORT" -h "$HOST" -U postgres -d "$DDBB" -f "$TEMP_DATAMODEL_FILE"
status=$?
rm -f "$TEMP_DATAMODEL_FILE"

if [ $status -ne 0 ];
then
    echo "ERROR: It was not possible to fill up the DDBB"
    exit -1
fi

echo "DDBB has been initiated correctly!"

exit 0
