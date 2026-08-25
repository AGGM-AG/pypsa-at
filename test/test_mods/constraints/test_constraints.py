# test/test_mods/test_constraints.py
"""Unit tests for EAG §4(2) net-zero electricity and TYNDP NTC cross-border flow constraints."""

import pandas as pd
import pypsa
import pytest

from evals.constants import DataModel as DM
from evals.utils import (
    calculate_input_share,
    filter_by,
    filter_for_carrier_connected_to,
    get_energy_totals_domestic_share,
)
from mods.constants import UNITS
from mods.constraints.eag import _compute_electricity_fraction
from mods.constraints.production import (
    GENERATOR_CARRIERS,
    LINK_CARRIERS,
    _add_eag_entries,
)
from mods.utils import get_relevant_links_and_lines
from scripts.prepare_sector_network import determine_emission_sectors
from test.conftest import require_config


def test_production_targets(nc):
    eag_enabled = require_config(nc, "mods", "net_zero_electricity", "enable")
    for year, n in nc.networks.items():
        constraints = n.meta["solving"]["constraints"]
        year = int(year)
        maximums = constraints.get("limits_volume_max", {})
        minimums = constraints.get("limits_volume_min", {})

        _add_eag_entries(eag_enabled)

        for sense, limits, suffix in [
            ("<=", maximums, "upper"),
            (">=", minimums, "lower"),
        ]:
            for source, region_dict in limits.items():
                for region, year_dict in region_dict.items():
                    if source not in (*GENERATOR_CARRIERS, *LINK_CARRIERS):
                        continue
                    years = year_dict.keys()
                    if year not in years:
                        continue
                    target = year_dict[year]
                    target *= UNITS["TWh"]

                    if source in LINK_CARRIERS:
                        input_carriers, output_carriers = LINK_CARRIERS[source]
                        supply = n.statistics.supply(
                            groupby=["bus0"],
                            components="Link",
                            bus_carrier=output_carriers,
                            nice_names=False,
                        )
                        bus0 = supply.index.get_level_values("bus0")
                        production = supply[
                            bus0.str.startswith(region)
                            & n.buses.carrier.reindex(bus0)
                            .isin(input_carriers)
                            .to_numpy()
                        ].sum()
                    else:
                        supply = n.statistics.supply(
                            groupby=["bus", "carrier"],
                            components="Generator",
                            nice_names=False,
                        )
                        bus = supply.index.get_level_values("bus")
                        production = supply[
                            bus.str.startswith(region)
                            & supply.index.get_level_values("carrier").isin(
                                GENERATOR_CARRIERS[source]
                            )
                        ].sum()
                    if sense == "<=":
                        assert production <= target + 1e-3, (
                            f"{year} {source} {region}: {production / 1e6:.6f} TWh/a above "
                            f"maximum {target / 1e6}"
                        )
                    else:
                        assert production >= target - 1e-3, (
                            f"{year} {source} {region}: {production / 1e6:.6f} TWh/a below "
                            f"minimum {target / 1e6}"
                        )


