# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT patch to prepare_sector_network rule.
"""


use rule prepare_sector_network as prepare_sector_network_at with:
    input:
        **rules.prepare_sector_network.input,
        powerplants=resources("powerplants_s_{clusters}.csv"),
    params:
        **rules.prepare_sector_network.params,
        consider_efficiency_classes=config_provider(
            "clustering", "consider_efficiency_classes"
        ),
        aggregation_strategies=config_provider("clustering", "aggregation_strategies"),
        exclude_carriers=config_provider("clustering", "exclude_carriers"),


ruleorder: prepare_sector_network_at > prepare_sector_network
