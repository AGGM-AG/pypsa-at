# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""National net-zero electricity constraints implementing EAG §4(2)."""

import logging

import pandas as pd
import pypsa

logger = logging.getLogger(__name__)


def constraint_net_zero_electricity(n: pypsa.Network, snakemake, investment_year: int):
    """
    Add national net-zero electricity production constraints.

    Parameters
    ----------
    n
        The pypsa network to add the constraints to.
    snakemake
        The snakemake workflow object.
    investment_year
        The current workflow planning horizon.

    Notes
    -----
    Implements EAG $ 4 (2) [RIS](https://www.ris.bka.gv.at/GeltendeFassung.wxe?Abfrage=Bundesnormen&Gesetzesnummer=20011619&FassungVom=2022-06-22)
    """
    net_zero_constraint = snakemake.config["mods"]["net_zero_electricity"]
    if not net_zero_constraint.get("enable"):
        logger.info(
            "Skipping net-zero electricity constraints because the feature is disabled."
        )
        return

    # the year in the config is an inclusive start year boundary.
    country_years = {
        k: v
        for k, v in net_zero_constraint.items()
        if k not in ("enable", "fuels", "h2_sources")
    }

    # Sub-national regions (e.g. AT11, DEA) and empty-string match-all keys are
    # out of scope per EAG §4(2) spec — constraints operate at country-prefix level.
    for country, start_year in country_years.items():
        if investment_year < int(start_year):
            logger.info(
                f"Skipping net-zero electricity constraint for country "
                f"{country} and investment year {investment_year} "
                f"because the start year {start_year} is not reached."
            )
            continue

        logger.info(
            f"Adding net-zero electricity constraints for "
            f"region {country} and year {investment_year}."
        )
        _add_net_zero_electricity_production_constraint(n, country)
        _add_green_gas_production_constraint(n, country)
        _add_hydrogen_production_constraint(n, country)
        _add_methanol_production_constraint(n, country)


def _compute_electricity_fraction(
    links: pd.DataFrame,
    electricity_buses: pd.Index,
    non_energy_buses: pd.Index,
) -> pd.Series:
    """
    For each link, return the fraction of its input energy attributable to electricity output.

    Returns 1.0 for degenerate links with no recognized output bus columns
    (``total_eff == 0``).

    Parameters
    ----------
    links
        Subset of ``n.links`` containing only the links to evaluate.
    electricity_buses
        Bus index of all AC and low-voltage buses.
    non_energy_buses
        Bus index of accounting-only buses whose "efficiency" is an
        emission rate, not an energy output (CO2 atmosphere, CO2 stored,
        process emissions).  Their ports are skipped entirely; counting
        them would deflate the electricity share of fossil gas-to-power
        and methanol-to-power links.

    Returns
    -------
    :
        Indexed by link name; values in [0, 1].
    """
    output_bus_cols = [
        c for c in links if c.startswith("bus") and c[3:].isdigit() and int(c[3:]) >= 1
    ]
    elec_eff = pd.Series(0.0, index=links.index)
    total_eff = pd.Series(0.0, index=links.index)

    for bus_col in output_bus_cols:
        port = bus_col[3:]
        eff_col = "efficiency" if port == "1" else f"efficiency{port}"
        if eff_col not in links.columns:
            continue
        # Skip unassigned ports: PyPSA fills unused bus columns with "" and
        # defaults efficiency to 1.0, which would otherwise inflate total_eff.
        # Skip non-energy ports (CO2): efficiency2 ≈ 0.198 tCO2/MWh_gas is an
        # emission rate, not an energy output.
        bus_assigned = links[bus_col].fillna("").ne("")
        on_energy_bus = ~links[bus_col].isin(non_energy_buses)
        eff = (
            links[eff_col]
            .fillna(0.0)
            .clip(lower=0.0)
            .where(bus_assigned & on_energy_bus, 0.0)
        )
        is_elec = links[bus_col].isin(electricity_buses)
        elec_eff += eff.where(is_elec, 0.0)
        total_eff += eff

    return (elec_eff / total_eff.replace(0.0, float("nan"))).fillna(1.0)


