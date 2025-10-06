"""A module to test pypsa-at modifications."""

import pytest


@pytest.mark.integration
def test_custom_clustering(networks):
    """
    Make sure the custom clustering yields the expected regions.
    """
    for n in networks.values():
        assert n.meta["mods"]["modify_nuts3_shapes"] is True
