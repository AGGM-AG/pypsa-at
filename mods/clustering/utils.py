# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Utility functions for PyPSA-AT custom administrative clustering.

Contains the NUTS aggregation logic used to collapse region-indexed data onto
the coarser regions present in a custom clustering, plus helpers to reassign
NUTS codes on the NUTS3 shape data and assert the resulting region counts.

The Austrian NUTS3 region AT333 (Osttirol) is treated specially at NUTS2 level:
it belongs to Tyrol (AT33x) geographically, but its NUTS2 code (AT33) is shared
with other Tyrolean districts. To keep it as a distinct region at NUTS2 resolution,
AT333 is mapped to itself (``AT333 → AT333``).
"""

import logging

import geopandas as gpd

from mods.clustering.constants import _DE_NUTS1_TO_DE5

logger = logging.getLogger(__name__)


def _map_at_nuts3_to_nuts2(code: str) -> str:
    """
    Map an AT NUTS3 code to its NUTS2 parent; all other codes pass through.

    - AT NUTS3 → AT NUTS2, e.g. ``"AT125"`` → ``"AT12"``
    - AT333 (Osttirol) → ``"AT333"`` (preserved as its own NUTS2 region)
    - All other codes pass through unchanged.

    Parameters
    ----------
    code
        Region code to map.

    Returns
    -------
    :
        The NUTS2 parent code for AT NUTS3 inputs, or the original code
        unchanged for everything else.
    """
    if code == "AT333":
        return code
    if code.startswith("AT") and len(code) == 5:
        return code[:4]
    return code


def _map_de_nuts1_to_de5(code: str) -> str:
    """
    Map a DE NUTS1 code to its DE5 macro-region; all other codes pass through.

    - DE NUTS1 → DE5 macro-region, e.g. ``"DE7"`` → ``"DE3"``
    - All other codes pass through unchanged.

    Parameters
    ----------
    code
        Region code to map.

    Returns
    -------
    :
        The DE5 macro-region code for DE NUTS1 inputs, or the original code
        unchanged for everything else.
    """
    return _DE_NUTS1_TO_DE5.get(code, code)


def combine_regions_by_clustering(df, clustering):
    """
    Aggregate region-indexed data to a custom clustering's spatial resolution.

    Sums the rows of ``df`` over the region groups implied by ``clustering``,
    collapsing data given at the finest supported NUTS resolution onto the
    coarser regions actually present in the clustered network:

    - ``AT10`` clusterings aggregate AT NUTS3 → AT NUTS2 (via
      :func:`_map_at_nuts3_to_nuts2`); AT333 (Osttirol) is preserved as its
      own region.
    - ``DE5`` clusterings aggregate DE NUTS1 → DE5 macro-regions (via
      :func:`_map_de_nuts1_to_de5`).

    ``AT35`` and ``DE16`` clusterings leave the respective regions untouched,
    and index entries matching neither mapping pass through unchanged.

    Parameters
    ----------
    df
        DataFrame or Series indexed by region code at the finest supported
        resolution: AT NUTS3 (5-character, e.g. ``"AT130"``) and DE NUTS1
        (e.g. ``"DE7"``). Values must be additive, since aggregation sums all
        rows that map to the same target region.
    clustering
        A custom clustering configuration, e.g. ``"AT10DE5"``. Only the
        ``AT10`` prefix and the ``DE5`` suffix trigger aggregation.

    Returns
    -------
    :
        ``df`` aggregated to the clustering's region resolution, with its
        index relabelled to the target region codes. Same type as the input.

    Examples
    --------
    Aggregate AT NUTS3 + DE NUTS1 gas storage capacities to AT10DE5 resolution:

    >>> storage = combine_regions_by_clustering(storage, "AT10DE5")
    """
    if clustering.startswith("AT10"):
        df = df.groupby(df.index.map(_map_at_nuts3_to_nuts2)).sum()
    if clustering.endswith("DE5"):
        df = df.groupby(df.index.map(_map_de_nuts1_to_de5)).sum()

    return df


def override_nuts(
    nuts3_regions: gpd.GeoDataFrame,
    nuts_code: str | tuple[str, ...],
    override: str,
    level: str = "level1",
) -> gpd.GeoDataFrame:
    """
    Reassign NUTS codes for matching regions.

    Finds all rows in the GeoDataFrame whose index starts with any of the
    provided ``nuts_code`` prefixes and sets their ``level`` column to
    ``override``.

    Parameters
    ----------
    nuts3_regions
        GeoDataFrame with NUTS3 shapes, indexed by NUTS3 code.
    nuts_code
        A single NUTS prefix string or a tuple of prefixes. All regions
        whose index starts with any prefix will be updated.
    override
        The new NUTS code to assign to matching regions.
    level
        Name of the column to update (e.g. ``"level1"``, ``"level2"``,
        ``"level3"``).

    Returns
    -------
    :
        The GeoDataFrame with updated NUTS codes in place.

    Examples
    --------
    Merge all AT NUTS3 codes that start with ``"AT1"`` into one region:

    >>> nuts3 = override_nuts(nuts3, "AT1", "AT1", level="level2")

    Merge two separate island groups into one region:

    >>> nuts3 = override_nuts(nuts3, ("DK01", "DK02"), "DK1", level="level1")
    """
    logger.debug(f"Overriding regions starting with codes {nuts_code} to {override}.")
    mask = nuts3_regions.index.str.startswith(nuts_code)
    nuts3_regions.loc[mask, level] = override
    return nuts3_regions


def assert_expected_region_count(
    nuts3_regions: gpd.GeoDataFrame,
    nuts_code: str,
    expected: int,
    lvl: int = 1,
    ci_prefix: str | None = "test-sector-myopic-at10",
    run_prefix: str | None = None,
) -> None:
    """
    Assert that a NUTS code maps to exactly the expected number of regions.

    Queries the GeoDataFrame for all rows where the ``level{lvl}`` column
    starts with ``nuts_code`` and checks the number of unique values. CI test
    runs are exempt from this check.

    Parameters
    ----------
    nuts3_regions
        GeoDataFrame with NUTS3 shapes and level columns.
    nuts_code
        The NUTS prefix to filter by.
    expected
        Expected number of distinct regions at the given level.
    lvl
        The clustering level to inspect (default ``1``).
    ci_prefix
        Run prefix string used for CI tests. When ``run_prefix`` matches this
        value the assertion is skipped.
    run_prefix
        The current run's prefix from ``snakemake.config["run"]["prefix"]``.
        Pass ``None`` to always enforce the assertion.

    Raises
    ------
    ValueError
        If the number of distinct regions does not equal ``expected``.

    Examples
    --------
    Verify Austria has exactly 10 NUTS2 regions after reassignment:

    >>> assert_expected_region_count(nuts3, "AT", expected=10, lvl=2)
    """
    if run_prefix == ci_prefix:
        return  # skip for CI tests

    col = f"level{lvl}"
    mask = nuts3_regions[col].astype(str).str.startswith(nuts_code)
    regions_at_level = nuts3_regions[mask]
    entries = regions_at_level[col].unique()
    if len(entries) != expected:
        raise ValueError(
            f"Expected {expected} regions for '{nuts_code}' at level {lvl}, "
            f"but found {len(entries)}: {sorted(entries)}"
        )
