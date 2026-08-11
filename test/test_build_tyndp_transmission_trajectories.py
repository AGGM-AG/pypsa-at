# SPDX-FileCopyrightText: 2025-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Integration test for scripts/pypsa-at/build_tyndp_transmission_trajectories.py."""

import pandas as pd
from build_tyndp_transmission_trajectories import build_tyndp_transmission_trajectories

from mods.constants import TYNDP_TO_PYPSA_LOCATION_TRANSMISSION


def test_build_tyndp_transmission_trajectories_full_pipeline(tmp_path):
    """Full pipeline: read → map → sort → build_trajectories produces correct 4-year NTC table."""
    # --- synthetic elec_reference_grid (sheet "2030") ---
    ref_grid_df = pd.DataFrame(
        {
            "Border": ["AT00-DE00", "AT00-CH00"],
            "Summary Direction 1": [3000.0, 1200.0],
            "Summary Direction 2": [2800.0, 1100.0],
        }
    )
    ref_grid_path = tmp_path / "ReferenceGrid_Electricity.xlsx"
    with pd.ExcelWriter(ref_grid_path, engine="openpyxl") as writer:
        ref_grid_df.to_excel(writer, sheet_name="2030", index=False)

    # --- synthetic invest_grid (sheet "Electricity") ---
    invest_df = pd.DataFrame(
        {
            "FROM NODE": ["AT00", "AT00", "AT00"],
            "TO NODE": ["DE00", "CH00", "DE00"],
            "BORDER": [
                "AT00-DE00 Real Project 1",
                "AT00-CH00 Real Project 2",
                "AT00-DE00 Concept Project 3",
            ],
            "DIRECT CAPACITY INCREASE (MW)": [500.0, 200.0, 300.0],
            "INDIRECT CAPACITY INCREASE (MW)": [400.0, 150.0, 250.0],
        }
    )
    invest_grid_path = tmp_path / "GRID.xlsx"
    with pd.ExcelWriter(invest_grid_path, engine="openpyxl") as writer:
        invest_df.to_excel(writer, sheet_name="Electricity", index=False)

    result = build_tyndp_transmission_trajectories(
        ref_grid_path, invest_grid_path, TYNDP_TO_PYPSA_LOCATION_TRANSMISSION
    )

    expected = pd.DataFrame(
        [
            ("AT", "CH", 1200.0, 1100.0, 2025),
            ("AT", "DE", 3000.0, 2800.0, 2025),
            ("AT", "CH", 1200.0, 1100.0, 2030),
            ("AT", "DE", 3000.0, 2800.0, 2030),
            ("AT", "CH", 1400.0, 1250.0, 2040),
            ("AT", "DE", 3500.0, 3200.0, 2040),
            ("AT", "CH", 1400.0, 1250.0, 2050),
            ("AT", "DE", 3800.0, 3450.0, 2050),
        ],
        columns=[
            "from_node",
            "to_node",
            "direct_capacity",
            "indirect_capacity",
            "year",
        ],
    )
    expected = expected.set_index(["from_node", "to_node"])

    pd.testing.assert_frame_equal(result, expected)
