import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))

    import marimo as mo
    import pandas as pd
    import pypsa

    return Path, mo, pd, pypsa


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    # Brownfield Network Comparison

    Compare existing capacities between two brownfield networks (pre-solve).
    Capacities are shown in **GW** (`p_nom` / `s_nom`, non-extendable components only).
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    path_a = mo.ui.text(
        value="tmp/with-pemmdb/networks/base_s_adm__none_2025_brownfield.nc",
        label="PEMMDB",
        full_width=True,
    )
    path_b = mo.ui.text(
        value="tmp/with-power-plant-matching/networks/base_s_adm__none_2025_brownfield.nc",
        label="PPM",
        full_width=True,
    )
    mo.vstack([path_a, path_b])
    return path_a, path_b


@app.cell
def _(Path, path_a, path_b, pypsa):
    na = pypsa.Network(path_a.value)
    nb = pypsa.Network(path_b.value)

    label_a = Path(path_a.value).stem
    label_b = Path(path_b.value).stem
    return label_a, label_b, na, nb


@app.cell
def _(pd):
    def capacity_by_carrier(component_df, capacity_col, fixed_only=True):
        """Return total capacity in GW per carrier, optionally filtering to non-extendable."""
        df = component_df
        if fixed_only and "p_nom_extendable" in df.columns:
            df = df[~df["p_nom_extendable"]]
        if df.empty or capacity_col not in df.columns:
            return pd.Series(dtype=float)
        return df.groupby("carrier")[capacity_col].sum() / 1e3  # MW → GW

    def comparison_table(series_a, series_b, label_a, label_b):
        """Combine two carrier series into a side-by-side GW table."""
        df = pd.DataFrame({label_a: series_a, label_b: series_b}).fillna(0.0)
        df["diff"] = df[label_b] - df[label_a]
        df["diff %"] = (df["diff"] / df[label_a].replace(0, float("nan")) * 100).round(
            1
        )
        df = df[df[[label_a, label_b]].sum(axis=1) > 0].sort_index()
        return df.round(3)

    _HEAT_KEYWORDS = (
        "heat",
        "boiler",
        "heat pump",
        "resistive",
        "solar thermal",
        "geothermal",
    )

    def is_heat(carrier: str) -> bool:
        c = carrier.lower()
        return any(kw in c for kw in _HEAT_KEYWORDS)

    return capacity_by_carrier, comparison_table, is_heat


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## Transmission
    """)
    return


@app.cell
def _(capacity_by_carrier, comparison_table, label_a, label_b, mo, na, nb, pd):
    # Lines (AC)
    _lines_a = capacity_by_carrier(na.lines, "s_nom", fixed_only=False)
    _lines_b = capacity_by_carrier(nb.lines, "s_nom", fixed_only=False)

    # DC links
    _dc_a = capacity_by_carrier(na.links[na.links.carrier == "DC"], "p_nom")
    _dc_b = capacity_by_carrier(nb.links[nb.links.carrier == "DC"], "p_nom")

    _tx_a = pd.concat([_lines_a, _dc_a])
    _tx_b = pd.concat([_lines_b, _dc_b])

    _tbl = comparison_table(_tx_a, _tx_b, label_a, label_b)
    if _tbl.empty:
        mo.callout(
            mo.md("No existing capacity found in either network for this section."),
            kind="warn",
        )
    mo.ui.table(
        _tbl.reset_index().rename(columns={"carrier": "Carrier"}),
        label="Lines + DC links (GW)",
    )

    return


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## Powerplants (Generators)
    """)
    return


@app.cell
def _(capacity_by_carrier, comparison_table, label_a, label_b, mo, na, nb):
    _gen_a = capacity_by_carrier(na.generators, "p_nom")
    _gen_b = capacity_by_carrier(nb.generators, "p_nom")
    _tbl = comparison_table(_gen_a, _gen_b, label_a, label_b)
    if _tbl.empty:
        mo.callout(
            mo.md("No existing capacity found in either network for this section."),
            kind="warn",
        )
    mo.ui.table(
        _tbl.reset_index().rename(columns={"carrier": "Carrier"}),
        label="Generators (GW)",
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## Heating Stock
    """)
    return


@app.cell
def _(
    capacity_by_carrier,
    comparison_table,
    is_heat,
    label_a,
    label_b,
    mo,
    na,
    nb,
):
    def _heat_links(n):
        mask = n.links["carrier"].apply(is_heat)
        return capacity_by_carrier(n.links[mask], "p_nom")

    _heat_a = _heat_links(na)
    _heat_b = _heat_links(nb)
    _tbl = comparison_table(_heat_a, _heat_b, label_a, label_b)
    if _tbl.empty:
        mo.callout(
            mo.md("No existing capacity found in either network for this section."),
            kind="warn",
        )
    mo.ui.table(
        _tbl.reset_index().rename(columns={"carrier": "Carrier"}),
        label="Heating links (GW)",
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## Conversion Technologies (Links)
    """)
    return


@app.cell
def _(
    capacity_by_carrier,
    comparison_table,
    is_heat,
    label_a,
    label_b,
    mo,
    na,
    nb,
):
    _EXCLUDE = {"DC"}

    def _conversion_links(n):
        mask = ~n.links["carrier"].apply(is_heat) & ~n.links["carrier"].isin(_EXCLUDE)
        return capacity_by_carrier(n.links[mask], "p_nom")

    _conv_a = _conversion_links(na)
    _conv_b = _conversion_links(nb)
    _tbl = comparison_table(_conv_a, _conv_b, label_a, label_b)
    if _tbl.empty:
        mo.callout(
            mo.md("No existing capacity found in either network for this section."),
            kind="warn",
        )
    mo.ui.table(
        _tbl.reset_index().rename(columns={"carrier": "Carrier"}),
        label="Conversion links (GW)",
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## Storage Units
    """)
    return


@app.cell
def _(capacity_by_carrier, comparison_table, label_a, label_b, mo, na, nb):
    _sto_a = capacity_by_carrier(na.storage_units, "p_nom")
    _sto_b = capacity_by_carrier(nb.storage_units, "p_nom")
    _tbl = comparison_table(_sto_a, _sto_b, label_a, label_b)
    if _tbl.empty:
        mo.callout(
            mo.md("No existing capacity found in either network for this section."),
            kind="warn",
        )
    mo.ui.table(
        _tbl.reset_index().rename(columns={"carrier": "Carrier"}),
        label="Storage units (GW)",
    )
    return


if __name__ == "__main__":
    app.run()
