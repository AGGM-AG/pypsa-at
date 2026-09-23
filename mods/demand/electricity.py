# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Electricity demand update module."""

import logging
import zipfile
from pathlib import Path

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.clustering.utils import map_at_nuts3_to_nuts2
from mods.demand.annual import region_by_load

logger = logging.getLogger(__name__)

#: Carriers of the Loads the electricity base load is split into.
BASE_LOAD_CARRIERS = (
    "electricity for residential",
    "electricity for services",
    "electricity for road",
    "electricity for rail",
    "agriculture electricity",
)


def base_load_load_splitting(
    n: pypsa.Network, pop_weighted_energy_totals: pd.DataFrame
) -> None:
    """
    Split the electricity base load into sectoral components.

    The base load time series of every node is distributed without
    remainder into sectoral Loads, using weights normalised over the
    sectoral energies from the JRC-IDEES based energy totals. All parts
    keep the measured ENTSO-E profile shape and sum up to the original
    base load, so grid losses and the statistical gap between measured
    load and the JRC-IDEES bottom-up totals are distributed across
    the sectors.

    The sectoral energies are composed as follows:

    - ``electricity for residential`` and ``electricity for services``
      exclude the space and water heating amounts, because those are
      already deducted from the base load in ``build_heat_demand()``.
    - ``electricity for road`` uses the aggregate ``electricity road``
      column, which includes the PHEV electricity share missing from
      the granular vehicle-class columns.
    - ``electricity for rail`` covers rail passenger and freight.
    - the ``total agriculture electricity`` share replaces the flat
      ``agriculture electricity`` Loads added in ``add_agriculture()``
      with a profiled time series. This avoids double counting the
      demand, which would occur if the amount stayed in the base load
      next to the flat Loads.

    Negative sectoral energies from source data inconsistencies (e.g.
    Norway reports less total services electricity than services space
    and water heating combined) are clipped to zero with a warning.

    The original base load components are removed from the network,
    because their demand is fully distributed to the sectoral Loads.

    Parameters
    ----------
    n
        The Network during ``prepare_sector_network``.
    pop_weighted_energy_totals
        The population weighted energy totals in TWh per calendar year.

    Returns
    -------
    :
        Updates the network in place.
    """
    pwet = pop_weighted_energy_totals
    nodes = pwet.index

    base_load_idx = n.loads.query("carrier == 'electricity'").index
    base_load = n.loads_t["p_set"][base_load_idx]

    # sanity check: both indices contain the same entries
    if not (differences := base_load.columns.symmetric_difference(nodes)).empty:
        raise ValueError(
            f"Electricity base load and energy totals indices are not identical: {differences}"
        )

    # n.add requires p_set columns to match the passed names positionally
    base_load = base_load[nodes]

    # annual sectoral energies in TWh per calendar year; the unit cancels
    # out in the weight normalisation below
    sector_energies = pd.DataFrame(
        {
            "electricity for residential": (
                pwet["electricity residential"]
                - pwet["electricity residential space"]  # heat already deducted
                - pwet["electricity residential water"]  # heat already deducted
            ),
            "electricity for services": (
                pwet["electricity services"]
                - pwet["electricity services space"]  # heat already deducted
                - pwet["electricity services water"]  # heat already deducted
            ),
            "electricity for road": pwet["electricity road"],
            "electricity for rail": pwet["electricity rail"],
            # replaces the flat Loads from add_agriculture(), see below
            "agriculture electricity": pwet["total agriculture electricity"],
        }
    )

    if not (negative := sector_energies[sector_energies.lt(0).any(axis=1)]).empty:
        logger.warning(
            f"Clipping negative sectoral energies to zero [TWh/a]:\n{negative.round(3)}"
        )
        sector_energies = sector_energies.clip(lower=0)

    weights = sector_energies.div(sector_energies.sum(axis="columns"), axis="index")

    # sanity check: 0/0 yields NaN weights for nodes without any sectoral energy
    if not (invalid := weights[weights.isna().any(axis="columns")]).empty:
        raise ValueError(
            f"Nodes without any sectoral energy: {invalid.index.to_list()}"
        )

    # distribute the base load without remainder: all parts keep the ENTSO-E
    # profile. No need to register the new carriers because
    # add_missing_carriers() runs at the end of prepare_sector_network.py.
    new_load_carriers = weights.columns.drop("agriculture electricity")
    for carrier in new_load_carriers:
        n.add(
            "Load",
            nodes,
            suffix=f" {carrier}",
            bus=n.loads.loc[nodes, "bus"],
            carrier=carrier,
            p_set=base_load.mul(weights[carrier], axis="columns"),
        )

    # the agriculture share replaces the flat Loads from add_agriculture():
    # a time-varying p_set takes precedence over the static value
    agriculture_loads = nodes + " agriculture electricity"
    if not (missing := agriculture_loads.difference(n.loads.index)).empty:
        raise ValueError(f"Missing agriculture electricity Loads: {missing}")
    agriculture_profile = base_load.mul(
        weights["agriculture electricity"], axis="columns"
    )
    agriculture_profile.columns = agriculture_loads

    # the profiled shares intentionally rescale the agriculture demand to the
    # measured base load: factor = measured base energy / JRC bottom-up total
    weightings = n.snapshot_weightings.generators
    profile_energy = agriculture_profile.mul(weightings, axis="index").sum()
    flat_energy = n.loads.loc[agriculture_loads, "p_set"] * weightings.sum()
    rescaling = (profile_energy / flat_energy).round(2)
    logger.info(
        "Replaced flat agriculture electricity Loads with profiled shares; "
        f"energy rescaling factors (measured/JRC): min {rescaling.min()}, "
        f"median {rescaling.median()}, max {rescaling.max()}"
    )

    n.loads_t["p_set"][agriculture_loads] = agriculture_profile
    n.loads.loc[agriculture_loads, "p_set"] = 0.0

    # the base load is fully distributed to the sectoral Loads; skipped
    # nodes keep their base load Load components
    n.remove("Load", nodes)

    logger.info(
        f"Split the electricity base load into sectoral Loads {list(new_load_carriers)}"
        " and moved the 'agriculture electricity' share onto the existing Loads."
    )


