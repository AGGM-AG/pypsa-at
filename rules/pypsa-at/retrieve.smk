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
# `copy2`, `unpack_archive`, `rmtree` and `storage` are imported in rules/retrieve.smk.

# KLIEN_POTENTIALS is defined in Snakefile (dataset_version("klien_potentials"))
# and available via include scope. Individual GeoJSON files are fetched via storage()
# using per-file path fragments appended to KLIEN_POTENTIALS['url'].

from mods.constants import NUTS2_CODES

BUNDESLAENDER = list(NUTS2_CODES.keys())


if KLIEN_POTENTIALS["source"] == "build":

    rule build_klien_potentials:
        input:
            nuts3_shapes=resources("nuts3_shapes.geojson"),
            pv_buildings=storage(
                f"{KLIEN_POTENTIALS['url']}/pv/pv_buildings/pv_buildings_EEPOT_W23.geojson"
            ),
            pv_ground_sealed=storage(
                f"{KLIEN_POTENTIALS['url']}/pv/pv_ground_mounted_sealed/pv_ground_mounted_sealed_EEPOT_W23.geojson"
            ),
            pv_ground_unsealed=storage(
                f"{KLIEN_POTENTIALS['url']}/pv/pv_ground_mounted_unsealed/pv_ground_mounted_unsealed_EEPOT_W23.geojson"
            ),
            wind=storage(f"{KLIEN_POTENTIALS['url']}/wind/wind_EEPOT_W23.geojson"),
        output:
            nuts3_buildings=f"{KLIEN_POTENTIALS['folder']}/nuts3_pv_buildings.csv",
            nuts3_ground=f"{KLIEN_POTENTIALS['folder']}/nuts3_pv_ground.csv",
            nuts3_wind=f"{KLIEN_POTENTIALS['folder']}/nuts3_wind.csv",
        log:
            logs("build_klien_potentials.log"),
        threads: 1
        resources:
            mem_mb=2000,
        message:
            "Building aggregated KLIEN potentials (PV + wind) from KLIEN GeoJSON sources"
        script:
            scripts("pypsa-at/build_klien_potentials.py")

elif KLIEN_POTENTIALS["source"] == "archive":

    rule retrieve_klien_potentials:
        input:
            nuts3_buildings=storage(f"{KLIEN_POTENTIALS['url']}/nuts3_pv_buildings.csv"),
            nuts3_ground=storage(f"{KLIEN_POTENTIALS['url']}/nuts3_pv_ground.csv"),
            nuts3_wind=storage(f"{KLIEN_POTENTIALS['url']}/nuts3_wind.csv"),
        output:
            nuts3_buildings=f"{KLIEN_POTENTIALS['folder']}/nuts3_pv_buildings.csv",
            nuts3_ground=f"{KLIEN_POTENTIALS['folder']}/nuts3_pv_ground.csv",
            nuts3_wind=f"{KLIEN_POTENTIALS['folder']}/nuts3_wind.csv",
        log:
            logs("retrieve_klien_potentials.log"),
        message:
            "Retrieving pre-aggregated KLIEN potentials (PV + wind) from archive"
        run:
            for key in input.keys():
                copy2(input[key], output[key])


# NEA_AT is defined in Snakefile (dataset_version("nea-at")); one ODS file per
# Bundesland is fetched via storage() from the NEA_AT["url"] base directory.

if NEA_AT["source"] == "primary":

    rule retrieve_nea_at:
        input:
            **{b: storage(f"{NEA_AT['url']}/NEA{b}Daten.ods") for b in BUNDESLAENDER},
        output:
            **{b: f"{NEA_AT['folder']}/NEA{b}Daten.ods" for b in BUNDESLAENDER},
        log:
            logs("retrieve_nea_at.log"),
        message:
            "Retrieving Statistik Austria NEA files per Bundesland"
        run:
            for b in BUNDESLAENDER:
                move(input[b], output[b])


# FfE (Forschungsstelle für Energiewirtschaft) normalized industrial electricity
# load profiles. `requests` and `json` are imported at module scope by rules/retrieve.smk,
# included before this file (see Snakefile).


rule retrieve_ffe_industry_load_profiles:
    output:
        "data/pypsa-at/ffe_industry_load_profiles.json",
    log:
        logs("retrieve_ffe_industry_load_profiles.log"),
    retries: 2
    resources:
        mem_mb=1000,
    message:
        "Retrieving FfE normalized industrial electricity load profiles"
    run:
        data = requests.get(
            "https://api.opendata.ffe.de/opendata",
            params={"id_opendata": 59},
        ).json()
        with open(output[0], "w") as f:
            json.dump(data, f)


if KFZ_BESTAND_AT["source"] in ["primary", "archive"]:

    rule retrieve_kfz_bestand_at:
        input:
            ods=storage(KFZ_BESTAND_AT["url"]),
        output:
            ods=f"{KFZ_BESTAND_AT['folder']}/kfz-bestand_{KFZ_BESTAND_AT['version']}.ods",
        message:
            "Retrieving Statistik Austria vehicle stock data"
        run:
            copy2(input["ods"], output["ods"])


if STATISTIK_AT_REGIONS["source"] in ["primary", "archive"]:

    rule retrieve_statistik_at_regions:
        input:
            ods=storage(STATISTIK_AT_REGIONS["url"]),
        output:
            ods=f"{STATISTIK_AT_REGIONS['folder']}/RegGemVz{STATISTIK_AT_REGIONS['version']}.ods",
        message:
            "Retrieving Statistik Austria municipality register"
        run:
            copy2(input["ods"], output["ods"])


rule retrieve_heat_demand_at:
    input:
        tif=storage(f"{HEAT_DEMAND_DATASET['url']}/{{heatmap_file}}"),
    output:
        tif=f"{HEAT_DEMAND_DATASET['folder']}/{{heatmap_file}}",
    retries: 2
    message:
        "Retrieving Austrian heat demand heatmap {wildcards.heatmap_file}"
    run:
        copy2(input.tif, output.tif)
