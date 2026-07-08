# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Hydrogen-side network modifications: H2 for industry bus and methane pyrolysis."""

from logging import getLogger
from types import SimpleNamespace

import pandas as pd
import pypsa
from snakemake.script import Snakemake

logger = getLogger(__name__)


def add_h2_for_industry_bus(n: pypsa.Network, nodes: pd.Index) -> None:
    """
    Create per-node "H2 for industry" Bus + Link topology and rewire existing Loads.

    Adds a dedicated "H2 for industry" bus per node, adds a unidirectional
    H2 → H2 for industry Link (so industry H2 demand is supplied from the H2
    bus but cannot flow back), and rewires the existing "H2 for industry" Loads
    from the H2 bus to the new dedicated bus.

    Mirrors the "gas for industry" Bus + Link + Load topology used in
    ``prepare_sector_network.add_industry``.  Links are unidirectional by
    PyPSA default (p_min_pu=0).

    Parameters
    ----------
    n
        Pre-network to modify in place.
    nodes
        Clustered node index (``pop_layout.index``).

    Returns
    -------
    :
        Modifies ``n`` in place.
    """
    h2_industry = nodes + " H2 for industry"

    n.add(
        "Bus",
        h2_industry,
        location=nodes,
        carrier="H2 for industry",
        unit="MWh_LHV",
    )

    # Rewire existing loads: "{node} H2 for industry" to new dedicated bus
    loads_to_rewire = h2_industry[h2_industry.isin(n.loads.index)]
    n.loads.loc[loads_to_rewire, "bus"] = loads_to_rewire

    n.add(
        "Link",
        h2_industry,
        bus0=nodes + " H2",
        bus1=h2_industry,
        carrier="H2 for industry",
        p_nom_extendable=True,
        efficiency=1.0,
    )
    logger.info(f"Set up H2 for industry Bus + Link topology for {len(nodes)} nodes.")


