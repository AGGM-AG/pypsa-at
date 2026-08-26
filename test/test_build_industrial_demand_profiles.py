# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""End-to-end test for the industry demand profile builder."""

import importlib
import json
from types import SimpleNamespace

import pandas as pd
import pytest

build = importlib.import_module("scripts.pypsa-at.build_industrial_demand_profiles")


@pytest.fixture()
def snakemake_data(tmp_path):
    snapshots = pd.date_range("2030-01-01", "2030-12-31 23:00", freq="h")

    ratios = pd.DataFrame({("AT", "Electric arc"): {"elec": 1.0}})
    ratios_file = tmp_path / "industry_sector_ratios_2030.csv"
    ratios.to_csv(ratios_file)

    production = pd.DataFrame({"Electric arc": [1_000.0]}, index=["AT0 0"])
    production_file = tmp_path / "industrial_production_2030.csv"
    production.to_csv(production_file)

    ffe_file = tmp_path / "ffe_profiles.json"
    ffe_file.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "internal_id": [1],
                        "values": [1 / len(snapshots)] * len(snapshots),
                    }
                ]
            }
        )
    )

    snapshot_file = tmp_path / "snapshot_weightings.csv"
    pd.DataFrame({"snapshot": snapshots}).to_csv(snapshot_file, index=False)

    snakemake = SimpleNamespace(
        input=SimpleNamespace(
            industry_sector_ratios=[str(ratios_file)],
            industrial_production_per_node=[str(production_file)],
            ffe_profiles=str(ffe_file),
            snapshot_weightings=str(snapshot_file),
        ),
        output=SimpleNamespace(
            industrial_demand_profiles=str(tmp_path / "profiles.csv")
        ),
        params=SimpleNamespace(
            planning_horizons=[2030],
            snapshots={
                "start": "2030-01-01",
                "end": "2030-12-31 23:00",
                "inclusive": "both",
            },
            drop_leap_day=False,
            carrier_mapping={"elec": "industry electricity"},
        ),
    )
    return snakemake


def test_build_industrial_demand_profiles(tmp_path, snakemake_data):
    """Build one profile resource and verify its schema and normalization."""
    build.main(snakemake_data)
    result = pd.read_csv(snakemake_data.output.industrial_demand_profiles)

    assert list(result.columns) == [
        "year",
        "region",
        "carrier",
        "snapshot",
        "value",
    ]
    assert len(result) == 8760
    assert result["year"].eq(2030).all()
    assert result["region"].eq("AT0 0").all()
    assert result["carrier"].eq("industry electricity").all()
    assert result["value"].sum() == pytest.approx(1)
