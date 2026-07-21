# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
from pathlib import Path

import pandas as pd
from pypsa import NetworkCollection

from evals.constants import BusCarrier, DataModel
from evals.fileio import Exporter
from evals.stats import collect_myopic_statistics
from evals.utils import (
    calculate_input_share,
    drop_from_multtindex_by_regex,
    filter_by,
    filter_for_carrier_connected_to,
    get_heat_loss_factor,
    rename_aggregate,
)
from evals.views.common import get_energy_for_heat_production


def view_demand_heat_total(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
    subdir: str | Path = "evaluation",
) -> None:
    """
    Evaluate and export energy required for heat production and generation.

    This function analyzes the energy input mix used for heat production by combining
    data from both link components (for heat production technologies like heat pumps,
    boilers) and generator components (for direct heat generation). Results are grouped
    by bus_carrier rather than carrier to show the input energy carrier mix for each
    type of heat bus. The output includes charts and Excel exports showing the energy
    balance for heat production across different heat technologies and carriers.

    Parameters
    ----------
    result_path
        Path where the evaluation results (plots and data files) will be saved.
    nc
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
        Each network should contain Link and Generator components with energy data.
    config
        Configuration dictionary containing view settings and chart specifications.
        Must include 'view' key with chart type and other plotting parameters.
    subdir
        Subdirectory name within result_path where outputs will be saved.

    Notes
    -----
    The function combines two data sources:
    1. Energy input for heat production from Link components (from get_energy_for_heat_production)
    2. Direct heat supply from Generator components connected to heat buses

    The data is organized by bus_carrier (heat bus types) rather than the usual carrier
    grouping to provide insight into the energy mix feeding different heat systems
    (urban central, urban decentral, rural heat). Index levels are swapped between
    carrier and bus_carrier to facilitate plotting with the specified chart class.
    """
    fed_for_heat = get_energy_for_heat_production(nc)

    generator_supply = collect_myopic_statistics(
        nc,
        "supply",
        comps="Generator",
        bus_carrier=BusCarrier.heat_buses(),
    )
    # swap index levels to keep carrier information during plotting
    generator_supply = generator_supply.swaplevel(
        DataModel.CARRIER, DataModel.BUS_CARRIER
    )
    generator_supply.index.names = DataModel.YEAR_IDX_NAMES

    exporter = Exporter(
        statistics=[fed_for_heat, generator_supply],
        view_config=config["view"],
    )

    exporter.defaults.plot_category = DataModel.BUS_CARRIER
    exporter.defaults.pivot_index = [
        DataModel.YEAR,
        DataModel.LOCATION,
        DataModel.BUS_CARRIER,
    ]

    exporter.export(result_path, subdir=subdir)


def view_demand_heat_system(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
    subdir: str | Path = "evaluation",
) -> None:
    """
    Evaluate and export heat system energy flows with carrier-focused visualization.

    This function analyzes the complete heat system by combining energy input for heat
    production from Link components with direct heat generation from Generator components
    (specifically solar thermal). Unlike view_demand_heat(), this function organizes
    results by carrier rather than bus_carrier to provide insight into the energy
    sources feeding the heat system. Solar heat generation is specifically aggregated
    and labeled for clear identification in the output.

    Parameters
    ----------
    result_path
        Path where the evaluation results (plots and data files) will be saved.
    nc
        Dictionary-like container for PyPSA network objects, typically keyed by year or scenario.
        Each network should contain Link and Generator components with energy data.
    config
        Configuration dictionary containing view settings and chart specifications.
        Must include 'view' key with chart type and other plotting parameters.
    subdir
        Subdirectory name within result_path where outputs will be saved.

    Notes
    -----
    The function combines two data sources:
    1. Energy input for heat production from Link components (from get_energy_for_heat_production)
    2. Solar heat generation from Generator components, aggregated as "solar heat"

    Key differences from view_demand_heat():
    - Results organized by carrier (energy source) rather than bus_carrier (heat bus type)
    - Generator supply specifically renamed to "solar heat" for clarity
    - Index levels swapped to prioritize carrier information during visualization
    - Simplified chart configuration without specific pivot settings

    This view is particularly useful for understanding the overall energy source mix
    feeding the heat system across all heat bus types.
    """
    fed_for_heat = get_energy_for_heat_production(nc)
    # swap index levels to keep carrier information during plotting
    fed_for_heat = fed_for_heat.swaplevel(DataModel.CARRIER, DataModel.BUS_CARRIER)
    fed_for_heat.index.names = DataModel.YEAR_IDX_NAMES

    generator_supply = collect_myopic_statistics(
        nc,
        "supply",
        comps="Generator",
        bus_carrier=BusCarrier.heat_buses(),
    ).pipe(rename_aggregate, "solar heat")

    exporter = Exporter(
        statistics=[fed_for_heat, generator_supply],
        view_config=config["view"],
    )

    exporter.export(result_path, subdir=subdir)


