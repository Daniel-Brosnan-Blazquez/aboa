"""Check release artifacts and, optionally, a clean installed package."""

import argparse
import configparser
from email.parser import BytesParser
import importlib.metadata
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sysconfig
import tarfile
import tempfile
import zipfile


RESOURCES = (
    "config/archive_configurations.xml",
    "config/datamodel.json",
    "config/engine.json",
    "schemas/aboa_archive_configurations.xsd",
    "datamodel/aboa_data_model.sql",
    "scripts/aboa_init_ddbb.sh",
    "scripts/initialize_aboa_ddbb.sh",
    "scripts/start_aboa.sh",
)
COMMANDS = (
    "aboa_init.py",
    "aboa_archive.py",
    "aboa_retrieve.py",
    "aboa_delete.py",
    "aboa_recover.py",
    "aboa_clean_up.py",
)


def require(condition, message):
    """
    Stop validation with ``message`` when ``condition`` is false.

    :param condition: validation result to check
    :param message: error message shown when validation fails
    :raises SystemExit: when the condition is false
    """
    if not condition:
        raise SystemExit(message)


def check_contents(names, prefix):
    """
    Check bundled runtime resources and reject development artifacts.

    :param names: archive member paths using POSIX separators
    :param prefix: path before the ``aboa/`` package directory; empty for a
        wheel or the source archive's root directory followed by ``src/``
    :raises SystemExit: when a resource is missing or test output or Python
        caches are included
    """
    for resource in RESOURCES:
        require(prefix + "aboa/" + resource in names, "Missing resource: " + resource)
    for name in names:
        parts = PurePosixPath(name).parts
        require(
            not {"tests", "__pycache__", ".pytest_cache"}.intersection(parts)
            and PurePosixPath(name).name != ".coverage"
            and not name.endswith((".pyc", ".pyo")),
            "Development artifact in distribution: " + name,
        )


def check_metadata(data, tag):
    """
    Validate release metadata and an optional version tag.

    :param data: bytes from a wheel's ``METADATA`` or an sdist's ``PKG-INFO``
    :param tag: expected release tag, such as ``v0.1.0``; empty to skip matching
    :return: parsed package metadata
    :raises SystemExit: when required metadata is missing or invalid, or the
        tag does not match the package version
    """
    metadata = BytesParser().parsebytes(data)
    require(metadata["Name"] == "aboa", "Unexpected distribution name")
    require(metadata["Requires-Python"] == ">=3.9", "Missing Python compatibility metadata")
    require(metadata["License-Expression"] == "MIT", "Missing MIT license metadata")
    require(metadata["Description-Content-Type"] == "text/markdown", "Missing Markdown description")
    require(metadata.get_payload().startswith("# ABOA"), "Missing README description")
    require(metadata.get_all("Requires-Dist"), "Missing runtime dependencies")
    require(metadata.get_all("Project-URL"), "Missing project URLs")
    require(metadata["Version"], "Missing version")
    if tag:
        require(tag == "v" + metadata["Version"], "Release tag must match v" + metadata["Version"])
    return metadata


def resolve_console_script(command, distribution):
    """
    Find an executable console launcher for an installed distribution.

    Search installation file records, the interpreter's scripts directory,
    the distribution root's ``bin`` directory, and ``PATH``, in that order.
    Exclude package modules that share the launcher's filename.

    :param command: installed console command name, including any suffix
    :param distribution: distribution metadata used to locate installed files
    :return: absolute, resolved path to the first executable launcher found
    :raises SystemExit: when no executable launcher can be found
    """
    candidates = [
        Path(distribution.locate_file(file))
        for file in distribution.files or ()
        if file.name == command and file.parts[:2] != ("aboa", "scripts")
    ]
    candidates.extend((
        Path(sysconfig.get_path("scripts")) / command,
        Path(distribution.locate_file("bin")) / command,
    ))
    on_path = shutil.which(command)
    if on_path:
        candidates.append(Path(on_path))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise SystemExit(
        "Installed console command " + command + " was not found. "
        "Install the release artifact with this Python interpreter and rerun "
        "the checker; for a custom installation, add its bin directory to PATH."
    )


