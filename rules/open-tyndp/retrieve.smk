# SPDX-FileCopyrightText: 2025-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Retrieval rules for Open-TYNDP datasets.

Downloads TYNDP 2024 data from the publicly available Google Cloud Storage
data store maintained by Open Energy Transition:
https://storage.googleapis.com/open-tyndp-data-store

The data store is populated by the open-tyndp project:
https://github.com/open-energy-transition/open-tyndp

The `tyndp` dataset entry in `data/versions.csv` must point to the Google
data store archive so that PEMMDB and the reference grids are available.
"""

# `dataset_version` and Snakemake imports are available from the enclosing
# Snakefile scope (rules/common.smk is included before this file).
# `copy2`, `unpack_archive`, `rmtree` are imported in rules/retrieve.smk.


# Versioning not implemented as the dataset is used only for plotting
# License - MIT - Copyright (c) 2021 Gavin Rehkemper
# Website: https://github.com/gavinr/world-countries-centroids
rule retrieve_countries_centroids:
    output:
        "data/countries_centroids.geojson",
    log:
        "logs/retrieve_countries_centroids.log",
    run:
        from scripts._helpers import progress_retrieve

        progress_retrieve(
            "https://cdn.jsdelivr.net/gh/gavinr/world-countries-centroids@v1.0.0/dist/countries.geojson",
            output[0],
            disable=True,
        )


if (OPEN_TYNDP_DATASET := dataset_version("tyndp"))["source"] in [
    "primary",
    "archive",
]:

    rule retrieve_open_tyndp:
        input:
            pemmdb=storage(OPEN_TYNDP_DATASET["url"] + "/PEMMDB2.zip"),
            nodes=storage(OPEN_TYNDP_DATASET["url"] + "/Nodes.zip"),
            line_data=storage(OPEN_TYNDP_DATASET["url"] + "/Line-data.zip"),
            hydro_inflows=storage(OPEN_TYNDP_DATASET["url"] + "/Hydro-Inflows.zip"),
            supply_tool=storage(
                OPEN_TYNDP_DATASET["url"] + "/20240518-Supply-Tool.xlsm.zip"
            ),
            demand_profiles=storage(OPEN_TYNDP_DATASET["url"] + "/Demand-Profiles.zip"),
            hydrogen=storage(OPEN_TYNDP_DATASET["url"] + "/Hydrogen.zip"),
            investment_datasets=storage(
                OPEN_TYNDP_DATASET["url"] + "/Investment-Datasets.zip"
            ),
            offshore_hubs=storage(OPEN_TYNDP_DATASET["url"] + "/Offshore-hubs.zip"),
        output:
            pemmdb_zip=f"{OPEN_TYNDP_DATASET['folder']}/PEMMDB2.zip",
            pemmdb=directory(f"{OPEN_TYNDP_DATASET['folder']}/PEMMDB2"),
            nodes_zip=f"{OPEN_TYNDP_DATASET['folder']}/Nodes.zip",
            nodes=f"{OPEN_TYNDP_DATASET['folder']}/Nodes/LIST OF NODES.xlsx",
            line_data_zip=f"{OPEN_TYNDP_DATASET['folder']}/Line-data.zip",
            elec_reference_grid=f"{OPEN_TYNDP_DATASET['folder']}/Line data/ReferenceGrid_Electricity.xlsx",
            h2_reference_grid=f"{OPEN_TYNDP_DATASET['folder']}/Line data/ReferenceGrid_Hydrogen.xlsx",
            hydro_inflows_zip=f"{OPEN_TYNDP_DATASET['folder']}/Hydro-Inflows.zip",
            hydro_inflows=directory(f"{OPEN_TYNDP_DATASET['folder']}/Hydro Inflows"),
            supply_tool_zip=f"{OPEN_TYNDP_DATASET['folder']}/20240518-Supply-Tool.xlsm.zip",
            supply_tool=f"{OPEN_TYNDP_DATASET['folder']}/20240518-Supply-Tool.xlsm",
            demand_profiles_zip=f"{OPEN_TYNDP_DATASET['folder']}/Demand-Profiles.zip",
            demand_profiles=directory(f"{OPEN_TYNDP_DATASET['folder']}/Demand Profiles"),
            hydrogen_zip=f"{OPEN_TYNDP_DATASET['folder']}/Hydrogen.zip",
            hydrogen=directory(f"{OPEN_TYNDP_DATASET['folder']}/Hydrogen"),
            h2_imports=f"{OPEN_TYNDP_DATASET['folder']}/Hydrogen/H2 IMPORTS GENERATORS PROPERTIES.xlsx",
            h2_storages=f"{OPEN_TYNDP_DATASET['folder']}/Hydrogen/H2 STORAGES.xlsx",
            smr=f"{OPEN_TYNDP_DATASET['folder']}/Hydrogen/SMR Figures.xlsx",
            investment_datasets_zip=f"{OPEN_TYNDP_DATASET['folder']}/Investment-Datasets.zip",
            trajectories=f"{OPEN_TYNDP_DATASET['folder']}/Investment Datasets/TRAJECTORY.xlsx",
            invest_grid=f"{OPEN_TYNDP_DATASET['folder']}/Investment Datasets/GRID.xlsx",
            offshore_hubs_zip=f"{OPEN_TYNDP_DATASET['folder']}/Offshore-hubs.zip",
            offshore_nodes=f"{OPEN_TYNDP_DATASET['folder']}/Offshore hubs/NODE.xlsx",
            offshore_grid=f"{OPEN_TYNDP_DATASET['folder']}/Offshore hubs/GRID.xlsx",
            offshore_electrolysers=f"{OPEN_TYNDP_DATASET['folder']}/Offshore hubs/ELECTROLYSER.xlsx",
            offshore_generators=f"{OPEN_TYNDP_DATASET['folder']}/Offshore hubs/GENERATOR.xlsx",
        log:
            "logs/retrieve_open_tyndp.log",
        message:
            "Retrieving TYNDP 2024 data package from open-tyndp Google data store "
            "(PEMMDB v2.4, reference grids, nodes, hydro inflows, demand profiles, "
            "H2 data, investment datasets, offshore hubs)"
        run:
            for key in input.keys():
                zip_output_key = f"{key}_zip"
                copy2(input[key], output[zip_output_key])

                output_folder = Path(output[zip_output_key]).parent
                unpack_archive(output[zip_output_key], output_folder)

                # Remove __MACOSX directory if present (macOS artifact in zips)
                macosx_dir = output_folder / "__MACOSX"
                rmtree(macosx_dir, ignore_errors=True)