def view_demand_fed_total(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
    subdir: str | Path = "evaluation",
) -> None:
    """
    Evaluate and export total final energy demand (FED) aggregated across all sectors.

    This function calculates and exports final energy demand aggregated across transport,
    industry, agriculture, and household & service sectors. The output is organized by
    bus_carrier (heat bus types and energy carriers) to show the total energy demand
    across the entire energy system without sector-level disaggregation.

    Parameters
    ----------
    result_path
        Path where the evaluation results (plots and data files) will be saved.
    nc
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
        Each network should contain Load, Link, and Generator components with energy data.
    config
        Configuration dictionary containing view settings and chart specifications.
        Must include 'view' key with chart type and other plotting parameters.
    subdir
        Subdirectory name within result_path where outputs will be saved.

    Notes
    -----
    Uses _get_sectoral_fed() to calculate FED with detailed heat mix processing and
    distribution loss accounting. Results are exported with bus_carrier as the primary
    plot category, showing the total energy demand pattern across all carriers without
    sector-level breakdown.

    See Also
    --------
    _get_sectoral_fed : Core calculation function for final energy demand
    view_demand_fed_sectoral : Export FED with sector-level disaggregation
    """
    fed = _get_sectoral_fed(nc)
    exporter = Exporter(statistics=[fed], view_config=config["view"])
    exporter.export(result_path, subdir=subdir)


def view_demand_fed_sectoral(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
    subdir: str | Path = "evaluation",
) -> None:
    """
    Evaluate and export final energy demand (FED) disaggregated by sector.

    This function calculates and exports final energy demand broken down by sector
    (Transport, Industry, Agriculture, HH & Service) with detailed energy carrier
    information. The output includes charts and Excel exports showing energy demand
    with sector-level disaggregation for comprehensive energy system analysis.

    Parameters
    ----------
    result_path
        Path where the evaluation results (plots and data files) will be saved.
    nc
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
        Each network should contain Load, Link, and Generator components with energy data.
    config
        Configuration dictionary containing view settings and chart specifications.
        Must include 'view' key with chart type and other plotting parameters.
    subdir
        Subdirectory name within result_path where outputs will be saved.

    Notes
    -----
    Uses _get_sectoral_fed() to calculate FED with detailed heat mix processing,
    distribution loss accounting, and sector aggregation. Results are exported
    with sector-level disaggregation to show how energy demand is distributed across
    different end-use sectors of the economy.

    See Also
    --------
    _get_sectoral_fed : Core calculation function for final energy demand
    view_demand_fed_total : Export FED aggregated across all sectors
    """
    fed = _get_sectoral_fed(nc)
    exporter = Exporter(statistics=[fed], view_config=config["view"])
    exporter.export(result_path, subdir=subdir)