class TestComputeElectricityFraction:
    """_compute_electricity_fraction returns fraction of input attributable to electricity output."""

    def _electricity_buses(self):
        return pd.Index(["AT0 AC", "AT0 low voltage"])

    def _non_energy_buses(self):
        return pd.Index(["co2 atmosphere", "co2 stored", "process emissions"])

    def test_pure_electricity_link_returns_one(self):
        links = pd.DataFrame(
            {"bus1": ["AT0 AC"], "efficiency": [0.4]},
            index=["AT0 OCGT"],
        )
        result = _compute_electricity_fraction(
            links, self._electricity_buses(), self._non_energy_buses()
        )
        assert result["AT0 OCGT"] == pytest.approx(1.0)

    def test_chp_returns_electricity_share(self):
        # electricity_fraction = 0.4 / (0.4 + 0.45) ≈ 0.4706
        links = pd.DataFrame(
            {
                "bus1": ["AT0 AC"],
                "bus2": ["AT0 heat"],
                "efficiency": [0.4],
                "efficiency2": [0.45],
            },
            index=["AT0 gas CHP"],
        )
        result = _compute_electricity_fraction(
            links, self._electricity_buses(), self._non_energy_buses()
        )
        assert result["AT0 gas CHP"] == pytest.approx(0.4 / (0.4 + 0.45))

    def test_negative_efficiency_ignored(self):
        # Negative efficiency at an aux output port (e.g. electricity input
        # at methanolisation bus2=AC with efficiency2<0) must not affect
        # the denominator — clip(lower=0) drops it.
        links = pd.DataFrame(
            {
                "bus1": ["AT0 AC"],
                "bus2": ["AT0 heat"],
                "bus3": ["AT0 AC"],
                "efficiency": [0.4],
                "efficiency2": [0.45],
                "efficiency3": [-0.2],
            },
            index=["AT0 gas CHP CC"],
        )
        result = _compute_electricity_fraction(
            links, self._electricity_buses(), self._non_energy_buses()
        )
        assert result["AT0 gas CHP CC"] == pytest.approx(0.4 / (0.4 + 0.45))

    def test_mixed_links_series_indexed_by_name(self):
        links = pd.DataFrame(
            {
                "bus1": ["AT0 AC", "AT0 AC"],
                "bus2": [None, "AT0 heat"],
                "efficiency": [0.4, 0.4],
                "efficiency2": [None, 0.45],
            },
            index=["AT0 OCGT", "AT0 gas CHP"],
        )
        result = _compute_electricity_fraction(
            links, self._electricity_buses(), self._non_energy_buses()
        )
        assert result["AT0 OCGT"] == pytest.approx(1.0)
        assert result["AT0 gas CHP"] == pytest.approx(0.4 / (0.4 + 0.45))

    def test_empty_bus_with_default_efficiency_ignored(self):
        # PyPSA fills unused bus ports with empty string ``""`` and default
        # ``efficiency*=1.0``. Those must not inflate ``total_eff``: a real
        # CCGT was observed at 0.21 instead of ~1.0 because of this.
        # The bus2=co2 atmosphere port must also be excluded — efficiency2
        # ≈ 0.198 tCO2/MWh_gas is an emission rate, not an energy output —
        # so the electricity fraction of a pure power plant is 1.0.
        links = pd.DataFrame(
            {
                "bus1": ["AT0 AC"],
                "bus2": ["co2 atmosphere"],
                "bus3": [""],
                "bus4": [""],
                "efficiency": [0.59],
                "efficiency2": [0.198],
                "efficiency3": [1.0],
                "efficiency4": [1.0],
            },
            index=["AT0 CCGT"],
        )
        result = _compute_electricity_fraction(
            links, self._electricity_buses(), self._non_energy_buses()
        )
        assert result["AT0 CCGT"] == pytest.approx(1.0)

    def test_chp_with_co2_emission_port(self):
        # gas CHP: bus1=AC (eff 0.4), bus2=heat (eff 0.4), bus3=co2 atmosphere
        # (eff3 ≈ 0.198 tCO2/MWh_gas). The CO2 port must be excluded so the
        # electricity share is elec / (elec + heat), not elec / (elec + heat
        # + co2_rate).
        links = pd.DataFrame(
            {
                "bus1": ["AT0 AC"],
                "bus2": ["AT0 heat"],
                "bus3": ["co2 atmosphere"],
                "efficiency": [0.4],
                "efficiency2": [0.4],
                "efficiency3": [0.198],
            },
            index=["AT0 gas CHP"],
        )
        result = _compute_electricity_fraction(
            links, self._electricity_buses(), self._non_energy_buses()
        )
        assert result["AT0 gas CHP"] == pytest.approx(0.5)