def _add_net_zero_electricity_production_constraint(n: pypsa.Network, country: str):
    """
    Require national green electricity production larger than national electricity demand.

    The constraint enforces, on a yearly basis:

    .. code-block:: none

        green_production - p2x_demand - phs_roundtrip_loss >= fixed_load

    LHS — green production (positive linopy terms):
        - Renewable generators (PV, wind, run-of-river).
        - Hydro reservoir and PHS dispatch (``StorageUnit-p_dispatch``).
        - Green fuel-to-power links (gas/H2/biomass/methanol → AC), ×efficiency.
          Green-ness of the input fuel is enforced by the companion constraints
          (:func:`_add_green_gas_production_constraint`, etc.).
        - Battery / home-battery dischargers, ×efficiency.

    RHS variable — demand and losses subtracted from LHS (all positive terms):
        - PHS charging (``StorageUnit-p_store``), capturing roundtrip loss.
        - Power-to-X links consuming from an electricity bus (battery and PHS
          chargers, H2 electrolysis, …).  Transmission links are excluded by
          requiring no output port on an electricity bus.
        - Auxiliary electricity at negative-efficiency output ports
          (e.g. methanolisation ``bus2=AC``, ``efficiency2 < 0``):
          demand = ``Link-p × |eff|``.
        - Reverse-flow links (heat pumps, ``p_max_pu ≤ 0``):
          demand = ``-eff × Link-p`` (positive because ``Link-p ≤ 0``).
        - Electricity distribution grid losses: ``Link-p × (1 − efficiency)``.
          LV loads are in the RHS scalar; only the dissipated fraction is added
          here.  Links with carrier ``"electricity distribution grid"`` are
          excluded from P2X because bus1 is a low-voltage bus.
        - Domestic AC transmission line losses (``Line-loss`` variable), only
          present when ``transmission_losses > 0`` in config.

    RHS scalar — fixed electricity demand:
        Weighted sum of ``Load`` components on AC and low-voltage buses
        (base load, industry, agriculture, etc.).

    Cross-border exports and internal AC-to-AC transmission links are excluded:
    no P2X link is counted if any output port lands on an electricity bus.

    Parameters
    ----------
    n
        The pypsa network with a linopy model attached (``n.model``).
    country
        Location prefix used to filter buses and links (e.g. ``"AT"``).
    """
    lhs = []  # variable production terms
    rhs = []  # variable demand terms, subtracted from lhs at assembly
    weightings = n.snapshot_weightings.generators
    electricity_buses = n.buses[n.buses.carrier.isin(["AC", "low voltage"])].index
    carrier_hydro = set(n.meta["renewable"]["hydro"]["carriers"])
    # solar rooftop is only added if distribution-grid is used
    carrier_res = set(n.meta["renewable"]) | {"solar rooftop"}
    renewables = sorted(carrier_res | carrier_hydro)  # noqa
    green_fuels = n.meta["mods"]["net_zero_electricity"]["fuels"]  # noqa
    output_ports = (1, 2, 3, 4)

    # Pre-filter all components to country scope once to prevent duplication
    where_country_and_active = "name.str.startswith(@country) & active"
    links = n.links.query(where_country_and_active)
    generators = n.generators.query(where_country_and_active)
    loads = n.loads.query(where_country_and_active)
    buses = n.buses.query("name.str.startswith(@country)")

    # RHS scalar: Fixed demand from electricity Loads
    idx_load = loads.query("bus in @electricity_buses").index
    # Loads are not optimization variables — their realized power equals ``p_set``
    # (Note that p_set may be time varying, or not)
    _cols = n.loads_t["p_set"].columns
    load_dynamic = (
        n.loads_t["p_set"][idx_load.intersection(_cols)].mul(weightings, axis=0).sum()
    )
    load_static = loads.loc[idx_load.difference(_cols), "p_set"] * weightings.sum()
    fixed_demand = load_dynamic.sum() + load_static.sum()

    # LHS (+) part 1: renewable Generators (includes Run-of-River `ror`)
    idx_gen = generators.query(
        "bus in @electricity_buses & carrier in @renewables"
    ).index
    if not idx_gen.empty:
        lhs.append(n.model["Generator-p"].loc[:, idx_gen].mul(weightings).sum())

    # LHS (+) part 2: power production from green fuel-to-power links
    # adds any electricity produced where bus0 is among green fuels
    idx_fuel_buses = buses.query("carrier in @green_fuels").index  # noqa
    for port in output_ports:
        eff = "efficiency" if port == 1 else f"efficiency{port}"
        idx_link_production = links.query(
            f"bus0 in @idx_fuel_buses "
            f"& bus{port} in @electricity_buses "
            f"& {eff} > 0"  # production only
        ).index
        if idx_link_production.empty:
            continue
        logger.info(
            f"For {country}, adding power production from Links at port {port}: "
            f"{sorted(links.loc[idx_link_production, 'carrier'].unique())}"
        )
        lhs.append(
            n.model["Link-p"]
            .loc[:, idx_link_production]
            .mul(links.loc[idx_link_production, eff])
            .mul(weightings)
            .sum()
        )

    # LHS (+) part 3: battery, PHS dischargers, hydro dischargers
    # They only have bus1 outputs
    idx_battery_output = links.query(
        "bus1 in @electricity_buses "
        "& carrier in ['battery discharger', 'home battery discharger', 'V2G', 'PHS discharger', 'hydro discharger']"
    ).index
    if not idx_battery_output.empty:
        logger.info(
            f"For {country}, adding battery outputs from carriers: "
            f"{sorted(links.loc[idx_battery_output, 'carrier'].unique())}"
        )
        lhs.append(
            n.model["Link-p"]
            .loc[:, idx_battery_output]
            .mul(links.loc[idx_battery_output, "efficiency"])
            .mul(weightings)
            .sum()
        )

    # RHS (+) part 4: Power2X Link power consumption
    # Catches battery/home-battery chargers, H2 Electrolysis, PHS, etc.
    has_electricity_output = pd.Series(False, index=links.index)
    for port in output_ports:
        has_electricity_output |= links[f"bus{port}"].isin(electricity_buses)
    idx_p2x = links.query(
        "bus0 in @electricity_buses & ~@has_electricity_output"  # excludes transmission
    ).index
    if not idx_p2x.empty:
        logger.info(
            f"For {country}, adding P2X / charger demand from carriers: "
            f"{sorted(links.loc[idx_p2x, 'carrier'].unique())}"
        )
        rhs.append(n.model["Link-p"].loc[:, idx_p2x].mul(weightings).sum())

    # RHS (+) part 5: auxiliary electricity at negative-efficiency ports
    # e.g. methanolisation has bus2=AC with efficiency2<0 (electricity input)
    # Demand = Link-p × |eff|; negating eff<0 gives the positive consumed power.
    for port in output_ports:
        eff = "efficiency" if port == 1 else f"efficiency{port}"  # noqa
        idx_auxiliary_electricity = links.query(
            f"bus{port} in @electricity_buses & {eff} < 0"  # demand only
        ).index
        if idx_auxiliary_electricity.empty:
            continue
        logger.info(
            f"For {country}, adding auxiliary electricity demand at port {port} "
            f"from carriers: {sorted(links.loc[idx_auxiliary_electricity, 'carrier'].unique())}"
        )
        rhs.append(
            -n.model["Link-p"]
            .loc[:, idx_auxiliary_electricity]
            .mul(links.loc[idx_auxiliary_electricity, eff])
            .mul(weightings)
            .sum()
        )

    # RHS (+) part 6: reverse-flow links (heat pumps)
    # PyPSA-Eur models heat pumps with bus0=heat, bus1=elec, eff1=1/COP and
    # ``p_max_pu <= 0`` (reverse-only): the link supplies heat at bus0 and
    # withdraws electricity at bus1.
    # Demand = -eff_t × Link-p (positive because Link-p ≤ 0).
    # Time-varying efficiency (1/COP) must be used where available; the static
    # column defaults to 1.0 for COP-based heat pumps, which would overcount
    # electricity demand by the COP factor.
    reversed_flow_links = links["p_max_pu"].le(0)  # noqa
    for port in output_ports:
        eff = "efficiency" if port == 1 else f"efficiency{port}"
        idx_heat_pumps = links.query(
            f"@reversed_flow_links & bus{port} in @electricity_buses & {eff} > 0"
        ).index
        if idx_heat_pumps.empty:
            continue
        logger.info(
            f"For {country}, adding reverse-flow electricity demand at port {port} "
            f"from carriers: {sorted(links.loc[idx_heat_pumps, 'carrier'].unique())}"
        )
        cop = n.links_t.get(eff, pd.DataFrame()).reindex(columns=idx_heat_pumps)
        rhs.append(
            -n.model["Link-p"]
            .loc[:, idx_heat_pumps]
            .mul(cop.mul(weightings, axis=0))
            .sum()
        )

    # RHS (+) part 7: electricity distribution grid losses
    # The distribution grid link (bus0=AC, bus1=low voltage, efficiency<1) is
    # excluded from idx_p2x because bus1 is in electricity_buses. LV loads are
    # already on the RHS scalar, so only the dissipated fraction is added here:
    # losses = Link-p × (1 − efficiency)
    idx_distribution = links.query("carrier == 'electricity distribution grid'").index
    if not idx_distribution.empty:
        logger.info(
            f"For {country}, adding distribution grid losses from "
            f"{len(idx_distribution)} links."
        )
        rhs.append(
            n.model["Link-p"]
            .loc[:, idx_distribution]
            .mul(1 - links.loc[idx_distribution, "efficiency"])
            .mul(weightings)
            .sum()
        )

    # RHS (+) part 8: Domestic AC transmission line losses
    # n.model["Line-loss"] is the piecewise-linear loss variable created by PyPSA
    # when transmission_losses > 0. It Lines are modeld with losses.
    expression = "bus0.str.startswith(@country) & bus1.str.startswith(@country)"
    idx_domestic_lines = n.lines.query(expression).index
    if not idx_domestic_lines.empty and "Line-loss" in n.model.variables:
        logger.info(
            f"For {country}, adding transmission losses from "
            f"{len(idx_domestic_lines)} domestic lines."
        )
        rhs.append(
            n.model["Line-loss"].loc[:, idx_domestic_lines].mul(weightings).sum()
        )

    # Assemble and register the constraint
    cname = f"net-zero-electricity-production-{country}"
    model_cname = f"GlobalConstraint-{cname}"

    if model_cname in n.model.constraints:
        logger.warning(
            f"Linopy constraint {model_cname} already exists. Dropping and adding it again."
        )
        n.model.remove_constraints(model_cname)

    n.model.add_constraints(sum(lhs) - sum(rhs) >= fixed_demand, name=model_cname)

    if cname in n.global_constraints.index:
        logger.warning(
            f"Global constraint {cname} already exists. Dropping and adding it again."
        )
        n.global_constraints.drop(cname, inplace=True)

    n.add(
        "GlobalConstraint",
        cname,
        constant=fixed_demand,
        sense=">=",
        type="",
        carrier_attribute="",
    )


