import importlib
from types import SimpleNamespace

import pandas as pd
import pytest
import xarray as xr

from mods.constants import UNITS

transport = importlib.import_module("scripts.pypsa-at.patch_transport_demand_at")


@pytest.fixture
def sector_options():
    """Minimal options required by transform_nea_to_km and define_spatial."""
    return {
        # Required by transform_nea_to_km
        "transport_ice_efficiency": 16.0712,
        "transport_electric_efficiency": 53.19,
        "transport_heating_deadband_lower": 15.0,
        "transport_heating_deadband_upper": 20.0,
        "ICE_lower_degree_factor": 0.0,
        "ICE_upper_degree_factor": 0.0,
        "EV_lower_degree_factor": 0.0,
        "EV_upper_degree_factor": 0.0,
        # Required by define_spatial
        "biomass_transport": False,
        "co2_spatial": False,
        "co2_network": False,
        "gas_network": False,
        "regional_gas_demand": False,
        "ammonia": False,
        "methanol": {
            "regional_methanol_demand": False,
        },
        "regional_oil_demand": False,
        "regional_coal_demand": False,
    }


@pytest.fixture
def model_input_files(tmp_path):
    population = pd.DataFrame(
        {
            "population": [1000, 2000],
        },
        index=pd.Index(
            ["AT111", "AT121"],
            name="region",
        ),
    )
    population_file = tmp_path / "clustered_pop_layout.csv"
    population.to_csv(population_file)

    # Temperatures are inside the deadband, so no temperature correction
    # is applied.
    temperature = xr.DataArray(
        [
            [17.0, 18.0],
            [18.0, 19.0],
        ],
        coords={
            "timestamp": pd.to_datetime(
                [
                    "2020-01-01 00:00",
                    "2020-01-01 01:00",
                ]
            ),
            "region": ["AT111", "AT121"],
        },
        dims=["timestamp", "region"],
    )
    temperature_file = tmp_path / "temperature.nc"
    temperature.to_netcdf(temperature_file)

    return population_file, temperature_file


@pytest.fixture
def snakemake_for_transformation(
    model_input_files,
    sector_options,
):
    population_file, temperature_file = model_input_files

    return SimpleNamespace(
        input=SimpleNamespace(
            clustered_pop_layout=population_file,
            temp_air_total=temperature_file,
        ),
        params=SimpleNamespace(
            sector=sector_options,
        ),
    )


@pytest.fixture
def transport_timeseries():
    return pd.DataFrame(
        {
            "AT111": [10.0, 20.0],
            "AT112": [30.0, 40.0],
            "DE111": [5.0, 15.0],
        },
        index=pd.DatetimeIndex(
            [
                "2020-01-01 00:00",
                "2020-01-01 01:00",
            ],
            name="timestamp",
        ),
    )


@pytest.fixture
def transport_demand_long(transport_timeseries):
    return transport.transform_timeseries_to_long(transport_timeseries)


def test_transform_timeseries_to_long(transport_timeseries):
    expected = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2020-01-01 00:00",
                    "2020-01-01 00:00",
                    "2020-01-01 00:00",
                    "2020-01-01 01:00",
                    "2020-01-01 01:00",
                    "2020-01-01 01:00",
                ]
            ),
            "region": [
                "AT111",
                "AT112",
                "DE111",
                "AT111",
                "AT112",
                "DE111",
            ],
            "value": [
                10.0,
                30.0,
                5.0,
                20.0,
                40.0,
                15.0,
            ],
            "NUTS-2 Code": [
                "AT11",
                "AT11",
                "DE11",
                "AT11",
                "AT11",
                "DE11",
            ],
        }
    )

    result = transport.transform_timeseries_to_long(transport_timeseries)

    pd.testing.assert_frame_equal(result, expected)


