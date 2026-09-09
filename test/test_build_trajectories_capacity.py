from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pypsa import Network, NetworkCollection

from mods.constants import HYDRO_CARRIER_MAPPING
from mods.utils import resolve_tyndp_locations
from test.conftest import require_config

AT_ROR_MAX = ("AT", "ror", "Generator-p_nom", "max")


def _reverse_dict(d: dict[Any, Any]) -> dict[Any, list[Any]]:
    rev = defaultdict(list)
    for key, value in d.items():
        rev[value].append(key)
    return dict(rev)


def _uses_klien_ror_corridor(n: Network, year: int) -> bool:
    """
    Whether the AT ror upper bound for ``year`` comes from the KLIEN corridor.

    The base planning horizon always keeps its PEMMDB row.
    """
    enabled = n.meta["mods"]["update_hydro_capacities_AT"]["enable"]
    return enabled and year != min(n.meta["scenario"]["planning_horizons"])


def _is_at_ror_max(df: pd.DataFrame, region: str) -> pd.Series:
    """Mask selecting the AT ror p_nom_max row of a (carrier, variable, sense) frame."""
    at, carrier, variable, sense = AT_ROR_MAX
    return (
        (region == at)
        & (df["carrier"] == carrier)
        & (df["variable"] == variable)
        & (df["sense"] == sense)
    )


def test_build_trajectories_capacity(nc: NetworkCollection) -> None:
    """
    Tests whether the values of the trajectories_{cluster}.csv resource file match the PEMMDB input data.

    The AT ``ror`` upper bound is excluded when it comes from the KLIEN corridor; that
    row is covered by ``test_build_trajectories_klien_ror_at``.
    """
    for year, n in nc.networks.items():
        # resolve the location mapping for the run's clustering configuration
        location_mapping = resolve_tyndp_locations(
            n.meta["clustering"]["administrative"],
            n.meta["mods"]["modify_nuts3_shapes"],
        )
        PYPSA_TO_TYNDP_LOCATIONS = _reverse_dict(location_mapping)
        trajectories = pd.DataFrame.from_dict(n.meta["resources"]["trajectories"])
        powerplants = pd.DataFrame.from_dict(n.meta["resources"]["powerplants"])
        trajectories = trajectories[trajectories["year"] == int(year)]
        input_path = Path(n.meta["resources"]["open_tyndp_hydro"]) / year
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
            # PEMMDB storage volumes are GWh, the network's Store-e_nom is MWh
            is_volume = expected_df["variable"] == "Store-e_nom"
            expected_df.loc[is_volume, "value"] *= 1e3
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
            ]
            if _uses_klien_ror_corridor(n, int(year)):
                expected_df = expected_df[~_is_at_ror_max(expected_df, region)]
                actual = actual[~_is_at_ror_max(actual, region)]
            pd.testing.assert_frame_equal(
                expected_df.reset_index(drop=True),
                actual.reset_index(drop=True),
                check_dtype=False,
            )


def test_build_trajectories_klien_ror_at(nc: NetworkCollection) -> None:
    """
    Tests whether the AT ror upper bound in trajectories_{cluster}.csv matches the KLIEN corridor.

    The corridor is the klien_ror_trajectory_{clusters}.csv resource file built by
    ``build_klien_hydro_trajectory_at``. The base planning horizon keeps its PEMMDB row
    and is therefore not compared.
    """
    require_config(nc, "mods", "update_hydro_capacities_AT", enable=False)
    for year, n in nc.networks.items():
        if not _uses_klien_ror_corridor(n, int(year)):
            continue
        corridor = pd.DataFrame.from_dict(
            n.meta["resources"]["klien_ror_trajectory"]
        ).set_index("year")
        trajectories = pd.DataFrame.from_dict(n.meta["resources"]["trajectories"])
        trajectories = trajectories[trajectories["year"] == int(year)].set_index(
            ["region", "carrier", "variable", "sense"]
        )
        assert int(year) in corridor.index, f"KLIEN corridor has no entry for {year}"
        assert AT_ROR_MAX in trajectories.index, f"AT ror p_nom_max row missing {year}"
        expected = corridor.loc[int(year), "value"]
        actual = trajectories.loc[AT_ROR_MAX, "value"]
        assert actual == pytest.approx(expected), (
            f"AT ror p_nom_max {year}: trajectories {actual} != KLIEN corridor {expected}"
        )
        # the corridor must grow from the calibrated fleet, never shrink it
        assert expected >= corridor.loc[int(year), "brownfield_mw"]


def test_storage_volumes_are_converted_to_mwh():
    from build_capacity_trajectories import convert_storage_volumes_to_mwh

    index = pd.MultiIndex.from_tuples(
        [
            (2030, "AT", "hydro store", "Store-e_nom", "max"),
            (2030, "AT", "hydro discharger", "Link-p_nom", "max"),
        ],
        names=["year", "region", "carrier", "variable", "sense"],
    )
    market_info = pd.Series([769.0, 2787.0], index=index, name="value")

    out = convert_storage_volumes_to_mwh(market_info)

    assert out.iloc[0] == pytest.approx(769_000.0)
    assert out.iloc[1] == pytest.approx(2787.0)
    assert market_info.iloc[0] == pytest.approx(769.0)
