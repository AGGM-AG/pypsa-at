import numpy as np
import pandas as pd
import pytest
from pypsa import NetworkCollection

from mods.constraints.trajectories import _get_region_mapping
from test.conftest import require_config


def test_constraint_generic_trajectories(
    nc: NetworkCollection,
) -> None:
    apply_trajectories = require_config(
        nc, "scenario", "trajectories", "apply_trajectories"
    )
    if not apply_trajectories:
        pytest.skip("No trajectories applied.")
    eps = require_config(nc, "scenario", "trajectories", "eps")

    for year, n in nc.networks.items():
        trajectories = pd.DataFrame.from_dict(n.meta["resources"]["trajectories"])
        trajectories = trajectories[trajectories["year"] == int(year)]
        trajectories = trajectories.rename(columns={"region": "traj_region"})
        mapping = _get_region_mapping(
            n.buses.location.unique(), trajectories.traj_region.unique()
        )
        mapping_df = pd.DataFrame(
            [(k, v) for k, values in mapping.items() for v in values],
            columns=["traj_region", "model_region"],
        )
        trajectories = trajectories.reset_index()
        trajectories_ext = trajectories.merge(
            mapping_df, on=["traj_region"], how="inner"
        )
        for (variable, sense), group in trajectories_ext.groupby(["variable", "sense"]):
            component, property = variable.split("-")
            df = n.components[component].df

            df_variable = df[
                [
                    "carrier",
                    property,
                    f"{property}_min",
                    f"{property}_max",
                    f"{property}_opt",
                    f"{property}_extendable",
                ]
            ].copy()
            df_variable["var_lower_bound"] = np.where(
                df_variable[f"{property}_extendable"],
                df_variable[f"{property}_min"],
                df_variable[f"{property}_opt"],
            )
            df_variable["var_upper_bound"] = np.where(
                df_variable[f"{property}_extendable"],
                df_variable[f"{property}_max"],
                df_variable[f"{property}_opt"],
            )
            df_variable["variable"] = variable
            df_variable["model_region"] = df_variable.index.to_frame()[
                "name"
            ].str.split(expand=True)[0]
            df_variable = df_variable.reset_index()

            trajectories_var = group.merge(
                df_variable, how="inner", on=["carrier", "variable", "model_region"]
            )
            trajectories_var = trajectories_var.groupby("index").agg(
                {
                    "value": "mean",
                    f"{property}_opt": "sum",
                    "var_upper_bound": "sum",
                    "var_lower_bound": "sum",
                }
            )

            match sense:
                case "max":
                    trajectories_var["result"] = np.where(
                        trajectories_var["value"] > trajectories_var["var_lower_bound"],
                        trajectories_var["value"] + eps
                        >= trajectories_var[f"{property}_opt"],
                        True,
                    )
                case "min":
                    trajectories_var["result"] = np.where(
                        trajectories_var["value"] < trajectories_var["var_upper_bound"],
                        trajectories_var["value"] - eps
                        <= trajectories_var[f"{property}_opt"],
                        True,
                    )
                case _:
                    trajectories_var["result"] = False

            violations = trajectories.set_index(["index"]).loc[
                trajectories_var[~trajectories_var["result"]].index
            ]
            assert violations.empty, f"Violated constraints {violations}"