def _add_green_gas_production_constraint(n: pypsa.Network, country: str) -> None:
    """
    Require domestic green methane production >= gas consumed for electricity.

    LHS: links where name starts with country, bus1 in AT gas buses, and
    bus0 carrier != "gas".  Captures biogas-to-gas, biogas-to-gas CC, Sabatier.
    Excludes EU->AT gas imports (bus0 carrier also "gas") and pipelines.

    Sabatier (H2 → gas) IS counted as green gas; its green-ness is enforced by
    :func:`_add_hydrogen_production_constraint`, which requires the H2 it
    consumes to come from domestic green producers (electrolysis).

    RHS: gas consumed by gas-to-power links x electricity_fraction.
    electricity_fraction = elec_output_efficiency / total_output_efficiency
    per link, so CHPs only contribute their electricity-attributable gas share.

    Known limitation: gas used by gas plants exporting electricity is included
    in RHS even though export does not count toward the AT EAG balance.

    Parameters
    ----------
    n
        The pypsa network with a linopy model attached (``n.model``).
    country
        Location prefix used to filter buses and links (e.g. ``"AT"``).
    """
    weightings = n.snapshot_weightings.generators
    electricity_buses = n.buses[n.buses.carrier.isin(["AC", "low voltage"])].index
    non_energy_buses = n.buses[
        n.buses.carrier.isin(["co2", "co2 stored", "process emissions"])
    ].index
    gas_buses = n.buses.query("country == @country & carrier == 'gas'").index

    if gas_buses.empty:
        logger.info(f"No gas buses for {country} — skipping green gas constraint.")
        return

    links = n.links.query("name.str.startswith(@country) & active")
    output_ports = (1, 2, 3, 4)

    # LHS: domestic green gas producers
    bus0_is_not_gas = links["bus0"].map(n.buses["carrier"]) != "gas"  # noqa
    idx_green_gas = links.query("bus1 in @gas_buses & @bus0_is_not_gas").index
    # Assumes all gas producers supply at bus1 (verified and tested for
    # current PyPSA-Eur carriers: biogas to gas, biogas to gas CC, Sabatier).

    if idx_green_gas.empty:
        logger.info(f"No green gas producers for {country} — skipping.")
        return

    logger.info(
        f"For {country}, green gas producers: "
        f"{sorted(links.loc[idx_green_gas, 'carrier'].unique())}"
    )

    lhs = (
        n.model["Link-p"]
        .loc[:, idx_green_gas]
        .mul(links.loc[idx_green_gas, "efficiency"])
        .mul(weightings)
        .sum()
    )

    # RHS: gas-to-power links x electricity fraction.
    # Assumes gas-to-power links carry gas on bus0 (verified and tested
    # for current PyPSA-Eur carriers: OCGT, CCGT, gas CHPs). The eff>0 guard
    # excludes auxiliary electricity-input ports (e.g. methane pyrolysis bus2=AC
    # with efficiency2<0) — those are not gas-to-power producers.
    has_electricity_output = pd.Series(False, index=links.index)
    for p in output_ports:
        eff = "efficiency" if p == 1 else f"efficiency{p}"
        _port_mask = links[f"bus{p}"].isin(electricity_buses) & (links[eff] > 0)
        has_electricity_output |= _port_mask

    idx_gas2power = links.query(
        "bus0 in @gas_buses & @has_electricity_output",
    ).index

    if idx_gas2power.empty:
        logger.info(
            f"No gas-to-power links for {country}. Skipping green gas constraint."
        )
        return

    # calculate amounts of fuel needed to produce electricity
    electricity_fraction = _compute_electricity_fraction(
        links.loc[idx_gas2power], electricity_buses, non_energy_buses
    )

    rhs = (
        n.model["Link-p"]
        .loc[:, idx_gas2power]
        .mul(electricity_fraction)
        .mul(weightings)
        .sum()
    )

    cname = f"green-gas-production-{country}"
    model_cname = f"GlobalConstraint-{cname}"

    if model_cname in n.model.constraints:
        logger.warning(
            f"Linopy constraint {model_cname} already exists. Dropping and adding it again."
        )
        n.model.remove_constraints(model_cname)

    # linopy converts `lhs >= rhs` to `lhs - rhs >= 0.0`
    n.model.add_constraints(lhs >= rhs, name=model_cname)

    if cname in n.global_constraints.index:
        logger.warning(
            f"Global constraint {cname} already exists. Dropping and adding it again."
        )
        n.global_constraints.drop(cname, inplace=True)

    n.add(
        "GlobalConstraint",
        cname,
        constant=0.0,
        sense=">=",
        type="",
        carrier_attribute="",
    )


