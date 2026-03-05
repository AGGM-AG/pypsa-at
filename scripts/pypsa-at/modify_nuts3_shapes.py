# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Modify the NUTS3 shapefile for custom administrative clustering."""

import logging

import geopandas as gpd

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)


def override_nuts(nuts_code: str | tuple, override: str, level: str = "level1") -> None:
    """
    Update the NUTS codes.

    Parameters
    ----------
    nuts_code
        The NUTS codes substrings in the index used to identify
        regions that should be updated.
    override
        The value to set for the specified regions.
    level
        The level to set the override value for.

    Returns
    -------
    :
        Updates the NUTS codes in the nuts_regions output file.
    """
    logger.debug(f"Overriding regions with code {nuts_code} to {override}.")
    mask = nuts3_regions.index.str.startswith(nuts_code)
    nuts3_regions.loc[mask, level] = override


def assert_expected_number_of_entries(nuts_code: str, expected: int, lvl: int = 1):
    """
    Ensure that a specific number of entries are present for a NUTS code.

    Parameters
    ----------
    nuts_code
        The NUTS code to check for.
    expected
        The expected number of entries.
    lvl
        The level to check the `nuts_code` at.

    Raises
    ------
    AssertionError
        If the number of entries does not match the expected value.
    """
    regions_at_level = nuts3_regions.query(f"level{lvl}.str.startswith(@nuts_code)")
    entries = regions_at_level[f"level{lvl}"].unique()
    if snakemake.config["run"]["prefix"] != "test-sector-myopic-at10":
        # skip for CI tests
        assert len(entries) == expected


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("modify_nuts3_shapes")

    configure_logging(snakemake)
    config = snakemake.config

    admin_levels = snakemake.params.get("admin_levels")
    nuts3_regions = gpd.read_file(snakemake.input.nuts3_shapes).set_index("index")
    custom_clustering = config.get("mods", {}).get("modify_nuts3_shapes")

    if config["clustering"]["mode"] != "administrative":
        raise ValueError(
            f"Unexpected clustering mode detected: {config['clustering']['mode']}. "
            f"Only 'administrative' is supported."
        )

    if base_level := admin_levels.get("level") != 0:
        raise ValueError(
            f"Base clustering level is {base_level}, but only 0 is supported."
        )

    if custom_clustering == "AT10DE5":
        nuts_at = 2
        nuts_de = 3
    elif custom_clustering == "AT10DE16":
        nuts_at = 2
        nuts_de = 1
    elif custom_clustering == "AT35DE5":
        nuts_at = 3
        nuts_de = 3
    elif custom_clustering == "AT35DE16":
        nuts_at = 3
        nuts_de = 1
    else:
        raise ValueError(
            f"Unexpected clustering detected: {custom_clustering}. "
            f"Chose one from {('AT10DE5', 'AT10DE16', 'AT35DE5', 'AT35DE16')}."
        )

    logger.info("Applying custom administrative clustering.")

    assert admin_levels.get("AT") == nuts_at, (
        f"Inconsistent administrative clustering defined for Austria: "
        f"clustering level AT is {admin_levels.get('AT')}, but the "
        f"requested custom clustering is {custom_clustering} which "
        f"yields AT NUTS level {nuts_at}. Both entries must be in sync. "
    )
    if nuts_at == 2:
        override_nuts("AT333", "AT333", "level2")
        assert_expected_number_of_entries("AT", expected=10, lvl=2)
    # else: NUTS level AT 3 is correct as it is.

    assert admin_levels.get("DE") == nuts_de, (
        f"Inconsistent administrative clustering defined for Germany: "
        f"clustering level DE is {admin_levels.get('DE')}, but the "
        f"requested custom clustering is {custom_clustering} which "
        f"yields DE NUTS level {nuts_de}. Both entries must be in sync. "
    )
    if nuts_de == 3:  # NUTS3 is a proxy for 5 regions
        # Baden-Württemberg (BW)
        override_nuts("DE1", "DE1", level="level3")
        # Bavaria
        override_nuts("DE2", "DE2", level="level3")
        # Midwest (HE, RP, SL, NW)
        override_nuts("DE7", "DE3", level="level3")
        override_nuts("DEB", "DE3", level="level3")
        override_nuts("DEC", "DE3", level="level3")
        override_nuts("DEA", "DE3", level="level3")
        # Mideast (BB, BE, MV, SN, ST, TH)
        override_nuts("DE3", "DE4", level="level3")
        override_nuts("DE4", "DE4", level="level3")
        override_nuts("DE8", "DE4", level="level3")
        override_nuts("DED", "DE4", level="level3")
        override_nuts("DEE", "DE4", level="level3")
        override_nuts("DEG", "DE4", level="level3")
        # North (SH, HH, HB, NI)
        override_nuts("DEF", "DE5", level="level3")
        override_nuts("DE6", "DE5", level="level3")
        override_nuts("DE9", "DE5", level="level3")
        override_nuts("DE5", "DE5", level="level3")

        assert_expected_number_of_entries("DE", expected=5, lvl=3)
    # IT: italy is in the test network but must not be clustered to reduce test complexity
    assert admin_levels.get("IT") == 1, (
        f"Custom clustering requires NUTS level 1 for Italy, "
        f"but {admin_levels.get('IT')} is configured."
    )
    override_nuts("IT", "IT0")  # mainland
    override_nuts("ITG1", "IT1")  # Sicily
    override_nuts("ITG2", "IT2")  # Sardinia
    assert_expected_number_of_entries("IT", expected=3)
    # DK: 2
    assert admin_levels.get("DK") == 1, (
        f"Custom clustering requires NUTS level 1 for Denmark, "
        f"but {admin_levels.get('DK')} is configured."
    )
    override_nuts("DK", "DK0")
    override_nuts(("DK01", "DK02"), "DK1")  # Sjaelland
    assert_expected_number_of_entries("DK", expected=2)
    # UK: 2
    assert admin_levels.get("GB") == 1, (
        f"Custom clustering requires NUTS level 1 for Great Britain, "
        f"but {admin_levels.get('GB')} is configured."
    )
    override_nuts("GB", "GB0")
    override_nuts("GBN", "GB1")  # North Ireland
    assert_expected_number_of_entries("GB", expected=2)
    # FR: 2
    assert admin_levels.get("FR") == 1, (
        f"Custom clustering requires NUTS level 1 for France, "
        f"but {admin_levels.get('FR')} is configured."
    )
    override_nuts("FR", "FR0")
    override_nuts("FRM0", "FR1")  # Corsica
    assert_expected_number_of_entries("FR", expected=2)
    # ES: 2
    assert admin_levels.get("ES") == 1, (
        f"Custom clustering requires NUTS level 1 for Spain, "
        f"but {admin_levels.get('ES')} is configured."
    )
    override_nuts("ES", "ES0")
    override_nuts("ES53", "ES1")  # Balearic Islands
    assert_expected_number_of_entries("ES", expected=2)

    nuts3_regions.to_file(snakemake.output.nuts3_shapes)
