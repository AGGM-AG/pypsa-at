# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""End-to-end tests verifying p_nom_max bounds against KLIEN and TYNDP input data."""

import pandas as pd
import pytest

from mods.utils import resolve_tyndp_locations
from test.conftest import require_config

_CARRIER_TO_KLIEN_FILE = {
    "solar rooftop": "nuts3_pv_buildings",
    "solar": "nuts3_pv_ground",
    "solar-hsat": "nuts3_pv_ground",
    "onwind": "nuts3_wind",
}


def _klien_scenario_column(meta) -> str:
    cfg = meta["mods"]["klien_potential_limits"]
    if cfg["use_technical_potentials"]:
        return "C_technical_potential"
    return f"C_{cfg['year']}_{cfg['ambition']}_{cfg['climate_scenario']}"


def test_klien_potentials(nc, project_root, is_testrun):
    """
    Verify AT extendable generator p_nom_max against KLIEN study input data for all
    planning horizons and carriers.

    technical_potential(at_port="0") recovers the KLIEN ceiling algebraically: the
    land-use constraint deduction in solve_network cancels with non-extendable p_nom.
    When installed capacity already exceeds the KLIEN ceiling, add_land_use_constraint
    clamps p_nom_max to the installed value; expected uses max(KLIEN, installed) to
    handle this case, mirroring the TYNDP test pattern.
    Only AT regions are compared. Skips when no KLIEN technologies are configured.
    """
    klien_cfg = require_config(nc, "mods", "klien_potential_limits")
    technologies = klien_cfg["technologies"]
    if not technologies:
        pytest.skip("klien_potential_limits.technologies is empty — nothing to verify.")

    # KLIEN column and file paths are global config — identical across planning horizons
    meta = nc["2030"].meta
    meta_data = meta["data"]["klien_potentials"]
    col = _klien_scenario_column(meta)
    klien_by_carrier = {
        carrier: pd.read_csv(
            project_root
            / "data"
            / "klien_potentials"
            / meta_data["source"]
            / meta_data["version"]
            / f"{_CARRIER_TO_KLIEN_FILE[carrier]}.csv",
            index_col=0,
        )[col]
        for carrier in technologies
    }

    stats_kwargs = dict(
        groupby=["location", "carrier"],
        aggregate_across_components=True,
        nice_names=False,
        drop_zero=False,
    )

    # actual: all planning horizons in one call via NetworkCollection statistics
    actual = nc.statistics.technical_potential(
        carrier=list(technologies), at_port="0", **stats_kwargs
    )
    actual.index.names = ["year", "location", "carrier"]
    actual = actual[
        actual.index.get_level_values("location").str.startswith("AT")
    ].sort_index()

    # expected: aggregate KLIEN NUTS3 potentials to each network location
    expected_vals = {}
    for year, location, carrier in actual.index:
        klien = klien_by_carrier[carrier]
        nuts3_mask = klien.index.str.startswith(location)
        if location == "AT33":
            nuts3_mask &= ~klien.index.str.startswith("AT333")
        expected_vals[(year, location, carrier)] = float(klien[nuts3_mask].sum())

    expect = pd.Series(
        expected_vals,
        index=pd.MultiIndex.from_tuples(
            list(expected_vals.keys()), names=["year", "location", "carrier"]
        ),
    ).sort_index()

    # When installed capacity exceeds the KLIEN ceiling, add_land_use_constraint clamps
    # p_nom_max to installed; technical_potential then returns installed rather than KLIEN.
    installed = nc.statistics.installed_capacity(
        carrier=list(technologies), at_port="0", **stats_kwargs
    )
    installed.index.names = ["year", "location", "carrier"]
    installed = installed[
        installed.index.get_level_values("location").str.startswith("AT")
    ]
    expect = expect.combine(installed.reindex(expect.index, fill_value=0.0), max)

    for carrier in actual.index.unique("carrier"):
        _actual = actual[actual.index.get_level_values("carrier") == carrier]
        _expect = expect[expect.index.get_level_values("carrier") == carrier]
        pd.testing.assert_series_equal(_actual, _expect, atol=1e-4, check_names=False)