def apply_heat_mix_to_decentral_heat_buses(
    load: pd.Series, heat_share: pd.Series
) -> pd.Series:
    """
    Apply heat production mix ratios to decentral heat loads to disaggregate by energy carrier.

    This function transforms decentral heat loads (rural and urban decentral heat buses) by
    breaking them down into their constituent energy carrier contributions based on the
    actual heat production mix. Non-decentral loads are passed through unchanged.

    Parameters
    ----------
    load
        Series containing heat load data indexed by year, location, carrier, and bus_carrier.
        Should include loads from both decentral and non-decentral heat buses.
    heat_share
        Series containing the fractional share of each energy carrier in the heat production
        mix for decentral heat buses, indexed by year, location, carrier, and bus_carrier.
        Values should sum to 1.0 for each (year, location) combination.

    Returns
    -------
    :
        Series combining unchanged non-decentral loads with disaggregated decentral loads,
        where each decentral heat load has been multiplied by the heat production mix ratios
        and expanded into separate entries for each contributing energy carrier.

    Notes
    -----
    Decentral heat buses are identified by regex pattern matching for "decentral" or "rural"
    in the index. Each decentral load value is multiplied by all applicable heat share ratios
    to produce a detailed breakdown of the energy carriers feeding that heat demand.
    """
    decentral_heat = load.filter(regex="decentral|rural")

    load = load.drop(decentral_heat.index)

    to_concat = [load]
    for (year, location, carrier), data in decentral_heat.groupby(
        [DataModel.YEAR, DataModel.LOCATION, DataModel.CARRIER]
    ):
        ratios = filter_by(heat_share, year=year, location=location)
        result = data.item() * ratios
        to_concat.append(rename_aggregate(result, carrier))

    return pd.concat(to_concat)


# Cache for _get_sectoral_fed using dict identity as key
_sectoral_fed_cache = {}