def test_national_co2_budget_constraint(nc):
    """
    Make sure the national CO2 budget constraints are adhered to.
    """
    cfg = require_config(nc, "solving", "constraints", "co2_budget_national")
    if not cfg:
        pytest.xfail(f"solving.constraints.co2_budget_national is set to {cfg}.")

    for year, n in nc.networks.items():
        national_co2_budgets = n.meta["solving"]["constraints"].get(
            "co2_budget_national"
        )
        if not national_co2_budgets:
            continue

        # prepare data needed to replicate inequality constraint
        nhours = n.snapshot_weightings.generators.sum()
        nyears = nhours / 8760
        co2_balance = n.statistics.energy_balance(
            groupby=["location", "carrier"], bus_carrier="co2"
        ).mul(1e-6)  # to Mt_CO2
        energy_totals = pd.DataFrame.from_dict(
            n.meta["resources"]["energy_totals"], orient="tight"
        )
        co2_totals = pd.DataFrame.from_dict(
            n.meta["resources"]["co2_totals"], orient="tight"
        )
        sectors = determine_emission_sectors(n.meta["sector"])
        co2_total_totals = co2_totals[sectors].sum(axis=1) * nyears
        domestic_aviation_factors = get_energy_totals_domestic_share(
            energy_totals, kind="aviation"
        )

        for ct, myopic_limits in cfg.items():
            # deduct emissions from international air transport
            locations = co2_balance.index.get_level_values(DM.LOCATION)
            mask_country = locations.str.startswith(ct)
            carrier = co2_balance.index.get_level_values(DM.CARRIER)
            mask_carrier = carrier == "kerosene for aviation"
            mask = mask_country & mask_carrier
            co2_balance.loc[mask] *= domestic_aviation_factors[ct]

            # 1990 limit including national target
            limit_sectoral = co2_total_totals[ct] * myopic_limits[year]
            country_limit = limit_sectoral.sum()

            # optimized model values
            country_emissions = co2_balance.loc[mask_country].sum()

            assert country_emissions <= country_limit + 1e-05, (
                f"Exceeded emission limit for country {ct} and year "
                f"{year}: {country_limit} > {country_emissions} in Mt_CO2"
            )


def test_green_gas_constraint_bus_contracts(nc):
    """
    Contract test for ``_add_green_gas_production_constraint``.

    The constraint identifies green-gas producers via ``bus1 == gas`` and
    gas-to-power consumers via ``bus0 == gas``. Both shortcuts silently
    miss links that route gas through a different port. This test fails
    early if a future PyPSA carrier breaks either contract so the constraint
    can be updated in accordingly.
    """
    for year, n in nc.networks.items():
        links = n.links
        bus0_carrier = links["bus0"].map(n.buses["carrier"])
        link_ports = links.filter(like="bus").columns.str[3:]
        aux_output_ports = [p for p in link_ports if p not in ("0", "1")]
        any_output_ports = [p for p in link_ports if p != "0"]
        gas_buses = n.buses[n.buses.carrier == "gas"].index
        electricity_buses = n.buses[n.buses.carrier.isin(["AC", "low voltage"])].index

        # Contract 1: green gas producers output gas at bus1 (never an aux port).
        for port in aux_output_ports:
            bus_col = f"bus{port}"
            eff_col = f"efficiency{port}"
            if bus_col not in links.columns or eff_col not in links.columns:
                continue
            violators = links[
                links[bus_col].isin(gas_buses)
                & (links[eff_col] > 0)
                & (bus0_carrier != "gas")
                & links["active"]
            ]
            assert violators.empty, (
                f"Year {year}: links produce gas at port {port} (not bus1) — "
                f"breaks _add_green_gas_production_constraint bus1 contract: "
                f"{sorted(violators['carrier'].unique())}"
            )

        # Contract 2: gas-to-power links consume gas via bus0, never via an
        # auxiliary negative-efficiency port.
        produces_electricity = pd.Series(False, index=links.index)
        for port in any_output_ports:
            bus_col = f"bus{port}"
            eff_col = "efficiency" if port == "1" else f"efficiency{port}"
            if bus_col not in links.columns or eff_col not in links.columns:
                continue
            produces_electricity |= (
                links[bus_col].isin(electricity_buses)
                & (links[eff_col] > 0)
                & links["active"]
            )
        for port in any_output_ports:
            bus_col = f"bus{port}"
            eff_col = "efficiency" if port == "1" else f"efficiency{port}"
            if bus_col not in links.columns or eff_col not in links.columns:
                continue
            violators = links[
                links[bus_col].isin(gas_buses)
                & (links[eff_col] < 0)
                & produces_electricity
                & links["active"]
            ]
            assert violators.empty, (
                f"Year {year}: links consume gas via aux port {port} (not bus0) "
                f"while producing electricity — breaks "
                f"_add_green_gas_production_constraint bus0 contract: "
                f"{sorted(violators['carrier'].unique())}"
            )


