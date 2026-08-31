# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Build annual Austrian NUTS3 heat demand from raster heatmaps."""

import logging

import geopandas as gpd
import pandas as pd
import rasterio
from rasterstats import zonal_stats
from snakemake.script import Snakemake

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)


def aggregate_heatmap(polygons: gpd.GeoDataFrame, raster_path: str) -> pd.Series:
    """
    Sum raster heat-density values, converted from MWh/ha to MWh, by region.

    Parameters
    ----------
    polygons : gpd.GeoDataFrame
        Regions for which heat demand is aggregated.
    raster_path : str
        Path to the heat-density raster.

    Returns
    -------
    :
        Heat demand in MWh indexed by region.
    """
    with rasterio.open(raster_path) as src:
        projected_polygons = polygons.to_crs(src.crs)
        density_mwh_per_ha = src.read(1, masked=True)
        pixel_area_ha = abs(src.res[0] * src.res[1]) / 10_000
        stats = zonal_stats(
            projected_polygons,
            density_mwh_per_ha * pixel_area_ha,
            affine=src.transform,
            nodata=src.nodata,
            stats=["sum"],
            all_touched=False,
        )

    return pd.Series(
        [0.0 if item["sum"] is None else item["sum"] for item in stats],
        index=polygons.index,
        dtype=float,
    )


def build_target_heat_demand(
    source_demands: pd.DataFrame, target_years: list[int]
) -> pd.DataFrame:
    """
    Create target-year demand using year-weighted linear interpolation.

    Parameters
    ----------
    source_demands : pd.DataFrame
        Heat demand indexed by region and labelled by source year columns.
    target_years : list[int]
        Years for which heat demand is returned.

    Returns
    -------
    :
        Long-form heat demand with region, year, and value columns.
    """
    demands = source_demands.reindex(
        columns=sorted({*source_demands.columns, *target_years})
    )
    demands = (
        demands.interpolate(axis=1, method="index")[target_years].stack().reset_index()
    )
    demands.columns = ["region", "year", "value"]
    return demands


def main(snakemake: Snakemake) -> None:
    """
    Build Austrian regional heat demand from raster heatmaps.

    Parameters
    ----------
    snakemake : Snakemake
        Snakemake input, output, and parameter collections.

    Returns
    -------
    :
        None. Writes the regional heat demand CSV.
    """
    polygons = gpd.read_file(snakemake.input.nuts3_shapes)
    level = "level2" if snakemake.params.clustering.startswith("AT10") else "level3"
    polygons = polygons.loc[polygons["country"].eq("AT"), [level, "geometry"]]
    polygons = polygons.dissolve(by=level)

    source_demands = pd.DataFrame(
        {
            int(path.split("_")[-1].split(".")[0]): aggregate_heatmap(polygons, path)
            for path in snakemake.input.heatmaps
        }
    )
    result = build_target_heat_demand(
        source_demands, [int(year) for year in snakemake.params.planning_horizons]
    )
    result.to_csv(snakemake.output.heat_demand, index=False)
    logger.info("Wrote %d regional annual heat demand values", len(result))


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_heat_demand_at", run="AT_KN2040", cluster="adm"
        )
    configure_logging(snakemake)
    main(snakemake)