# =============================================================================
# Austrian base load regionalisation (issue pypsa-at-planning#300)
# =============================================================================

#: NEA energy carrier label for electricity.
NEA_ELECTRICITY = "Elektrische Energie"

#: NEA useful energy category holding space heating, hot water and cooling.
NEA_HEAT_USE = "Raumklima und Warmwasser"

#: NEA sectors ("Bereich") mapped onto the base-load carriers. Industry
#: belongs to the industry override, "Sonstiger Landverkehr" to the road
#: transport override and "Transport in Rohrfernleitungen" is endogenous
#: gas pipeline compression.
NEA_BASE_LOAD_SECTORS = {
    "electricity for residential": "Private Haushalte",
    "electricity for services": "Offentliche und Private Dienstleistungen",
    "agriculture electricity": "Landwirtschaft",
    "electricity for rail": "Eisenbahn",
}

#: Carriers whose electric space and water heating is endogenous in the
#: model (heat pumps, resistive heaters) and therefore excluded from the
#: NEA target. Cooling inside the same NEA category is a known gap.
NEA_HEAT_EXCLUDED_CARRIERS = ("electricity for residential", "electricity for services")

#: CSV inside the Energiemosaik data package with energy use by purpose
#: and sector per municipality.
ENERGIEMOSAIK_FILE = "7_AT_EVnachVZETDetailNutz.csv"

#: Energiemosaik columns used as the NUTS3 distribution key of a carrier.
#: The "Motoren / Elektrogeräte" purpose is the closest proxy for
#: non-heating electricity, since the package has no carrier split.
ENERGIEMOSAIK_COLUMNS = {
    "electricity for residential": "Energieverbrauch Motoren / Elektrogeräte Wohnen (MWh / a)",
    "electricity for services": "Energieverbrauch Motoren / Elektrogeräte Dienstleistungen (MWh / a)",
    "agriculture electricity": "Energieverbrauch Motoren / Elektrogeräte Land- und Forstwirtschaft (MWh / a)",
}


