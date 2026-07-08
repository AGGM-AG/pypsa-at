# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.

import logging

import pandas as pd
import xarray as xr

from scripts._helpers import (
    configure_logging,
    mock_snakemake,
    set_scenario_config,
)

"""
Build hydroelectric inflows time-series for each model region.

Combines normalized inflow profiles from ERA5 data and inflow totals per country and technology from PEMMDB.

Outputs
-------

- ``inflow_per_region_{clusters}.nc``:

    ===================  ================  =========================================================
    Field                Dimensions        Description
    ===================  ================  =========================================================
    inflow               countries, time,  Inflow profile per region and carrier,
                         carrier           e.g. due to river inflow in hydro reservoir.
    ===================  ================  =========================================================
"""

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "build_inflows_per_region",
            opts="",
            clusters="adm",
            # configfiles="config/test/config.at10.yaml",
            sector_opts="none",
            run="AT_KN2040",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    logger.info("Extracting hydropower inflow totals per region...")

    # Loads normalized hydroelectric inflow profile time-series for each model region.
    profile = xr.open_dataarray(snakemake.input.profile)

    # Loads total annual hydroelectric inflows volumes (in MWh) for each model region based on PEMMDB.
    totals_df = pd.read_csv(snakemake.input.totals)

    totals_pivot = totals_df.pivot_table(
        index="bus", columns="carrier", values="inflow"
    ).rename_axis(index={"bus": "countries"})

    totals_xr = xr.DataArray(
        totals_pivot.values,
        dims=["countries", "carrier"],
        coords={"countries": totals_pivot.index, "carrier": totals_pivot.columns},
    )

    # Multiply: (time, name) * (name, carrier) -> (time, name, carrier)
    result = profile * totals_xr

    result.to_netcdf(snakemake.output.inflow)
    logger.info(f"Saved inflows to {snakemake.output.inflow}")