def _add_hydrogen_production_constraint(n: pypsa.Network, country: str) -> None:
    """
    Require domestic green H2 production >= H2 consumed for electricity-bound
    pathways.

    LHS: links where name starts with country, bus1 in AT H2 buses, and
    ``bus0`` carrier in the configured ``h2_sources`` allowlist.  By default,
    this admits electrolysis (``bus0`` carrier ∈ {AC, low voltage}) and
    biomass-to-H2 (``bus0`` carrier "solid biomass").

    Why an allowlist and not a "bus0 ≠ H2" mirror of the gas/methanol
    pattern: SMR / SMR CC (``bus0 = gas``, ``bus1 = H2``) is blue/grey H2,
    and the green-gas constraint only enforces green gas for gas-to-power —
    not for gas-to-H2.  A "bus0 ≠ H2" filter would silently admit fossil-gas
    H2 onto the green-H2 LHS.  Methane pyrolysis is also excluded by
    topology today (its output bus has the separate ``"H2 for industry"``
    carrier); if it is ever rewired to the regular H2 bus, treat it as a
    separate design decision rather than relying on the allowlist.

    Biogas-fed SMR could be admitted as a renewable-H2 pathway under EU RED
    III / RFNBO definitions if the green-gas constraint is extended to also
    cover gas-for-SMR-for-power.  That requires a downstream "share of H2
    that ends up as electricity" factor analogous to ``electricity_fraction``,
    propagated across two conversion stages (gas → H2 → power).  Out of
    scope today: ``gas`` is intentionally omitted from ``h2_sources`` so the
    current single-stage constraint stack remains consistent.

    RHS: H2 consumed by

    1. H2-to-power links × electricity_fraction, and
    2. H2-to-other-green-fuel synthesis links (e.g. Sabatier, methanolisation).

    The second term ensures that green gas / green methanol produced from H2
    is backed by domestically produced green H2 — otherwise the upstream
    fuel constraints could be satisfied with "green" gas/methanol made from
    grey H2.

    Known limitation: H2 used by plants exporting electricity is included in RHS.

    Parameters
    ----------
    n
        The pypsa network with a linopy model attached (``n.model``).
    country
        Location prefix used to filter buses and links (e.g. ``"AT"``).
    """
    rhs = []  # variable H2 consumption to produce green fuels
    weightings = n.snapshot_weightings.generators
    electricity_buses = n.buses[n.buses.carrier.isin(["AC", "low voltage"])].index
    non_energy_buses = n.buses[
        n.buses.carrier.isin(["co2", "co2 stored", "process emissions"])
    ].index
    h2_buses = n.buses.query("country == @country & carrier == 'H2'").index

    if h2_buses.empty:
        logger.info(f"No H2 buses for {country}. Skipping green H2 constraint.")
        return

    links = n.links.query("name.str.startswith(@country) & active")
    output_ports = (1, 2, 3, 4)
    bus0_carrier = links["bus0"].map(n.buses["carrier"])

    # LHS: domestic green H2 producers (bus0 carrier in configured allowlist)
    h2_sources = n.meta["mods"]["net_zero_electricity"]["h2_sources"]  # noqa
    bus0_in_h2_sources = bus0_carrier.isin(h2_sources)  # noqa
    green_h2_idx = links.query("bus1 in @h2_buses & @bus0_in_h2_sources").index

    if green_h2_idx.empty:
        logger.info(f"No green H2 producers for {country} — skipping.")
        return

    logger.info(
        f"For {country}, green H2 producers: "
        f"{sorted(links.loc[green_h2_idx, 'carrier'].unique().tolist())}"
    )

    lhs = (
        n.model["Link-p"]
        .loc[:, green_h2_idx]
        .mul(links.loc[green_h2_idx, "efficiency"])
        .mul(weightings)
        .sum()
    )

    # RHS part 1: H2-to-power links x electricity fraction. The eff > 0 guard
    # excludes auxiliary electricity-input ports (e.g. methanolisation bus2=AC
    # with efficiency2<0) — those are H2-to-fuel synthesis with auxiliary
    # electricity input, not H2-to-power producers, and are accounted for in
    # RHS part 2 instead.
    has_electricity_output = pd.Series(False, index=links.index)
    for p in output_ports:
        eff = "efficiency" if p == 1 else f"efficiency{p}"
        has_electricity_output |= links[f"bus{p}"].isin(electricity_buses) & (
            links[eff] > 0
        )
    h2_to_power = links.query("bus0 in @h2_buses & @has_electricity_output").index

    if not h2_to_power.empty:
        electricity_fraction = _compute_electricity_fraction(
            links.loc[h2_to_power], electricity_buses, non_energy_buses
        )
        rhs.append(
            n.model["Link-p"]
            .loc[:, h2_to_power]
            .mul(electricity_fraction)
            .mul(weightings)
            .sum()
        )

    # RHS part 2: H2 consumed by other green-fuel synthesis (Sabatier,
    # methanolisation). These links carry H2 on bus0 and output another
    # green fuel covered by the constraint stack (gas / methanol / biomass).
    # H2 flow at bus0 == Link-p (no efficiency multiplier).
    green_fuel_carriers = n.meta["mods"]["net_zero_electricity"]["fuels"]
    other_fuels = [c for c in green_fuel_carriers if c != "H2"]
    h2_to_fuel = pd.Index([], dtype=object)
    for fuel_carrier in other_fuels:  # noqa
        fuel_buses = n.buses.query(
            "country == @country & carrier == @fuel_carrier"
        ).index
        if fuel_buses.empty:
            continue
        has_fuel_output = pd.Series(False, index=links.index)
        for p in output_ports:
            has_fuel_output |= links[f"bus{p}"].isin(fuel_buses)
        h2_to_fuel = h2_to_fuel.union(
            links.query("bus0 in @h2_buses & @has_fuel_output").index
        )

    if not h2_to_fuel.empty:
        logger.info(
            f"For {country}, H2 → other-fuel consumers: "
            f"{sorted(links.loc[h2_to_fuel, 'carrier'].unique().tolist())}"
        )
        rhs.append(n.model["Link-p"].loc[:, h2_to_fuel].mul(weightings).sum())

    if not rhs:
        logger.info(
            f"No H2 consumers (power or fuel synthesis) for {country} — "
            "skipping green H2 constraint."
        )
        return

    rhs = sum(rhs)

    cname = f"green-h2-production-{country}"
    model_cname = f"GlobalConstraint-{cname}"

    if model_cname in n.model.constraints:
        logger.warning(
            f"Linopy constraint {model_cname} already exists. Dropping and adding it again."
        )
        n.model.remove_constraints(model_cname)

    n.model.add_constraints(lhs >= rhs, name=model_cname)

    if cname in n.global_constraints.index:
        logger.warning(
            f"Global constraint {cname} already exists. Dropping and adding it again."
        )
        n.global_constraints.drop(cname, inplace=True)

    n.add(
        "GlobalConstraint",
        cname,
        constant=0.0,
        sense=">=",
        type="",
        carrier_attribute="",
    )


