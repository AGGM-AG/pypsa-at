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

rule create_onshore_regions_nuts3:
    input:
        regions=resources_shared("regions_onshore_base_s_{clusters}.geojson"),
        shapes=resources_shared("nuts3_shapes.geojson"),
    output:
        regions_nuts3=resources_shared("regions_onshore_base_s_{clusters}_nuts3.geojson"),
    log:
        logs_shared("create_onshore_regions_nuts3_{clusters}.log"),
    benchmark:
        benchmarks_shared("create_onshore_regions_nuts3_{clusters}")
    threads: 1
    message:
        "Building NUTS3 onshore regions geojson"
    script:
        scripts("pypsa-at/create_onshore_regions_nuts3.py")
