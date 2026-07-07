from logging import getLogger
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from pypsa import Network
from snakemake.script import Snakemake

from scripts.add_electricity import add_missing_carriers, load_and_aggregate_powerplants

logger = getLogger(__name__)


def add_phs(n: Network, snakemake: Snakemake, costs: pd.DataFrame):
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
    phs = ppl.query('carrier == "PHS"')
    p = snakemake.params.renewable["hydro"].copy()
    renewable_carriers = set(snakemake.params.electricity["renewable_carriers"])
    carriers = p.pop("carriers", [])

    if "hydro" in renewable_carriers and "PHS" in carriers and not phs.empty:
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
            p_nom=phs_pump["p_nom"],
            p_nom_extendable=False,
            capital_cost=costs.at["PHS", "capital_cost"],
            onight_cost=costs.at["PHS", "investment"],
            efficiency=np.sqrt(costs.at["PHS", "efficiency"]),
        )

        n.add(
            "Link",
            phs_turbine.index,
            carrier="PHS discharger",
            bus0=phs.index + " bus",
            bus1=phs_turbine["bus"],
            p_nom=phs_turbine["p_nom"] / np.sqrt(costs.at["PHS", "efficiency"]),
            p_nom_extendable=False,
            capital_cost=costs.at["PHS", "capital_cost"]
            * np.sqrt(costs.at["PHS", "efficiency"]),
            onight_cost=costs.at["PHS", "investment"]
            * np.sqrt(costs.at["PHS", "efficiency"]),
            efficiency=np.sqrt(costs.at["PHS", "efficiency"]),
        )

        n.add(
            "Store",
            phs_store.index,
            carrier="PHS store",
            bus=phs.index + " bus",
            e_nom=phs_store["p_nom"] * phs_store["max_hours"],
            e_nom_extendable=False,
            capital_cost=costs.at["PHS", "capital_cost"],
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


def patch_inflows(n: Network, snakemake: Snakemake) -> None:
    """
    Apply inflows to hydro components in the network.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, and config.

    Returns
    -------
    :
        Modifies the network in place.
    """
    # Load inflow (time, name, carrier)
    inflow = xr.open_dataarray(Path(snakemake.input.inflow))
    inflow = _modify_inflow_snapshots(n, inflow)

    # Patch hydro inflow
    hydro_idx = n.storage_units.query('carrier == "hydro"').index
    hydro_inflows = (
        inflow.sel(carrier="hydro")
        .to_dataframe(name="inflow")
        .fillna(0)["inflow"]
        .unstack()
        .rename(columns=lambda x: f"{x} hydro")
    )
    n.storage_units_t.inflow[hydro_idx] = hydro_inflows[hydro_idx]

    hydro_missed_inflow_regions = list(set(hydro_inflows.columns) - set(hydro_idx))
    if hydro_inflows[hydro_missed_inflow_regions].sum().sum() > 0:
        logger.warning(
            f"Left out non-zero hydro inflow data due to missing network components for {hydro_missed_inflow_regions}"
        )

    # Patch PHS inflow
    phs_idx = n.generators.query('carrier == "PHS inflow"').index
    phs_inflows = (
        inflow.sel(carrier="PHS")
        .to_dataframe(name="PHS")
        .fillna(0)["PHS"]
        .unstack()
        .rename(columns=lambda x: f"{x} PHS inflow")
    )
    n.generators_t.p_max_pu[phs_idx] = phs_inflows[phs_idx] / phs_inflows[phs_idx].max()
    n.generators.loc[phs_idx, "p_nom"] = phs_inflows[phs_idx].max()

    phs_missed_inflow_regions = list(set(phs_inflows.columns) - set(phs_idx))
    if phs_inflows[phs_missed_inflow_regions].sum().sum() > 0:
        logger.warning(
            f"Left out non-zero phs inflow data due to missing network components for {phs_missed_inflow_regions}"
        )

    # Patch ROR generation
    ror_idx = n.generators.query('carrier == "ror"').index
    ror_inflows = (
        inflow.sel(carrier="ror")
        .to_dataframe(name="ror")
        .fillna(0)["ror"]
        .unstack()
        .rename(columns=lambda x: f"{x} ror")
    )
    ror_p_max_pu = ror_inflows[ror_idx] / n.generators.loc[ror_idx, "p_nom"]
    ror_p_max_pu = _redistribute_peaks(ror_p_max_pu)
    n.generators_t.p_max_pu[ror_idx] = ror_p_max_pu

    ror_missed_inflow_regions = list(set(ror_inflows.columns) - set(ror_idx))
    if ror_inflows[ror_missed_inflow_regions].sum().sum() > 0:
        logger.warning(
            f"Left out non-zero ror inflow data due to missing network components for {ror_missed_inflow_regions}"
        )
