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


def test_build_trajectories_capacity(nc: NetworkCollection) -> None:
    PYPSA_TO_TYNDP_LOCATIONS = _reverse_dict(TYNDP_TO_PYPSA_LOCATION)
    for year, n in nc.networks.items():
        trajectories = pd.DataFrame.from_dict(n.meta["resources"]["trajectories"])
        powerplants = pd.DataFrame.from_dict(n.meta["resources"]["powerplants"])
        trajectories = trajectories[trajectories["year"] == int(year)]
        input_path = Path(n.meta["resources"]["otyndp_hydro"]) / year
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
            ppl_filtered = powerplants[
                powerplants["bus"].str.startswith(region)
                & powerplants["carrier"].isin(
                    set(expected_df["carrier"].str.split(" ", n=1).str[0])
                )
            ]
            expected_df = expected_df[
                expected_df["carrier"]
                .str.split(" ", n=1)
                .str[0]
                .isin(ppl_filtered["carrier"])
            ].reset_index(drop=True)
            pd.testing.assert_frame_equal(expected_df, actual, check_dtype=False)
