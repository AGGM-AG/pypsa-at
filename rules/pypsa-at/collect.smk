# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT main rule to run the workflow.
"""


rule all_at:
    default_target: True
    input:
        expand(RESULTS + "test_report.html", run=config["run"]["name"]),
        lambda w: balance_map_paths("interactive", w),