def nea_parent(region: str) -> str:
    """
    Return the NEA Bundesland (NUTS2) code of an Austrian model region.

    Parameters
    ----------
    region
        Austrian NUTS2 or NUTS3 model region code, e.g. ``"AT125"`` or
        ``"AT12"``. Osttirol (``"AT333"``) belongs to Tirol (``"AT33"``).

    Returns
    -------
    :
        The NUTS2 code used in the NEA dataset.

    Raises
    ------
    ValueError
        If the region is not an Austrian region.
    """
    if not region.startswith("AT"):
        raise ValueError(f"Cannot determine the NEA Bundesland for region {region!r}.")
    return region[:4]


def nea_base_load_targets(nea: pd.DataFrame, source_year: int) -> pd.DataFrame:
    """
    Aggregate the NEA electricity demand per Bundesland and base-load carrier.

    Parameters
    ----------
    nea
        Stacked NEA data in long format (``build_nea_at`` output).
    source_year
        NEA year to use.

    Returns
    -------
    :
        Electricity demand in TWh per year, indexed by NUTS2 code with one
        column per base-load carrier. Space heating, hot water and cooling
        electricity is excluded for households and services.

    Raises
    ------
    ValueError
        If the NEA dataset has no electricity rows for the source year.
    """
    electricity = nea[
        nea["Energieträger"].eq(NEA_ELECTRICITY) & nea["year"].eq(source_year)
    ]
    if electricity.empty:
        raise ValueError(
            f"The NEA dataset has no electricity demand for source year {source_year}. "
            f"Available years: {sorted(nea['year'].unique())}."
        )
    targets = {}
    for carrier, sector in NEA_BASE_LOAD_SECTORS.items():
        rows = electricity[electricity["Bereich"].eq(sector)]
        if carrier in NEA_HEAT_EXCLUDED_CARRIERS:
            rows = rows[rows["Nutzenergiekategorie"].ne(NEA_HEAT_USE)]
        targets[carrier] = rows.groupby("NUTS-2 Code")["value_TWh"].sum()
    targets = pd.DataFrame(targets).fillna(0.0)
    targets.index.name = "parent"
    return targets


def read_energiemosaik(archive: str | Path) -> pd.DataFrame:
    """
    Read the municipality electricity proxies from the Energiemosaik package.

    Parameters
    ----------
    archive
        Path to ``Energiemosaik_Datenpaket_AT.zip``.

    Returns
    -------
    :
        Annual energy in MWh indexed by municipality code (``Gemeindecode``)
        with one column per carrier in :data:`ENERGIEMOSAIK_COLUMNS`, plus
        the ``district`` code used as mapping fallback.
    """
    with zipfile.ZipFile(archive) as package, package.open(ENERGIEMOSAIK_FILE) as csv:
        data = pd.read_csv(csv, sep=";", encoding="cp1252", index_col=0)
    if missing := set(ENERGIEMOSAIK_COLUMNS.values()) - set(data.columns):
        raise ValueError(
            f"Energiemosaik file {ENERGIEMOSAIK_FILE} lacks columns {missing}."
        )
    data = data.set_index(data["Gemeindecode"].astype(int))
    proxies = data[list(ENERGIEMOSAIK_COLUMNS.values())].rename(
        columns={v: k for k, v in ENERGIEMOSAIK_COLUMNS.items()}
    )
    return proxies.assign(district=data["Bezirkscode"].astype(int))


def municipality_regions(register: pd.DataFrame, nuts3_regions: bool) -> pd.Series:
    """
    Map Austrian municipality codes to model regions.

    Parameters
    ----------
    register
        Statistik Austria municipality register (``build_statistik_at_regions``
        output) with ``municipality_code`` and ``nuts3_code`` columns.
    nuts3_regions
        ``True`` if the Austrian model regions are NUTS3 regions, ``False``
        for NUTS2 regions (AT10 clustering, Osttirol kept separate).

    Returns
    -------
    :
        Model region indexed by integer municipality code.
    """
    rows = register.dropna(subset=["municipality_code"]).drop_duplicates(
        "municipality_code"
    )
    regions = rows.set_index(rows["municipality_code"].astype(int))["nuts3_code"]
    if not nuts3_regions:
        regions = regions.map(map_at_nuts3_to_nuts2)
    return regions.rename("region")


