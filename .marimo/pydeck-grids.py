import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")


@app.cell
def _():
    import sys

    import yaml

    sys.path.insert(0, ".")

    import marimo as mo

    from evals.fileio import read_networks

    n = read_networks(
        [
            "results/electricity-load-clipping/AT_KN2040/networks/base_s_adm__none_2050.nc"
        ]
    )["2050"]

    # n = pypsa.Network("results/v2025.04/AT_KN2040/networks/base_s_adm__none_2050.nc")
    return mo, n, yaml


@app.cell
def _(mo):
    mo.md(r"""
    ### Follow documentation guidlines in https://docs.pypsa.org/stable/user-guide/plotting/explore/#preparation
    """)
    return


@app.cell
def _(n, yaml):
    with open("config/plotting.default.yaml") as f:
        default_tech_colors = yaml.safe_load(f)["plotting"]["tech_colors"]

    with open("config/plotting.at.yaml") as f:
        at_tech_colors = yaml.safe_load(f)["plotting"]["tech_colors"]

    tech_colors = {**default_tech_colors, **at_tech_colors}

    n.carriers["color"] = n.carriers.index.map(tech_colors).fillna("darkred")
    return


@app.cell
def _(n):
    eb = n.statistics.energy_balance(
        bus_carrier="H2",
        groupby=["bus", "carrier"],
        aggregate_across_components=True,
    )
    eb

    # eb = (
    #    n.statistics.energy_balance(
    #        groupby=["bus", "carrier"],
    #        components=["Generator", "Load", "StorageUnit"],
    #    )
    #    .groupby(["bus", "carrier"])
    #    .sum()
    # ).drop(["EU uranium", "EU oil primary", "EU coal", "EU lignite"], level="bus")
    return (eb,)


@app.cell
def _(n):
    line_flow = n.lines_t.p0.sum(axis=0)
    # link_flow = n.links_t.p0.sum(axis=0)
    return (line_flow,)


@app.cell
def _(n):
    link_flow = n.links_t.p0.filter(like="H2").sum(axis=0)
    return (link_flow,)


@app.cell
def _():
    # eu_links = link_flow.filter(
    #    regex="kerosene|methanolisation|oil refining|nuclear|preocess emissions|electrobiofuels"
    # )
    # link_flow_clean = eu_links.drop(eu_links.index, inplace=True)
    return


@app.cell
def _(n):
    # some components (e.g. H2 retrofit CCGT/OCGT links) reference
    # carriers that were never registered in n.carriers at all, not just
    # missing a color -- n.explore() needs a color entry for every
    # carrier it encounters, so backfill any that are missing.
    used_carriers = set()
    for static_df in (
        n.generators,
        n.links,
        n.lines,
        n.loads,
        n.storage_units,
        n.stores,
    ):
        if "carrier" in static_df.columns:
            used_carriers |= set(static_df["carrier"].unique())

    missing_carrier = sorted(used_carriers - set(n.carriers.index))
    for carr in missing_carrier:
        n.carriers.loc[carr, "color"] = "darkred"
    return


@app.cell
def _(eb, line_flow, link_flow, n):
    view_state = {}
    view_state["zoom"] = 6
    view_state["pitch"] = 0  # Up/down angle relative to the map's plane

    map_big = n.explore(
        view_state=view_state,
        map_style="light",
        bus_size=eb,  # MWh -> km²
        bus_split_circle=True,
        bus_size_max=7000,  # km²
        line_color="green",
        line_width=line_flow,  # MWh -> km
        link_width=link_flow,  # MWh -> km
        line_flow=line_flow,  # MWh -> km
        link_flow=link_flow,  # MWh -> km
        branch_width_max=16,  # km
        auto_scale=True,
        bus_columns=["v_nom"],
        line_columns=["s_nom"],
        link_columns=["p_nom"],
        arrow_size_factor=2,
        tooltip=True,  # disabled here for technical limits of mkdocs-jupyter plugin
    )
    return (map_big,)


@app.cell
def _(map_big):
    map_big.to_html("gridmap.html")
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
