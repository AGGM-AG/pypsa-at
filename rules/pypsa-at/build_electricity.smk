# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT patch to electricity build rules.
"""


use rule process_cost_data as process_cost_data_at with:
    input:
        **{
            **rules.process_cost_data.input,
            "custom_costs": resources("custom_cost_at.csv"),
        },


ruleorder: process_cost_data_at > process_cost_data


# powerplantmatching 0.8.x tags the large German lignite condensing units
# Set="CHP", which the inherited PyPSA-DE powerplants_filter then drops. See
# scripts/pypsa-at/patch_powerplants_set_at.py for the full rationale.
rule patch_powerplants_set_at:
    input:
        powerplants=rules.retrieve_powerplants.output["powerplants"],
    output:
        powerplants=resources_shared("powerplants_set_patched.csv"),
    log:
        logs_shared("patch_powerplants_set_at.log"),
    threads: 1
    resources:
        mem_mb=2000,
    message:
        "Restoring Set=PP on the large German lignite condensing units"
    script:
        scripts("pypsa-at/patch_powerplants_set_at.py")


# The matched table is written to a "-raw" side file and becomes the canonical
# powerplants_s_{clusters}.csv only after overwrite_powerplants_at has applied
# the Austrian corrections, so that every consumer -- add_electricity, the solve
# rules and add_existing_baseyear -- sees the same fleet.
use rule build_powerplants as build_powerplants_at with:
    input:
        **{
            **rules.build_powerplants.input,
            "powerplants": rules.patch_powerplants_set_at.output["powerplants"],
        },
    output:
        resources("powerplants_s_{clusters}-raw.csv"),
    log:
        logs("build_powerplants_s_{clusters}-raw.log"),
    benchmark:
        benchmarks("build_powerplants_s_{clusters}-raw")


rule create_onshore_regions_nuts3:
    input:
        regions=resources_shared("regions_onshore_base_s_{clusters}.geojson"),
        shapes=resources_shared("nuts3_shapes.geojson"),
    output:
        regions_nuts3=resources_shared(
            "regions_onshore_nuts3_base_s_{clusters}.geojson"
        ),
    log:
        logs_shared("create_onshore_regions_nuts3_{clusters}.log"),
    benchmark:
        benchmarks_shared("create_onshore_regions_nuts3_{clusters}")
    threads: 1
    message:
        "Building NUTS3 onshore regions geojson"
    script:
        scripts("pypsa-at/create_onshore_regions_nuts3.py")


use rule determine_availability_matrix as determine_availability_matrix_onwind_nuts3 with:
    input:
        **{
            **rules.determine_availability_matrix.input,
            "regions": resources_shared(
                "regions_onshore_nuts3_base_s_{clusters}.geojson"
            ),
        },
    output:
        nc=resources_shared("availability_matrix_nuts3_{clusters}_{technology}.nc"),
        plot=branch(
            config["atlite"]["plot_availability_matrix"],
            then=resources_shared(
                "availability_matrix_nuts3_{clusters}_{technology}.png"
            ),
        ),
    log:
        logs_shared("determine_availability_matrix_nuts3_{clusters}_{technology}.log"),
    benchmark:
        benchmarks_shared("determine_availability_matrix_nuts3_{clusters}_{technology}")
    wildcard_constraints:
        technology="onwind",
    message:
        "Determining availability matrix for {wildcards.clusters} clusters and {wildcards.technology} technology for nuts3"


use rule build_renewable_profiles as build_renewable_profiles_onwind_nuts3 with:
    input:
        **{
            **rules.build_renewable_profiles.input,
            "availability_matrix": resources_shared(
                "availability_matrix_nuts3_{clusters}_{technology}.nc"
            ),
            "distance_regions": resources_shared(
                "regions_onshore_nuts3_base_s_{clusters}.geojson"
            ),
            "resource_regions": resources_shared(
                "regions_onshore_nuts3_base_s_{clusters}.geojson"  # Input needed by original rule
            ),
        },
    output:
        **{
            **rules.build_renewable_profiles.output,
            "profile": resources_shared("profile_nuts3_{clusters}_{technology}.nc"),
            "class_regions": resources_shared(
                "regions_by_class_nuts3_{clusters}_{technology}.geojson"
            ),
        },
    log:
        logs_shared("build_renewable_profile_nuts3_{clusters}_{technology}.log"),
    benchmark:
        benchmarks_shared("build_renewable_profile_nuts3_{clusters}_{technology}")
    wildcard_constraints:
        technology="onwind",
    message:
        "Building NUTS3 renewable profiles for {wildcards.clusters} clusters and onwind technology"


if config["clustering"]["administrative"]["AT"] == 2:

    use rule build_renewable_profiles as build_renewable_profiles_onwind_nuts2 with:
        output:
            **{
                **rules.build_renewable_profiles.output,
                "profile": resources_shared(
                    "profile_nuts2_{clusters}_{technology}.nc"
                ),
                "class_regions": resources(
                    "regions_by_class_{clusters}_{technology}.geojson"
                ),
            },
        log:
            logs_shared("build_renewable_profile_nuts2_{clusters}_{technology}.log"),
        benchmark:
            benchmarks_shared("build_renewable_profile_nuts2_{clusters}_{technology}")
        wildcard_constraints:
            technology="onwind",
        message:
            "Building NUTS2 renewable profiles for {wildcards.clusters} clusters and onwind technology"

    ruleorder: build_renewable_profiles_onwind_nuts2 > build_renewable_profiles

    rule build_renewable_profiles_onwind_klien:
        input:
            profile_nuts2=resources_shared("profile_nuts2_{clusters}_{technology}.nc"),
            profile_nuts3=resources_shared("profile_nuts3_{clusters}_{technology}.nc"),
            klien_wind=f"{KLIEN_POTENTIALS['folder']}/nuts3_wind.csv",
        output:
            profile=resources("profile_{clusters}_{technology}.nc"),
        log:
            logs("build_renewable_profile_{clusters}_{technology}_klien.log"),
        benchmark:
            benchmarks("build_renewable_profile_{clusters}_{technology}_klien")
        wildcard_constraints:
            technology="onwind",
        message:
            "Applying KLIEN-weighted NUTS3 onwind profiles to NUTS2 output"
        script:
            scripts("pypsa-at/build_renewable_profiles_onwind_klien.py")

    ruleorder: build_renewable_profiles_onwind_klien > build_renewable_profiles
