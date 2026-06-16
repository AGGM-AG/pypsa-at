# SPDX-FileCopyrightText: Contributors to Open-TYNDP <https://github.com/open-energy-transition/open-tyndp>
#
# SPDX-License-Identifier: MIT
"""
Filters TYNDP H2 import potentials, maximum capacity, offer quantity and marginal cost for pipeline and shipping
for a specific TYNDP scenario and a given year wildcard.
The function saves a csv file with TYNDP H2 import potentials and marginal cost filtered for a specific TYNDP scenario
and for a given year.
"""

import logging

import pandas as pd

from scripts._helpers import (
    configure_logging,
    set_scenario_config,
)

logger = logging.getLogger(__name__)

bus_mappings = {
    "DE": "DE5",  # German Hydrogen Imports can stem from Norway or by sea (ammonia). In both cases they go through North-Germany.
    "IT": "IT1",  # Italian Hydrogen Imports are exclusively from Algeria and do therefore have to go through Sicily
}


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_tyndp_h2_imports",
            clusters="adm",
            planning_horizons="2030",
            run="AT_KN2040",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    # Parameters
    scenario = snakemake.params.scenario
    year = int(snakemake.wildcards.planning_horizons)

    # Load prepped import potentials and filter
    fn = snakemake.input.import_potentials_prepped
    countries = snakemake.params.countries
    import_potentials = pd.read_csv(fn, index_col=0)
    import_potentials_filtered = import_potentials.query(
        "(Scenario == 'All' or Scenario == @scenario) and Year == @year and bus1 in @countries"
    )
    import_potentials_filtered["bus1"] = import_potentials_filtered["bus1"].replace(
        bus_mappings
    )

    # Validate bus1 values against known network buses
    busmap = pd.read_csv(snakemake.input.busmap, index_col=0)
    nodes = busmap.squeeze().unique()
    unknown_buses = set(import_potentials_filtered["bus1"].unique()) - set(nodes)
    if unknown_buses:
        raise ValueError(
            f"The following bus values are not present in the network: {sorted(unknown_buses)}"
        )

    # Save filtered H2 import potentials
    import_potentials_filtered.to_csv(snakemake.output.h2_import_potentials)
