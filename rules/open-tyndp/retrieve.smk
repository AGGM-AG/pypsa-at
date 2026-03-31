# SPDX-FileCopyrightText: 2025 Austrian Gas Grid Management AG
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

if (OPEN_TYNDP_DATASET := dataset_version("tyndp"))["source"] in [
    "primary",
    "archive",
]:

    rule retrieve_open_tyndp:
        message:
            "Retrieving TYNDP 2024 data package from open-tyndp Google data store "
            "(PEMMDB v2.4, reference grids, nodes)"
        input:
            pemmdb=storage(OPEN_TYNDP_DATASET["url"] + "/PEMMDB2.zip"),
            nodes=storage(OPEN_TYNDP_DATASET["url"] + "/Nodes.zip"),
            line_data=storage(OPEN_TYNDP_DATASET["url"] + "/Line-data.zip"),
        output:
            pemmdb_zip=f"{OPEN_TYNDP_DATASET['folder']}/PEMMDB2.zip",
            pemmdb=directory(f"{OPEN_TYNDP_DATASET['folder']}/PEMMDB2"),
            nodes_zip=f"{OPEN_TYNDP_DATASET['folder']}/Nodes.zip",
            nodes=f"{OPEN_TYNDP_DATASET['folder']}/Nodes/LIST OF NODES.xlsx",
            line_data_zip=f"{OPEN_TYNDP_DATASET['folder']}/Line-data.zip",
            elec_reference_grid=f"{OPEN_TYNDP_DATASET['folder']}/Line data/ReferenceGrid_Electricity.xlsx",
            h2_reference_grid=f"{OPEN_TYNDP_DATASET['folder']}/Line data/ReferenceGrid_Hydrogen.xlsx",
        log:
            "logs/retrieve_open_tyndp.log",
        run:
            for key in input.keys():
                zip_output_key = f"{key}_zip"
                copy2(input[key], output[zip_output_key])

                output_folder = Path(output[zip_output_key]).parent
                unpack_archive(output[zip_output_key], output_folder)

                # Remove __MACOSX directory if present (macOS artifact in zips)
                macosx_dir = output_folder / "__MACOSX"
                rmtree(macosx_dir, ignore_errors=True)
