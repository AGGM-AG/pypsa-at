# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for mods/network_updates.py."""

import pandas as pd
import pypsa
import pytest


def _make_energy_totals() -> pd.DataFrame:
    """Return a minimal energy_totals DataFrame matching the real layout."""
    index = pd.MultiIndex.from_tuples(
        [("AT", "electricity"), ("AT", "gas"), ("DE", "electricity")],
        names=["country", "sector"],
    )
    return pd.DataFrame({"value": [100.0, 200.0, 300.0]}, index=index)


def _make_co2_totals() -> pd.DataFrame:
    """Return a minimal co2_totals DataFrame matching the real layout."""
    return pd.DataFrame(
        {"industry": [10.0, 20.0], "transport": [5.0, 8.0]},
        index=pd.Index(["AT", "DE"], name="country"),
    )


def _attach_resources(n: pypsa.Network) -> None:
    """
    Embed resource DataFrames into n.meta["resources"] using the same
    serialisation as ``attach_resources_to_network_meta``.
    """
    energy_totals = _make_energy_totals()
    co2_totals = _make_co2_totals()
    n.meta["resources"] = {
        "energy_totals": energy_totals.to_dict(orient="tight"),
        "co2_totals": co2_totals.to_dict(orient="tight"),
    }


class TestMetaResourcesRoundTrip:
    """Verify that n.meta['resources'] survives a NetCDF export/import cycle."""

    @pytest.fixture
    def network_with_resources(self) -> pypsa.Network:
        n = pypsa.Network()
        n.meta = {}
        _attach_resources(n)
        return n

    @pytest.mark.AT
    def test_resources_key_present_after_roundtrip(
        self, network_with_resources, tmp_path
    ):
        """meta['resources'] must survive export_to_netcdf → import_from_netcdf."""
        nc_path = tmp_path / "network.nc"
        network_with_resources.export_to_netcdf(str(nc_path))

        n2 = pypsa.Network(str(nc_path))
        assert "resources" in n2.meta, "n.meta['resources'] missing after round-trip"

    @pytest.mark.AT
    def test_energy_totals_roundtrip(self, network_with_resources, tmp_path):
        """energy_totals DataFrame must be reconstructable after round-trip."""
        original = _make_energy_totals()
        nc_path = tmp_path / "network.nc"
        network_with_resources.export_to_netcdf(str(nc_path))

        n2 = pypsa.Network(str(nc_path))
        recovered = pd.DataFrame.from_dict(
            n2.meta["resources"]["energy_totals"], orient="tight"
        )
        pd.testing.assert_frame_equal(recovered, original)

    @pytest.mark.AT
    def test_co2_totals_roundtrip(self, network_with_resources, tmp_path):
        """co2_totals DataFrame must be reconstructable after round-trip."""
        original = _make_co2_totals()
        nc_path = tmp_path / "network.nc"
        network_with_resources.export_to_netcdf(str(nc_path))

        n2 = pypsa.Network(str(nc_path))
        recovered = pd.DataFrame.from_dict(
            n2.meta["resources"]["co2_totals"], orient="tight"
        )
        pd.testing.assert_frame_equal(recovered, original)

    @pytest.mark.AT
    def test_resources_not_lost_by_pop(self, network_with_resources, tmp_path):
        """
        Verify that popping 'resources' from a deepcopy does not affect the
        original network (mirrors the cli.py deepcopy guard).
        """
        import copy

        nc_path = tmp_path / "network.nc"
        network_with_resources.export_to_netcdf(str(nc_path))
        n2 = pypsa.Network(str(nc_path))

        meta_copy = copy.deepcopy(n2.meta)
        meta_copy.pop("resources", None)

        # original meta must still contain resources
        assert "resources" in n2.meta, (
            "Popping from deepcopy should not mutate the original network meta"
        )
