from logging import getLogger
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from pypsa import Network
from snakemake.script import Snakemake

from scripts.add_electricity import add_missing_carriers, load_and_aggregate_powerplants

logger = getLogger(__name__)


def process_hydro(n: Network, snakemake: Snakemake, costs: pd.DataFrame):
    """
    Entry point for all hydro related mods

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, and config.
    costs
        Processed cost DataFrame for the current planning horizon.

    Returns
    -------
    :
        Modifies the network in place.
    """
    ppl = load_and_aggregate_powerplants(
        snakemake.input.powerplants,
        costs,
        snakemake.params.consider_efficiency_classes,
        snakemake.params.aggregation_strategies,
        snakemake.params.exclude_carriers,
    )
    add_phs_hydro(n, snakemake, costs, ppl)
    patch_inflows(n, snakemake, ppl)


def add_phs_hydro(
    n: Network, snakemake: Snakemake, costs: pd.DataFrame, ppl: pd.DataFrame
):
    """
    Add PHS components as links, bus, store and generator.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, and config.
    costs
        Processed cost DataFrame for the current planning horizon.
    ppl
        Aggregated powerplants data

    Returns
    -------
    :
        Modifies the network in place.
    """
    phs = ppl.query('carrier == "PHS"')
    hydro = ppl.query('carrier == "hydro"')
    p = snakemake.params.renewable["hydro"].copy()
    renewable_carriers = set(snakemake.params.electricity["renewable_carriers"])
    carriers = p.pop("carriers", [])
    year = int(snakemake.wildcards.planning_horizons)
    is_base_year = year == min(snakemake.params.planning_horizons)

    if "hydro" in renewable_carriers:
        if "PHS" in carriers and not phs.empty:
            # fill missing max hours to params value and
            # assume no natural inflow due to lack of data
            max_hours = p["PHS_max_hours"]
            phs = phs.replace({"max_hours": {0: max_hours, np.nan: max_hours}})
            add_missing_carriers(
                n, ["PHS charger", "PHS discharger", "PHS store", "PHS inflow"]
            )

            n.add(
                "Bus",
                phs.index + " bus",
                carrier="PHS",
                location=n.buses.loc[phs["bus"], "location"].values,
                unit="MWh_el",
            )

            phs_pump = phs.copy()
            phs_pump.index += " charger"

            phs_turbine = phs.copy()
            phs_turbine.index += " discharger"

            phs_store = phs.copy()
            phs_store.index += " store"

            n.add(
                "Link",
                phs_pump.index,
                carrier="PHS charger",
                bus0=phs_pump["bus"],
                bus1=phs.index + " bus",
                p_nom_min=phs_pump["p_nom"] if is_base_year else 0,
                p_nom_extendable=True,
                lifetime=100,
                capital_cost=costs.at["PHS", "capital_cost"] / 2,
                onight_cost=costs.at["PHS", "investment"] / 2,
                efficiency=np.sqrt(costs.at["PHS", "efficiency"]),
            )

            n.add(
                "Link",
                phs_turbine.index,
                carrier="PHS discharger",
                bus0=phs.index + " bus",
                bus1=phs_turbine["bus"],
                p_nom_min=(
                    phs_turbine["p_nom"] / np.sqrt(costs.at["PHS", "efficiency"])
                )
                if is_base_year
                else 0,
                p_nom_extendable=True,
                lifetime=100,
                capital_cost=costs.at["PHS", "capital_cost"]
                * np.sqrt(costs.at["PHS", "efficiency"])
                / 2,
                onight_cost=costs.at["PHS", "investment"]
                * np.sqrt(costs.at["PHS", "efficiency"])
                / 2,
                efficiency=np.sqrt(costs.at["PHS", "efficiency"]),
            )

            n.add(
                "Store",
                phs_store.index,
                carrier="PHS store",
                bus=phs.index + " bus",
                e_nom_min=(phs_store["p_nom"] * phs_store["max_hours"])
                if is_base_year
                else 0,
                e_nom_extendable=True,
                lifetime=100,
                capital_cost=costs.at["Pumped-Storage-Hydro-store", "capital_cost"],
                e_cyclic=True,
            )

            n.add(
                "Generator",
                phs.index + " inflow",
                carrier="PHS inflow",
                bus=phs.index + " bus",
                p_nom=0,
                p_nom_extendable=False,
            )

        if "hydro" in carriers and not hydro.empty:
            hydro_max_hours = p.get("hydro_max_hours")
            max_hours = p["PHS_max_hours"]
            if snakemake.input.hydro_capacities is None:
                raise ValueError("No path for hydro capacities given.")

            hydro_stats = pd.read_csv(
                snakemake.input.hydro_capacities,
                comment="#",
                na_values="-",
                index_col=0,
            )
            e_target = hydro_stats["E_store[TWh]"].clip(lower=0.2) * 1e6
            e_installed = hydro.eval("p_nom * max_hours").groupby(hydro.country).sum()
            e_missing = e_target - e_installed
            missing_mh_i = hydro.query("max_hours.isnull() or max_hours == 0").index
            # some countries may have missing storage capacity but only one plant
            # which needs to be scaled to the target storage capacity
            missing_mh_single_i = hydro.index[
                ~hydro.country.duplicated()
                & hydro.country.isin(e_missing.dropna().index)
            ]
            missing_mh_i = missing_mh_i.union(missing_mh_single_i)

            if hydro_max_hours == "energy_capacity_totals_by_country":
                # watch out some p_nom values like IE's are totally underrepresented
                max_hours_country = (
                    e_missing / hydro.loc[missing_mh_i].groupby("country").p_nom.sum()
                )

            elif hydro_max_hours == "estimate_by_large_installations":
                max_hours_country = (
                    hydro_stats["E_store[TWh]"]
                    * 1e3
                    / hydro_stats["p_nom_discharge[GW]"]
                )
            else:
                raise ValueError(f"Unknown hydro_max_hours method: {hydro_max_hours}")

            max_hours_country.clip(0, inplace=True)

            missing_countries = pd.Index(hydro["country"].unique()).difference(
                max_hours_country.dropna().index
            )
            if not missing_countries.empty:
                logger.warning(
                    f"Assuming max_hours=6 for hydro reservoirs in the countries: {', '.join(missing_countries)}"
                )
            hydro_max_hours = hydro.max_hours.where(
                (hydro.max_hours > 0) & ~hydro.index.isin(missing_mh_single_i),
                hydro.country.map(max_hours_country),
            ).fillna(max_hours)

            add_missing_carriers(n, ["hydro discharger", "hydro store", "hydro inflow"])

            n.add(
                "Bus",
                hydro.index + " bus",
                carrier="hydro",
                location=n.buses.loc[hydro["bus"], "location"].values,
                unit="MWh_el",
            )

            hydro_turbine = hydro.copy()
            hydro_turbine.index += " discharger"

            hydro_store = hydro.copy()
            hydro_store.index += " store"

            n.add(
                "Link",
                hydro_turbine.index,
                carrier="hydro discharger",
                bus0=hydro.index + " bus",
                bus1=hydro_turbine["bus"],
                p_nom_min=hydro_turbine["p_nom"] if is_base_year else 0,
                p_nom_extendable=True,
                lifetime=100,
                capital_cost=costs.at["PHS", "capital_cost"] / 2,
                onight_cost=costs.at["PHS", "investment"] / 2,
                marginal_cost=costs.at["hydro", "marginal_cost"],
                efficiency=costs.at["hydro", "efficiency"],
            )

            n.add(
                "Store",
                hydro_store.index,
                carrier="hydro store",
                bus=hydro.index + " bus",
                e_nom_min=(hydro_store["p_nom"] * hydro_max_hours.values)
                if is_base_year
                else 0,
                e_nom_extendable=True,
                lifetime=100,
                capital_cost=costs.at["Pumped-Storage-Hydro-store", "capital_cost"],
                onight_cost=costs.at["Pumped-Storage-Hydro-store", "investment"],
                e_cyclic=True,
            )

            n.add(
                "Generator",
                hydro.index + " inflow",
                carrier="hydro inflow",
                bus=hydro.index + " bus",
                p_nom=0,
                p_nom_extendable=False,
            )

        if "ror" in carriers:
            ror_idx = n.generators.query('carrier == "ror"').index
            n.generators.loc[ror_idx, "p_nom_min"] = (
                n.generators.loc[ror_idx, "p_nom"] if is_base_year else 0
            )
            n.generators.loc[ror_idx, "p_nom_extendable"] = True
            n.generators.loc[ror_idx, "lifetime"] = 100


