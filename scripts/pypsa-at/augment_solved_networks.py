"""
Attach additional resource data to solved network NetCDF files.

This script reads solved network files, attaches CSV data, and saves the
augmented networks back to their original locations.

Using a separate rule and script instead of patching scripts/solve_networks.py
is preferred because
- Clean separation of concerns
- Doesn't modify core solving logic
- Can be run independently or skipped
- Works with existing solved networks

At the costs of
- File I/O overhead (read → modify → write) estimated 2 Minutes
"""

import logging
from pathlib import Path

import pandas as pd
import pypsa

from scripts._helpers import (
    configure_logging,
    set_scenario_config,
)

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "augment_solved_networks",
            run="AT_KN2040",
            opts="",
            clusters="adm",
            configfiles="config/config.at.yaml",
            sector_opts="none",
            planning_horizons="2020",
        )
    configure_logging(snakemake)
    set_scenario_config(snakemake)

    # Load resource data from rule inputs that should be attached to all networks
    logger.info(f"Loading energy totals from {snakemake.input.energy_totals}")
    energy_totals = pd.read_csv(snakemake.input.energy_totals, index_col=[0, 1])
    # the energy totals file contains values for all years from 1990 onwards. The
    # workflow selects one year for calculations as configured by the user in the
    # configuration. We only attach this year's data to the network to safe space
    # and simplify downstream data selection.
    energy_totals = energy_totals.xs(
        snakemake.params.energy_totals_year, axis="index", level="year", drop_level=True
    )

    logger.info(f"Loading energy totals from {snakemake.input.co2_totals}")
    co2_totals = pd.read_csv(snakemake.input.co2_totals, index_col=0)

    # Prepare dictionaries and to attach. PyPSA's export_to_netcdf() uses an
    # explicit whitelist of what to serialize. Random attributes like
    # n.resources are ignored because PyPSA doesn't know how to serialize them.
    to_attach = {
        "energy_totals": energy_totals.to_dict(orient="tight"),
        "co2_totals": co2_totals.to_dict(orient="tight"),
        # add more items here if needed
    }

    # Attach to each network file
    for network_path in snakemake.input.networks:
        logger.info(
            f"Attaching {len(to_attach)} data tables to network at {network_path}."
        )
        n = pypsa.Network(network_path)

        # update the 'Unnamed Network' default name with a more descriptive name
        year = n.meta["wildcards"]["planning_horizons"]
        new_name = f"PyPSA-AT Network {year}"
        logger.info(f"Renaming network from {n.name} to {new_name}")
        n.name = new_name

        if "resources" in n.meta:  # Fail fast to prevent unexpected behavior
            raise ValueError("The configuration already contains a 'resources' entry.")
        n.meta["resources"] = to_attach

        n.export_to_netcdf(Path(network_path))
        logger.info(f"Successfully updated {network_path}")

    logger.info(f"Completed processing {len(snakemake.input.networks)} network files")