def district_regions(register: pd.DataFrame, nuts3_regions: bool) -> pd.Series:
    """
    Map Austrian district codes to the model region holding most of their population.

    Municipalities merged or renamed after the Energiemosaik data year are
    missing from the current register; their district still identifies the
    model region.

    Parameters
    ----------
    register
        Statistik Austria municipality register with ``district_code``,
        ``nuts3_code`` and ``population`` columns.
    nuts3_regions
        ``True`` for NUTS3 model regions, ``False`` for NUTS2 regions.

    Returns
    -------
    :
        Model region indexed by integer district code.
    """
    rows = register.dropna(subset=["district_code"])
    population = (
        rows.groupby([rows["district_code"].astype(int), "nuts3_code"])["population"]
        .sum()
        .reset_index()
        # nuts3_code as secondary key keeps the choice deterministic on ties
        .sort_values(["population", "nuts3_code"])
        .drop_duplicates("district_code", keep="last")
    )
    regions = population.set_index("district_code")["nuts3_code"]
    if not nuts3_regions:
        regions = regions.map(map_at_nuts3_to_nuts2)
    return regions.rename("region")


def aggregate_energiemosaik(
    energiemosaik: pd.DataFrame,
    regions: pd.Series,
    fallback_regions: pd.Series | None = None,
) -> pd.DataFrame:
    """
    Sum the municipality electricity proxies per model region.

    Parameters
    ----------
    energiemosaik
        Output of :func:`read_energiemosaik`.
    regions
        Output of :func:`municipality_regions`.
    fallback_regions
        Output of :func:`district_regions`, used for municipalities that are
        missing from ``regions``.

    Returns
    -------
    :
        Annual energy in MWh per model region and carrier.

    Raises
    ------
    ValueError
        If municipalities cannot be mapped to a model region.
    """
    region = pd.Series(energiemosaik.index.map(regions), index=energiemosaik.index)
    if (
        unmapped := energiemosaik.index[region.isna()]
    ).size and fallback_regions is not None:
        region[unmapped] = energiemosaik.loc[unmapped, "district"].map(fallback_regions)
        logger.warning(
            f"Mapped {unmapped.size} Energiemosaik municipalities missing from the "
            f"register via their district: {unmapped.to_list()[:10]}"
        )
    if (unmapped := energiemosaik.index[region.isna()]).size:
        raise ValueError(
            f"{unmapped.size} Energiemosaik municipalities have no model region: "
            f"{unmapped.to_list()[:10]}"
        )
    return energiemosaik.drop(columns="district").groupby(region.to_numpy()).sum()


def build_base_load_table(targets: pd.DataFrame, keys: pd.DataFrame) -> pd.DataFrame:
    """
    Distribute the Bundesland targets to model regions with the given keys.

    Parameters
    ----------
    targets
        Output of :func:`nea_base_load_targets`.
    keys
        Distribution key values per Austrian model region (index) and
        carrier (columns). Keys are normalised inside each Bundesland, so
        any positive quantity works (energy, population).

    Returns
    -------
    :
        Long table with ``region``, ``carrier`` and ``value_TWh`` columns.
        The values of every carrier sum to the NEA target.

    Raises
    ------
    ValueError
        If keys or targets do not cover the same Bundesländer and carriers.
    """
    keys = keys.reindex(columns=targets.columns)
    if keys.isna().any().any():
        raise ValueError(
            f"Distribution keys are missing for {keys.columns[keys.isna().any()].to_list()}."
        )
    parents = keys.index.map(nea_parent)
    if missing := set(parents) - set(targets.index):
        raise ValueError(
            f"No NEA target for the Bundesland of regions {sorted(missing)}."
        )
    if missing := set(targets.index) - set(parents):
        raise ValueError(f"No model region for NEA Bundesländer {sorted(missing)}.")
    weights = keys.div(keys.groupby(parents).transform("sum"))
    if weights.isna().any().any():
        raise ValueError(
            "A Bundesland has zero distribution key for at least one carrier."
        )
    values = weights.mul(targets.reindex(parents).to_numpy())
    table = (
        values.rename_axis(index="region", columns="carrier")
        .stack()
        .rename("value_TWh")
    )
    return table.reset_index().sort_values(["carrier", "region"], ignore_index=True)