def test_tyndp_trajectory_ceilings(nc, project_root, is_testrun):
    """
    Verify component p_nom_max against TYNDP trajectory input data.

    technical_potential(at_port) recovers the raw trajectory value in all cases:
    land-use carriers, myopic brownfield deductions, and port-efficiency scaling
    all cancel algebraically, so no per-case correction is needed here.
    Skips gracefully when year/location/carrier is absent from the network or trajectory data.
    """
    cfg = require_config(nc, "mods", "PEMMDB_trajectories", enable=False)

    planning_horizons = nc["2030"].meta["scenario"]["planning_horizons"]
    carrier_port_0 = ["H2 Electrolysis", "onwind", "solar rooftop"]
    carrier_port_1 = ["battery discharger", "home battery discharger", "nuclear"]
    skip_countries = tuple(cfg["skip_countries"])

    raw = pd.read_csv(project_root / "resources" / "tyndp_trajectories.csv")
    expect = raw.set_index(["pyear", "bus", "pypsa_eur_carrier"]).query(
        f"scenario == '{cfg['tyndp_scenario']}'"
    )["p_nom_max"]
    expect.index.names = ["year", "location", "carrier"]

    # rename to pypsa-at location names, resolved for the run's clustering
    location_mapping = resolve_tyndp_locations(
        nc["2030"].meta["clustering"]["administrative"],
        nc["2030"].meta["mods"]["modify_nuts3_shapes"],
    )
    expect = expect.rename(index=location_mapping, level="location")

    # the technical potential statistics calculates the upper boundary
    kwargs = dict(
        groupby=["location", "carrier"],
        aggregate_across_components=True,
        nice_names=False,
        drop_zero=False,
    )
    actual = pd.concat(
        [
            nc.statistics.technical_potential(
                carrier=carrier_port_0, at_port="0", **kwargs
            ),
            nc.statistics.technical_potential(
                carrier=carrier_port_1, at_port="1", **kwargs
            ),
        ]
    )

    # exclude skip countries from comparison. DE and AT are covered by different input files
    expect = expect[
        ~expect.index.get_level_values("location").str.startswith(skip_countries)
    ]
    actual = actual[
        ~actual.index.get_level_values("location").str.startswith(skip_countries)
    ]

    # solar(-hsat) trajectories are covered by a constraint, not p_nom_max attribute
    expect = expect[expect.index.get_level_values("carrier") != "solar(-hsat)"]

    # some countries have subregions in trajectories file but not in PyPSA-AT
    expect = expect.groupby(level=["year", "location", "carrier"]).sum()

    # trajectories contain all inter- and extrapolated years
    expect = expect[expect.index.get_level_values("year").isin(planning_horizons)]

    # must cast to string for comparison
    expect = expect.rename(index=str, level="year")

    # network collection names year as 'network'
    actual.index.names = ["year", "location", "carrier"]

    # drop Kosovo for the comparison because there are no trajectories
    # in open-tyndp and we use Serbia instead in PyPSA-AT
    actual = actual[actual.index.get_level_values("location") != "XK"]

    # drop Cyprus because its not modeled in PyPSA-AT
    expect = expect[~expect.index.get_level_values("location").isin(("CY", "MT"))]

    # add electrolysis for northern ireland: it is missing in open-tyndp and
    # PyPSA-AT currently set it to 0
    h2_electrolysis_north_ireland = pd.Series(
        index=pd.MultiIndex.from_product(
            [actual.index.unique(0).tolist(), ["GB1"], ["H2 Electrolysis"]],
            names=["year", "location", "carrier"],
        ),
        data=0.0,
    )
    expect = pd.concat([expect, h2_electrolysis_north_ireland])

    actual = actual.sort_index()
    expect = expect.sort_index()

    # In the base year, add_land_use_constraint (solve_network.py) may clamp
    # p_nom_max = p_nom_min when vintage capacity already exceeds the trajectory
    # ceiling. Once clamped, the trajectory value is no longer recoverable from
    # the solved network; the algebraic cancellation breaks down. Use
    # max(trajectory, installed_capacity) as the expected value to handle this.
    installed = pd.concat(
        [
            nc.statistics.installed_capacity(
                carrier=carrier_port_0, at_port="0", **kwargs
            ),
            nc.statistics.installed_capacity(
                carrier=carrier_port_1, at_port="1", **kwargs
            ),
        ]
    )
    installed.index.names = ["year", "location", "carrier"]
    installed = installed[
        ~installed.index.get_level_values("location").str.startswith(skip_countries)
    ]
    installed = installed[installed.index.get_level_values("location") != "XK"]
    installed = installed.rename(index=str, level="year").sort_index()
    expect = expect.combine(installed.reindex(expect.index, fill_value=0), max)

    # Nuclear is a conventional carrier: where it is NOT extendable (today only the
    # base year) it carries no trajectory ceiling, so its expectation is the installed
    # brownfield rather than the (backward-extrapolated) trajectory value that the
    # max() above would otherwise pick when the synthetic base-year trajectory exceeds
    # the brownfield (e.g. HU, SI). Keying on p_nom_extendable rather than the base
    # year keeps this correct if the model ever makes nuclear extendable in the base
    # year — those rows then fall back to the trajectory comparison automatically.
    extendable_nuclear = {
        (str(year), name.split(" ")[0])
        for year, net in nc.networks.items()
        for name in net.links.query("carrier == 'nuclear' and p_nom_extendable").index
    }
    nuclear_brownfield = pd.Series(
        [
            carrier == "nuclear" and (year, location) not in extendable_nuclear
            for year, location, carrier in expect.index
        ],
        index=expect.index,
    )
    expect[nuclear_brownfield] = installed.reindex(expect.index, fill_value=0)[
        nuclear_brownfield
    ]

    # The trajectory file lists nuclear (mostly p_nom_max=0) for every country, but
    # nuclear is conventional and non-extendable, so the network only builds a nuclear
    # link where brownfield capacity is nonzero. Drop the zero-valued nuclear rows so
    # expect matches the locations actually present in the network.
    nuclear_zero = (expect.index.get_level_values("carrier") == "nuclear") & (
        expect == 0
    )
    expect = expect[~nuclear_zero]

    if is_testrun:
        # In test runs not all (location, carrier) pairs from TYNDP are modelled.
        # A location can exist in the network for some carriers but not others
        # (e.g. IT1/IT2 have batteries but no onwind in at10), so filter on the
        # full index pair rather than location alone.
        expect = expect[expect.index.isin(actual.index)]

    # First compare indices
    pd.testing.assert_index_equal(actual.index.unique(0), expect.index.unique(0))
    pd.testing.assert_index_equal(actual.index.unique(1), expect.index.unique(1))
    pd.testing.assert_index_equal(actual.index.unique(2), expect.index.unique(2))

    # Carrier wise comparisons for better feedback
    for carrier in actual.index.unique("carrier"):
        _actual = actual[actual.index.get_level_values("carrier") == carrier]
        _expect = expect[expect.index.get_level_values("carrier") == carrier]
        pd.testing.assert_series_equal(_actual, _expect, atol=1e-4)
