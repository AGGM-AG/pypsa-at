# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Build sector rule extensions for AT-specific datasets.
"""


use rule prepare_sector_network as prepare_sector_network_at with:
    input:
        **rules.prepare_sector_network.input,
        **rules.modify_brownfield_gas_network_AT.output,


ruleorder: prepare_sector_network_at > prepare_sector_network