def apply_electricity_base_load(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Rebuild the Austrian base electricity Loads from NEA and regional keys.

    Every base-load carrier keeps the Austrian aggregate profile of its
    Loads, i.e. the measured ENTSO-E shape after the upstream deductions.
    The regional series are rebuilt as ``profile shape × regional NEA
    target × horizon factor``, so the national energy is calibrated to the
    NEA base year and the regions follow the prepared distribution table.
    The rebuild removes the negative hours that the population-weighted
    heat deduction produced in regions with a small base load.

    When the Austrian road transport override is active, the
    ``electricity for road`` Loads are removed from the Austrian nodes,
    because the NEA road electricity already feeds the EV Loads.

    Non-Austrian Loads are not touched.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, config,
        and wildcards.

    Returns
    -------
    :
        Updates the network in place.

    Raises
    ------
    ValueError
        If the horizon has no scaling factor, or the table and the network
        disagree on the Austrian regions.
    """
    cfg = snakemake.params.electricity_base_load
    if not cfg["enable"]:
        return

    year = int(snakemake.wildcards.planning_horizons)
    try:
        factor = cfg["scaling_factors"][year]
    except KeyError as err:
        raise ValueError(
            f"No base load scaling factor for {year} in "
            f"'mods: electricity_base_load: scaling_factors:' ({cfg['scaling_factors']})."
        ) from err

    table = pd.read_csv(snakemake.input.electricity_base_load_at)
    weightings = n.snapshot_weightings.generators

    if snakemake.params.use_nea_transport_demand:
        regions = region_by_load(n)
        road = n.loads.index[
            regions.str.startswith("AT") & n.loads.carrier.eq("electricity for road")
        ]
        dropped = n.loads_t.p_set[road].mul(weightings, axis=0).sum().sum() / 1e6
        n.remove("Load", road)
        logger.info(
            f"Removed {len(road)} Austrian 'electricity for road' Loads ({dropped:.2f} TWh); "
            "the NEA road electricity is carried by the EV Loads."
        )

    regions = region_by_load(n)
    is_at = regions.str.startswith("AT")
    for carrier, group in table.groupby("carrier"):
        loads = n.loads.index[is_at & n.loads.carrier.eq(carrier)]
        targets = group.set_index("region")["value_TWh"]
        if (differences := targets.index.symmetric_difference(regions[loads])).size:
            raise ValueError(
                f"Regions of the base load table and the '{carrier}' Loads differ: "
                f"{differences.to_list()}"
            )

        profile = n.loads_t.p_set[loads].sum(axis="columns")
        energy = profile.mul(weightings).sum()
        if energy <= 0:
            raise ValueError(f"The Austrian '{carrier}' Loads have no positive energy.")
        shape = profile / energy  # 1/h, integrates to one over the year

        new_energy = targets.reindex(regions[loads]) * 1e6 * factor  # MWh
        new_energy.index = loads
        n.loads_t.p_set[loads] = pd.DataFrame(
            shape.to_numpy()[:, None] * new_energy.to_numpy()[None, :],
            index=n.snapshots,
            columns=loads,
        )
        n.loads.loc[loads, "p_set"] = 0.0
        logger.info(
            f"Rebuilt {len(loads)} Austrian '{carrier}' Loads: {energy / 1e6:.2f} TWh -> "
            f"{new_energy.sum() / 1e6:.2f} TWh (NEA target x factor {factor})."
        )