def test_filter_nea():
    nea_input = pd.DataFrame(
        {
            "year": [
                2019,
                2020,
                2020,
                2020,
                2020,
                2020,
                2021,
                2020,
            ],
            "Bereich": [
                "Sonstiger Landverkehr",
                "Sonstiger Landverkehr",
                "Sonstiger Landverkehr",
                "Sonstiger Landverkehr",
                "Anderer Bereich",
                "Sonstiger Landverkehr",
                "Sonstiger Landverkehr",
                "Sonstiger Landverkehr",
            ],
            "Nutzenergiekategorie": [
                "Verkehr",
                "Verkehr",
                "Verkehr",
                "Verkehr",
                "Verkehr",
                "Andere Kategorie",
                "Verkehr",
                "Verkehr",
            ],
            "NUTS-2 Code": [
                "AT11",
                "AT11",
                "AT11",
                "AT12",
                "AT12",
                "AT12",
                "AT11",
                "AT99",
            ],
            "Energieträger": [
                "Benzin",
                "Benzin",
                "Benzin",
                "Elektrische Energie",
                "Diesel",
                "Diesel",
                "Benzin",
                "Diesel",
            ],
            "value_TWh": [
                9.0,
                0.001,
                0.002,
                0.004,
                10.0,
                10.0,
                20.0,
                0.0,
            ],
        }
    )

    expected = pd.DataFrame(
        {
            "NUTS-2 Code": ["AT11", "AT12"],
            "Energieträger": [
                "Benzin",
                "Elektrische Energie",
            ],
            "value": [
                0.003 * UNITS["TWh"],
                0.004 * UNITS["TWh"],
            ],
        }
    )

    result = transport.filter_nea(
        nea_input,
        base_year=2020,
        source_years={2020: 2020},
    )

    pd.testing.assert_frame_equal(result, expected)


def test_filter_nea_missing_source_year():
    nea_input = pd.DataFrame(
        {
            "year": [2020],
            "Bereich": ["Sonstiger Landverkehr"],
            "Nutzenergiekategorie": ["Verkehr"],
            "NUTS-2 Code": ["AT11"],
            "Energieträger": ["Benzin"],
            "value_TWh": [1.0],
        }
    )

    with pytest.raises(ValueError, match="No NEA source year configured"):
        transport.filter_nea(nea_input, base_year=2030, source_years={2020: 2020})


def test_filter_nea_no_data_for_source_year():
    nea_input = pd.DataFrame(
        {
            "year": [2020],
            "Bereich": ["Sonstiger Landverkehr"],
            "Nutzenergiekategorie": ["Verkehr"],
            "NUTS-2 Code": ["AT11"],
            "Energieträger": ["Benzin"],
            "value_TWh": [1.0],
        }
    )

    with pytest.raises(ValueError, match="no road transport demand"):
        transport.filter_nea(nea_input, base_year=2020, source_years={2020: 2018})


def test_transform_nea_to_km(snakemake_for_transformation):
    # This covers every carrier in NEA_TO_TECHNOLOGY_MAPPING.
    nea_input = pd.DataFrame(
        {
            "NUTS-2 Code": [
                "AT11",
                "AT11",
                "AT11",
                "AT11",
                "AT12",
                "AT12",
            ],
            "Energieträger": [
                "Benzin",
                "Biogene Brenn- und Treibstoffe",
                "Diesel",
                "Elektrische Energie",
                "Erdgas",
                "Flüssiggas",
            ],
            "value": [
                10.0,
                20.0,
                30.0,
                40.0,
                50.0,
                60.0,
            ],
        }
    )

    # Both configured base efficiencies are 1.0 and all temperatures are
    # inside the deadband. Therefore only aggregation changes the values.
    expected = pd.DataFrame(
        {
            "NUTS-2 Code": ["AT11", "AT12"],
            "value": [
                60.0 * 16.0712 + 40.0 * 53.19,
                110.0 * 16.0712,
            ],
        }
    )

    result = transport.transform_nea_to_km(
        snakemake_for_transformation,
        nea_input.copy(),
    )

    pd.testing.assert_frame_equal(result, expected)


def test_transform_nea_to_km_unmatched_region(snakemake_for_transformation):
    nea_input = pd.DataFrame(
        {
            "NUTS-2 Code": ["AT99"],
            "Energieträger": ["Benzin"],
            "value": [10.0],
        }
    )

    with pytest.raises(ValueError, match="AT99"):
        transport.transform_nea_to_km(
            snakemake_for_transformation,
            nea_input.copy(),
        )


