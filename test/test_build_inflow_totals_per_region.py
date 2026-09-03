import build_inflow_totals_per_region as build
import pandas as pd

from mods.constants import TYNDP_TO_PYPSA_LOCATION


def test_process_inflow_per_region_groups_regions_and_technologies():
    inflow_df = pd.DataFrame(
        {
            "Run of River - Year Dependent": [1.0, 2.0, 10.0],
            "Pondage - Year Dependent": [3.0, 4.0, 20.0],
            "Reservoir - Year Dependent": [5.0, 6.0, 30.0],
            "PS Open - Year Dependent": [7.0, 8.0, 40.0],
            "PS Closed - Year Dependent": [9.0, 10.0, 50.0],
        },
        index=["DE00", "DEKF", "FR00"],
    )

    market_info_df = pd.DataFrame(
        {
            "market_node_a": [100, 200, 300],
            "market_node_b": [1, 2, 3],
        },
        index=["DE00", "DEKF", "FR00"],
    )

    result_inflow_df, result_market_info_df = build.process_inflow_per_region(
        inflow_df,
        market_info_df,
        TYNDP_TO_PYPSA_LOCATION,
    )

    expected_inflow_df = pd.DataFrame(
        {
            "ror": [10_000.0, 30_000.0],
            "hydro": [11_000.0, 30_000.0],
            "PHS": [34_000.0, 90_000.0],
        },
        index=["DE", "FR"],
    )

    expected_market_info_df = pd.DataFrame(
        {
            "market_node_a": [300, 300],
            "market_node_b": [3, 3],
        },
        index=["DE", "FR"],
    )

    pd.testing.assert_frame_equal(
        result_inflow_df.sort_index().sort_index(axis=1),
        expected_inflow_df.sort_index().sort_index(axis=1),
    )

    pd.testing.assert_frame_equal(
        result_market_info_df.sort_index(),
        expected_market_info_df.sort_index(),
    )


def test_normalize_ror_normalizes_country_ror_inflow_using_powerplant_capacity():
    inflow_df = pd.DataFrame(
        {
            "ror": [1000.0],
            "hydro": [5000.0],
            "PHS": [2000.0],
        },
        index=["AT"],
    )

    ppl = pd.DataFrame(
        {
            "bus": ["AT01", "AT02", "AT03"],
            "carrier": ["ror", "ror", "hydro"],
            "p_nom": [10.0, 30.0, 100.0],
        }
    )

    market_info_df = pd.DataFrame(
        {
            "Run of River - MW": [100.0],
            "Pondage - MW": [300.0],
        },
        index=["AT"],
    )

    result_inflow, region_to_country_mapping = build.normalize_ror(
        inflow_df,
        ppl,
        market_info_df,
    )

    expected_inflow = pd.Series(
        [100.0, 5000.0, 2000.0],
        index=pd.MultiIndex.from_tuples(
            [
                ("AT", "ror"),
                ("AT", "hydro"),
                ("AT", "PHS"),
            ],
            names=["country", "carrier"],
        ),
        name="inflow",
    )

    pd.testing.assert_series_equal(
        result_inflow.sort_index(),
        expected_inflow.sort_index(),
    )

    assert region_to_country_mapping["AT01"] == "AT"
    assert region_to_country_mapping["AT02"] == "AT"
    assert region_to_country_mapping["AT03"] == "AT"


def test_distribute_inflow_to_powerplants_distributes_by_capacity_share():
    inflow = pd.Series(
        [100.0, 5000.0, 2000.0],
        index=pd.MultiIndex.from_tuples(
            [
                ("AT", "ror"),
                ("AT", "hydro"),
                ("AT", "PHS"),
            ],
            names=["country", "carrier"],
        ),
        name="inflow",
    )

    powerplants_df = pd.DataFrame(
        {
            "bus": ["AT01", "AT02", "AT03", "AT04"],
            "carrier": ["ror", "ror", "hydro", "PHS"],
            "p_nom": [10.0, 30.0, 100.0, 50.0],
        }
    )

    region_to_country_mapping = {
        "AT01": "AT",
        "AT02": "AT",
        "AT03": "AT",
        "AT04": "AT",
    }

    result = build.distribute_inflow_to_powerplants(
        inflow,
        powerplants_df,
        region_to_country_mapping,
    )

    expected = pd.DataFrame(
        {
            "bus": ["AT01", "AT02", "AT03", "AT04"],
            "carrier": ["ror", "ror", "hydro", "PHS"],
            "inflow": [25.0, 75.0, 5000.0, 2000.0],
        }
    )

    result = result.sort_values(["bus", "carrier"]).reset_index(drop=True)
    expected = expected.sort_values(["bus", "carrier"]).reset_index(drop=True)

    pd.testing.assert_frame_equal(result, expected)
