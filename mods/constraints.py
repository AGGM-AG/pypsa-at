"""Module to collect PyPSA-AT constraints."""

import logging

import pandas as pd
import pypsa

from mods.pemmdb_overwrites import aggregate_by_cluster_and_country
from mods.tyndp_utils import get_relevant_links_and_lines
from scripts.prepare_sector_network import determine_emission_sectors

logger = logging.getLogger(__name__)


def add_national_co2_budgets(
    n: pypsa.Network, snakemake, national_co2_budgets: dict, investment_year: int
) -> None:
    """
    Replaces the PyPSA-DE national CO2 budget function.

    This function
      - adds CO2 national constraints based on a balance at
        the `co2 atmosphere` bus
      - scales emissions from kerosene for aviation with the
        domestic / total aviation ratio
      - emissions (positive and negative) are balanced at the
        respective model region

    Differences to PyPSA-DE
      - Does not distinguish E-Fuels like BioMethane or synthetic oil.

    Parameters
    ----------
    n
        The pypsa network to add the constraints to.
    snakemake
        The snakemake workflow object.
    national_co2_budgets
        A dictionary with country codes as key and years emission
        limits as values.
    investment_year
        The myopic planning horizon.

    Notes
    -----
    This function overwrites the PyPSA-DE function in
    scripts/pypsa-de/additional_functionality.py.
    """
    logger.info(f"Adding national CO2 budgets to {n.name} for year {investment_year}")
    nhours = n.snapshot_weightings.generators.sum()
    nyears = nhours / 8760
    MtCO2_to_tCO2 = 1e6

    co2_totals = pd.read_csv(snakemake.input.co2_totals_name, index_col=0).mul(
        MtCO2_to_tCO2
    )
    sectors = determine_emission_sectors(n.meta["sector"])
    co2_total_totals = co2_totals[sectors].sum(axis=1) * nyears

    for ct in national_co2_budgets:
        limit = co2_total_totals[ct] * national_co2_budgets[ct][investment_year]
        logger.info(
            f"Limiting emissions in country {ct} to {national_co2_budgets[ct][investment_year]:.1%} of "
            f"1990 levels, i.e. {limit:,.2f} tCO2/a",
        )

        lhs = []
        weightings = n.snapshot_weightings.generators
        links = n.components.links.static
        link_ports = links.filter(like="bus").columns.str[3:]
        for port in link_ports:
            idx = links.query(
                f"name.str.startswith('{ct}') "
                f"& bus{port} == 'co2 atmosphere' "
                f"& carrier != 'kerosene for aviation'"
                # exclude aviation here to multiply it with a domestic factor later
            ).index

            logger.info(
                f"For {ct} adding following link carriers to port {port} "
                f"CO2 constraint: {sorted(links.loc[idx, 'carrier'].unique())}"
            )

            if port == "0":
                efficiency = -1.0
            elif port == "1":
                efficiency = links.loc[idx, "efficiency"]
            else:
                efficiency = links.loc[idx, f"efficiency{port}"]

            port_emissions = (
                n.model["Link-p"].loc[:, idx].mul(efficiency).mul(weightings).sum()
            )
            lhs.append(port_emissions)

        # Aviation demand
        country_year = (ct, snakemake.params.energy_year)
        energy_totals = pd.read_csv(snakemake.input.energy_totals, index_col=[0, 1])
        aviation_domestic = energy_totals.loc[country_year, "total domestic aviation"]
        aviation_international = energy_totals.loc[
            country_year, "total international aviation"
        ]
        aviation_total = aviation_domestic + aviation_international
        if aviation_total == 0:  # avoids division by zero errors
            domestic_aviation_factor = 0.0
        else:
            domestic_aviation_factor = aviation_domestic / aviation_total
        aviation_links = links.query(
            f"name.str.startswith('{ct}') & carrier == 'kerosene for aviation'"
        )
        aviation_emissions = (
            n.model["Link-p"]
            .loc[:, aviation_links.index]
            # assuming 'co2 atmosphere' at bus2 for aviation links
            .mul(aviation_links["efficiency2"])
            .mul(weightings)
            .sum()
            .mul(domestic_aviation_factor)
        )
        lhs.append(aviation_emissions)
        logger.info(
            f"Adding domestic aviation emissions for {ct} with "
            f"a factor of {domestic_aviation_factor:.2f}"
        )

        # Navigation demand
        # todo: do we need to deduct emissions from internation navigation?

        # add total regional emissions to the model and make sure to drop existing
        # constraints from previous year
        lhs = sum(lhs)

        cname = f"co2_limit-{ct}"

        n.model.add_constraints(
            lhs <= limit,
            name=f"GlobalConstraint-{cname}",
        )

        if cname in n.global_constraints.index:
            logger.warning(
                f"Global constraint {cname} already exists. Dropping and adding it again."
            )
            n.global_constraints.drop(cname, inplace=True)

        n.add(
            "GlobalConstraint",
            cname,
            constant=limit,
            sense="<=",
            type="",
            carrier_attribute="",
        )


