import logging
from collections.abc import Iterable
from typing import Literal

import numpy as np
import pandas as pd
import xarray as xr
from linopy import LinearExpression
from pypsa import Network
from snakemake.script import Snakemake

logger = logging.getLogger(__name__)


def _get_region_mapping(
    n_regions: Iterable[str], m_regions: Iterable[str]
) -> dict[str, list[str]]:
    """
    Maps model regions to respective countries from trajectories data.

    Note: DK0, DK1, EE, GB1 are not mapped due to lack of data for the regions. The regions have negligible hydro
          capacities. EU is also not mapped.

    Parameters
    ----------
    n_regions
        List of all model regions (e.g. AT111, DE1, CH)
    m_regions
        List of all countries in the trajectories data.

    Returns
    -------
    :
        Dictionary mapping model regions to their respective country names.

    """
    out = {m: [n for n in n_regions if n.startswith(m)] for m in m_regions} | {
        "EU": list(n_regions)
    }
    if "XK" in n_regions:
        out["RS"].append("XK")
    return out


def safe_inner_join(
    left: pd.DataFrame,
    right: pd.DataFrame,
    on: list[str],
    check_column: str = "index",
    value_column: str = "value",
) -> pd.DataFrame:
    """
    Performs an inner join of the given DataFrames that logs a warning if essential values are lost in the join.

    Parameters
    ----------
    left
        The left DataFrame to join.
    right
        The right DataFrame to join.
    on
        The columns to join on.
    check_column
        The column to check for missing values after the join.
    value_column
        Value column that allows missing entries if 0.

    Returns
    -------
    :
        The merged DataFrame
    """
    result = left.merge(right, on=on, how="inner")
    missing = left[
        left[check_column].isin(set(left[check_column]) - set(result[check_column]))
        & (left[value_column] > 0)
    ]

    if not missing.empty:
        logger.warning(f"Merge removed constraints {missing}")
    return result


def add_regions_to_trajectories(n: Network, trajectories: pd.DataFrame) -> pd.DataFrame:
    """
    Add model regions to trajectories.

    Parameters
    ----------
    n
        The pypsa network.
    trajectories
        The trajectories DataFrame containing a region column to be mapped

    Returns
    -------
    :
        The trajectories DataFrame with the added model regions.
    """
    trajectories = trajectories.rename(columns={"region": "traj_region"})
    mapping = _get_region_mapping(
        n.buses.location.unique(), trajectories.traj_region.unique()
    )
    mapping_df = pd.DataFrame(
        [(k, v) for k, values in mapping.items() for v in values],
        columns=["traj_region", "model_region"],
    )
    trajectories = trajectories.reset_index()
    return safe_inner_join(trajectories, mapping_df, ["traj_region"])


def calculate_limit(
    n: Network, variable: str, sense: str, group: pd.DataFrame
) -> tuple[pd.Series, pd.DataFrame]:
    """
    Calculates the upper/lower limits for extendable component constraints based on trajectories input and existing non-extendable components.

    Parameters
    ----------
    n
        The PyPSA Network.
    variable
        Name of the model variable to consider.
    sense
        Sense for constraint (e.g. upper or lower)
    group
        Subset of trajectories data for the given variable

    Returns
    -------
    :
        A tuple consisting of the series of limits per constraint and a DataFrame mapping constraint indices to PyPSA
        component names
    """
    component, property = variable.split("-", 1)

    if component not in [c.name for c in n.components]:
        raise ValueError(
            f"Component {component} listed in trajecories.csv not found in network."
        )
    df = n.components[component].df
    if "carrier" not in df:
        raise ValueError(
            f"No carrier column for component {component} found in network."
        )

    df_variable = df[["carrier"]].copy()
    df_variable["variable"] = variable
    df_variable["model_region"] = df_variable.index.to_frame()["name"].str.split(
        expand=True
    )[0]

    if property not in df.columns:
        df_variable["val_non_ext"] = 0
        df_variable["val_ext"] = 0
    elif f"{property}_extendable" not in df.columns:
        df_variable["val_non_ext"] = 0
        df_variable["val_ext"] = df[property]
    else:
        df_variable["val_non_ext"] = np.where(
            df[f"{property}_extendable"], 0, df[property]
        )
        df_variable["val_ext"] = np.where(
            df[f"{property}_extendable"],
            df[f"{property}_min"] if sense == "max" else df[f"{property}_max"],
            0,
        )
    df_variable = df_variable.reset_index()

    trajectories_var = safe_inner_join(
        group,
        df_variable,
        ["carrier", "variable", "model_region"],
    )
    df_names = trajectories_var[["index", "name"]]
    trajectories_var["val_non_ext"] *= -1
    trajectories_var = trajectories_var.groupby("index").agg(
        {"value": "mean", "val_non_ext": "sum", "val_ext": "sum"}
    )
    trajectories_var["limit"] = trajectories_var[["value", "val_non_ext"]].sum(axis=1)
    trajectories_var["limit"] = (
        trajectories_var[["limit", "val_ext"]].max(axis=1)
        if sense == "max"
        else trajectories_var[["limit", "val_ext"]].min(axis=1)
    )
    trajectories_var["limit"] = trajectories_var["limit"].clip(lower=0)
    return trajectories_var["limit"], df_names