def add_methane_pyrolysis_plasma(
    n: pypsa.Network,
    snakemake: Snakemake,
    costs: pd.DataFrame,
    nodes: pd.Index,
    spatial: SimpleNamespace,
) -> None:
    """
    Add Methane Pyrolysis (Plasma) H₂ production Links to the sector network.

    Methane pyrolysis (plasma variant) splits CH₄ into H₂ and solid carbon
    (carbon black) using a plasma torch.  No CO₂ is emitted during the
    process; the carbon is captured as a solid material, enabling turquoise
    hydrogen production with negative emissions potential if the carbon black
    is permanently stored.

    * bus0 = gas (CH₄ input, ``p_nom`` reference in MW_CH4)
    * bus1 = H2 for industry  (H₂ output, directly to industry demand bus)
    * bus2 = AC  (electricity consumption for plasma torch)
    * CO₂ stored bus is intentionally **not** connected: carbon black is
      a solid transported by road/rail/ship, not through the CO₂ pipeline
      network.

    Requires ``add_h2_for_industry_bus`` to have been called beforehand so that
    the "H2 for industry" Bus + Link topology already exists in the network.

    All cost parameters in ``costs`` are normalized to MWh_H₂.  Since bus0
    is gas (MW_CH4), efficiencies and capital cost are converted using
    ``eta_H2 = 1 / methane-input``.

    Carbon black revenue: carbon black sold to the market is valued at
    the CO₂ price of the same planning horizon, scaled by the stoichiometric
    CO₂ intensity of carbon black.

    Parameters
    ----------
    n
        Pre-network to modify in place.
    snakemake
        The workflow snakemake object.
    costs
        Processed cost DataFrame for the current planning horizon.
    nodes
        Clustered node index (``pop_layout.index``).
    spatial
        Spatial namespace produced by ``define_spatial``.

    Returns
    -------
    :
        Modifies ``n`` in place.
    """
    config = snakemake.config["mods"]["methane_pyrolysis"]

    if not config.get("plasma", False):
        logger.info("Methane pyrolysis plasma: disabled — skipping.")
        return

    # carrier name. Used to mitigate downstream repetitions
    tech = "methane pyrolysis plasma"

    pyear = int(snakemake.wildcards.planning_horizons)

    # Guard: technology not available before 2030 (no cost data in custom_costs).
    if tech not in costs.index:
        logger.info(
            f"Methane pyrolysis plasma not available in "
            f"{pyear} (not available before 2030) — skipping."
        )
        return

    # fail-safe against zero costs technologies caused by incomplete costs entries
    if costs.at[tech, "investment"] == 0:
        raise ValueError(
            "`process_cost_data` fills missing investment with 0; "
            "capital_cost would also be 0, making capacity free. "
            "Check your costs file and processing pipeline."
        )

    logger.info("Adding Methane Pyrolysis (Plasma) H₂ production Links.")

    # All costs.csv values are normalized to MWh_H2. This is a DEA choice preserved
    # in technology-data and ultimately a consequence here at model level. Since
    # bus0 = gas → need to convert efficiencies and capital cost to per-MWh_CH4.
    ch4_input = costs.at[tech, "methane-input"]  # MWh_CH4/MWh_H2
    eta_H2 = 1.0 / ch4_input  # MWh_H2/MWh_CH4

    cb_revenue = 0  # no revenue from carbon black sales by default
    if cb_utilization := float(config.get("utilization_share", 0.0)):
        # Carbon black (cb) revenue: priced at CO2 cost of the same planning horizon.
        co2_price = costs.at["CO2", "fuel"]  # EUR/tCO2
        co2_stored_total = costs.at[tech, "CO2 stored"]  # tCO2/MWh_H2
        cb_energy = costs.at[tech, "carbon-black-output"]  # MWh_Cblack/MWh_H2
        cb_co2_intensity = co2_stored_total / cb_energy  # tCO2/MWh_Cblack
        cb_revenue = (
            cb_utilization * cb_energy * cb_co2_intensity * co2_price
        )  # EUR/MWh_H2

    cost_capital = costs.at[tech, "capital_cost"] * eta_H2  # to EUR/MW_CH4
    cost_marginal = costs.at[tech, "VOM"] * eta_H2 - cb_revenue  # EUR/MWh_CH4
    efficiency_elec = -costs.at[tech, "electricity-input"] * eta_H2
    lifetime = costs.at[tech, "lifetime"]

    n.add(
        "Link",
        nodes,
        carrier=tech,
        suffix=f" {tech}",
        bus0=spatial.gas.df.loc[nodes, "nodes"].values,
        bus1=nodes + " H2 for industry",
        bus2=nodes,
        p_nom_extendable=True,
        efficiency=eta_H2,
        efficiency2=efficiency_elec,
        capital_cost=cost_capital,
        marginal_cost=cost_marginal,
        lifetime=lifetime,
    )

    logger.info(f"Added {len(nodes)} methane pyrolysis plasma Links.")


def add_h2_imports(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Add hydrogen import options.

    Parameters
    ----------
    n
        Pre-network to modify in place.
    snakemake
        The workflow snakemake object.

    """
    options = snakemake.params["sector"]
    import_config = options["imports"]
    if (
        import_config["enable"]
        and "H2" in import_config["carriers_tyndp"]
        and options["h2_topology_tyndp"]
    ):
        logger.info("Adding TYNDP H2 import.")
        import_potentials_h2 = pd.read_csv(
            snakemake.input.h2_imports_tyndp, index_col=0
        )

        # change coordinates of import buses with existing H2 buses (e.g. NO)
        h2_coords = (
            n.buses.query("carrier.str.contains('H2')")
            .groupby("country")
            .first()[["x", "y"]]
            .rename(columns={"x": "bus0_x", "y": "bus0_y"})
        )
        temp_df = import_potentials_h2.set_index("bus0")
        temp_df.update(h2_coords)
        import_potentials_h2[["bus0_x", "bus0_y"]] = temp_df[
            ["bus0_x", "bus0_y"]
        ].values

        # Note: h2_zones_tyndp is experimental and untested
        suffix = "H2 Z2" if options["h2_zones_tyndp"] else "H2"
        n.add(
            "Generator",
            import_potentials_h2.Corridor,
            suffix=" H2 import",
            bus=import_potentials_h2.bus1.values + f" {suffix}",
            carrier="import H2",
            p_nom_extendable=False,
            p_nom=import_potentials_h2.p_nom.values,
            marginal_cost=import_potentials_h2.marginal_cost.values,
            e_sum_max=import_potentials_h2.e_sum_max.values,
        )

        logger.info(f"Added {len(import_potentials_h2)} h2 import Generators.")
