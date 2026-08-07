"""
Functions definition for the datamodel component.

module aboa
"""

import json
import os

from aboa.datamodel.errors import AboaResourcesPathNotAvailable


def get_resources_path():
    """
    Return the ABOA resources path from the environment.

    :raises AboaResourcesPathNotAvailable: when ABOA_RESOURCES_PATH is not defined
    """
    aboa_resources_path = os.environ.get("ABOA_RESOURCES_PATH")
    if aboa_resources_path is None:
        raise AboaResourcesPathNotAvailable("The environment variable ABOA_RESOURCES_PATH is not defined")
    return aboa_resources_path


def read_configuration():
    """
    Read the datamodel configuration JSON.

    :return: parsed datamodel configuration
    :rtype: dict
    """
    aboa_resources_path = get_resources_path()
    with open(os.path.join(aboa_resources_path, "datamodel.json")) as json_data_file:
        config = json.load(json_data_file)

    if "ABOA_DDBB_HOST" in os.environ:
        config["DDBB_CONFIGURATION"]["host"] = os.environ["ABOA_DDBB_HOST"]

    return config
