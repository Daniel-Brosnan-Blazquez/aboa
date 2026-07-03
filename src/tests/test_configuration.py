import unittest
from pathlib import Path

from aboa.engine.errors import ArchiveConfigurationError
from aboa.engine.parsing import get_archive_configuration


INPUTS = Path(__file__).parent / "inputs"


def input_configuration(name):
    return str(INPUTS / name)


class TestConfiguration(unittest.TestCase):
    def test_get_archive_configuration_returns_xpath_evaluator(self):
        configuration = get_archive_configuration(input_configuration("example_basic.xml"))

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

    def test_retention_policies_can_be_selected(self):
        configuration = get_archive_configuration(input_configuration("example_with_retention.xml"))

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
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("does_not_exist.xml"))

    def test_invalid_key_configuration_is_rejected(self):
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("example_invalid_key.xml"))

    def test_invalid_duration_configuration_is_rejected(self):
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("example_invalid_duration.xml"))

    def test_missing_required_attribute_configuration_is_rejected(self):
        with self.assertRaises(ArchiveConfigurationError):
            get_archive_configuration(input_configuration("example_missing_attribute.xml"))
