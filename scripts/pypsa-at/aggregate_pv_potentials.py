# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Snakemake script: aggregate PV potentials from municipality GeoJSONs to NUTS3 and AT10 regions.

For each of three PV input files (buildings, ground-mounted sealed, ground-mounted unsealed):

1. Spatially joins every municipality polygon (via its representative point) to NUTS3 shapes.
2. Derives the AT10 aggregation code.
3. Sums energy-potential float columns by NUTS3 and by AT10 and writes two CSVs.

Additionally, the element-wise sum of the sealed and unsealed ground-mounted potentials is written
to combined outputs (``nuts3_ground`` and ``at10_ground``).
"""

import logging

import geopandas as gpd
import pandas as pd

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)


def assign_nuts_regions(
    muni_gdf: gpd.GeoDataFrame,
    nuts3_shapes: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Spatial-join municipalities to NUTS3 shapes and add ``nuts3`` / ``at10`` columns.

    Parameters
    ----------
    muni_gdf:
        Municipality GeoDataFrame with polygon geometry.
    nuts3_shapes:
        NUTS3 shapes indexed by NUTS3 code, with ``level2`` (NUTS2) and ``level3`` (NUTS3) columns.

    Returns
    -------
    :
        Copy of *muni_gdf* (positionally re-indexed) enriched with ``nuts3`` and ``at10`` columns.

    Raises
    ------
    ValueError
        If any municipality could not be properly matched to NUTS3
    """
    muni_gdf = muni_gdf.to_crs(nuts3_shapes.crs)

    shapes_sub = nuts3_shapes[["level2", "level3", "geometry"]].reset_index(drop=True)

    pts = gpd.GeoDataFrame(
        geometry=muni_gdf.geometry.reset_index(drop=True).representative_point(),
        crs=muni_gdf.crs,
    )

    joined = gpd.sjoin(pts, shapes_sub, how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]

    unmatched = joined["level3"].isna()
    if unmatched.any():
        raise ValueError("The regions could not be matched to NUTS3 level.")

    out = muni_gdf.copy().reset_index(drop=True)
    out["nuts3"] = joined["level3"].values
    out["at10"] = joined["level2"].values

    return out


def process_pv_file(
    pv_path: str, nuts3_shapes: gpd.GeoDataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load one PV GeoJSON, assign regions and aggregate to NUTS3 and AT10.

    Parameters
    ----------
    pv_path:
        Path to the municipality-level PV GeoJSON.
    nuts3_shapes:
        NUTS3 shapes GeoDataFrame (indexed by NUTS3 code).

    Returns
    -------
    :
        Tuple of ``(nuts3_agg, at10_agg)`` DataFrames with aggregated potentials,
        indexed by ``nuts3`` and ``at10`` respectively.

    Raises
    ------
    ValueError
        If either no Capacity column were found in the GeoJSON or the municipalities could not be properly matched.
    """
    gdf = gpd.read_file(pv_path)
    gdf.columns = gdf.columns.str.strip()

    capacity_cols = [c for c in gdf.columns if c.startswith("C_")]
    if not capacity_cols:
        raise ValueError(f"No 'C_'-prefixed energy columns found in '{pv_path}'.")

    gdf = assign_nuts_regions(gdf, nuts3_shapes)

    n_missing = gdf["nuts3"].isna().sum()
    if n_missing != 0:
        raise ValueError(
            f"NUTS3 assignment failed for {n_missing} municipalities in '{pv_path}'."
        )

    logger.info("Processed %d municipalities from '%s'.", len(gdf), pv_path)

    nuts3_agg = gdf.groupby("nuts3")[capacity_cols].sum()
    at10_agg = gdf.groupby("at10")[capacity_cols].sum()

    return nuts3_agg, at10_agg


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("aggregate_pv_potentials")

    configure_logging(snakemake)

    nuts3_shapes = gpd.read_file(snakemake.input.nuts3_shapes).set_index("index")

    nuts3_buildings, at10_buildings = process_pv_file(
        snakemake.input.pv_buildings, nuts3_shapes
    )
    nuts3_buildings.to_csv(snakemake.output.nuts3_buildings)
    at10_buildings.to_csv(snakemake.output.at10_buildings)

    nuts3_sealed, at10_sealed = process_pv_file(
        snakemake.input.pv_ground_sealed, nuts3_shapes
    )
    nuts3_unsealed, at10_unsealed = process_pv_file(
        snakemake.input.pv_ground_unsealed, nuts3_shapes
    )

    nuts3_ground = nuts3_sealed.add(nuts3_unsealed, fill_value=0)
    nuts3_ground.index.name = "nuts3"  # ensure index name is preserved after .add()
    nuts3_ground.to_csv(snakemake.output.nuts3_ground)

    at10_ground = at10_sealed.add(at10_unsealed, fill_value=0)
    at10_ground.index.name = "at10"  # ensure index name is preserved after .add()
    at10_ground.to_csv(snakemake.output.at10_ground)
