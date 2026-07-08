# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Snakemake script: aggregate KLIEN potentials from municipality GeoJSONs to NUTS3 regions.

For each of three PV input files (buildings, ground-mounted sealed, ground-mounted unsealed)
and one wind input file:

1. Reprojects both the input GeoDataFrame and the NUTS3 shapes to EPSG:3035 (equal-area CRS).
2. Computes intersection fragments between municipality polygons and NUTS3 shapes via
   ``geopandas.overlay``.
3. Weights each capacity column by the fractional area overlap (intersection / input polygon area).
4. Redirects overlay fragments that fall outside Austria (non-AT NUTS3 codes) to the
   nearest AT NUTS3 region via centroid-based nearest-neighbour lookup.
5. Validates that per-municipality area weights sum to at least 0.99 (raises ``ValueError`` if not).
6. Groups by NUTS3 code and sums weighted capacities.
7. Writes one NUTS3-level CSV per input file.

Aggregation to coarser clustering resolutions (e.g. AT10) happens downstream in
``mods.network.potentials.apply_klien_potential_limits`` via
``mods.clustering.utils.combine_regions_by_clustering``.

Additionally, the element-wise sum of the sealed and unsealed ground-mounted PV potentials is
written to a combined output (``nuts3_ground``).
"""

import logging

import geopandas as gpd
import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

# Minimum required sum of area weights per input polygon.  Weights below this
# threshold indicate that a municipality polygon did not overlap sufficiently
# with the NUTS3 shapes (e.g. due to CRS misalignment or topology gaps).
_MIN_WEIGHT_SUM = 0.99

# Equal-area CRS used for all area calculations to ensure accurate fractional
# overlap computation regardless of the input CRS.
_AREA_CRS = 3035

# Country prefix for Austrian NUTS codes; used to distinguish AT regions from
# non-AT regions (DE, CH, IT, etc.) in the nuts3_shapes GeoDataFrame.
_AT_NUTS_PREFIX = "AT"


def map_to_nuts3_weighted(
    muni_gdf: gpd.GeoDataFrame,
    nuts3_shapes: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """
    Map municipality polygons to NUTS3 regions using area-weighted overlay.

    Reprojects both GeoDataFrames to EPSG:3035, computes polygon intersections,
    and distributes capacity values proportionally by overlap area.  Any
    intersection fragments that fall in non-AT NUTS3 regions (e.g. from border
    municipalities whose polygons slightly extend into neighbouring countries) are
    redirected to the nearest AT NUTS3 region before aggregation.  The result
    is labelled with its NUTS3 (``nuts3``) code.

    Parameters
    ----------
    muni_gdf
        Municipality GeoDataFrame with polygon geometry and one or more
        ``C_``-prefixed capacity columns.
    nuts3_shapes
        NUTS3 shapes GeoDataFrame with ``level2`` (NUTS2) and ``level3`` (NUTS3)
        columns.

    Returns
    -------
    DataFrame with a ``nuts3`` column and all weighted capacity columns.

    Raises
    ------
    ValueError
        If any municipality polygon's intersection weights sum to less than
        ``_MIN_WEIGHT_SUM``, naming the offending original index.
    """
    # Reproject both inputs to the equal-area CRS for correct area computation.
    input_proj = muni_gdf.to_crs(_AREA_CRS).copy()
    nuts3_proj = nuts3_shapes[["level2", "level3", "geometry"]].to_crs(_AREA_CRS)

    # Record each input polygon's total projected area before overlay resets the index.
    input_proj["_input_area"] = input_proj.geometry.area

    # Store the original row identifier so we can group-check weights after overlay.
    input_proj["_orig_idx"] = input_proj.index

    # Compute pairwise intersections; overlay resets the index.
    overlay = gpd.overlay(input_proj, nuts3_proj, how="intersection")

    # Weight = fragment area / original polygon area.
    overlay["weight"] = overlay.geometry.area / overlay["_input_area"]

    # Sanity-check: weights must sum to ≥ _MIN_WEIGHT_SUM per original polygon.
    # Reindex over all original indices so that polygons with zero intersection
    # (absent from the overlay result entirely) are explicitly assigned 0.0 and
    # caught by the check rather than silently dropped.
    all_orig_idx = input_proj["_orig_idx"].unique()
    weight_sums = (
        overlay.groupby("_orig_idx")["weight"]
        .sum()
        .reindex(all_orig_idx, fill_value=0.0)
    )
    bad = weight_sums[weight_sums < _MIN_WEIGHT_SUM]
    if not bad.empty:
        raise ValueError(
            f"Area-weight sum below {_MIN_WEIGHT_SUM} for municipality index(es): "
            f"{bad.index.tolist()}.  Check CRS alignment between input and NUTS3 shapes."
        )

    # Redirect fragments that intersected non-AT NUTS3 regions to the nearest AT NUTS3.
    # This handles border municipalities whose polygons slightly extend into neighbouring
    # countries (DE, CH, IT, etc.) due to dataset boundary differences.
    at_mask = overlay["level3"].str.startswith(_AT_NUTS_PREFIX)
    if not at_mask.all():
        at_nuts3 = nuts3_proj[nuts3_proj["level3"].str.startswith(_AT_NUTS_PREFIX)][
            ["level2", "level3", "geometry"]
        ].reset_index(drop=True)
        non_at_centroids = gpd.GeoDataFrame(
            geometry=overlay.loc[~at_mask, "geometry"].centroid,
            crs=overlay.crs,
        )
        nearest = gpd.sjoin_nearest(non_at_centroids, at_nuts3, how="left")
        overlay.loc[~at_mask, "level2"] = nearest["level2"]
        overlay.loc[~at_mask, "level3"] = nearest["level3"]

    # Identify capacity columns (all C_-prefixed columns present in the overlay result).
    capacity_cols = [c for c in muni_gdf.columns if c.startswith("C_")]

    # Multiply each capacity column by the fractional area weight.
    for col in capacity_cols:
        overlay[col] = overlay[col] * overlay["weight"]

    overlay["nuts3"] = overlay["level3"]

    return overlay[["nuts3"] + capacity_cols]


def fix_gdf(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Fix data error from original KLIEN dataset.

    The original KLIEN dataset has a column shift error. This function identifies and fixes the shift.

    Parameters
    ----------
    gdf
        Read GeoDataFrame to process.

    Returns
    -------
    GeoDataFrame with the shift fix.
    """
    broken_columns = gdf.columns[((gdf == 0) | gdf.isna()).all()]

    # Fail-safe to prevent legitimate all-zero columns to be shifted
    expected = {"C_2030_low_wocc"}
    if unexpected := set(broken_columns) - expected:
        raise ValueError(f"Unexpected broken columns detected: {unexpected}")

    result = gdf.copy()
    for col in broken_columns:
        i_col_broken = result.columns.get_loc(col)
        i_col_last = result.columns.get_loc("geometry")
        to_shift = result.columns[i_col_broken:i_col_last]
        # preserve last columns values. They are lost during shifting
        last_values = result[to_shift[-1]].values.copy()
        result.loc[:, to_shift] = result.loc[:, to_shift].shift(periods=-1, axis=1)
        result[to_shift[-1]] = last_values

    return result


