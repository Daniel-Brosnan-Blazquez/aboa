# Publishing ABOA to PyPI

ABOA distribution package's name is `aboa`. The version and all package metadata live in
the file `pyproject.toml`. Follow the next steps to build, install and publish a release in PyPI.

## Validate a release locally

Use a virtual environment with Python 3.9 or newer (e.g. the environment inside the development container).

From the repository root:

```bash
python3 -m pip install build twine
python3 -m build
python3 -m twine check --strict dist/*
python3 tools/check_distribution.py dist --tag v0.1.0
```

Use a fresh `dist/` directory for each build. The default `python3 -m build`
builds the wheel from the source distribution, checking that the source archive
contains everything needed to rebuild it. The checker verifies metadata,
licenses, bundled JSON/XML/XSD/SQL/shell resources, console entry points, and
absence of test output and Python caches.

Install each artifact in a separate clean environment outside the source tree,
then run the checker:

```bash
python3 -m pip install /path/to/aboa/dist/aboa-0.1.0-py3-none-any.whl
python3 -m pip check
python3 /path/to/aboa/tools/check_distribution.py /path/to/aboa/dist --installed
```

Repeat in another clean environment using `aboa-0.1.0.tar.gz`.
Relevant Github actions activated for every release, performs both
installations on Python 3.9 and 3.12 and runs the resource, configuration,
function, and logging tests.

## Publish a release

1. Update the version in `pyproject.toml` for subsequent releases. PyPI does not
   allow reusing an uploaded filename/version.
2. Commit and push the release changes. Confirm the packaging and integration
   workflows pass.
3. Create and publish a GitHub release whose tag is exactly `v` followed by the
   package version, for example `v0.1.0`, targeting the validated commit.
4. The `aboa-publish.yml` workflow builds the wheel and source distribution,
   validates the tag against their metadata, and tests their installations.
   Its final job uploads those same artifacts to PyPI through the `pypi`
   environment.
5. Verify the release at [ABOA on PyPI](https://pypi.org/project/aboa/) and install
   it in a fresh environment with `python -m pip install aboa==0.1.0`.

Pushes, pull requests, and manual workflow runs only build and validate; a
published GitHub release triggers the upload. GitHub prereleases also upload,
so use a PEP 440 prerelease version such as `0.2.0rc1` and tag `v0.2.0rc1` when
publishing a release candidate.

## Manual upload

To upload directly to PyPI, complete the local validation above and upload with:

```bash
python -m twine upload dist/*
```