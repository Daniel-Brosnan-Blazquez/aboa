"""
Tests for archive XML configuration parsing and schema validation.
"""

import unittest
from pathlib import Path

from aboa.engine.errors import ArchiveConfigurationError
from aboa.engine.parsing import get_archive_configuration


INPUTS = Path(__file__).parent / "inputs"


def input_configuration(name):
    """
    Return an XML configuration fixture path by file name.
    """
    return str(INPUTS / name)


class TestConfiguration(unittest.TestCase):
    """
    Parser tests for valid and invalid archive configuration fixtures.
    """

    def test_get_archive_configuration_returns_xpath_evaluator(self):
        """
        Parse a basic XML configuration into a callable XPath evaluator.
        """
        configuration = get_archive_configuration(input_configuration("example_basic.xml"))

        # The engine relies on XPath selections rather than persisted rule rows.
        self.assertTrue(callable(configuration))
        self.assertEqual(
            configuration("string(/archive_configurations/@root_directory)"),
            "/tmp/aboa_archive",
        )
        self.assertEqual(
            configuration("string(/archive_configurations/archive_configuration/@file_group)"),
            "group_a",
        )
        self.assertEqual(
            configuration("string(/archive_configurations/archive_configuration/file_mask)"),
            "*.txt",
        )
        self.assertEqual(
            configuration("string(/archive_configurations/archive_configuration/file_directory)"),
            "texts",
        )

    def test_multiple_archive_configurations_can_be_selected(self):
        """
        Select multiple archive rules and rule-specific processor values.
        """
        configuration = get_archive_configuration(input_configuration("example_multiple_groups.xml"))

        self.assertEqual(configuration("count(/archive_configurations/archive_configuration)"), 2.0)
        self.assertEqual(
            configuration("/archive_configurations/archive_configuration/@file_group"),
            ["images", "documents"],
        )
        self.assertEqual(
            configuration("/archive_configurations/archive_configuration/file_directory/text()"),
            ["images", "documents"],
        )
        self.assertEqual(
            configuration("string(/archive_configurations/archive_configuration[@file_group='images']/file_processor)"),
            "metadata_processor",
        )

    def test_duplicate_archive_configuration_fields_are_warned(self):
        """
        Warn about duplicated archive-rule routing values without rejecting XML.
        """
        with self.assertLogs("aboa.engine.parsing", level="WARNING") as log_records:
            configuration = get_archive_configuration(input_configuration("example_duplicate_archive_configuration_fields.xml"))

        warnings = "\n".join(log_records.output)
        self.assertEqual(configuration("count(/archive_configurations/archive_configuration)"), 3.0)
        self.assertIn("same file_group 'group_a'", warnings)
        self.assertIn("same file_mask '*.txt'", warnings)
        self.assertIn("same file_directory 'texts'", warnings)

    def test_retention_policies_can_be_selected(self):
        """
        Read retention policies from global and archive-rule XML locations.
        """
        configuration = get_archive_configuration(input_configuration("example_with_retention.xml"))

        # Retention policies can be attached either to a specific archive rule or
        # to the global retention_policies section.
        archive_policy = configuration(
            "/archive_configurations/archive_configuration[@file_group='invoices']/retention_policy"
        )[0]
        global_policy = configuration("/archive_configurations/retention_policies/retention_policy")[0]

        self.assertEqual(archive_policy.get("key"), "archive_date")
        self.assertEqual(archive_policy.get("active"), "true")
        self.assertEqual(archive_policy.text, "P180D")
        self.assertEqual(global_policy.get("key"), "validity_stop_date")
        self.assertEqual(global_policy.get("active"), "true")
        self.assertEqual(global_policy.text, "P365D")

    def test_missing_configuration_file_is_rejected(self):
        """
        Reject configuration paths that do not exist.
        """
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("does_not_exist.xml"))

    def test_invalid_key_configuration_is_rejected(self):
        """
        Reject retention policies using keys outside the schema enumeration.
        """
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("example_invalid_key.xml"))

    def test_last_access_date_retention_key_is_rejected(self):
        """
        Reject last-access timestamps as retention policy keys.
        """
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("example_invalid_last_access_key.xml"))

    def test_invalid_duration_configuration_is_rejected(self):
        """
        Reject retention policy durations that are not XML duration values.
        """
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("example_invalid_duration.xml"))

    def test_missing_required_attribute_configuration_is_rejected(self):
        """
        Reject retention policies missing schema-required attributes.
        """
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("example_missing_attribute.xml"))

    def test_multiple_archive_rule_retention_policies_are_rejected(self):
        """
        Reject more than one retention policy inside a single archive rule.
        """
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("example_multiple_archive_rule_retention_policies.xml"))

    def test_multiple_global_retention_policies_are_rejected(self):
        """
        Reject more than one retention policy inside the global policy section.
        """
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("example_multiple_global_retention_policies.xml"))