@pytest.mark.parametrize("cc", ["AT"])
def test_net_zero_electricity_constraint_statistics(nc, cc):
    """
    Verify the net-zero electricity constraint via ``pypsa.statistics``:
    yearly renewable supply >= yearly electricity demand on electricity buses.

    Renewable supply (LHS) sums:
      - Generator supply on AC / low voltage buses (renewables: wind, solar,
        ror, …).
      - Link supply attributable to green fuels (``bus0`` ∈ {gas, H2, solid
        biomass, methanol} buses) plus battery and home-battery discharger
        Links (``bus0`` ∈ battery store buses).
      - StorageUnit supply on electricity buses (PHS dispatch, hydro
        reservoir dispatch).

    Electricity demand (RHS) sums:
      - Load withdrawal on electricity buses.
      - Link withdrawal on electricity buses (chargers, P2X, methanolisation
        aux-power, …).
      - StorageUnit withdrawal on electricity buses (PHS pumping).

    Storage cycling losses are captured naturally: chargers add to demand at
    full input while their matching dischargers contribute to supply at
    discharge efficiency.

    Parameters
    ----------
    nc
        The network collection.
    cc
        The country code.
    """
    cfg = require_config(nc, "mods", "net_zero_electricity", enable=False)
    start_year = cfg[cc]
    electricity_bus_carrier = ["AC", "low voltage"]
    groupby = ["country", "carrier", "bus_carrier"]
    common_kwargs = {
        "groupby": groupby,
        "bus_carrier": electricity_bus_carrier,
        "drop_zero": True,
        "nice_names": False,
    }
    renewables = sorted(
        set(nc[start_year].meta["renewable"])
        | set(set(nc[start_year].meta["renewable"]["hydro"]["carriers"]))
        | {"solar rooftop"}
    )
    compare = ["network"] + groupby

    # only test networks after start year
    nc = pypsa.NetworkCollection(
        {k: v for k, v in nc.networks.items() if int(k) >= int(start_year)}
    )

    # Electricity supply from renewable Generators
    generators = nc.statistics.supply(
        components=["Generator", "StorageUnit"], **common_kwargs
    ).pipe(filter_by, country=cc, carrier=renewables)

    # Electricity supply from renewable fuels
    fuels_buses = nc[start_year].buses.query(f"carrier.isin({cfg['fuels']})").index
    link_supply = nc.statistics.supply(
        groupby=["country", "carrier", "bus_carrier", "bus0"],
        components="Link",
        bus_carrier=electricity_bus_carrier,
        nice_names=False,
    ).pipe(filter_by, country=cc, bus0=list(fuels_buses))

    # Electricity supply from batteries
    battery_supply = nc.statistics.supply(
        components="Link",
        carrier=[
            "battery discharger",
            "home battery discharger",
            "PHS discharger",
            "hydro discharger",
        ],
        **common_kwargs,
    ).pipe(filter_by, country=cc)

    supply = pd.concat(
        [
            generators.groupby(compare).sum(),
            link_supply.groupby(compare).sum(),
            battery_supply.groupby(compare).sum(),
        ]
    )

    # Electricity demand
    electricity_demand = (
        nc.statistics.withdrawal(
            groupby=groupby,
            components=["Load", "Link", "StorageUnit"],
            bus_carrier=electricity_bus_carrier,
            drop_zero=True,
            nice_names=False,
        )
        .pipe(filter_by, country=cc)
        .pipe(filter_by, carrier=["electricity distribution grid", "DC"], exclude=True)
    )

    eb_lines = nc.statistics.energy_balance(
        groupby=groupby + ["bus0", "bus1"],
        components="Line",
        nice_names=False,
    )
    domestic_line_losses = eb_lines[
        eb_lines.index.get_level_values("bus0").str.startswith(cc)
        & eb_lines.index.get_level_values("bus1").str.startswith(cc)
    ]

    distribution_grid_losses = nc.statistics.energy_balance(
        components="Link", carrier="electricity distribution grid", **common_kwargs
    ).pipe(filter_by, country=cc)

    demand = pd.concat(
        [
            electricity_demand.groupby(compare).sum(),
            domestic_line_losses.groupby(compare).sum(),
            distribution_grid_losses.groupby(compare).sum(),
        ]
    )

    for year in nc.index:
        s = supply.xs(year).sum()
        d = demand.xs(year).sum()
        assert s >= d * 0.999, (
            f"Year {year}, country {cc}: renewable supply {s:,.0f} "
            f"MWh < electricity demand {d:,.0f} MWh"
        )


