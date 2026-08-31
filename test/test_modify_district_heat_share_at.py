from importlib import import_module

import pandas as pd

combine = import_module(
    "scripts.pypsa-at.modify_district_heat_share_at"
).combine_district_heat_share


def test_combine_district_heat_share_updates_austrian_rows():
    district_heat_share = pd.DataFrame(
        {
            "district fraction of node": [0.0, 0.2, 0.3],
            "urban fraction": [0.0, 0.4, 0.5],
        },
        index=["AT111", "AT112", "DE111"],
    )
    urban_fraction_at = pd.DataFrame({"2030": [0.6, 0.7]}, index=["AT111", "AT112"])

    result = combine(district_heat_share, urban_fraction_at, 2030)

    expected = pd.DataFrame(
        {
            "district fraction of node": [0.6, 0.2, 0.3],
            "urban fraction": [0.6, 0.7, 0.5],
        },
        index=["AT111", "AT112", "DE111"],
    )
    pd.testing.assert_frame_equal(result, expected)