def process_potential_file(
    potential_path: str,
    nuts3_shapes: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """
    Load one KLIEN GeoJSON, apply area-weighted NUTS3 mapping, and aggregate.

    Parameters
    ----------
    potential_path
        Path to the municipality-level KLIEN GeoJSON file.
    nuts3_shapes
        NUTS3 shapes GeoDataFrame (with ``level2`` and ``level3`` columns).

    Returns
    -------
    DataFrame with aggregated potentials, indexed by ``nuts3``.

    Raises
    ------
    ValueError
        If no ``C_``-prefixed capacity columns are found in the GeoJSON, or if
        municipality-to-NUTS3 area-weight validation fails.
    """
    gdf = gpd.read_file(potential_path)
    gdf.columns = gdf.columns.str.strip(" ,")
    gdf = fix_gdf(gdf)

    capacity_cols = [c for c in gdf.columns if c.startswith("C_")]
    if not capacity_cols:
        raise ValueError(
            f"No 'C_'-prefixed energy columns found in '{potential_path}'."
        )

    mapped = map_to_nuts3_weighted(gdf, nuts3_shapes)

    nuts3_agg = mapped.groupby("nuts3")[capacity_cols].sum()

    return nuts3_agg


def main(snakemake: Snakemake) -> None:
    """
    Orchestrate KLIEN potentials aggregation for a Snakemake run.

    Processes PV buildings, ground-mounted (sealed + unsealed combined), and wind
    GeoJSON files into NUTS3-level capacity potential CSVs.

    Parameters
    ----------
    snakemake
        Snakemake workflow object providing ``input``, ``output``, and ``log`` paths.
    """
    configure_logging(snakemake)

    nuts3_shapes = gpd.read_file(snakemake.input.nuts3_shapes).set_index("index")

    # ── PV buildings ─────────────────────────────────────────────────────────
    nuts3_buildings = process_potential_file(snakemake.input.pv_buildings, nuts3_shapes)
    nuts3_buildings.to_csv(snakemake.output.nuts3_buildings)

    # ── PV ground-mounted (sealed + unsealed, summed) ─────────────────────────
    nuts3_sealed = process_potential_file(
        snakemake.input.pv_ground_sealed, nuts3_shapes
    )
    nuts3_unsealed = process_potential_file(
        snakemake.input.pv_ground_unsealed, nuts3_shapes
    )

    nuts3_ground = nuts3_sealed.add(nuts3_unsealed, fill_value=0)
    # .add() resets .index.name when operands have different names; restore explicitly.
    nuts3_ground.index.name = "nuts3"
    nuts3_ground.to_csv(snakemake.output.nuts3_ground)

    # ── Wind ──────────────────────────────────────────────────────────────────
    nuts3_wind = process_potential_file(snakemake.input.wind, nuts3_shapes)
    nuts3_wind.to_csv(snakemake.output.nuts3_wind)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("build_klien_potentials")

    main(snakemake)
