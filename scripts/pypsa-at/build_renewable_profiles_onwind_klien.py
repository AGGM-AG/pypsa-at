# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Apply KLIEN-weighted NUTS3 onshore wind profiles to the NUTS2 profile."""

import logging

import pandas as pd
import xarray as xr
from snakemake.script import Snakemake

from mods.clustering.utils import map_at_nuts3_to_nuts2
from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)


def main(snakemake: Snakemake) -> None:
    """
    Copy NUTS2 data and replace its profile with KLIEN-weighted NUTS3 data.

    Parameters
    ----------
    snakemake
        Snakemake object providing input, parameters and output.

    Returns
    -------
    :
        Stores the results in snakemake.output
    """
    with (
        xr.open_dataset(snakemake.input.profile_nuts2) as nuts2_file,
        xr.open_dataset(snakemake.input.profile_nuts3) as nuts3_file,
    ):
        nuts2 = nuts2_file.load()
        nuts3 = nuts3_file.load()

    potentials = pd.read_csv(snakemake.input.klien_wind, index_col=0)[
        "C_technical_potential"
    ]
    source_buses = nuts3.indexes["bus"]
    target = xr.DataArray(
        source_buses.map(map_at_nuts3_to_nuts2).to_numpy(),
        dims="bus",
        coords={"bus": source_buses},
        name="target_bus",
    )

    weights = pd.Series(1.0, index=source_buses)
    at_buses = source_buses.str.startswith("AT")
    weights.loc[at_buses] = potentials.reindex(source_buses[at_buses])
    if weights.isna().any():
        missing = weights[weights.isna()].index.tolist()
        raise ValueError(f"Missing KLIEN technical potentials for: {missing}")

    weight = xr.DataArray(weights.to_numpy(), dims="bus", coords={"bus": source_buses})
    weight_sum = weight.groupby(target).sum("bus")
    target_buses = nuts2.indexes["bus"]
    target_weights = weight_sum.reindex(target_bus=target_buses)
    if target_weights.isnull().any() or (target_weights <= 0).any():
        missing = target_buses[target_weights.isnull() | (target_weights <= 0)].tolist()
        raise ValueError(f"No positive KLIEN weight for: {missing}")

    weighted = (nuts3["profile"] * weight).groupby(target).sum("bus") / weight_sum
    weighted = weighted.rename({"target_bus": "bus"}).sel(bus=target_buses)
    nuts2["profile"] = weighted.transpose(*nuts2["profile"].dims)
    nuts2.to_netcdf(snakemake.output.profile)
    logger.info(f"Wrote KLIEN-weighted onwind profile to {snakemake.output.profile}.")


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_renewable_profiles_onwind_klien", clusters="adm", technology="onwind"
        )

    configure_logging(snakemake)
    main(snakemake)
