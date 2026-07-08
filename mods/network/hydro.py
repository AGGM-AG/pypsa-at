import numpy as np
import pandas as pd
from pypsa import Network
from snakemake.script import Snakemake

from scripts.add_electricity import add_missing_carriers, load_and_aggregate_powerplants


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
    carriers = p.pop("carriers", [])

    if "PHS" in carriers and not phs.empty:
        # fill missing max hours to params value and
        # assume no natural inflow due to lack of data
        max_hours = p.get("PHS_max_hours", 6)
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
