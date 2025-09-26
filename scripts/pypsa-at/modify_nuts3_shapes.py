# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Modify the NUTS3 shapefile for custom administrative clustering."""

import logging
import sys

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
        assert len(entries) == expected


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("modify_nuts3_shapes")

    configure_logging(snakemake)
    config = snakemake.config

    admin_levels = snakemake.params.get("admin_levels")
    nuts3_regions = gpd.read_file(snakemake.input.nuts3_shapes).set_index("index")

    if not (
        config.get("mods", {}).get("modify_nuts3_shapes")
        and config["clustering"]["mode"] == "administrative"
    ):
        logger.info("Skipping NUTS3 shapefile modification.")
        nuts3_regions.to_file(snakemake.output.nuts3_shapes)
        sys.exit(0)

    assert admin_levels.get("level") == 0
    logger.info("Applying custom administrative clustering.")

    # AT: 10
    assert admin_levels.get("AT") in (2, 3)
    if admin_levels.get("AT") == 2:
        override_nuts("AT333", "AT333", "level2")
        assert_expected_number_of_entries("AT", expected=10, lvl=2)
    # DE: NUTS1 (19 regions) or NUTS3 as a proxy for 5 regions
    if admin_levels.get("DE") == 3:
        # update NUTS3 codes to contain 5 unique codes for clustering algorithm
        # the 'GG' suffix is necessary to mark the custom region codes. the letter
        # G is the highest value that still matches the NUTS regex in
        # evals.constants.Regex.region and .country.
        # Baden-Württemberg (BW)
        override_nuts("DE1", "DE1GG", level="level3")
        # Bavaria
        override_nuts("DE2", "DE2GG", level="level3")
        # Midwest (HE, RP, SL, NW)
        override_nuts("DE7", "DE3GG", level="level3")
        override_nuts("DEB", "DE3GG", level="level3")
        override_nuts("DEC", "DE3GG", level="level3")
        override_nuts("DEA", "DE3GG", level="level3")
        # Mideast (BB, BE, MV, SN, ST, TH)
        override_nuts("DE3", "DE4GG", level="level3")
        override_nuts("DE4", "DE4GG", level="level3")
        override_nuts("DE8", "DE4GG", level="level3")
        override_nuts("DED", "DE4GG", level="level3")
        override_nuts("DEE", "DE4GG", level="level3")
        override_nuts("DEG", "DE4GG", level="level3")
        # North (SH, HH, HB, NI)
        override_nuts("DEF", "DE5GG", level="level3")
        override_nuts("DE6", "DE5GG", level="level3")
        override_nuts("DE9", "DE5GG", level="level3")
        override_nuts("DE5", "DE5GG", level="level3")

        assert_expected_number_of_entries("DE", expected=5, lvl=3)
    # IT: italy is in test network but must not be clustered to reduce test complexity
    assert admin_levels.get("IT") == 1
    override_nuts("IT", "IT0")  # mainland
    override_nuts("ITG1", "IT1")  # Sicily
    override_nuts("ITG2", "IT2")  # Sardinia
    assert_expected_number_of_entries("IT", expected=3)
    # DK: 2
    assert admin_levels.get("DK") == 1
    override_nuts("DK", "DK0")
    override_nuts(("DK01", "DK02"), "DK1")  # Sjaelland
    assert_expected_number_of_entries("DK", expected=2)
    # UK: 2
    assert admin_levels.get("GB") == 1
    override_nuts("GB", "GB0")
    override_nuts("GBN", "GB1")  # North Ireland
    assert_expected_number_of_entries("GB", expected=2)
    # FR: 2
    assert admin_levels.get("FR") == 1
    override_nuts("FR", "FR0")
    override_nuts("FRM0", "FR1")  # Corsica
    assert_expected_number_of_entries("FR", expected=2)
    # ES: 2
    assert admin_levels.get("ES") == 1
    override_nuts("ES", "ES0")
    override_nuts("ES53", "ES1")  # Balearic Islands
    assert_expected_number_of_entries("ES", expected=2)

    nuts3_regions.to_file(snakemake.output.nuts3_shapes)
