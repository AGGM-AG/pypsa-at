# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Retrieval rules for AT-specific datasets.

Downloads AT-specific data from the sources for the dataset entries in
 `data/versions.csv`.
"""

# `dataset_version` and Snakemake imports are available from the enclosing
# Snakefile scope (rules/common.smk is included before this file).
# `copy2`, `unpack_archive`, `rmtree` are imported in rules/retrieve.smk.

if (KLIEN_PV_BUILDINGS_POTENTIAL := dataset_version("klien_pv_buildings_potential"))[
    "source"
] in [
    "primary",
    "archive",
]:

    rule retrieve_klien_pv_buildings_potential:
        message:
            "Retrieving KLIEN PV Buildings Potential"
        input:
            klien_pv_buildings_potential=storage(KLIEN_PV_BUILDINGS_POTENTIAL["url"]),
        output:
            klien_pv_buildings_potential=f"{KLIEN_PV_BUILDINGS_POTENTIAL['folder']}/pv_buildings_potential.geojson",
        run:
            copy2(
                input["klien_pv_buildings_potential"],
                output["klien_pv_buildings_potential"],
            )


if (
    KLIEN_PV_GROUND_MOUNTED_SEALED_POTENTIAL := dataset_version(
        "klien_pv_ground_mounted_sealed_potential"
    )
)["source"] in [
    "primary",
    "archive",
]:

    rule retrieve_klien_pv_ground_mounted_sealed_potential:
        message:
            "Retrieving KLIEN PV Ground Mounted Sealed Potential"
        input:
            klien_pv_ground_mounted_sealed_potential=storage(
                KLIEN_PV_GROUND_MOUNTED_SEALED_POTENTIAL["url"]
            ),
        output:
            klien_pv_ground_mounted_sealed_potential=f"{KLIEN_PV_GROUND_MOUNTED_SEALED_POTENTIAL['folder']}/pv_ground_sealed_potential.geojson",
        run:
            copy2(
                input["klien_pv_ground_mounted_sealed_potential"],
                output["klien_pv_ground_mounted_sealed_potential"],
            )


if (
    KLIEN_PV_GROUND_MOUNTED_UNSEALED_POTENTIAL := dataset_version(
        "klien_pv_ground_mounted_unsealed_potential"
    )
)["source"] in [
    "primary",
    "archive",
]:

    rule retrieve_klien_pv_ground_mounted_unsealed_potential:
        message:
            "Retrieving KLIEN PV Ground Mounted Unsealed Potential"
        input:
            klien_pv_ground_mounted_unsealed_potential=storage(
                KLIEN_PV_GROUND_MOUNTED_UNSEALED_POTENTIAL["url"]
            ),
        output:
            klien_pv_ground_mounted_unsealed_potential=f"{KLIEN_PV_GROUND_MOUNTED_UNSEALED_POTENTIAL['folder']}/pv_ground_unsealed_potential.geojson",
        run:
            copy2(
                input["klien_pv_ground_mounted_unsealed_potential"],
                output["klien_pv_ground_mounted_unsealed_potential"],
            )
