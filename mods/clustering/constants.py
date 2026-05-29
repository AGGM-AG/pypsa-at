# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Constants for PyPSA-AT custom administrative clustering."""

# Valid clustering configurations and their implied NUTS levels.
VALID_CONFIGURATIONS = ("AT10DE5", "AT10DE16", "AT35DE5", "AT35DE16")

# Single source of truth for the DE5 macro-region groupings.
# Maps each DE5 aggregate code to the DE NUTS1 state codes it contains.
# Consumed by apply_custom_clustering() and by network update functions that
# need to aggregate DE NUTS1 storage data to DE5 resolution.
DE5_GROUPS = {
    "DE1": ("DE1",),  # Baden-Württemberg
    "DE2": ("DE2",),  # Bavaria
    "DE3": ("DE7", "DEB", "DEC", "DEA"),  # Midwest: Hesse, RP, Saarland, NRW
    "DE4": (  # Mideast
        "DE3",  # Berlin
        "DE4",  # Brandenburg
        "DE8",  # MV
        "DED",  # Saxony
        "DEE",  # SA
        "DEG",  # Thuringia
    ),
    "DE5": ("DEF", "DE6", "DE9", "DE5"),  # North: SH, Hamburg, Bremen, Lower Saxony
}


_DE_NUTS1_TO_DE5: dict[str, str] = {
    nuts1: de5 for de5, nuts1_codes in DE5_GROUPS.items() for nuts1 in nuts1_codes
}
