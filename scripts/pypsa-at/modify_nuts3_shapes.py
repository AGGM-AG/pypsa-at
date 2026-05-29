# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Snakemake script: apply custom NUTS3 clustering to the Austrian shape file.

This is a thin Snakemake wrapper around
:func:`mods.clustering.apply_custom_clustering`. All business logic lives in
the ``mods`` module so that it is importable, testable, and visible in the
Function Reference documentation.

See Also
--------
mods.clustering.apply_custom_clustering : the underlying implementation.
"""

import logging

import geopandas as gpd

from mods import apply_custom_clustering
from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "modify_nuts3_shapes",
            simpl="",
            clusters="adm",
            opts="",
            ll="v1.25",
            sector_opts="none",
            run="AT_KN2040",
        )

    configure_logging(snakemake)
    config = snakemake.config

    custom_clustering = config["mods"]["modify_nuts3_shapes"]
    if custom_clustering not in ("AT10DE5", "AT35DE5", "AT10DE16", "AT35DE16"):
        raise ValueError(f"Custom clustering {custom_clustering!r} is not supported.")

    if config["clustering"]["mode"] != "administrative":
        raise ValueError(
            f"Unexpected clustering mode: '{config['clustering']['mode']}'. "
            f"Only 'administrative' is supported by modify_nuts3_shapes."
        )

    admin_levels = snakemake.params["admin_levels"]
    base_level = admin_levels["level"]
    if base_level != 0:
        raise ValueError(
            f"Base clustering level is {base_level!r}, but only 0 is supported."
        )

    custom_clustering = config["mods"]["modify_nuts3_shapes"]
    run_prefix = config["run"]["prefix"]

    nuts3_regions = gpd.read_file(snakemake.input.nuts3_shapes).set_index("index")

    nuts3_regions = apply_custom_clustering(
        nuts3_regions,
        custom_clustering=custom_clustering,
        admin_levels=admin_levels,
        run_prefix=run_prefix,
    )

    nuts3_regions.to_file(snakemake.output.nuts3_shapes)