def _add_methanol_production_constraint(n: pypsa.Network, country: str) -> None:
    """
    Require domestic green methanol production >= methanol consumed for electricity.

    LHS: links where name starts with country, bus1 in AT methanol buses, and
    bus0 carrier != "methanol".  Captures biomass-to-methanol, biomass-to-methanol CC.
    Excludes EU->AT methanol imports via EU copper plate (bus0 carrier "EU methanol").

    RHS: methanol consumed by methanol-to-power links x electricity_fraction.
    Captures CCGT methanol, OCGT methanol, CCGT methanol CC (all pure electricity
    output -> electricity_fraction = 1.0).

    Known limitation: methanol used by plants exporting electricity is included in RHS.

    Parameters
    ----------
    n
        The pypsa network with a linopy model attached (``n.model``).
    country
        Location prefix used to filter buses and links (e.g. ``"AT0"``).
    """
    weightings = n.snapshot_weightings.generators
    electricity_buses = n.buses[n.buses.carrier.isin(["AC", "low voltage"])].index
    non_energy_buses = n.buses[
        n.buses.carrier.isin(["co2", "co2 stored", "process emissions"])
    ].index
    methanol_buses = n.buses.query("country == @country & carrier == 'methanol'").index

    if methanol_buses.empty:
        logger.info(
            f"No methanol buses for {country} — skipping green methanol constraint."
        )
        return

    links = n.links.query("name.str.startswith(@country) & active")
    output_ports = (1, 2, 3, 4)
    bus0_carrier = links["bus0"].map(n.buses["carrier"])

    # LHS: domestic green methanol producers
    bus0_is_not_methanol = bus0_carrier != "methanol"  # noqa
    green_methanol_idx = links.query(
        "bus1 in @methanol_buses & @bus0_is_not_methanol"
    ).index

    if green_methanol_idx.empty:
        logger.info(f"No green methanol producers for {country} — skipping.")
        return

    logger.info(
        f"For {country}, green methanol producers: "
        f"{sorted(links.loc[green_methanol_idx, 'carrier'].unique().tolist())}"
    )

    lhs = (
        n.model["Link-p"]
        .loc[:, green_methanol_idx]
        .mul(links.loc[green_methanol_idx, "efficiency"])
        .mul(weightings)
        .sum()
    )

    # RHS: methanol-to-power links x electricity fraction
    has_electricity_output = pd.Series(False, index=links.index)
    for p in output_ports:
        has_electricity_output |= links[f"bus{p}"].isin(electricity_buses)
    methanol_to_power = links.query(
        "bus0 in @methanol_buses & @has_electricity_output"
    ).index

    if methanol_to_power.empty:
        logger.info(
            f"No methanol-to-power links for {country} — skipping green methanol constraint."
        )
        return

    electricity_fraction = _compute_electricity_fraction(
        links.loc[methanol_to_power], electricity_buses, non_energy_buses
    )

    rhs = (
        n.model["Link-p"]
        .loc[:, methanol_to_power]
        .mul(electricity_fraction)
        .mul(weightings)
        .sum()
    )

    cname = f"green-methanol-production-{country}"
    model_cname = f"GlobalConstraint-{cname}"

    if model_cname in n.model.constraints:
        logger.warning(
            f"Linopy constraint {model_cname} already exists. Dropping and adding it again."
        )
        n.model.remove_constraints(model_cname)

    n.model.add_constraints(lhs >= rhs, name=model_cname)

    if cname in n.global_constraints.index:
        logger.warning(
            f"Global constraint {cname} already exists. Dropping and adding it again."
        )
        n.global_constraints.drop(cname, inplace=True)

    n.add(
        "GlobalConstraint",
        cname,
        constant=0.0,
        sense=">=",
        type="",
        carrier_attribute="",
    )
