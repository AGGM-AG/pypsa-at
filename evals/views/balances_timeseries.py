# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
from pathlib import Path

from pypsa import NetworkCollection

from evals.views.common import (
    simple_residual_load,
    simple_timeseries,
)


def view_timeseries_electricity(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
) -> None:
    """
    Evaluate and export time series data for electricity supply, demand, and trade.

    This function generates hourly or sub-hourly time series showing electricity production
    from various sources (renewables, thermal plants, storage) and consumption across
    different sectors (industry, transport, heat, electrolysis). It preserves temporal
    resolution to enable analysis of system operation patterns, peak demand, and renewable
    generation variability. The function delegates to simple_timeseries for data collection
    and export.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    nc
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        storage_links, chart type, and export parameters.

    Notes
    -----
    Time series data is useful for analyzing hourly patterns, ramping requirements,
    storage cycling, and the integration of variable renewable energy sources.
    Net trade combines foreign and domestic imports/exports into a single saldo value.
    """
    simple_timeseries(nc, config, result_path)


def view_timeseries_hydrogen(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
) -> None:
    """
    Evaluate and export time series data for hydrogen supply, demand, and trade.

    This function generates hourly or sub-hourly time series showing hydrogen production
    from electrolysis, steam methane reforming, and other sources, along with hydrogen
    consumption in fuel cells, industrial processes, synthetic fuel production, and other
    applications. The temporal resolution enables analysis of hydrogen system operation,
    including electrolyzer operation patterns, storage cycling, and the coupling between
    electricity and hydrogen systems. The function delegates to simple_timeseries for
    data collection and export.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    nc
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        storage_links, chart type, and export parameters.

    Notes
    -----
    Time series data reveals the coupling between hydrogen and electricity sectors,
    particularly the role of electrolyzers in providing demand flexibility and the
    operation of hydrogen storage for seasonal energy shifting.
    """
    simple_timeseries(nc, config, result_path)


def view_timeseries_methane(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
) -> None:
    """
    Evaluate and export time series data for methane supply, demand, and trade.

    This function generates hourly or sub-hourly time series showing methane (natural gas)
    supply from production, imports, biogas upgrading, and methanation processes, along
    with methane consumption in gas boilers, combined heat and power plants, gas turbines,
    steam methane reforming, and industrial applications. The temporal resolution enables
    analysis of gas system operation, storage cycling, and the seasonal patterns of gas
    demand for heating. The function delegates to simple_timeseries for data collection
    and export.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    nc
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        storage_links, chart type, and export parameters.

    Notes
    -----
    Time series data shows the seasonal nature of gas demand, particularly for heating,
    and the role of gas storage in balancing supply and demand. It also reveals the
    transition from fossil natural gas to renewable and synthetic methane sources.
    """
    simple_timeseries(nc, config, result_path)


def view_timeseries_carbon(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
) -> None:
    """
    Evaluate and export time series data for carbon emissions, capture, and sequestration.

    This function generates hourly or sub-hourly time series showing CO2 emissions from
    combustion processes (power plants, boilers, industry), CO2 capture from direct air
    capture and carbon capture systems, and CO2 sequestration or storage. The temporal
    resolution enables analysis of emission patterns, the operation of carbon capture
    facilities, and the timing of CO2 storage operations. The function delegates to
    simple_timeseries for data collection and export.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    nc
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        storage_links, chart type, and export parameters.

    Notes
    -----
    Time series data reveals the temporal patterns of CO2 emissions and the operation
    of carbon management infrastructure. It shows how emissions vary with electricity
    and heat demand, and how carbon capture facilities operate to manage system-wide
    emissions constraints.
    """
    simple_timeseries(nc, config, result_path)


def view_timeseries_residual_load(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
) -> None:
    """
    Evaluate and export time series data for the residual load

    This function generates hourly time series showing residual load calculated
    as the load on the respective AC bus (i.e. all withdrawal except electricity
    transmission and storage) + tranmission losses - electricity from fluctuating
    renewable sources (e.g. wind, solar). The function delegates to
    simple_residual_load for data collection and export.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    nc
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        storage_links, chart type, and export parameters.

    """
    simple_residual_load(nc, config, result_path)


def view_residual_load_duration_curve(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
) -> None:
    """
    Evaluate and export duration curve data for the residual load

    This function generates a hourly duration curve showing residual load calculated
    as the load on the respective AC bus (i.e. all withdrawal except electricity
    transmission and storage) + tranmission losses - electricity from fluctuating
    renewable sources (e.g. wind, solar). The function delegates to
    simple_residual_load for data collection and export.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    nc
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        storage_links, chart type, and export parameters.

    """
    simple_residual_load(nc, config, result_path)