def check_installed(version):
    """
    Validate the installed package's version, resources, and CLI help.

    Run every console command with ``--help``, using bundled configuration
    defaults and a temporary log directory without initializing a database.

    :param version: expected installed package version
    :raises SystemExit: when the version, resources, entry points, or command
        help output fail validation
    :raises importlib.metadata.PackageNotFoundError: when ABOA is not installed
    :raises ImportError: when the installed ABOA package cannot be imported
    """
    import aboa

    distribution = importlib.metadata.distribution("aboa")
    require(distribution.version == version, "Installed version does not match release")
    package = Path(aboa.__file__).parent
    for resource in RESOURCES:
        require((package / resource).is_file(), "Installed resource missing: " + resource)
    commands = {ep.name for ep in distribution.entry_points if ep.group == "console_scripts"}
    require(commands == set(COMMANDS), "Unexpected installed console commands")
    with tempfile.TemporaryDirectory(prefix="aboa-package-check-") as log_path:
        env = dict(os.environ, ABOA_LOG_PATH=log_path)
        env.pop("ABOA_RESOURCES_PATH", None)
        for command in COMMANDS:
            executable = resolve_console_script(command, distribution)
            result = subprocess.run(
                [str(executable), "--help"], env=env, capture_output=True, text=True,
            )
            require(result.returncode == 0, command + " failed: " + result.stderr)
            require("usage:" in result.stdout.lower(), command + " did not show help")


def main():
    """
    Validate release artifacts selected by command-line arguments.

    Require exactly one wheel and one source archive in the ``dist`` directory.
    Check their contents, metadata, licenses, entry points, and version agreement.
    ``--tag`` checks the release tag, and ``--installed`` also checks the package
    installed for the current Python interpreter.

    :raises SystemExit: when arguments are invalid or a validation check fails
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    parser.add_argument("--tag", default="")
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    wheels = list(args.dist.glob("*.whl"))
    sdists = list(args.dist.glob("*.tar.gz"))
    require(len(wheels) == len(sdists) == 1, "Expected exactly one wheel and one source distribution")
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        check_contents(names, "")
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        require(len(metadata_paths) == 1, "Expected one wheel metadata file")
        metadata_path = metadata_paths[0]
        metadata = check_metadata(wheel.read(metadata_path), args.tag)
        dist_info = metadata_path.rsplit("/", 1)[0]
        for license_file in ("LICENSE", "AUTHORS"):
            require(dist_info + "/licenses/" + license_file in names, "Missing wheel license file: " + license_file)
        entry_points = configparser.ConfigParser()
        entry_points.read_string(wheel.read(dist_info + "/entry_points.txt").decode())
        require(set(entry_points["console_scripts"]) == set(COMMANDS), "Unexpected wheel console commands")
    with tarfile.open(sdists[0]) as sdist:
        names = set(sdist.getnames())
        roots = {PurePosixPath(name).parts[0] for name in names}
        require(len(roots) == 1, "Expected one source distribution root")
        root = roots.pop() + "/"
        check_contents(names, root + "src/")
        for filename in ("README.md", "LICENSE", "AUTHORS", "pyproject.toml"):
            require(root + filename in names, "Missing source file: " + filename)
        sdist_metadata = check_metadata(sdist.extractfile(root + "PKG-INFO").read(), args.tag)
        require(sdist_metadata["Version"] == metadata["Version"], "Distribution versions differ")
    if args.installed:
        check_installed(metadata["Version"])
    print("Validated ABOA " + metadata["Version"] + " distributions" + (" and installation" if args.installed else ""))


if __name__ == "__main__":
    main()
