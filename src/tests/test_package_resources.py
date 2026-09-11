"""
Tests for package-installed ABOA resource files.
"""

from pathlib import Path

import aboa
from aboa.scripts import aboa_init


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
        package_path / "scripts" / "aboa_init_ddbb.sh",
        package_path / "scripts" / "initialize_aboa_ddbb.sh",
        package_path / "scripts" / "start_aboa.sh",
    )

    for resource_file in expected_files:
        assert resource_file.is_file()


def test_aboa_init_uses_packaged_datamodel_when_default_datamodel_is_missing(monkeypatch):
    """
    Fall back to the package SQL file when the Docker-mounted datamodel is absent.
    """
    commands = []

    def fake_isfile(path):
        return path == aboa_init.PACKAGE_DATAMODEL_PATH

    def fake_execute_command(command, success_message, check_error=True):
        commands.append(command)

    monkeypatch.setattr(aboa_init.os.path, "isfile", fake_isfile)
    monkeypatch.setattr(aboa_init, "execute_command", fake_execute_command)

    assert aboa_init.resolve_datamodel_path(aboa_init.DEFAULT_DATAMODEL_PATH) == aboa_init.PACKAGE_DATAMODEL_PATH

    aboa_init.init()

    assert commands[0][commands[0].index("-f") + 1] == aboa_init.PACKAGE_DATAMODEL_PATH
