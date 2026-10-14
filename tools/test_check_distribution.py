"""Regression tests for finding installed console launchers."""

from importlib.metadata import PackagePath
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from check_distribution import resolve_console_script


class ConsoleScriptTests(unittest.TestCase):
    """
    Verify launcher discovery across supported installation locations.
    """

    def setUp(self):
        """
        Create an isolated package layout and mock script search locations.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packages = self.root / "lib" / "python3.12" / "site-packages"
        self.packages.mkdir(parents=True)
        self.command = "aboa_init.py"
        self.distribution = Mock()
        self.distribution.files = [PackagePath("aboa/scripts/" + self.command)]
        self.distribution.locate_file.side_effect = lambda file: self.packages / file
        self.addCleanup(patch.stopall)
        self.default_scripts = self.root / "system-bin"
        patch("check_distribution.sysconfig.get_path", return_value=str(self.default_scripts)).start()
        self.which = patch("check_distribution.shutil.which", return_value=None).start()

    def launcher(self, folder):
        """
        Create an executable launcher fixture in ``folder`` and return its path.
        """
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / self.command
        path.write_text("#!/usr/bin/env python3\n")
        path.chmod(0o755)
        return path

    def test_user_install_uses_recorded_launcher_when_not_on_path(self):
        """
        Find a recorded user launcher while ignoring a matching package module.
        """
        launcher = self.launcher(self.root / "bin")
        self.distribution.files.append(PackagePath("../../../bin/" + self.command))
        # A package module has the same basename but is not a console launcher.
        self.launcher(self.packages / "aboa" / "scripts")
        self.assertEqual(resolve_console_script(self.command, self.distribution), launcher)

    def test_virtual_environment_uses_its_scripts_directory(self):
        """
        Find a launcher in the interpreter's scripts directory without PATH.
        """
        launcher = self.launcher(self.default_scripts)
        self.assertEqual(resolve_console_script(self.command, self.distribution), launcher)

    def test_target_install_finds_bin_inside_distribution_root(self):
        """
        Find a target installation's launcher in its local ``bin`` directory.
        """
        launcher = self.launcher(self.packages / "bin")
        self.assertEqual(resolve_console_script(self.command, self.distribution), launcher)

    def test_custom_launcher_can_be_found_on_path(self):
        """
        Use PATH when the launcher is absent from the other search locations.
        """
        launcher = self.launcher(self.root / "custom-bin")
        self.which.return_value = str(launcher)
        self.assertEqual(resolve_console_script(self.command, self.distribution), launcher)

    def test_missing_or_non_executable_launcher_has_actionable_error(self):
        """
        Reject a non-executable launcher with a clear installation error.
        """
        launcher = self.launcher(self.default_scripts)
        launcher.chmod(0o644)
        with self.assertRaisesRegex(SystemExit, "Installed console command aboa_init.py was not found"):
            resolve_console_script(self.command, self.distribution)


if __name__ == "__main__":
    unittest.main()
