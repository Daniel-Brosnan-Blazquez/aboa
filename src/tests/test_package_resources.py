"""
Tests for package-installed ABOA resource files.
"""

from pathlib import Path

import aboa


def test_package_resource_folders_are_inside_aboa_package():
    """
    Keep install-time resources under the aboa package directory.
    """
    package_path = Path(aboa.__file__).parent

    expected_files = (
        package_path / "config" / "archive_configurations.xml",
        package_path / "config" / "datamodel.json",
        package_path / "config" / "engine.json",
        package_path / "schemas" / "aboa_archive_configurations.xsd",
        package_path / "datamodel" / "aboa_data_model.sql",
    )

    for resource_file in expected_files:
        assert resource_file.is_file()
