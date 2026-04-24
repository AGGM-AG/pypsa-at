# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Functions to apply custom administrative clustering to NUTS3 shape data.

PyPSA-AT supports four custom clustering configurations that combine different
NUTS resolution levels for Austria and Germany:

| Configuration | AT NUTS level | DE NUTS regions |
|---------------|---------------|-----------------|
| ``AT10DE5``   | 2 (10 regions)| 5 aggregates    |
| ``AT10DE16``  | 2 (10 regions)| 16 states       |
| ``AT35DE5``   | 3 (35 regions)| 5 aggregates    |
| ``AT35DE16``  | 3 (35 regions)| 16 states       |

The clustering is applied as a pre-processing step in the Snakemake rule
``modify_nuts3_shapes`` before the network clustering step. The modifications
are stored in the ``level1``, ``level2``, or ``level3`` columns of the NUTS3
GeoDataFrame and are later consumed by PyPSA-Eur's clustering pipeline.

The Austrian NUTS3 region AT333 (Osttirol) is treated specially at NUTS2 level:
it belongs to Tyrol (AT33x) geographically, but its NUTS2 code (AT33) is shared
with other Tyrolean districts. To keep it as a distinct region at NUTS2 resolution,
AT333 is mapped to itself (``AT333 → AT333``).
"""

import logging

import geopandas as gpd

logger = logging.getLogger(__name__)

#: Valid clustering configurations and their implied NUTS levels.
VALID_CONFIGURATIONS = ("AT10DE5", "AT10DE16", "AT35DE5", "AT35DE16")


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


def apply_custom_clustering(
    nuts3_regions: gpd.GeoDataFrame,
    custom_clustering: str,
    admin_levels: dict,
    run_prefix: str | None = None,
) -> gpd.GeoDataFrame:
    """
    Apply a PyPSA-AT custom administrative clustering to the NUTS3 shapes.

    Validates configuration consistency and reassigns NUTS region codes in
    ``nuts3_regions`` so that PyPSA-Eur's clustering pipeline produces the
    requested spatial resolution for Austria, Germany, Italy, Denmark, Great
    Britain, and Spain. France is modelled at NUTS level 0 (single country
    region) — Corsica has no OSM transmission buses.

    Supported configurations:

    - ``AT10DE5``: Austria at NUTS2 (10 regions) + Germany aggregated to 5 macro-regions
    - ``AT10DE16``: Austria at NUTS2 (10 regions) + Germany at NUTS1 (16 federal states)
    - ``AT35DE5``: Austria at NUTS3 (35 regions) + Germany aggregated to 5 macro-regions
    - ``AT35DE16``: Austria at NUTS3 (35 regions) + Germany at NUTS1 (16 federal states)

    Parameters
    ----------
    nuts3_regions
        GeoDataFrame with NUTS3 shapes, indexed by NUTS3 code. Must contain
        ``level1``, ``level2``, and ``level3`` columns.
    custom_clustering
        One of ``"AT10DE5"``, ``"AT10DE16"``, ``"AT35DE5"``, ``"AT35DE16"``.
    admin_levels
        Dictionary mapping country codes to their configured NUTS level, as
        read from ``config["clustering"]["administrative"]``. Used to validate
        that the YAML config is consistent with the requested clustering.
    run_prefix
        Current run prefix from ``config["run"]["prefix"]``. Used to suppress
        the region count assertions in CI test runs.

    Returns
    -------
    :
        The modified GeoDataFrame with updated NUTS codes in all relevant
        level columns.

    Raises
    ------
    ValueError
        If ``custom_clustering`` is not one of the supported values.
    AssertionError
        If ``admin_levels`` in the config is inconsistent with the requested
        clustering, or if the resulting region counts do not match expectations.

    Examples
    --------
    Apply AT35DE5 clustering (Austria at NUTS3, Germany at 5 macro-regions):

    >>> import geopandas as gpd
    >>> nuts3 = gpd.read_file("resources/nuts3_shapes-raw.geojson").set_index("index")
    >>> admin_levels = {"AT": 3, "DE": 3, "IT": 1, "DK": 1, "GB": 1, "ES": 1}
    >>> result = apply_custom_clustering(nuts3, "AT35DE5", admin_levels)
    """
    if custom_clustering not in VALID_CONFIGURATIONS:
        raise ValueError(
            f"Unexpected clustering: '{custom_clustering}'. "
            f"Choose one of {VALID_CONFIGURATIONS}."
        )

    # Determine implied NUTS levels from configuration name
    expected_at_level = 2 if custom_clustering.startswith("AT10") else 3
    expected_de_level = 3 if custom_clustering.endswith("DE5") else 1

    logger.info(f"Applying custom administrative clustering: {custom_clustering}")

    # check consistency between clustering configuration items
    if admin_levels.get("AT") != expected_at_level:
        raise ValueError(
            f"Inconsistent config for Austria: admin_levels['AT']={admin_levels.get('AT')}, "
            f"but '{custom_clustering}' requires NUTS level {expected_at_level}."
        )

    if admin_levels.get("DE") != expected_de_level:
        raise ValueError(
            f"Inconsistent config for Germany: admin_levels['DE']={admin_levels.get('DE')}, "
            f"but '{custom_clustering}' requires NUTS level {expected_de_level}."
        )

    # AT333 (Osttirol) has the same NUTS2 prefix as other Tyrolean districts.
    # Map it to itself to preserve it as a distinct region at NUTS2 resolution.
    nuts3_regions = override_nuts(nuts3_regions, "AT333", "AT333", "level2")
    assert_expected_region_count(nuts3_regions, "AT", expected=10, lvl=2)

    # NUTS3 codes are used as a proxy to aggregate Germany into 5 macro-regions.
    # Baden-Württemberg
    nuts3_regions = override_nuts(nuts3_regions, "DE1", "DE1", level="level3")
    # Bavaria
    nuts3_regions = override_nuts(nuts3_regions, "DE2", "DE2", level="level3")
    # Midwest (Hesse, Rhineland-Palatinate, Saarland, North Rhine-Westphalia)
    nuts3_regions = override_nuts(
        nuts3_regions, ("DE7", "DEB", "DEC", "DEA"), "DE3", level="level3"
    )
    # Mideast (Brandenburg, Berlin, Mecklenburg-Vorpommern, Saxony, Saxony-Anhalt, Thuringia)
    nuts3_regions = override_nuts(
        nuts3_regions, ("DE3", "DE4", "DE8", "DED", "DEE", "DEG"), "DE4", level="level3"
    )
    # North (Schleswig-Holstein, Hamburg, Bremen, Lower Saxony)
    nuts3_regions = override_nuts(
        nuts3_regions, ("DEF", "DE6", "DE9", "DE5"), "DE5", level="level3"
    )
    assert_expected_region_count(
        nuts3_regions, "DE", expected=5, lvl=3, run_prefix=run_prefix
    )

    # Separate Islands from main land for IT, DK, GB, and ES
    if admin_levels.get("IT") == 1:
        nuts3_regions = override_nuts(nuts3_regions, "IT", "IT0")  # mainland
        nuts3_regions = override_nuts(nuts3_regions, "ITG1", "IT1")  # Sicily
        nuts3_regions = override_nuts(nuts3_regions, "ITG2", "IT2")  # Sardinia
        assert_expected_region_count(
            nuts3_regions, "IT", expected=3, run_prefix=run_prefix
        )

    if admin_levels.get("DK") == 1:
        nuts3_regions = override_nuts(nuts3_regions, "DK", "DK0")
        nuts3_regions = override_nuts(
            nuts3_regions, ("DK01", "DK02"), "DK1"
        )  # Sjaelland
        assert_expected_region_count(
            nuts3_regions, "DK", expected=2, run_prefix=run_prefix
        )

    if admin_levels.get("GB") == 1:
        nuts3_regions = override_nuts(nuts3_regions, "GB", "GB0")
        nuts3_regions = override_nuts(nuts3_regions, "GBN", "GB1")  # Northern Ireland
        assert_expected_region_count(
            nuts3_regions, "GB", expected=2, run_prefix=run_prefix
        )

    if admin_levels.get("ES") == 1:
        nuts3_regions = override_nuts(nuts3_regions, "ES", "ES0")
        nuts3_regions = override_nuts(nuts3_regions, "ES53", "ES1")  # Balearic Islands
        assert_expected_region_count(
            nuts3_regions, "ES", expected=2, run_prefix=run_prefix
        )

    if admin_levels.get("FR") == 1:
        nuts3_regions = override_nuts(nuts3_regions, "FR", "FR0")
        nuts3_regions = override_nuts(nuts3_regions, "FRM0", "FR1")  # Corsica
        assert_expected_region_count(
            nuts3_regions, "FR", expected=2, run_prefix=run_prefix
        )

    return nuts3_regions
