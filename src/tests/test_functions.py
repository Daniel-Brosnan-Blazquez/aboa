"""
Tests for engine and datamodel helper validation functions.
"""

import datetime
import os
import unittest
from pathlib import Path

from lxml import etree

from aboa.datamodel import errors as datamodel_errors
from aboa.datamodel import functions as datamodel_functions
from aboa.engine import functions as engine_functions
from aboa.engine.errors import (
    AboaLogPathNotAvailable,
    AboaResourcesPathNotAvailable,
    InputError,
)
from aboa.engine.xpath_functions import _xpath_match


INPUTS = Path(__file__).parent / "inputs"


class TestFunctions(unittest.TestCase):
    """
    Unit tests for shared validators and environment helpers.
    """

    def setUp(self):
        """
        Preserve environment variables mutated by these tests.
        """
        self.environment = os.environ.copy()

    def tearDown(self):
        """
        Restore the process environment.
        """
        os.environ.clear()
        os.environ.update(self.environment)

    def test_environment_helpers_raise_when_required_paths_are_missing(self):
        """
        Report missing runtime path environment variables explicitly.
        """
        os.environ.pop("ABOA_RESOURCES_PATH", None)
        os.environ.pop("ABOA_LOG_PATH", None)

        with self.assertRaises(AboaResourcesPathNotAvailable):
            engine_functions.get_resources_path()
        with self.assertRaises(AboaLogPathNotAvailable):
            engine_functions.get_log_path()
        with self.assertRaises(datamodel_errors.AboaResourcesPathNotAvailable):
            datamodel_functions.get_resources_path()

    def test_datamodel_configuration_accepts_database_host_environment_override(self):
        """
        Apply datamodel database host overrides from the environment.
        """
        os.environ["ABOA_DDBB_HOST"] = "db.example.test"

        configuration = datamodel_functions.read_configuration()

        assert configuration["DDBB_CONFIGURATION"]["host"] == "db.example.test"

    def test_datamodel_configuration_uses_defaults_without_host_override(self):
        """
        Leave database configuration defaults unchanged when overrides are absent.
        """
        os.environ.pop("ABOA_DDBB_HOST", None)

        configuration = datamodel_functions.read_configuration()

        assert configuration["DDBB_CONFIGURATION"]["host"] == "localhost"
        assert configuration["DDBB_CONFIGURATION"]["db_api"] == "postgresql"

    def test_datetime_helpers_accept_objects_and_reject_invalid_text(self):
        """
        Parse valid datetime inputs and reject invalid values in is_datetime.
        """
        value = datetime.datetime(2026, 7, 16, 10, 30, 0)

        assert engine_functions.parse_datetime(None) is None
        assert engine_functions.parse_datetime(value) is value
        assert engine_functions.is_datetime("not-a-date") is False

    def test_positive_integer_validation_rejects_invalid_values(self):
        """
        Validate non-negative integers and reject malformed values.
        """
        assert engine_functions.is_valid_positive_integer("0") is True
        with self.assertRaises(InputError):
            engine_functions.is_valid_positive_integer("five")
        with self.assertRaises(InputError):
            engine_functions.is_valid_positive_integer(-1)

    def test_order_by_validation_rejects_malformed_descriptors(self):
        """
        Reject each malformed order-by shape.
        """
        for value in (
            "archive_date",
            {"field": "archive_date"},
            {"field": 1, "descending": False},
            {"field": "archive_date", "descending": "no"},
        ):
            with self.subTest(value=value):
                with self.assertRaises(InputError):
                    engine_functions.is_valid_order_by(value)

    def test_text_filter_validation_rejects_malformed_descriptors(self):
        """
        Reject invalid text filter operators and value types.
        """
        for value in (
            "name",
            {"filter": "sample.txt"},
            {"filter": "sample.txt", "op": "bad"},
            {"filter": "sample.txt", "op": "in"},
            {"filter": 1, "op": "like"},
        ):
            with self.subTest(value=value):
                with self.assertRaises(InputError):
                    engine_functions.is_valid_text_filter(value)

    def test_date_filter_validation_rejects_malformed_descriptors(self):
        """
        Reject invalid date filter containers, operators, and values.
        """
        for value in (
            {"date": "2026-07-16T00:00:00", "op": "=="},
            ["2026-07-16T00:00:00"],
            [{"date": "2026-07-16T00:00:00"}],
            [{"date": "2026-07-16T00:00:00", "op": "bad"}],
            [{"date": "not-a-date", "op": "=="}],
        ):
            with self.subTest(value=value):
                with self.assertRaises(InputError):
                    engine_functions.is_valid_date_filters(value)

    def test_number_filter_validation_rejects_malformed_descriptors(self):
        """
        Reject invalid number filter containers, operators, and values.
        """
        for value in (
            {"number": 1, "op": "=="},
            [1],
            [{"number": 1}],
            [{"number": 1, "op": "bad"}],
            [{"number": "many", "op": "=="}],
        ):
            with self.subTest(value=value):
                with self.assertRaises(InputError):
                    engine_functions.is_valid_number_filters(value)

    def test_bool_filter_validation_rejects_malformed_descriptors(self):
        """
        Reject invalid boolean filter containers, operators, and values.
        """
        for value in (
            True,
            {"filter": True},
            {"filter": True, "op": "bad"},
            {"filter": "true", "op": "=="},
        ):
            with self.subTest(value=value):
                with self.assertRaises(InputError):
                    engine_functions.is_valid_bool_filter(value)

    def test_xpath_match_handles_list_arguments_and_element_masks(self):
        """
        Match XPath extension arguments passed as lists or XML nodes.
        """
        mask = etree.parse(str(INPUTS / "xpath_mask.xml")).getroot()

        assert _xpath_match(None, [mask], ["sample.txt"]) is True
        assert _xpath_match(None, [None], []) is False
