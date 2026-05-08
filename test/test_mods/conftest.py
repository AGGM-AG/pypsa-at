# test/test_mods/conftest.py
"""Shared fixtures for mods unit tests."""

import pytest
from pypsa import NetworkCollection

from evals.fileio import read_networks


@pytest.fixture(scope="session")
def nc(result_path) -> NetworkCollection:
    """Load the networks."""
    return read_networks(result_path)


@pytest.fixture(scope="session")
def is_testrun(nc) -> bool:
    return any(n.meta["run"]["prefix"] == "test-sector-myopic-at10" for n in nc)
