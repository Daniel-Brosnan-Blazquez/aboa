#!/usr/bin/env python3
"""
Script for initializing ABOA environment.

module aboa
"""

import argparse
import os
import shlex
from subprocess import PIPE, Popen

from aboa.datamodel.functions import read_configuration


config = read_configuration()
db_configuration = config["DDBB_CONFIGURATION"]
DEFAULT_DATAMODEL_PATH = "/datamodel/aboa_data_model.sql"
PACKAGE_DATAMODEL_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "datamodel", "aboa_data_model.sql")
)


def execute_command(command, success_message, check_error=True):
    """
    Execute a command and stop on failure.
    """
    if isinstance(command, str):
        command_split = shlex.split(command)
    else:
        command_split = command
    command_display = " ".join(shlex.quote(str(part)) for part in command_split)
    program = Popen(command_split, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    output, error = program.communicate()
    if check_error and program.returncode != 0:
        print(
            "The execution of the command {} has ended unexpectedly with the following output: {} but the following error: {}".format(
                command_display,
                str(output.decode()),
                str(error.decode()),
            )
        )
        exit(-1)
    print(success_message)


def resolve_datamodel_path(datamodel_path=None):
    """
    Resolve the SQL datamodel path used to initialize the database.

    :param datamodel_path: optional path to the SQL datamodel
    :type datamodel_path: str or None
    :return: path to an existing SQL datamodel
    :rtype: str
    """
    if datamodel_path is None:
        datamodel_path = DEFAULT_DATAMODEL_PATH

    if os.path.isfile(datamodel_path):
        return datamodel_path

    if datamodel_path == DEFAULT_DATAMODEL_PATH:
        if os.path.isfile(PACKAGE_DATAMODEL_PATH):
            return PACKAGE_DATAMODEL_PATH
        print(
            "Neither the default datamodel file {} nor the package datamodel file {} exists".format(
                DEFAULT_DATAMODEL_PATH,
                PACKAGE_DATAMODEL_PATH,
            )
        )
        exit(-1)

    print("The specified path to the datamodel file {} does not exist".format(datamodel_path))
    exit(-1)


def init(datamodel_path=None):
    """
    Initialize the ABOA DDBB using the generated datamodel SQL file.

    :param datamodel_path: optional path to the SQL datamodel
    :type datamodel_path: str or None
    """
    datamodel_path = resolve_datamodel_path(datamodel_path)

    database_address = db_configuration["host"]
    database_port = db_configuration["port"]
    database_name = db_configuration["database"]
    script_path = os.path.join(os.path.dirname(__file__), "aboa_init_ddbb.sh")

    command = [
        "bash",
        script_path,
        "-h",
        str(database_address),
        "-p",
        str(database_port),
        "-d",
        str(database_name),
        "-f",
        str(datamodel_path),
    ]
    print("The ABOA database is going to be initialized using the datamodel SQL file {}...".format(datamodel_path))
    execute_command(command, "The ABOA database has been initialized successfully :-)")


def main():
    """
    Command-line entry point.
    """
    args_parser = argparse.ArgumentParser(description="Initialize ABOA environment.")
    args_parser.add_argument("-f", dest="datamodel_path", type=str, nargs=1, help="path to the datamodel", required=False)
    args_parser.add_argument(
        "-y",
        "--accept_everything",
        help="Accept by default every request. Be careful: this drops all existing ABOA data.",
        action="store_true",
    )

    args = args_parser.parse_args()

    if not args.accept_everything:
        continue_flag = input(
            "\n"
            "Welcome to the ABOA initializer :-)\n"
            "You are about to initialize the DDBB of the archive engine.\n"
            "This operation will erase all the information stored related to ABOA, would you still want to continue? [Ny]"
        )

        if continue_flag != "y":
            print("No worries! The initialization is going to be aborted :-)")
            exit(0)

    datamodel_path = None
    if args.datamodel_path is not None:
        datamodel_path = args.datamodel_path[0]

    init(datamodel_path)
    exit(0)


if __name__ == "__main__":
    main()