def _get_sectoral_fed(nc):
    """
    Calculate final energy demand (FED) across all sectors with detailed energy carrier breakdown.

    This function processes load data from PyPSA networks to calculate final energy demand
    across transport, industry, agriculture, and household & service sectors. It applies
    heat mix calculations for decentral heating systems, accounts for distribution losses
    in central heat, and disaggregates energy carriers based on actual production shares.

    Parameters
    ----------
    nc
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
        Each network should contain Load, Link, and Generator components with energy data.

    Returns
    -------
    :
        Multi-indexed Series containing final energy demand in MWh, indexed by year,
        location, bus_carrier (used as primary category), carrier (energy source),
        and sector. The carrier and bus_carrier levels are swapped to facilitate plotting.
        Includes 'unit' and 'name' attributes.

    Notes
    -----
    The function processes several energy sectors:
    - Transport: Includes shipping, aviation, and land transport (including EVs)
    - Industry: Industrial loads and low-temperature heat, including NH3 production and CC losses
    - Agriculture: Agricultural loads with heat mix applied to decentral heating
    - HH & Service: Household and service loads including building heat and base electricity

    Heat processing:
    - Central heat loads are reduced by distribution losses since these losses are not
      counted as final energy demand
    - Decentral heat buses (rural and urban decentral) use calculated heat mix ratios
      to determine the input energy carrier breakdown
    - Heat mix is calculated separately for decentral systems from both Link components
      (heat production technologies) and Generator components (solar thermal)

    Index level swapping:
    The carrier and bus_carrier index levels are swapped at the end to simplify plotting
    with GroupedBarChart, where bus_carrier becomes the primary grouping dimension.

    Caching:
    Results are cached using the identity (id) of the networks dictionary to avoid
    redundant calculations when the same networks dict is passed multiple times.
    """
    # Check cache using dict identity
    cache_key = id(nc)
    if cache_key in _sectoral_fed_cache:
        return _sectoral_fed_cache[cache_key]

    decentral_heat_bus_carrier = [
        BusCarrier.HEAT_RURAL,
        BusCarrier.HEAT_URBAN_DECENTRAL,
    ]
    # calculate the heat production share per bus_carrier. Cannot use
    # get_energy_for_heat_production() because it calculates for all
    # bus_carrier collectively, and we need to treat central and decentral
    # systems differently.
    decentral_production = (
        collect_myopic_statistics(nc, "energy_balance", comps="Link")
        .drop(["co2", "co2 stored"], level=DataModel.BUS_CARRIER)
        .pipe(drop_from_multtindex_by_regex, "water tanks|water pits")
        .pipe(filter_for_carrier_connected_to, decentral_heat_bus_carrier)
        .pipe(calculate_input_share, decentral_heat_bus_carrier)
        .pipe(rename_aggregate, "heat_mix")
    )
    decentral_production = decentral_production[decentral_production > 0]

    decentral_generation = (
        collect_myopic_statistics(
            nc,
            "supply",
            comps="Generator",
            bus_carrier=decentral_heat_bus_carrier,
        )
        .pipe(rename_aggregate, "heat_mix")
        .pipe(rename_aggregate, "solar heat", level=DataModel.BUS_CARRIER)
    )

    decentral_heat_mix = pd.concat([decentral_production, decentral_generation])

    heat_share = decentral_heat_mix / decentral_heat_mix.groupby(
        [DataModel.YEAR, DataModel.LOCATION]
    ).transform("sum")

    loads = collect_myopic_statistics(nc, "withdrawal", comps="Load")

    # reduce central heat loads by distribution losses. Distribution losses
    # are not metered and do not count as final energy demand
    loss_factor = get_heat_loss_factor(nc)
    central_heat_loads = filter_by(loads, bus_carrier="urban central heat")
    loads.loc[central_heat_loads.index] = central_heat_loads / (1 + loss_factor)

    # transport Loads are final energy
    # FixMe: aviation includes international amounts. International aviation
    #  demands should not be in regional demands.
    transport = loads.filter(regex="transport|shipping|aviation")
    # no need to harmonize V2g:
    # bev_load = filter_by(transport, bus_carrier="EV battery")
    # v2g_demand = collect_myopic_statistics(nc, "withdrawal", comps="Link", bus_carrier="EV battery")
    # bev_charger = collect_myopic_statistics(nc, "supply", comps="Link", bus_carrier="EV battery")
    # bev_charger.loc[("2050", "SE")].item() - v2g_demand.loc[("2050", "SE")].item()
    # bev_load.loc[("2050", "SE")].item()
    # --> they are equal, and we simply use the load

    # agriculture contains final energy Loads and useful energy Loads (heat)
    agriculture = loads.filter(regex="agriculture")
    agriculture = apply_heat_mix_to_decentral_heat_buses(agriculture, heat_share)

    # industry contains FED and useful energy (low-temperature heat for industry)
    industry = loads.filter(regex="industry|NH3")
    industry = apply_heat_mix_to_decentral_heat_buses(industry, heat_share)

    industry_cc = (
        collect_myopic_statistics(nc, "energy_balance", comps="Link")
        .filter(like="for industry CC")
        .drop(["co2", "co2 stored"], level=DataModel.BUS_CARRIER)
        .pipe(rename_aggregate, "CC losses", level=DataModel.BUS_CARRIER)
        .mul(-1)
    )
    # swap levels to preserve carrier as bus_carrier
    industry_cc = industry_cc.swaplevel(DataModel.CARRIER, DataModel.BUS_CARRIER)
    industry_cc.index.names = DataModel.YEAR_IDX_NAMES
    industry = pd.concat([industry, industry_cc])

    # electricity base load contain loads for rail transport and services sector
    base_load = filter_by(loads, carrier="electricity")
    # todo: base load splitting

    # heat for buildings
    heat = filter_by(loads, carrier=BusCarrier.heat_buses())
    # filter by 'carrier' not 'bus_carrier' to prevent capturing agriculture or industry loads
    heat = apply_heat_mix_to_decentral_heat_buses(heat, heat_share)

    fed = pd.concat(
        [
            rename_aggregate(transport, "Transport"),
            rename_aggregate(industry, "Industry"),
            rename_aggregate(agriculture, "Agriculture"),
            rename_aggregate(base_load, "HH & Service"),
            rename_aggregate(heat, "HH & Service"),
        ]
    )
    fed.attrs["unit"] = "MWh"
    fed.attrs["name"] = "FED"

    # swap carrier and bus_carrier to simplify plotting with GroupedBarChart
    fed = fed.swaplevel(DataModel.CARRIER, DataModel.BUS_CARRIER)
    fed.index.names = DataModel.YEAR_IDX_NAMES

    # Cache the result
    _sectoral_fed_cache[cache_key] = fed
    return fed
