import numpy as np
import pandas as pd
import pypsa
from snakemake.iocontainers import Snakemake


def _check_extendable(df: pd.DataFrame, expected: bool) -> None:
    """
    Checks that all rows is the DataFrame have the expected extendability

    Parameters
    ----------
    df
        The dataframe to check. Needs to have a column 'p_nom_extendable'
    expected
        The expected value

    Raises
    ------
    ValueError
        If expected value is not matched.
    """
    if not (df.p_nom_extendable == expected).all():
        errors = df[df.p_nom_extendable != expected]
        raise ValueError(f"Extendability assumptions not matched in {errors}.")


def _add_missing_components(
    n: pypsa.Network,
    missing_components: pd.DataFrame,
    current_year: int,
    lifetime: int,
    efficiency: float,
    marginal_cost: float,
    capital_cost: float,
    onight_cost: float,
) -> None:
    """
    Add missing brownfield components to the network

    Parameters
    ----------
    n
        The pre-network to modify in place.
    missing_components
        DataFrame of missing components with capacities
    current_year
        Current year to consider
    lifetime
        Lifetime for onwind components
    efficiency
        Efficiency for onwind components

    Returns
    -------
    :
        Network is modified inplace.
    """
    if missing_components.empty:
        return
    if (missing_components.year == current_year).any():
        raise ValueError(
            f"Missing base year generators for a region with non-zero brownfield: {missing_components[missing_components.year == current_year]}"
        )

    new_components = (
        missing_components.region
        + " 0 onwind-"
        + missing_components.year.astype(int).astype(str)
    ).to_frame("name")
    new_components["bus"] = missing_components.region
    new_components["build_year"] = missing_components.year
    new_components["lifetime"] = lifetime
    new_components["p_nom"] = missing_components.capacity
    new_components["p_nom_extendable"] = False
    new_components["carrier"] = "onwind"
    new_components["efficiency"] = efficiency
    new_components["marginal_cost"] = marginal_cost
    new_components["capital_cost"] = capital_cost
    new_components["onight_cost"] = onight_cost
    new_components = new_components.set_index("name")

    n.add(
        "Generator",
        new_components.index,
        **new_components.to_dict(orient="series"),
    )

    profiles = (
        n.generators_t["p_max_pu"]
        .stack()
        .reset_index()
        .query(f"name.str.contains('onwind') & name.str.contains('{current_year}')")
    )
    profiles["bus"] = profiles.name.map(lambda x: x.split(" ")[0])
    new_profiles = (
        new_components.bus.reset_index()
        .merge(profiles.drop(columns="name"), on="bus")
        .drop_duplicates()
    )
    new_profiles = new_profiles.pivot(columns="name", index="snapshot", values=0)
    n.generators_t["p_max_pu"][new_profiles.columns] = new_profiles


def apply_onwind_brownfield(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Replace Austrian onshore-wind capacity with the prepared brownfield data.

    Fixed onshore-wind generators are replaced by the active CSV vintages.
    Existing extendable generators are reset so their capacity remains
    available for new buildout, including in the base year.

    Parameters
    ----------
    n
        The pre-network to modify in place.
    snakemake
        The Snakemake workflow object providing the brownfield CSV and
        planning-horizon wildcard.

    Returns
    -------
    :
        Network is modified inplace.
    """
    current_year = int(snakemake.wildcards.planning_horizons)
    base_year = snakemake.params.planning_horizons[0]
    brownfield = pd.read_csv(snakemake.input.onwind_brownfield)
    at_onwind = n.generators.query("(carrier == 'onwind') & index.str.startswith('AT')")

    lifetime = at_onwind.lifetime.iloc[0]
    efficiency = at_onwind.efficiency.iloc[0]
    marginal_cost = at_onwind.marginal_cost.iloc[0]
    capital_cost = at_onwind.capital_cost.iloc[0]
    onight_cost = at_onwind.onight_cost.iloc[0]
    brownfield = brownfield[
        (brownfield.year + lifetime > current_year) & (brownfield.capacity > 0)
    ]
    merge = brownfield.merge(
        at_onwind.reset_index(),
        right_on=["bus", "build_year"],
        left_on=["region", "year"],
        how="outer",
    )

    missing_components = merge[merge.name.isna()]
    missing_brownfield = merge[
        merge.name.notna() & merge.region.isna() & (merge.build_year < base_year)
    ].set_index("name")
    base_year_components = merge[
        merge.region.notna() & merge.name.notna() & (merge.build_year == base_year)
    ].set_index("name")
    other_components = merge[
        merge.region.notna() & merge.name.notna() & (merge.build_year < base_year)
    ].set_index("name")

    ### Fix capacities for existing onwind components prior to base_year
    _check_extendable(other_components, False)
    n.generators.loc[other_components.index, "p_nom"] = other_components["capacity"]

    ### Set capacity to 0 for existing onwind components without brownfield
    _check_extendable(missing_brownfield, False)
    n.generators.loc[missing_brownfield.index, "p_nom"] = 0

    ### Set capacity to 0 for existing onwind components without brownfield
    if current_year == base_year:
        _check_extendable(base_year_components, True)
        n.generators.loc[base_year_components.index, "p_nom_min"] = (
            base_year_components.capacity
        )
        n.generators.loc[base_year_components.index, "p_nom"] = n.generators.loc[
            base_year_components.index, "p_nom_min"
        ]
    else:
        _check_extendable(base_year_components, False)
        n.generators.loc[base_year_components.index, "p_nom"] = np.maximum(
            n.generators.loc[base_year_components.index, "p_nom"],
            base_year_components.capacity,
        )

    # Add onwind components where brownfield exists
    _add_missing_components(
        n,
        missing_components,
        current_year,
        lifetime,
        efficiency,
        marginal_cost,
        capital_cost,
        onight_cost,
    )
