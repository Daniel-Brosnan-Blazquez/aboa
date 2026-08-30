"""
Functions definition for the engine component.

module aboa
"""

import datetime
import json
import os

import aboa
from dateutil import parser

from aboa.engine.errors import (
    AboaLogPathNotAvailable,
    InputError,
)
from aboa.engine.operators import arithmetic_operators, text_operators


def is_datetime(date):
    """
    Check whether a value can be parsed as a datetime.

    :param date: value to parse
    :type date: str

    :return: True when parsing succeeds
    :rtype: bool
    """
    try:
        parser.parse(date)
    except Exception:
        return False
    return True


def parse_datetime(value):
    """
    Parse a value into a datetime object.

    :param value: datetime, string, or None
    :type value: datetime.datetime or str or None

    :return: datetime object or None
    :rtype: datetime.datetime or None
    """
    if value is None or isinstance(value, datetime.datetime):
        return value
    return parser.parse(value)


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


def get_log_path():
    """
    Return the ABOA log path from the environment.

    :raises AboaLogPathNotAvailable: when ABOA_LOG_PATH is not defined
    """
    aboa_log_path = os.environ.get("ABOA_LOG_PATH")
    if aboa_log_path is None:
        raise AboaLogPathNotAvailable("The environment variable ABOA_LOG_PATH is not defined")
    return aboa_log_path


def read_configuration():
    """
    Read the engine configuration JSON from ABOA_RESOURCES_PATH.

    :return: parsed engine configuration
    :rtype: dict
    """
    with open(os.path.join(get_resources_path(), "engine.json")) as json_data_file:
        return json.load(json_data_file)


def is_valid_positive_integer(value):
    """
    Validate a non-negative integer value.

    :param value: value to validate
    :raises InputError: when the value is not a non-negative integer
    """
    try:
        int(value)
    except (TypeError, ValueError):
        raise InputError("The parameter filter must be an integer (received filter: {}).".format(value))
    if int(value) < 0:
        raise InputError("The parameter filter must be a positive integer (received filter: {}).".format(value))
    return True


def is_valid_order_by(order_by):
    """
    Validate an order-by descriptor.

    :param order_by: dictionary with field and descending keys
    :type order_by: dict
    :raises InputError: when the descriptor is malformed
    """
    if type(order_by) != dict:
        raise InputError("The parameter order_by must be a dictionary (received order_by: {}).".format(order_by))
    if set(order_by.keys()) != set(["field", "descending"]):
        raise InputError("Every order_by should be a dictionary with keys field and descending.")
    if type(order_by["field"]) != str:
        raise InputError("The key field inside order_by must be a string.")
    if type(order_by["descending"]) != bool:
        raise InputError("The key descending inside order_by must be a boolean.")
    return True


def is_valid_text_filter(text_filter):
    """
    Validate an ABOA text filter.

    :param text_filter: dictionary with filter and op keys
    :type text_filter: dict
    :raises InputError: when the filter is malformed
    """
    if type(text_filter) != dict:
        raise InputError("The parameter text_filter must be a dictionary.")
    if set(text_filter.keys()) != set(["filter", "op"]):
        raise InputError("Every text_filter should be a dictionary with keys filter and op.")
    if text_filter["op"] not in text_operators:
        raise InputError("The specified op is not a valid text operator.")
    if text_filter["op"] in ("in", "notin"):
        if type(text_filter["filter"]) != list:
            raise InputError("The filter for in/notin operators must be a list.")
    elif type(text_filter["filter"]) != str:
        raise InputError("The filter for text operators must be a string.")
    return True


def is_valid_date_filters(date_filters):
    """
    Validate a list of date filter dictionaries.

    :param date_filters: filters with date and op keys
    :type date_filters: list
    :raises InputError: when any filter is malformed
    """
    if type(date_filters) != list:
        raise InputError("The parameter date_filters must be a list of dictionaries.")
    for date_filter in date_filters:
        if type(date_filter) != dict:
            raise InputError("The parameter date_filters must contain dictionaries.")
        if set(date_filter.keys()) != set(["date", "op"]):
            raise InputError("Every date_filter should be a dictionary with keys date and op.")
        if date_filter["op"] not in arithmetic_operators:
            raise InputError("The specified op is not a valid operator.")
        if not is_datetime(date_filter["date"]):
            raise InputError("The specified date is not a valid date.")
    return True


def is_valid_number_filters(number_filters):
    """
    Validate a list of numeric filter dictionaries.

    :param number_filters: filters with number and op keys
    :type number_filters: list
    :raises InputError: when any filter is malformed
    """
    if type(number_filters) != list:
        raise InputError("The parameter number_filters must be a list of dictionaries.")
    for number_filter in number_filters:
        if type(number_filter) != dict:
            raise InputError("The parameter number_filters must contain dictionaries.")
        if set(number_filter.keys()) != set(["number", "op"]):
            raise InputError("Every number_filter should be a dictionary with keys number and op.")
        if number_filter["op"] not in arithmetic_operators:
            raise InputError("The specified op is not a valid operator.")
        try:
            float(number_filter["number"])
        except (TypeError, ValueError):
            raise InputError("The specified number is not valid.")
    return True

def is_valid_bool_filter(bool_filter):
    """
    Validate a boolean filter dictionary.

    :param bool_filter: dictionary with filter and op keys
    :type bool_filter: dict
    :raises InputError: when the filter is malformed
    """
    if type(bool_filter) != dict:
        raise InputError("The parameter bool_filter must be a dictionary.")
    if set(bool_filter.keys()) != set(["filter", "op"]):
        raise InputError("Every bool_filter should be a dictionary with keys filter and op.")
    if bool_filter["op"] not in arithmetic_operators:
        raise InputError("The specified op is not a valid operator.")
    if type(bool_filter["filter"]) != bool:
        raise InputError("The bool filter value must be a boolean.")
    return True
