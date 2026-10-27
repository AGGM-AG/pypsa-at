import numpy as np
import pandas as pd
import pytest
from pypsa import NetworkCollection

from mods.constraints.trajectories import _get_region_mapping
from test.conftest import require_config


def test_constraint_generic_trajectories(
    nc: NetworkCollection,
) -> None:
    """
    Tests that all trajectory constraints that are defined in the resources folder trajectories_{cluster}.csv are
    """
    trajectories = require_config(nc, "mods", "trajectories", apply_trajectories=False)
    if not trajectories["apply_trajectories"]:
        pytest.skip("No trajectories applied.")
    tol = trajectories["tol"]

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
                df_variable,
                how="left",
                on=["carrier", "variable", "model_region"],
                indicator=True,
            )
            trajectories_var = trajectories_var[trajectories_var["_merge"] == "both"]
            trajectories_var = trajectories_var.groupby("index").agg(
                {
                    "value": "mean",
                    f"{property}_opt": "sum",
                    "var_upper_bound": "sum",
                    "var_lower_bound": "sum",
                    "_merge": lambda x: "both" if x.eq("both").any() else "left_only",
                }
            )

            assert (
                (trajectories_var["_merge"] == "both")
                | (trajectories_var["value"] == 0)
            ).all(), "Not all trajectory variables are present in the network"

            if sense == "max":
                trajectories_var["result"] = np.where(
                    trajectories_var["value"] > trajectories_var["var_lower_bound"],
                    trajectories_var["value"] + tol
                    >= trajectories_var[f"{property}_opt"],
                    True,
                )
            elif sense == "min":
                trajectories_var["result"] = np.where(
                    trajectories_var["value"] < trajectories_var["var_upper_bound"],
                    trajectories_var["value"] - tol
                    <= trajectories_var[f"{property}_opt"],
                    True,
                )
            else:
                trajectories_var["result"] = False

            violations = trajectories.set_index(["index"]).loc[
                trajectories_var[~trajectories_var["result"]].index
            ]
            assert violations.empty, f"Violated constraints {violations}"


class TestBuildModelExpression:
    """Rows without an extendable component are dropped, not turned into constant constraints."""

    def _network(self):
        import pypsa

        n = pypsa.Network()
        n.set_snapshots(pd.date_range("2013-01-01", periods=2, freq="h"))
        n.add("Bus", "AT130", carrier="AC")
        n.add("Bus", "AT121", carrier="AC")
        n.add(
            "Generator",
            "AT130 ror",
            bus="AT130",
            carrier="ror",
            p_nom=100.0,
            marginal_cost=1.0,
        )
        n.add(
            "Generator",
            "AT130 ror-2030",
            bus="AT130",
            carrier="ror",
            p_nom_extendable=True,
            p_nom_max=10.0,
            capital_cost=1.0,
        )
        n.add(
            "Generator",
            "AT121 ror",
            bus="AT121",
            carrier="ror",
            p_nom=300.0,
            marginal_cost=1.0,
        )
        n.optimize.create_model()
        return n

    def test_rows_without_variables_are_dropped(self):
        from mods.constraints.trajectories import build_model_expression

        n = self._network()
        names = pd.DataFrame(
            {
                "index": [0, 0, 1],
                "name": ["AT130 ror", "AT130 ror-2030", "AT121 ror"],
            }
        )

        expr = build_model_expression(n, names, "Generator-p_nom")

        assert expr.coords["index"].to_numpy().tolist() == [0]
        assert expr.nterm == 1

    def test_returns_none_when_nothing_is_extendable(self):
        from mods.constraints.trajectories import build_model_expression

        n = self._network()
        names = pd.DataFrame({"index": [1], "name": ["AT121 ror"]})

        assert build_model_expression(n, names, "Generator-p_nom") is None