def _modify_inflow_snapshots(n: Network, inflow: xr.DataArray) -> xr.DataArray:
    """
    Aggregate inflow timeseries for the snapshots in the network.

    Parameters
    ----------
    n
       The pre-network.
    inflow
        The inflow DataArray

    Returns
    -------
    :
        The aggregated inflow DataArray
    """
    time = pd.DatetimeIndex(inflow["time"].values)

    ending_snapshot = time[-1] + pd.Timedelta(hours=1)
    snapshots = n.snapshots.copy()
    snapshots = snapshots.append(pd.DatetimeIndex([ending_snapshot]))

    time_bins = pd.cut(time, bins=snapshots, labels=snapshots[:-1], right=False)

    snapshot_groups = xr.DataArray(
        time_bins, dims="time", coords={"time": inflow["time"]}, name="snapshot"
    )
    inflow = inflow.groupby(snapshot_groups).mean(dim="time")
    return inflow


def _redistribute_peaks(
    df: pd.DataFrame, upper: float = 1, lower: float = 0, eps: float = 0.01
) -> pd.DataFrame:
    """
    Redistribute peak values (column-wise) in a dataframe

    Parameters
    ----------
    df
        The DataFrame to modify
    upper
        The upper limit to cap
    lower
        The lower limit to cap
    eps
        Values at upper + eps are just capped and not redistributed.

    Returns
    -------
    :
        The modified DataFrame
    """
    df = df.copy()
    weights = df / df.sum()
    diff = df - df.clip(lower, upper)
    max_diff = diff.sum().max()
    while max_diff > eps:
        df = df.clip(lower, upper) + diff.sum() * weights
        diff = df - df.clip(lower, upper)
        max_diff = diff.sum().max()
    df = df.clip(lower, upper)
    return df


