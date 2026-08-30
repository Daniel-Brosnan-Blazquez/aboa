"""
Functions definition for the datamodel component.

module aboa
"""

import json
import os

import aboa


def get_resources_path():
    """
    Return the ABOA resources path.

    Use ``ABOA_RESOURCES_PATH`` when it is defined. Otherwise, use the default
    configuration bundled inside the ``aboa`` package.
    """
    aboa_resources_path = os.environ.get("ABOA_RESOURCES_PATH")
    if aboa_resources_path is None:
        aboa_resources_path = os.path.join(os.path.dirname(aboa.__file__), "config")
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