@pytest.mark.parametrize("cc", ["AT"])
def test_green_gas_constraint_statistics(nc, cc):
    """
    Verify the green-gas constraint via ``pypsa.statistics``: yearly
    green-gas production >= yearly gas-attributable-to-electricity for
    gas-to-power links.

    Supply (LHS): ``Link`` supply on gas buses with ``bus0`` not on a gas
    bus (biogas-to-gas, biogas-to-gas CC, Sabatier). Pipelines / imports
    (``bus0`` carrier ``gas``) are excluded.

    Demand (RHS): for each gas-to-power Link, gas input weighted by the
    electricity output share = ``elec_output / total_output``.  Computed
    via :func:`evals.utils.calculate_input_share` with
    ``apply_scaling=False`` (input-side magnitudes), then filtered to the
    ``gas`` ``bus_carrier`` level.

    This matches ``_add_green_gas_production_constraint`` exactly,
    including the per-link ``electricity_fraction`` adjustment for CHPs.
    """
    cfg = require_config(nc, "mods", "net_zero_electricity", enable=False)
    start_year = cfg[cc]
    nc = pypsa.NetworkCollection(
        {k: v for k, v in nc.networks.items() if int(k) >= int(start_year)}
    )

    # contract: "all networks have same has buses" is tested
    gas_buses = nc[start_year].buses.query("carrier == 'gas'").index

    # Supply: green gas production
    green_gas = (
        (
            nc.statistics.supply(
                groupby=["country", "carrier", "bus0"],
                components="Link",
                bus_carrier="gas",
                drop_zero=True,
                nice_names=False,
            )
            .pipe(filter_by, country=cc)
            .pipe(
                filter_by, bus0=list(gas_buses), exclude=True
            )  # drop gas2gas pipelines
        )
        .groupby(["network", "carrier"])
        .sum()
    )

    # Demand: gas x electricity_fraction for gas-to-power links
    gas_for_power = (
        (
            nc.statistics.energy_balance(
                groupby=["country", "carrier", "bus_carrier"],
                components="Link",
                drop_zero=True,
                nice_names=False,
            )
            .pipe(filter_by, country=cc)
            .drop(["co2", "co2 stored"], level="bus_carrier")
            .pipe(filter_for_carrier_connected_to, ["AC", "low voltage"])
            .pipe(
                calculate_input_share,
                bus_carrier=["AC", "low voltage"],
                apply_scaling=False,
            )
            .pipe(filter_by, bus_carrier="gas")
        )
        .groupby(["network", "carrier"])
        .sum()
    )

    for year in nc.index:
        supply = green_gas.xs(year)
        demand = gas_for_power.xs(year)
        assert green_gas.xs(year).sum() >= gas_for_power.xs(year).sum() * 0.999, (
            f"Year {year}, country {cc}: green gas {supply.sum():.0f} "
            f"MWh < electricity-attributable gas for power {demand.sum():.0f} MWh"
        )


