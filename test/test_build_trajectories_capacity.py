from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from pypsa import NetworkCollection

from mods.constants import HYDRO_CARRIER_MAPPING, TYNDP_TO_PYPSA_LOCATION


def _reverse_dict(d: dict[Any, Any]) -> dict[Any, list[Any]]:
    rev = defaultdict(list)
    for key, value in d.items():
        rev[value].append(key)
    return dict(rev)


def test_build_trajectories_capacity(nc: NetworkCollection, project_root: Path) -> None:
    PYPSA_TO_TYNDP_LOCATIONS = _reverse_dict(TYNDP_TO_PYPSA_LOCATION)
    for year, n in nc.networks.items():
        prefix = n.meta["run"]["prefix"]
        run_name = n.meta["run"]["name"][0]
        trajectories_path = (
            project_root / "resources" / prefix / run_name / "trajectories.csv"
        )
        trajectories = pd.read_csv(trajectories_path)
        trajectories = trajectories[trajectories["year"] == int(year)]

        input_path = (
            project_root
            / "data"
            / "tyndp"
            / n.meta["data"]["tyndp"]["source"]
            / "2024"
            / "Hydro Inflows"
            / year
        )
        for (region,), actual in trajectories.groupby(["region"]):
            if (actual["value"] == 0).all():
                continue
            actual = actual[["carrier", "variable", "sense", "value"]].reset_index(
                drop=True
            )

            input_files = []
            for tyndp_region in PYPSA_TO_TYNDP_LOCATIONS[region]:
                input_files = [
                    *input_files,
                    *list(
                        input_path.glob(
                            f"PEMMDB_{tyndp_region}*_Hydro_Inflows_{year}.xlsx"
                        )
                    ),
                ]
            if len(input_files) == 0:
                raise ValueError(
                    f"Found no input data file for region {region} and year {year}"
                )
            market_data_list = []
            for file in input_files:
                market_data_list.append(
                    pd.read_excel(
                        file, sheet_name="MarketNodeInfo", header=5, index_col=0
                    )
                )
            expected_df = sum(market_data_list)
            expected_df = expected_df.reset_index()
            expected_df.columns = ["technology", "value"]
            expected_df[["carrier", "variable", "sense"]] = pd.DataFrame(
                expected_df["technology"].map(HYDRO_CARRIER_MAPPING).tolist(),
                index=expected_df.index,
            )
            expected_df = expected_df.dropna()
            expected_df = (
                expected_df.groupby(["carrier", "variable", "sense"])["value"]
                .sum()
                .abs()
                .reset_index()
            )
            pd.testing.assert_frame_equal(expected_df, actual, check_dtype=False)