def add_cross_border_flow_limits(
    n: pypsa.Network, snakemake, investment_year: int
) -> None:
    """
    Add TYNDP NTC-style net cross-border flow limit constraints per snapshot.

    Reads the TYNDP transmission trajectory CSV for ``investment_year``,
    validates corridor coverage via :func:`compare_tyndp_and_model_borders`,
    and adds two per-snapshot linopy constraints to ``n.model`` for each
    corridor: one limiting net flow in the direct direction and one limiting
    net flow in the indirect direction.

    Net flow from location A to location B is defined as:

    .. code-block:: none

        sum(Line-s for lines with bus0_tyndp == A, bus1_tyndp == B)
        − sum(Line-s for lines with bus0_tyndp == B, bus1_tyndp == A)
        + sum(efficiency × Link-p for DC links with bus0_tyndp == A, bus1_tyndp == B)
        − sum(Link-p for DC links with bus0_tyndp == B, bus1_tyndp == A)

    Parameters
    ----------
    n : pypsa.Network
        PyPSA network with a linopy model attached (``n.model``).
    snakemake
        Snakemake workflow object. Must expose
        ``snakemake.input.tyndp_transmission_trajectories`` — path to a CSV
        with columns ``from_node``, ``to_node``, ``direct_capacity``,
        ``indirect_capacity``, and ``year``.  ``direct_capacity`` is the
        capacity in the ``from_node → to_node`` direction (MW);
        ``indirect_capacity`` is the capacity in the reverse direction (MW).
    investment_year : int
        Planning horizon year used to filter the CSV.

    Raises
    ------
    ValueError
        If the CSV contains no rows for ``investment_year``.

    Notes
    -----
    * The ``enable`` guard (``mods.tyndp_cross_border_flow_limits.enable``) is
      handled by the caller; this function does not check it.
    * DC Links are **included** in the NTC constraint alongside AC Lines: direct
      links contribute ``efficiency × link_p`` (power received at bus1); indirect
      links contribute raw ``link_p`` (power dispatched from their grid).
    * Constraint names follow the pattern
      ``tyndp_ntc_flow_dir-{A}-{B}-{year}`` (direct) and
      ``tyndp_ntc_flow_indir-{B}-{A}-{year}`` (indirect).
    * Corridors with no matching active AC Lines or DC Links in the network
      are skipped with a warning (no constraint is added).
    * Constraints are time-varying (one inequality per snapshot) and are
      therefore **not** registered as ``GlobalConstraint`` network objects.
    """
    df = pd.read_csv(snakemake.input.tyndp_transmission_trajectories)
    df = df[df["year"] == investment_year]

    if df.empty:
        raise ValueError(
            f"No cross-border NTC limits defined for year {investment_year}."
        )

    logger.info(f"Adding cross-border flow limits for year {investment_year}")

    relevant_links, relevant_lines = get_relevant_links_and_lines(n)

    line_s = n.model["Line-s"]
    link_p = n.model["Link-p"]

    for row in df.itertuples():
        from_node: str = row.from_node
        to_node: str = row.to_node
        dir_cap: float = row.direct_capacity
        indir_cap: float = row.indirect_capacity

        links_dir_idx = relevant_links[
            (relevant_links["bus0_tyndp"] == from_node)
            & (relevant_links["bus1_tyndp"] == to_node)
        ].index
        links_indir_idx = relevant_links[
            (relevant_links["bus0_tyndp"] == to_node)
            & (relevant_links["bus1_tyndp"] == from_node)
        ].index

        lines_dir_idx = relevant_lines[
            (relevant_lines["bus0_tyndp"] == from_node)
            & (relevant_lines["bus1_tyndp"] == to_node)
        ].index
        lines_indir_idx = relevant_lines[
            (relevant_lines["bus0_tyndp"] == to_node)
            & (relevant_lines["bus1_tyndp"] == from_node)
        ].index

        if (
            links_dir_idx.empty
            and links_indir_idx.empty
            and lines_dir_idx.empty
            and lines_indir_idx.empty
        ):
            logger.warning(
                f"Ignoring constraints for border {from_node}->{to_node} in {investment_year}"
            )
            continue

        lines_lhs_dir = line_s.sel(name=lines_dir_idx).sum("name") - line_s.sel(
            name=lines_indir_idx
        ).sum("name")
        lines_lhs_indir = -1 * lines_lhs_dir

        eff_dir = n.links.loc[links_dir_idx, "efficiency"]
        eff_indir = n.links.loc[links_indir_idx, "efficiency"]

        links_lhs_dir = link_p.sel(name=links_dir_idx).mul(eff_dir).sum(
            "name"
        ) - link_p.sel(name=links_indir_idx).sum("name")

        links_lhs_indir = link_p.sel(name=links_indir_idx).mul(eff_indir).sum(
            "name"
        ) - link_p.sel(name=links_dir_idx).sum("name")

        cname_dir = f"tyndp_ntc_flow_dir-{from_node}-{to_node}-{investment_year}"
        cname_indir = f"tyndp_ntc_flow_indir-{to_node}-{from_node}-{investment_year}"

        n.model.add_constraints(
            lines_lhs_dir + links_lhs_dir <= dir_cap, name=cname_dir
        )
        n.model.add_constraints(
            lines_lhs_indir + links_lhs_indir <= indir_cap, name=cname_indir
        )

        logger.info(
            f"TYNDP NTC constraint added: {from_node}→{to_node} ≤ {dir_cap} MW, "
            f"{to_node}→{from_node} ≤ {indir_cap} MW."
        )