def test_apply_nea(transport_demand_long):
    nea_input = pd.DataFrame(
        {
            "NUTS-2 Code": ["AT11"],
            "value": [200.0],
        }
    )

    # Original AT11 total:
    # 10 + 30 + 20 + 40 = 100
    #
    # The new target is 200, so every AT11 value is multiplied by 2.
    # DE11 has no NEA value and remains unchanged.
    expected = pd.DataFrame(
        {
            "AT111": [20.0, 40.0],
            "AT112": [60.0, 80.0],
            "DE111": [5.0, 15.0],
        },
        index=pd.DatetimeIndex(
            [
                "2020-01-01 00:00",
                "2020-01-01 01:00",
            ],
            name="timestamp",
        ),
    )
    expected.columns.name = "region"

    result = transport.apply_nea(
        transport_demand_long.copy(),
        nea_input,
    )

    pd.testing.assert_frame_equal(result, expected)


def test_apply_nea_zero_baseline():
    zero_demand = pd.DataFrame(
        {
            "AT111": [0.0, 0.0],
        },
        index=pd.DatetimeIndex(
            ["2020-01-01 00:00", "2020-01-01 01:00"],
            name="timestamp",
        ),
    )
    transport_demand_long = transport.transform_timeseries_to_long(zero_demand)
    nea_input = pd.DataFrame(
        {
            "NUTS-2 Code": ["AT11"],
            "value": [200.0],
        }
    )

    with pytest.raises(ValueError, match="zero"):
        transport.apply_nea(transport_demand_long, nea_input)


def test_main(
    tmp_path,
    model_input_files,
    sector_options,
):
    population_file, temperature_file = model_input_files

    transport_demand_input = pd.DataFrame(
        {
            "AT111": [10.0, 30.0],
            "AT121": [20.0, 40.0],
        },
        index=pd.DatetimeIndex(
            [
                "2020-01-01 00:00",
                "2020-01-01 01:00",
            ],
            name="timestamp",
        ),
    )
    transport_demand_file = tmp_path / "transport_demand.csv"
    transport_demand_input.to_csv(transport_demand_file)

    nea_input = pd.DataFrame(
        {
            "year": [2020, 2020],
            "Bereich": [
                "Sonstiger Landverkehr",
                "Sonstiger Landverkehr",
            ],
            "Nutzenergiekategorie": [
                "Verkehr",
                "Verkehr",
            ],
            "NUTS-2 Code": ["AT11", "AT12"],
            "Energieträger": [
                "Benzin",
                "Elektrische Energie",
            ],
            "value_TWh": [
                100.0 / UNITS["TWh"],
                60.0 / UNITS["TWh"],
            ],
        }
    )
    nea_file = tmp_path / "nea.csv"
    nea_input.to_csv(nea_file, index=False)

    output_file = tmp_path / "transport_demand_patched.csv"

    snakemake = SimpleNamespace(
        input=SimpleNamespace(
            transport_demand=transport_demand_file,
            nea_at=nea_file,
            clustered_pop_layout=population_file,
            temp_air_total=temperature_file,
        ),
        params=SimpleNamespace(
            planning_horizons=[2020],
            source_years={2020: 2020},
            sector=sector_options,
        ),
        output=SimpleNamespace(
            transport_demand_patched=output_file,
        ),
    )

    # AT11 changes from a total of 40 to 100:
    # [10, 30] -> [25, 75]
    #
    # AT12 already has the requested total of 60.
    expected = pd.DataFrame(
        {
            "AT111": [401.78, 1205.34],
            "AT121": [1063.79, 2127.59],
        },
        index=pd.DatetimeIndex(
            [
                "2020-01-01 00:00",
                "2020-01-01 01:00",
            ],
            name="timestamp",
        ),
    )

    transport.main(snakemake)

    result = pd.read_csv(
        output_file,
        index_col=0,
        parse_dates=True,
    )

    pd.testing.assert_frame_equal(
        result,
        expected,
        check_freq=False,
    )
