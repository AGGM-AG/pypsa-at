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


use rule build_powerplants as build_powerplants_at with:
    input:
        **{
            **rules.build_powerplants.input,
            "powerplants": rules.patch_powerplants_set_at.output["powerplants"],
        },


ruleorder: build_powerplants_at > build_powerplants


rule create_onshore_regions_nuts3:
    input:
        regions=resources("onshore_regions.geojson"),
        shapes=resources("nuts3_shapes.geojson"),
    output:
        regions_nuts3=resources("onshore_regions_nuts3.geojson"),
    log:
        logs("create_onshore_regions_nuts3.log"),
    benchmark:
        benchmarks("create_onshore_regions_nuts3")
    threads: 1
    message:
        "Building NUTS3 onshore regions geojson"
    script:
        scripts("pypsa-at/create_onshore_regions_nuts3.py")


use rule determine_availability_matrix as determine_availability_matrix_onwind_nuts3 with:
    input:
        **{
            **rules.determine_availability_matrix.input,
            "regions": resources("onshore_regions_nuts3.geojson"),
        },
    output:
        nc=resources("availability_matrix_nuts3_{technology}.nc"),
        plot=branch(
            config["atlite"]["plot_availability_matrix"],
            then=resources("availability_matrix_nuts3_{technology}.png"),
        ),
    log:
        logs("determine_availability_matrix_nuts3_{technology}.log"),
    benchmark:
        benchmarks("determine_availability_matrix_nuts3_{technology}")
    wildcard_constraints:
        technology="onwind",
    message:
        "Determining availability matrix for {wildcards.technology} technology for nuts3"


use rule build_renewable_profiles as build_renewable_profiles_onwind_nuts3 with:
    input:
        **{
            **rules.build_renewable_profiles.input,
            "availability_matrix": resources(
                "availability_matrix_nuts3_{technology}.nc"
            ),
            "distance_regions": resources("onshore_regions_nuts3.geojson"),
            "resource_regions": resources(
                "onshore_regions_nuts3.geojson"  # Input needed by original rule
            ),
        },
    output:
        **{
            **rules.build_renewable_profiles.output,
            "profile": resources("profile_nuts3_{technology}.nc"),
            "class_regions": resources("regions_by_class_nuts3_{technology}.geojson"),
        },
    log:
        logs("build_renewable_profile_nuts3_{technology}.log"),
    benchmark:
        benchmarks("build_renewable_profile_nuts3_{technology}")
    wildcard_constraints:
        technology="onwind",
    message:
        "Building NUTS3 renewable profiles for onwind technology"


def use_klien_onwind(w):
    """Whether the run clusters Austria at NUTS2, where KLIEN weights apply.

    Evaluated per scenario, so runs with different (custom) clusterings can
    share one workflow. ``mods.modify_nuts3_shapes`` AT10* implies NUTS2.
    """
    mode = config_provider("clustering", "mode")(w)
    admin_levels = config_provider("clustering", "administrative")(w)
    return mode == "administrative" and admin_levels.get("AT") == 2


# The upstream onwind profile is written to a "-raw" file. The KLIEN rule
# below turns it into the final profile: KLIEN-weighted NUTS3 profiles for
# Austria at NUTS2, otherwise an unchanged copy.
use rule build_renewable_profiles as build_renewable_profiles_onwind_raw with:
    output:
        **{
            **rules.build_renewable_profiles.output,
            "profile": resources("profile_{technology}-raw.nc"),
            "class_regions": resources("regions_by_class_{technology}.geojson"),
        },
    log:
        logs("build_renewable_profile_{technology}-raw.log"),
    benchmark:
        benchmarks("build_renewable_profile_{technology}-raw")
    wildcard_constraints:
        technology="onwind",
    message:
        "Building raw renewable profiles for onwind technology"


ruleorder: build_renewable_profiles_onwind_raw > build_renewable_profiles


rule build_renewable_profiles_onwind_klien:
    input:
        profile_raw=resources("profile_{technology}-raw.nc"),
        profile_nuts3=branch(
            use_klien_onwind, resources("profile_nuts3_{technology}.nc"), []
        ),
        klien_wind=branch(
            use_klien_onwind, f"{KLIEN_POTENTIALS['folder']}/nuts3_wind.csv", []
        ),
    output:
        profile=resources("profile_{technology}.nc"),
    log:
        logs("build_renewable_profile_{technology}_klien.log"),
    benchmark:
        benchmarks("build_renewable_profile_{technology}_klien")
    wildcard_constraints:
        technology="onwind",
    params:
        apply_klien=use_klien_onwind,
    message:
        "Applying KLIEN-weighted NUTS3 onwind profiles where Austria is at NUTS2"
    script:
        scripts("pypsa-at/build_renewable_profiles_onwind_klien.py")


ruleorder: build_renewable_profiles_onwind_klien > build_renewable_profiles