def add_solar_utility_trajectory_constraints(
    n: pypsa.Network,
    snakemake,
    investment_year: int,
) -> None:
    """
    Add joint solar utility trajectory floor/ceiling constraints.

    Enforces combined ``solar`` + ``solar-hsat`` capacity per modelled location
    against TYNDP ``solar-pv-utility`` trajectory bands, after deducting
    existing brownfield capacity.

    The constraint reads:

    .. code-block:: none

        p_nom_opt[solar @ loc] + p_nom_opt[solar-hsat @ loc]
            >= max(0, traj_p_nom_min[loc] - brownfield[loc])   # floor
        p_nom_opt[solar @ loc] + p_nom_opt[solar-hsat @ loc]
            <= max(0, traj_p_nom_max[loc] - brownfield[loc])   # ceiling

    Locations where both bounds equal 0 after brownfield deduction are skipped.

    Parameters
    ----------
    n
        The pypsa network with a linopy model attached (``n.model``).
    snakemake
        The snakemake workflow object.  Must expose
        ``snakemake.input.tyndp_trajectories`` and the config key
        ``mods.PEMMDB_trajectories``.
    investment_year
        The myopic planning horizon (e.g. 2030, 2040, 2050).

    Notes
    -----
    ``solar-pv-utility`` trajectories cover the *combined* deployment of
    ``solar`` (flat-panel) and ``solar-hsat`` (single-axis tracking).  They
    are intentionally skipped in ``overwrite_pemmdb_capacities`` and handled
    here as linopy constraints so that the solver can choose the mix freely.
    """
    cfg = snakemake.config["mods"]["PEMMDB_trajectories"]
    if not cfg.get("enable"):
        logger.info(
            "PEMMDB_trajectories disabled — skipping solar utility trajectory constraints."
        )
        return

    skip_countries = cfg["skip_countries"]

    trajectories = pd.read_csv(snakemake.input.tyndp_trajectories).query(
        "pyear == @investment_year"
    )
    traj_clustered = aggregate_by_cluster_and_country(trajectories, [])

    # solar-pv-utility rows carry pypsa_eur_carrier == "solar(-hsat)"
    traj_solar = traj_clustered.xs("solar(-hsat)", level="pypsa_eur_carrier")

    # Pre-compute brownfield: sum of installed solar + solar-hsat per location
    carrier = ["solar", "solar-hsat"]
    brownfield = n.statistics.installed_capacity(
        groupby=["location", "carrier"],
        carrier=carrier,
        aggregate_across_components=True,
        nice_names=False,
        drop_zero=False,
    )
    # Sum over the carrier level → single Series indexed by location
    brownfield_by_loc = brownfield.groupby(level="location").sum()

    for loc in brownfield_by_loc.index:
        if loc.startswith(tuple(skip_countries)):
            logger.info(f"Skipping solar trajectory constraint for {loc}.")
            continue

        # Kosovo "XK" has no TYNDP data. Always use RS trajectories instead. Note
        # that the location proxy is different from the missing p_nom_min/max
        # replacements further below. Here, we always want to replace values, not only
        # if they are zero.
        loc_proxy = "RS" if loc == "XK" else loc
        p_nom_min = traj_solar.at[loc_proxy, "p_nom_min"]
        p_nom_max = traj_solar.at[loc_proxy, "p_nom_max"]

        # some countries do not have trajectories for solar-utility. Want to
        # replace by trajectory values from a nearby country of similar size.
        if p_nom_min == 0.0 and p_nom_max == 0.0:
            traj_proxy = {"BE": "NL", "CH": "AT", "NO": "SE", "SI": "SK", "XK": "RS"}
            if loc not in traj_proxy:
                raise KeyError(
                    f"Unexpected missing trajectories detected for loc {loc} and {investment_year}."
                )
            # fetch trajectories again from updated locations
            p_nom_min = traj_solar.at[traj_proxy[loc], "p_nom_min"]
            p_nom_max = traj_solar.at[traj_proxy[loc], "p_nom_max"]

        # existing brownfield from the original country
        existing_brownfield = brownfield_by_loc.at[loc]

        # determine brownfield correction
        pyear = int(n.meta["wildcards"]["planning_horizons"])
        deduction = 0  # for base year 2025
        if pyear > 2025:
            # reduce total boundaries by already built and still existing
            # capacities from previous myopic optimizations
            deduction = existing_brownfield

        # apply brownfield correction
        rhs_min = max(0.0, p_nom_min - deduction)
        rhs_max = max(0.0, p_nom_max - deduction)

        # it is possible that extrapolated p_nom_max values are smaller than the existing
        # brownfield from powerplant-matching. The function add_existing_baseyear.py
        # automatically adds p_nom-lower >= existing_brownfield constraints. We cannot set
        # upper boundaries smaller than the lower limit, which is the existing capactiy.
        if pyear == 2025:
            rhs_max = max(rhs_max, existing_brownfield)

        # Collect extendable solar and solar-hsat generators at this location
        gens = n.generators.query(
            "carrier in @carrier and bus.str.startswith(@loc) and p_nom_extendable"
        ).index.tolist()
        if not gens:
            logger.debug(
                f"No extendable solar/solar-hsat generators at {loc} — skipping."
            )
            continue

        lhs = n.model["Generator-p_nom"].sel(name=gens).sum()

        cname_upper = f"tyndp-combined-solar-upper[{loc} solar(-hsat)-{pyear}]"
        cname_lower = f"tyndp-combined-solar-lower[{loc} solar(-hsat)-{pyear}]"

        if rhs_min == 0.0 and rhs_max == 0.0:
            # Brownfield fills the ceiling — lock new builds to zero.
            n.model.add_constraints(lhs <= 0.0, name=cname_upper)
            logger.info(
                f"Solar utility capacity locked at 0 for {loc}: "
                f"brownfield={existing_brownfield:.1f} MW fills trajectory ceiling of {rhs_max:.1f} MW."
            )
            continue

        # add constraints twice: once to model and once to the Network object
        # constraints are only persisted to output networks if they are appended
        # the network objects GlobalConstraint attribute.
        n.model.add_constraints(lhs <= rhs_max, name=cname_upper)
        if cname_upper not in n.global_constraints.index:
            n.add(
                "GlobalConstraint",
                cname_upper,
                constant=rhs_max,
                sense="<=",
                type="",
                carrier_attribute="",
            )

        n.model.add_constraints(lhs >= rhs_min, name=cname_lower)
        if cname_lower not in n.global_constraints.index:
            n.add(
                "GlobalConstraint",
                cname_lower,
                constant=rhs_min,
                sense=">=",
                type="",
                carrier_attribute="",
            )

        logger.info(
            f"Solar utility constraint added for {loc}: "
            f"floor={rhs_min:.1f} MW, ceiling={rhs_max:.1f} MW "
            f"(brownfield={deduction:.1f} MW deducted)"
        )
