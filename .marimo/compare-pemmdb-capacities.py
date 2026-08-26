import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Illustrate TYNDP - Pathways
    This notebook illustrates TYNDP-pathways for techs in Austria.
    """)
    return


@app.cell
def _():
    import marimo as mo
    import pandas as pd

    return mo, pd


@app.cell
def _(pd):
    tyndp_input = "resources/tyndp_trajectories.csv"
    raw = pd.read_csv(tyndp_input)
    return (raw,)


@app.cell
def _(mo, raw):
    carrier_selector = mo.ui.dropdown(
        options=sorted(raw.carrier.unique()),
        value=sorted(raw.carrier.unique())[0],
        label="Carrier",
    )
    carrier_selector
    return (carrier_selector,)


@app.cell
def _(carrier_selector, raw):
    at_carrier = raw[(raw.carrier == carrier_selector.value) & (raw.bus == "AT00")]
    at_carrier
    return (at_carrier,)


@app.cell(hide_code=True)
def _(at_carrier, carrier_selector):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    _colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for _i, (_index_carrier, _group) in enumerate(at_carrier.groupby("index_carrier")):
        _group = _group.sort_values("pyear")
        _color = _colors[_i % len(_colors)]
        ax.plot(
            _group.pyear,
            _group.p_nom_min,
            marker="o",
            color=_color,
            linestyle="-",
            label=f"{_index_carrier} p_nom_min",
        )
        ax.plot(
            _group.pyear,
            _group.p_nom_max,
            marker="s",
            color=_color,
            linestyle="--",
            label=f"{_index_carrier} p_nom_max",
        )
        ax.fill_between(
            _group.pyear, _group.p_nom_min, _group.p_nom_max, color=_color, alpha=0.15
        )
    ax.set_xlabel("pyear")
    ax.set_ylabel("MW")
    ax.set_title(f"{carrier_selector.value} — AT00")
    ax.legend()
    fig
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
