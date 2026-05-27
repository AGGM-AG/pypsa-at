"""A module to test pypsa-at modifications."""

import pandas as pd
import pytest

from evals.constants import DataModel as DM
from evals.utils import get_energy_totals_domestic_share
from mods.tyndp_utils import get_relevant_links_and_lines
from scripts.prepare_sector_network import determine_emission_sectors
from test.conftest import require_config


@pytest.mark.AT
def test_custom_clustering(nc, is_testrun):
    """
    Make sure the custom clustering yields the expected regions.
    """
    if is_testrun:
        pytest.xfail(
            "Testrun has different countries and is expected to fail this test."
        )
    clusterings = set()
    for n in nc:
        # check for unexpected configurations
        clustering = n.meta["mods"]["modify_nuts3_shapes"]
        clusterings.add(clustering)
        # check for expected number of regions
        locations = n.buses.location.unique()
        locations_at = [loc for loc in locations if loc.startswith("AT")]
        locations_de = [loc for loc in locations if loc.startswith("DE")]
        if clustering == "AT10DE5":
            # 34 countries, + 9 AT, + 4 DE, + 2 IT, + 1 DK-GB, +1 EU (FR and ES merged)
            assert len(locations) == 52
            assert len(locations_at) == 10
            assert len(locations_de) == 5
        elif clustering == "AT10DE16":
            assert len(locations) == 63
            assert len(locations_at) == 10
            assert len(locations_de) == 16
        elif clustering == "AT35DE5":
            assert len(locations) == 77
            assert len(locations_at) == 35
            assert len(locations_de) == 5
        elif clustering == "AT35DE16":
            assert len(locations) == 88
            assert len(locations_at) == 35
            assert len(locations_de) == 16
        else:
            raise AssertionError(f"Unexpected clustering detected: {clustering}")

        assert len([loc for loc in locations if loc.startswith("IT")]) == 3
        assert len([loc for loc in locations if loc.startswith("DK")]) == 2
        assert len([loc for loc in locations if loc.startswith("GB")]) == 2
        assert len([loc for loc in locations if loc.startswith("FR")]) == 1
        assert len([loc for loc in locations if loc.startswith("ES")]) == 1

    assert len(clusterings) == 1, "Varying myopic clustering is not supported."


@pytest.mark.AT
def test_national_co2_budget_constraint(nc):
    """
    Make sure the national CO2 budget constraints are adhered to.
    """
    for year, n in nc.networks.items():
        national_co2_budgets = n.meta["solving"]["constraints"].get(
            "co2_budget_national"
        )
        if not national_co2_budgets:
            continue

        # prepare data needed to replicate inequality constraint
        nhours = n.snapshot_weightings.generators.sum()
        nyears = nhours / 8760
        co2_balance = n.statistics.energy_balance(
            groupby=["location", "carrier"], bus_carrier="co2"
        ).mul(1e-6)  # to Mt_CO2
        energy_totals = pd.DataFrame.from_dict(
            n.meta["resources"]["energy_totals"], orient="tight"
        )
        co2_totals = pd.DataFrame.from_dict(
            n.meta["resources"]["co2_totals"], orient="tight"
        )
        sectors = determine_emission_sectors(n.meta["sector"])
        co2_total_totals = co2_totals[sectors].sum(axis=1) * nyears
        domestic_aviation_factors = get_energy_totals_domestic_share(
            energy_totals, kind="aviation"
        )

        for ct, myopic_limits in national_co2_budgets.items():
            # deduct emissions from international air transport
            locations = co2_balance.index.get_level_values(DM.LOCATION)
            mask_country = locations.str.startswith(ct)
            carrier = co2_balance.index.get_level_values(DM.CARRIER)
            mask_carrier = carrier == "kerosene for aviation"
            mask = mask_country & mask_carrier
            co2_balance.loc[mask] *= domestic_aviation_factors[ct]

            # 1990 limit including national target
            limit_sectoral = co2_total_totals[ct] * myopic_limits[year]
            country_limit = limit_sectoral.sum()

            # optimized model values
            country_emissions = co2_balance.loc[mask_country].sum()

            assert country_emissions <= country_limit + 1e-6, (
                f"Exceeded emission limit for country {ct} and year "
                f"{year}: {country_limit} > {country_emissions} in Mt_CO2"
            )


@pytest.mark.AT
def test_no_load_supply(nc):
    """
    Verify that no Load components supply energy to buses. Ever.

    The ``process emissions`` carrier is excluded: PyPSA-Eur models exogenous
    industrial CO2 emissions as a Load with negative ``p_set`` on a CO2 bus
    (``unit="t_co2"``), so that ``-p_set`` injects positive flow representing
    emissions. This is an upstream design pattern, not energy supply, but
    ``statistics.supply`` cannot distinguish the bus unit and reports it.
    See ``scripts/prepare_sector_network.py`` (upstream) for the construction.
    """
    load_supply = nc.statistics.supply(
        components="Load", groupby=["location", "carrier"]
    )
    load_supply = load_supply.drop(
        "process emissions", level="carrier", errors="ignore"
    )

    assert load_supply.empty, (
        f"Detected node supply from Load components: {load_supply}"
    )


@pytest.mark.AT
def test_constant_buses_topology(nc):
    """
    Needs a filter because retired technologies and their buses vanish.

    todo: docstring + explanation why this is needed
    """
    fuels = require_config(nc, "mods", "net_zero_electricity", "fuels")  # noqa
    expr = "carrier.isin(@fuels)"

    first = nc[0].buses.query(expr).index
    for n in nc[1:]:
        subsequent = n.buses.query(expr).index
        pd.testing.assert_index_equal(first, subsequent, check_order=False)


@pytest.mark.AT
def test_tyndp_ntc_lower_limits_applied(nc, pytestconfig):
    """2040 capacities should be at least TYNDP NTC capacity."""
    ntc_path = (
        pytestconfig.rootpath / "resources" / "tyndp_transmission_trajectories.csv"
    )

    ntc_df = pd.read_csv(ntc_path)

    for year_str, n in nc.networks.items():
        if year_str not in n.meta["mods"]["tyndp_lower_bounds"]["years"]:
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