@pytest.mark.parametrize("cc", ["AT"])
def test_green_h2_constraint_statistics(nc, cc):
    """
    Verify the green-H2 constraint via ``pypsa.statistics``: yearly
    green-H2 production >= yearly H2 used for power
    (× ``electricity_fraction``) plus full H2 used by other-green-fuel
    synthesis (Sabatier, methanolisation).

    Supply (LHS): ``Link`` supply on H2 buses with ``bus0`` on an
    electricity bus (H2 Electrolysis). SMR (bus0 = gas) and H2 pipelines
    (bus0 = H2) are excluded.

    Demand (RHS):
      1. H2 × ``electricity_fraction`` for H2-to-power links — computed via
         :func:`calculate_input_share` with ``apply_scaling=False``,
         filtered to ``bus_carrier="H2"``.
      2. Full H2 withdrawal for H2-to-other-fuel synthesis (Sabatier,
         methanolisation) — matches the constraint, which counts the
         entire H2 input regardless of co-products.

    This matches ``_add_hydrogen_production_constraint`` exactly.
    """
    cfg = require_config(nc, "mods", "net_zero_electricity", enable=False)
    start_year = cfg[cc]
    nc = pypsa.NetworkCollection(
        {k: v for k, v in nc.networks.items() if int(k) >= int(start_year)}
    )

    buses = nc[start_year].buses
    h2_buses = buses.query("carrier == 'H2'").index
    h2_source_buses = buses[buses.carrier.isin(cfg["h2_sources"])].index
    other_fuels = [c for c in cfg["fuels"] if c != "H2"]

    # Supply: green H2 production (bus0 carrier ∈ configured h2_sources)
    h2_supply = nc.statistics.supply(
        groupby=["country", "carrier", "bus0"],
        components="Link",
        bus_carrier="H2",
        drop_zero=True,
        nice_names=False,
    ).pipe(filter_by, country=cc)
    green_h2 = h2_supply[h2_supply.index.get_level_values("bus0").isin(h2_source_buses)]

    # ── Demand part 1: H2 × electricity_fraction for H2-to-power ────────────
    h2_for_power = (
        nc.statistics.energy_balance(
            groupby=["country", "carrier", "bus_carrier"],
            components="Link",
            drop_zero=True,
            nice_names=False,
        )
        .pipe(filter_by, country=cc)
        .pipe(
            calculate_input_share,
            bus_carrier=["AC", "low voltage"],
            apply_scaling=False,
        )
        .pipe(filter_by, bus_carrier="H2")
    )

    # ── Demand part 2: full H2 withdrawal by H2-to-other-fuel synthesis ─────
    h2_to_fuel_supply = nc.statistics.supply(
        groupby=["country", "carrier", "bus0"],
        components="Link",
        bus_carrier=other_fuels,
        drop_zero=True,
        nice_names=False,
    ).pipe(filter_by, country=cc)
    h2_to_fuel_carriers = (
        h2_to_fuel_supply[
            h2_to_fuel_supply.index.get_level_values("bus0").isin(h2_buses)
        ]
        .index.get_level_values("carrier")
        .unique()
    )
    h2_withdrawal = nc.statistics.withdrawal(
        groupby=["country", "carrier"],
        components="Link",
        bus_carrier="H2",
        drop_zero=True,
        nice_names=False,
    ).pipe(filter_by, country=cc)
    h2_for_fuel = h2_withdrawal[
        h2_withdrawal.index.get_level_values("carrier").isin(h2_to_fuel_carriers)
    ]

    for year in nc.index:
        supply = green_h2.xs(year)
        power_demand = h2_for_power.xs(year)
        fuel_demand = h2_for_fuel.xs(year)
        assert supply.sum() + 1e-4 >= power_demand.sum() + fuel_demand.sum(), (
            f"Year {year}, country {cc}: green H2 {supply.sum():.0f} MWh < "
            f"H2 for power {power_demand.sum():.0f} MWh + "
            f"H2 for fuel synthesis {fuel_demand.sum():.0f} MWh"
        )