def build_model_expression(
    n: Network, trajectories_names: pd.DataFrame, variable: str
) -> LinearExpression:
    """
    Build the LinearExpression to constrain.

    Parameters
    ----------
    n
        The PyPSA Network.
    trajectories_names
        A DataFrame mapping constraint indices to PyPSA component names
    variable
        Name of the model variable to consider.

    Return
    ------
    :
        The aggregated LinearExpression

    """
    model_vars = n.model.variables[variable]
    trajectories_filtered = trajectories_names[
        trajectories_names["name"].isin(model_vars.coords["name"].values)
    ]
    missing_idx = set(trajectories_names["index"]) - set(trajectories_filtered["index"])
    missing_trajectories = trajectories_names[
        trajectories_names["index"].isin(missing_idx)
    ]
    if len(missing_idx) > 0:
        raise ValueError(
            f"Missing variables for components {missing_trajectories['name']}."
        )
    expr = model_vars.sel(name=list(trajectories_filtered.name))
    grouper = xr.DataArray(
        trajectories_filtered["index"].to_numpy(), dims=["name"], name="index"
    )
    return expr.groupby(grouper).sum()


def apply_constraint(
    n: Network,
    limits: pd.Series,
    expr: LinearExpression,
    variable: str,
    carriers: list[str],
    sign: Literal["<=", ">="],
    limit_name: Literal["upper limit", "lower limit"],
) -> None:
    """
    Apply given limits to the given expression using the sign.

    Parameters
    ----------
    n
        The PyPSA Network.
    limits
        The series of limits per constraint
    expr
        The LinearExpression to constrain..
    variable
        Name of the model variable to consider.
    carriers
        List of carriers. For naming purposes only.
    sign
        Sign for constraints.
    limit_name
        Name of the limit for constraint. For naming purposes only.

    Return
    ------
    :
        The constraints are applied inplace.

    """
    cname = f"Trajectories {variable} {limit_name} for carriers {carriers}."
    n.model.add_constraints(
        expr,
        sign,
        limits,
        cname,
    )
    if cname in n.global_constraints.index:
        logger.warning(
            f"Global constraint {cname} already exists. Dropping and adding it again."
        )
        n.global_constraints.drop(cname, inplace=True)
    n.add(
        "GlobalConstraint",
        cname,
        sense=sign,
        type="",
        carrier_attribute="",
    )


def constraint_generic_trajectories(
    n: Network, snakemake: Snakemake, investment_year: int
) -> None:
    """
    Apply generic constraints from trajectories.csv resource file.

    Parameters
    ----------
    n
        The pypsa network to add the constraints to.
    snakemake
        The snakemake workflow object.
    investment_year
        The current workflow planning horizon.

    Returns
    -------
    None
        Changes are applied to the network inplace
    """
    if not snakemake.params.apply_trajectories:
        logger.info("Generic trajectories skipped as per configuration")
        return

    trajectories = pd.read_csv(snakemake.input.trajectories).query(
        f"year == {investment_year}"
    )
    trajectories = add_regions_to_trajectories(n, trajectories)

    for (variable, sense), group in trajectories.groupby(["variable", "sense"]):
        if variable not in n.model.variables:
            raise ValueError(f"Unknown network variable {variable}.")
        limits, trajectories_names = calculate_limit(n, variable, sense, group)
        if limits.empty:
            continue

        expr = build_model_expression(n, trajectories_names, variable)
        carriers = group["carrier"].drop_duplicates().tolist()
        match sense:
            case "max":
                limits += snakemake.params.trajectories_eps
                apply_constraint(
                    n, limits, expr, variable, carriers, "<=", "upper limit"
                )
            case "min":
                limits = np.where(
                    limits > snakemake.params.trajectories_eps,
                    limits - snakemake.params.trajectories_eps,
                    0,
                )
                apply_constraint(
                    n, limits, expr, variable, carriers, ">=", "lower limit"
                )
            case _:
                raise ValueError(f"Unknown trajectory type {sense}")
