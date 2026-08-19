# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Apply recalibrated Austrian urban fractions to district heat shares."""

import pandas as pd
from snakemake.script import Snakemake


def combine_district_heat_share(
    district_heat_share: pd.DataFrame,
    urban_fraction_at: pd.DataFrame,
    planning_horizon: int | str,
) -> pd.DataFrame:
    """
    Replace Austrian urban fractions for one planning horizon.

    Parameters
    ----------
    district_heat_share
        DataFrame with district heating shares and urban fractions.
    urban_fraction_at
        DataFrame containing urban fraction for austrian regions
    planning_horizon
        Planning horizon year for the current data

    Returns
    -------
    :
        The modified DataFrame with district heating shares and urban fractions
    """
    new_urban_fraction = urban_fraction_at[str(planning_horizon)].reindex(
        district_heat_share.index
    )
    at_rows = district_heat_share.index.astype(str).str.startswith("AT")
    update_district_fraction = (
        at_rows & district_heat_share["urban fraction"].eq(0) & new_urban_fraction.gt(0)
    )

    result = district_heat_share.copy()
    result.loc[at_rows, "urban fraction"] = new_urban_fraction.loc[at_rows]
    result.loc[update_district_fraction, "district fraction of node"] = (
        new_urban_fraction.loc[update_district_fraction]
    )
    return result


def main(snakemake: Snakemake) -> None:
    """
    Main function to read, write and transform data.

    Combines urban heat fraction for a given district heat share file with at values.

    Parameters
    ----------
    snakemake
        The Snakemake workflow object providing inputs, params, and config.

    Returns
    -------
    :
        Exports the result
    """
    district_heat_share = pd.read_csv(snakemake.input.district_heat_share, index_col=0)
    urban_fraction_at = pd.read_csv(snakemake.input.urban_fraction_at, index_col=0)
    result = combine_district_heat_share(
        district_heat_share,
        urban_fraction_at,
        snakemake.wildcards.planning_horizons,
    )
    result.to_csv(snakemake.output.district_heat_share)


if __name__ == "__main__":
    from scripts._helpers import configure_logging, mock_snakemake

    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "modify_district_heat_share_at",
            clusters="adm",
            planning_horizons="2025",
            run="AT_KN2040",
        )
    configure_logging(snakemake)
    main(snakemake)
