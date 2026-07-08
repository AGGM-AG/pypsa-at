# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for mods/network_updates.py."""

import pandas as pd
import pypsa
import pytest

from mods.utils import get_relevant_links_and_lines
from test.conftest import require_config


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

    def test_resources_key_present_after_roundtrip(
        self, network_with_resources, tmp_path
    ):
        """meta['resources'] must survive export_to_netcdf → import_from_netcdf."""
        nc_path = tmp_path / "network.nc"
        network_with_resources.export_to_netcdf(str(nc_path))

        n2 = pypsa.Network(str(nc_path))
        assert "resources" in n2.meta, "n.meta['resources'] missing after round-trip"

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


def test_tyndp_ntc_lower_limits_applied(nc, pytestconfig):
    """2040 capacities should be at least TYNDP NTC capacity."""
    lower_bounds_years = require_config(nc, "mods", "tyndp_lower_bounds")["years"]

    ntc_path = (
        pytestconfig.rootpath / "resources" / "tyndp_transmission_trajectories.csv"
    )

    ntc_df = pd.read_csv(ntc_path)

    for year_str, n in nc.networks.items():
        if year_str not in lower_bounds_years:
            continue

        year_int = int(year_str)

        df_year = ntc_df[ntc_df["year"] == year_int]

        relevant_links, relevant_lines = get_relevant_links_and_lines(n)

        for row in df_year.itertuples():
            from_node: str = row.from_node
            to_node: str = row.to_node

            lines_dir_idx = relevant_lines[
                (relevant_lines["bus0_tyndp"] == from_node)
                & (relevant_lines["bus1_tyndp"] == to_node)
            ].index
            lines_indir_idx = relevant_lines[
                (relevant_lines["bus0_tyndp"] == to_node)
                & (relevant_lines["bus1_tyndp"] == from_node)
            ].index
            links_dir_idx = relevant_links[
                (relevant_links["bus0_tyndp"] == from_node)
                & (relevant_links["bus1_tyndp"] == to_node)
            ].index
            links_indir_idx = relevant_links[
                (relevant_links["bus0_tyndp"] == to_node)
                & (relevant_links["bus1_tyndp"] == from_node)
            ].index

            ac_cap = (
                n.lines.loc[lines_dir_idx | lines_indir_idx, "s_nom_opt"]
                * n.lines.loc[lines_dir_idx | lines_indir_idx, "s_max_pu"]
            ).sum()
            dc_cap_dir = (
                n.links.loc[links_dir_idx, "p_nom_opt"]
                * n.links.loc[links_dir_idx, "p_max_pu"]
            ).sum()
            dc_cap_indir = (
                n.links.loc[links_indir_idx, "p_nom_opt"]
                * n.links.loc[links_indir_idx, "p_max_pu"]
            ).sum()

            assert ac_cap + dc_cap_dir >= max(
                row.direct_capacity, row.indirect_capacity
            ), (
                f"TYNDP lower limit violation in {year_int}: {from_node}→{to_node} "
                f"Direct cross border capacity {ac_cap + dc_cap_dir:.1f} MW is lower than min NTC "
                f"capacity {max(row.direct_capacity, row.indirect_capacity):.1f} MW"
            )
            assert ac_cap + dc_cap_indir >= max(
                row.direct_capacity, row.indirect_capacity
            ), (
                f"TYNDP lower limit violation in {year_int}: {from_node}→{to_node} "
                f"Indirect cross border capacity {ac_cap + dc_cap_indir:.1f} MW is lower than min NTC "
                f"capacity {max(row.direct_capacity, row.indirect_capacity):.1f} MW"
            )
