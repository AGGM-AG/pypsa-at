import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell
def _():
    from pathlib import Path

    import pandas as pd

    return Path, pd


@app.cell
def _(Path, pd):
    base = Path("resources/v2025.04/AT_KN2040")
    horizons = [2030, 2040, 2050]

    dfs = [pd.read_csv(base / f"pemmdb_capacities_{h}.csv") for h in horizons]
    raw = pd.concat(dfs, ignore_index=True)
    raw = raw[raw["p_nom"] > 0]
    return (raw,)


@app.cell
def _(raw):
    pivot = (
        raw.groupby(
            [
                "bus",
                "country",
                "open_tyndp_carrier",
                "pypsa_eur_carrier",
                "planning_horizon",
            ]
        )["p_nom"]
        .sum()
        .reset_index()
        .pivot(
            index=["bus", "country", "open_tyndp_carrier", "pypsa_eur_carrier"],
            columns="planning_horizon",
            values="p_nom",
        )
        .rename_axis(columns=None)
        .reset_index()
        .sort_values(["country", "bus", "open_tyndp_carrier", "pypsa_eur_carrier"])
        .reset_index(drop=True)
    )
    pivot  # .dropna(subset=["2025", "2030", "2040", "2050"], how="all", axis=1)
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
