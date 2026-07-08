# test/test_mods/conftest.py
"""Shared fixtures for ``./mods`` tests."""

import pathlib

import pytest
from pypsa import NetworkCollection

from evals.fileio import read_networks
from evals.utils import get_latest_results_folder


@pytest.fixture(scope="session")
def result_path(pytestconfig) -> pathlib.Path:
    """
    Retrieve the results path from CLI.

    Note, that we cannot directly access the run_path (project root), because
    we want to run the tests on copied results folders as well.
    """
    default_path = get_latest_results_folder()
    result_path = pytestconfig.getoption("result_path")
    return pathlib.Path(result_path) if result_path else default_path


@pytest.fixture(scope="session")
def nc(result_path: pathlib.Path) -> NetworkCollection:
    """Load the networks."""
    return read_networks(result_path)


@pytest.fixture(scope="session")
def project_root(pytestconfig) -> pathlib.Path:
    return pytestconfig.rootpath


@pytest.fixture(scope="session")
def is_testrun(nc) -> bool:
    return any(n.meta["run"]["prefix"] == "test-sector-myopic-at10" for n in nc)