def _patch_component_inflows(
    n: Network,
    inflow: xr.DataArray,
    inflow_carrier: str,
    model_carrier: str,
) -> tuple[pd.Index, pd.DataFrame]:
    """
    Patch inflow values for a given carrier.

    Parameters
    ----------
    n
        The pypsa network to patch
    inflow
        Timeseries of inflow values for all carriers
    inflow_carrier
        Name of the carrier in the inflow DataArray
    model_carrier
        Name of the carrier in the model

    Returns
    -------
    :
        Return a tuple of the changed index and inflows for the carrier.
    """
    component_name = "generators"
    idx = (
        n.components[component_name].static.query(f'carrier == "{model_carrier}"').index
    )
    inflows = (
        inflow.sel(carrier=inflow_carrier)
        .to_dataframe(name="inflow")
        .fillna(0)["inflow"]
        .unstack()
        .rename(columns=lambda x: f"{x} {model_carrier}")
    )
    match inflow_carrier:
        case "hydro":
            n.components[component_name].dynamic.p_max_pu[idx] = np.where(
                inflows[idx].max() > 0, inflows[idx] / inflows[idx].max(), 0
            )
            n.components[component_name].static.loc[idx, "p_nom"] = inflows[idx].max()
        case "PHS":
            n.components[component_name].dynamic.p_max_pu[idx] = np.where(
                inflows[idx].max() > 0, inflows[idx] / inflows[idx].max(), 0
            )
            n.components[component_name].static.loc[idx, "p_nom"] = inflows[idx].max()
        case "ror":
            p_nom = n.components[component_name].static.loc[idx, "p_nom"]
            ror_p_max_pu = (
                inflows[idx].div(p_nom.where(p_nom > 0), axis="columns").fillna(0.0)
            )
            ror_p_max_pu = _redistribute_peaks(ror_p_max_pu)
            n.components[component_name].dynamic.p_max_pu[idx] = ror_p_max_pu
        case _:
            raise ValueError(f"Unknown inflow carrier {inflow_carrier}")

    missed_inflow_regions = list(set(inflows.columns) - set(idx))
    if inflows[missed_inflow_regions].sum().sum() > 0:
        logger.warning(
            f"Left out non-zero {model_carrier} data due to missing network components for {missed_inflow_regions}"
        )
    return (idx, inflows)


def patch_inflows(n: Network, snakemake: Snakemake, ppl: pd.DataFrame) -> None:
    """
    Apply inflows to hydro components in the network.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, and config.
    ppl
        Aggregated powerplants data

    Returns
    -------
    :
        Modifies the network in place.
    """
    # Load inflow (time, name, carrier)
    inflow = xr.open_dataarray(Path(snakemake.input.inflow))
    inflow = _modify_inflow_snapshots(n, inflow)

    # Patch inflows
    hydro_idx, hydro_inflows = _patch_component_inflows(
        n, inflow, "hydro", "hydro inflow"
    )
    _patch_component_inflows(n, inflow, "PHS", "PHS inflow")
    _patch_component_inflows(n, inflow, "ror", "ror")

    # modify average capacity factor for hydro
    p = snakemake.params.renewable["hydro"].copy()
    hydro = ppl.query('carrier == "hydro"')
    renewable_carriers = set(snakemake.params.electricity["renewable_carriers"])
    if p.get("flatten_dispatch", False) and "hydro" in renewable_carriers:
        buffer = p.get("flatten_dispatch_buffer", 0.2)
        hydro_p_nom = hydro["p_nom"]
        link_idx = hydro_p_nom.index + " discharger"
        hydro_p_nom.index += " inflow"
        average_capacity_factor = hydro_inflows[hydro_idx].mean() / hydro_p_nom
        average_capacity_factor.index = link_idx
        n.links.loc[link_idx, "p_max_pu"] = (average_capacity_factor + buffer).clip(
            upper=1
        )
