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


def execute_command(command, success_message, check_error=True):
    """
    Execute a command and stop on failure.
    """
    command_split = shlex.split(command)
    program = Popen(command_split, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    output, error = program.communicate()
    if check_error and program.returncode != 0:
        print(
            "The execution of the command {} has ended unexpectedly with the following output: {} but the following error: {}".format(
                command,
                str(output.decode()),
                str(error.decode()),
            )
        )
        exit(-1)
    print(success_message)


def init(datamodel_path=None):
    """
    Initialize the ABOA DDBB using the generated datamodel SQL file.

    :param datamodel_path: optional path to the SQL datamodel
    :type datamodel_path: str or None
    """
    if datamodel_path is not None:
        if not os.path.isfile(datamodel_path):
            print("The specified path to the datamodel file {} does not exist".format(datamodel_path))
            exit(-1)
    else:
        # Default path for the docker environment.
        datamodel_path = "/datamodel/aboa_data_model.sql"

    database_address = db_configuration["host"]
    database_port = db_configuration["port"]
    database_name = db_configuration["database"]

    command = "aboa_init_ddbb.sh -h {} -p {} -d {} -f {}".format(
        database_address,
        database_port,
        database_name,
        datamodel_path,
    )
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
