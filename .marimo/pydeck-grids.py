import marimo

__generated_with = "0.17.6"
app = marimo.App(width="medium")


@app.cell
def _():
    import sys

    sys.path.insert(0, ".")

    import marimo as mo

    from evals.fileio import read_networks

    n = read_networks(["results/v2025.04/AT_KN2040/networks/base_s_adm__none_2050.nc"])[
        "2050"
    ]

    # n = pypsa.Network("results/v2025.04/AT_KN2040/networks/base_s_adm__none_2050.nc")
    return mo, n


@app.cell
def _(mo):
    mo.md(r"""
    ### Follow documentation guidlines in https://docs.pypsa.org/stable/user-guide/plotting/explore/#preparation
    """)
    return


@app.cell
def _(n):
    colors = {
        "Multiple": "pink",
        "AC": "black",
        "Brown Coal": "saddlebrown",
        "Gas": "darkorange",
        "Geothermal": "firebrick",
        "Hard Coal": "darkslategray",
        "Nuclear": "mediumorchid",
        "Oil": "peru",
        "Other": "dimgray",
        "Pumped Hydro": "cornflowerblue",
        "Run of River": "royalblue",
        "Solar": "gold",
        "Storage Hydro": "navy",
        "Waste": "olive",
        "Wind Offshore": "teal",
        "Wind Onshore": "turquoise",
    }
    n.carriers.color = n.carriers.index.map(colors)
    return


@app.cell
def _(n):
    # hotfix missing colors
    no_color = n.carriers["color"].isna()
    n.carriers.loc[no_color, "color"] = "red"
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
    # need to add missing carrier
    missing_carrier = [
        "Offshore Wind (AC)",
        "Offshore Wind (DC)",
        "Onshore Wind",
        "Reservoir & Dam",
        "Run of River",
        "Solar",
        "Pumped Hydro Storage",
        "production gas",
        "lng gas",
        "pipeline gas",
    ]
    for carr in missing_carrier:
        n.carriers.loc[carr, "color"] = "darkred"
    return


@app.cell
def _(eb, line_flow, link_flow, n):
    view_state = {}
    view_state["zoom"] = 6
    view_state["pitch"] = 0  # Up/down angle relative to the map's plane

    map = n.explore(
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
    return (map,)


@app.cell
def _(map):
    map.to_html("gridmap.html")
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