@pytest.mark.parametrize("cc", ["AT"])
def test_green_methanol_constraint_statistics(nc, cc):
    """
    Verify the green-methanol constraint via ``pypsa.statistics``: yearly
    green-methanol production >= yearly methanol-attributable-to-electricity
    for methanol-to-power links.

    Supply (LHS): ``Link`` supply on methanol buses with ``bus0`` not on a
    methanol bus (biomass-to-methanol, biomass-to-methanol CC,
    methanolisation). Methanol pipelines / imports (``bus0`` carrier
    ``methanol``) are excluded.

    Demand (RHS): for each methanol-to-power Link, methanol input weighted
    by the electricity output share.  Computed via
    :func:`calculate_input_share` with ``apply_scaling=False``, then
    filtered to the ``methanol`` ``bus_carrier`` level.

    This matches ``_add_methanol_production_constraint`` exactly.
    """
    cfg = require_config(nc, "mods", "net_zero_electricity", enable=False)
    start_year = cfg[cc]
    nc = pypsa.NetworkCollection(
        {k: v for k, v in nc.networks.items() if int(k) >= int(start_year)}
    )

    methanol_buses = nc[start_year].buses.query("carrier == 'methanol'").index

    # ── Supply: green methanol production ───────────────────────────────────
    methanol_supply = (
        nc.statistics.supply(
            groupby=["country", "carrier", "bus0"],
            components="Link",
            bus_carrier="methanol",
            drop_zero=True,
            nice_names=False,
        )
        .pipe(filter_by, country=cc)
        .pipe(filter_by, bus0=methanol_buses, exclude=True)
    )

    # ── Demand: methanol × electricity_fraction for methanol-to-power ──────
    methanol_for_power = (
        nc.statistics.energy_balance(
            groupby=["country", "carrier", "bus_carrier"],
            components="Link",
            drop_zero=True,
            nice_names=False,
        )
        .pipe(filter_by, country=cc)
        .pipe(
            calculate_input_share,
            bus_carrier=["AC", "low voltage"],
            apply_scaling=False,
        )
        .pipe(filter_by, bus_carrier="methanol")
    )

    # methanol supply and demand are often empty
    for year in nc.index:
        supply_sum = filter_by(methanol_supply, network=year).sum()
        demand_sum = filter_by(methanol_for_power, network=year).sum()
        assert supply_sum + 1e-6 >= demand_sum, (
            f"Year {year}, country {cc}: green methanol {supply_sum:.0f} "
            f"MWh < electricity-attributable methanol for power "
            f"{demand_sum:.0f} MWh"
        )


def _sum_flows(flows_t: pd.DataFrame, idx: pd.Index) -> pd.Series:
    """
    Sum component flows across columns, returning zeros for an empty index.

    Parameters
    ----------
    flows_t : pd.DataFrame
        Time-indexed flow DataFrame (e.g. ``n.lines_t.p0`` or
        ``n.links_t.p0``).  Columns are component names.
    idx : pd.Index
        Column labels to select and sum.  Must be a subset of
        ``flows_t.columns``; a mismatch will raise ``KeyError``.

    Returns
    -------
    pd.Series
        Per-snapshot summed flow.  All zeros when ``idx`` is empty,
        with the same index as ``flows_t``.
    """
    if idx.empty:
        return pd.Series(0.0, index=flows_t.index)
    return flows_t[idx].sum(axis=1)


