"""A module to test pypsa-at modifications."""

import pytest


@pytest.mark.integration
def test_custom_clustering(networks):
    """
    Make sure the custom clustering yields the expected regions.
    """
    clusterings = set()
    for n in networks.values():
        if n.meta["run"]["prefix"] == "test-sector-myopic-at10":
            return True
        # check for unexpected configurations
        clustering = n.meta["mods"]["modify_nuts3_shapes"]
        clusterings.add(clustering)
        # check for expected number of regions
        locations = n.static("Bus")["location"].unique()
        locations_at = [loc for loc in locations if loc.startswith("AT")]
        locations_de = [loc for loc in locations if loc.startswith("DE")]
        if clustering == "AT10DE5":
            # 34 countries, + 9 AT, + 4 DE, + 2 IT, + 1 DK-GB-FR-ES, +1 EU
            assert len(locations) == 54
            assert len(locations_at) == 10
            assert len(locations_de) == 5
        elif clustering == "AT10DE19":
            assert len(locations) == 68
            assert len(locations_at) == 10
            assert len(locations_de) == 19
        elif clustering == "AT35DE5":
            assert len(locations) == 77
            assert len(locations_at) == 30
            assert len(locations_de) == 5
        elif clustering == "AT35DE19":
            assert len(locations) == 93
            assert len(locations_at) == 30
            assert len(locations_de) == 19
        else:
            raise AssertionError(f"Unexpected clustering detected: {clustering}")

        assert len([loc for loc in locations if loc.startswith("IT")]) == 3
        assert len([loc for loc in locations if loc.startswith("DK")]) == 2
        assert len([loc for loc in locations if loc.startswith("GB")]) == 2
        assert len([loc for loc in locations if loc.startswith("FR")]) == 2
        assert len([loc for loc in locations if loc.startswith("ES")]) == 2

    assert len(clusterings) == 1, "Varying myopic clustering is not supported."