def test_tyndp_ntc_flow_limits_satisfied(nc, pytestconfig):
    """
    Per-snapshot net flow on every TYNDP corridor must not exceed NTC capacity.

    NTC flow limits are only enforced for the planning horizons configured in
    ``mods.tyndp_lower_bounds.years`` (see
    :func:`mods.constraints.add_cross_border_flow_limits`). In unconstrained
    horizons the optimizer is free to build transmission beyond the NTC values,
    so those years are skipped here to match the constraint's scope.
    """
    require_config(nc, "mods", "tyndp_cross_border_flow_limits", enable=False)
    lower_bounds_years = require_config(nc, "mods", "tyndp_lower_bounds")["years"]

    ntc_path = (
        pytestconfig.rootpath / "resources" / "tyndp_transmission_trajectories.csv"
    )
    ntc_df = pd.read_csv(ntc_path)

    for year_str, n in nc.networks.items():
        year_int = int(year_str)
        # NTC limits are only applied for configured years; skip the rest.
        if year_int not in lower_bounds_years:
            continue

        df_year = ntc_df[ntc_df["year"] == year_int]

        relevant_links, relevant_lines = get_relevant_links_and_lines(n)

        for row in df_year.itertuples():
            from_node: str = row.from_node
            to_node: str = row.to_node

            lines_dir_idx = relevant_lines[
                (relevant_lines["bus0_tyndp"] == from_node)
                & (relevant_lines["bus1_tyndp"] == to_node)
            ].index
            lines_indir_idx = relevant_lines[
                (relevant_lines["bus0_tyndp"] == to_node)
                & (relevant_lines["bus1_tyndp"] == from_node)
            ].index
            links_dir_idx = relevant_links[
                (relevant_links["bus0_tyndp"] == from_node)
                & (relevant_links["bus1_tyndp"] == to_node)
            ].index
            links_indir_idx = relevant_links[
                (relevant_links["bus0_tyndp"] == to_node)
                & (relevant_links["bus1_tyndp"] == from_node)
            ].index

            if (
                lines_dir_idx.empty
                and lines_indir_idx.empty
                and links_dir_idx.empty
                and links_indir_idx.empty
            ):
                continue

            net_flow_dir = (
                -_sum_flows(n.lines_t.p1, lines_dir_idx)
                - _sum_flows(n.lines_t.p0, lines_indir_idx)
                - _sum_flows(n.links_t.p1, links_dir_idx)
                - _sum_flows(n.links_t.p0, links_indir_idx)
            )

            net_flow_indir = (
                -_sum_flows(n.lines_t.p0, lines_dir_idx)
                - _sum_flows(n.lines_t.p1, lines_indir_idx)
                - _sum_flows(n.links_t.p0, links_dir_idx)
                - _sum_flows(n.links_t.p1, links_indir_idx)
            )

            # 1e-3 MW tolerance accounts for HiGHS primal feasibility residual (~1e-7)
            assert net_flow_dir.max() <= row.direct_capacity + 1e-3, (
                f"NTC violation in {year_int}: {from_node}→{to_node} "
                f"max flow {net_flow_dir.max():.1f} MW exceeds "
                f"capacity {row.direct_capacity:.1f} MW"
            )
            assert net_flow_indir.max() <= row.indirect_capacity + 1e-3, (
                f"NTC violation in {year_int}: {to_node}→{from_node} "
                f"max flow {net_flow_indir.max():.1f} MW exceeds "
                f"capacity {row.indirect_capacity:.1f} MW"
            )
