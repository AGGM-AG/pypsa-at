import marimo

__generated_with = "0.14.17"
app = marimo.App(width="medium")


@app.cell
def _():
    import pandas as pd

    nodes_dict = {
        "id": {
            "IMPORT": 0,
            "TRANSFORMATION_IN": 1,
            "TRANSFORMATION_OUT": 2,
            "INDUSTRY": 3,
            "HH_SERVICES": 4,
            "EXPORT": 5,
            "METHANE_PRIMARY_IN": 6,
            "METHANE_PRIMARY_OUT": 7,
            "METHANE_BYPASS_IN": 8,
            "METHANE_BYPASS_OUT": 9,
            "METHANE_SECONDARY_IN": 10,
            "METHANE_SECONDARY_OUT": 11,
        },
        "label": {
            "IMPORT": "Import<br>232 TWh Methane",
            "TRANSFORMATION_IN": "Transformation<br>& Storage",
            "TRANSFORMATION_OUT": "",
            "INDUSTRY": "Industry",
            "HH_SERVICES": "Households & Services",
            "EXPORT": "Export<br>78 TWh Methane",
            "METHANE_PRIMARY_IN": "232 TWh",
            "METHANE_PRIMARY_OUT": "",
            "METHANE_BYPASS_IN": "112 TWh",
            "METHANE_BYPASS_OUT": "",
            "METHANE_SECONDARY_IN": "193 TWh",
            "METHANE_SECONDARY_OUT": "",
        },
        "color": {
            "IMPORT": "#000000",
            "TRANSFORMATION_IN": "#E19990",
            "TRANSFORMATION_OUT": "#E19990",
            "INDUSTRY": "#000000",
            "HH_SERVICES": "#000000",
            "EXPORT": "#000000",
            "METHANE_PRIMARY_IN": "#e8cc99",
            "METHANE_PRIMARY_OUT": "#e8cc99",
            "METHANE_BYPASS_IN": "#e8cc99",
            "METHANE_BYPASS_OUT": "#e8cc99",
            "METHANE_SECONDARY_IN": "#e8cc99",
            "METHANE_SECONDARY_OUT": "#e8cc99",
        },
        "x": {
            "IMPORT": 0.05,
            "TRANSFORMATION_IN": 0.4,
            "TRANSFORMATION_OUT": 0.6,
            "INDUSTRY": 0.99,
            "HH_SERVICES": 0.99,
            "EXPORT": 0.99,
            "METHANE_PRIMARY_IN": 0.3,
            "METHANE_PRIMARY_OUT": 0.3,
            "METHANE_BYPASS_IN": 0.4,
            "METHANE_BYPASS_OUT": 0.6,
            "METHANE_SECONDARY_IN": 0.8,
            "METHANE_SECONDARY_OUT": 0.8,
        },
        "y_rank": {
            "IMPORT": 0.1,
            "TRANSFORMATION_IN": 0.9,
            "TRANSFORMATION_OUT": 0.9,
            "INDUSTRY": 0.5,
            "HH_SERVICES": 0.3,
            "EXPORT": 0.2,
            "METHANE_PRIMARY_IN": 0.3,
            "METHANE_PRIMARY_OUT": 0.3,
            "METHANE_BYPASS_IN": 0.3,
            "METHANE_BYPASS_OUT": 0.3,
            "METHANE_SECONDARY_IN": 0.3,
            "METHANE_SECONDARY_OUT": 0.3,
        },
    }

    nodes = pd.DataFrame(nodes_dict)
    nodes
    return (nodes,)


@app.cell
def _():
    import plotly.graph_objects as go

    # nodes.loc["IMPORT", "x"] = 0.2
    # nodes.loc["IMPORT", "y_rank"] = 0.0

    # nodes.loc["METHANE_SECONDARY_IN", "x"] = 0.0001

    # nodes.loc["METHANE_PRIMARY_IN", "y_rank"] = 0.1
    # nodes.loc["METHANE_PRIMARY_OUT", "x"] = 0.15
    # nodes.loc["METHANE_PRIMARY_OUT", "y_rank"] = 0.1
    # nodes.loc["TRANSFORMATION_IN", "x"] = .3
    # nodes.loc["TRANSFORMATION_IN", "y_rank"] = 0.5
    # nodes.loc["TRANSFORMATION_OUT", "x"] = .4
    # nodes.loc["TRANSFORMATION_OUT", "y_rank"] = 0.5

    until = 12

    fig = go.Figure(
        go.Sankey(
            arrangement="fixed",
            node={
                "label": [
                    "IMPORT",
                    "TRANSFORMATION_IN",
                    "TRANSFORMATION_OUT",
                    "INDUSTRY",
                    "HH_SERVICES",
                    "EXPORT",
                    "METHANE_PRIMARY_IN",  # 6
                    "METHANE_PRIMARY_OUT",
                    "METHANE_BYPASS_IN",
                    "METHANE_BYPASS_OUT",
                    "METHANE_SECONDARY_IN",
                    "METHANE_SECONDARY_OUT",
                ],
                "x": [0.05, 0.4, 0.6, 0.99, 0.99, 0.99, 0.3, 0.35, 0.4, 0.6, 0.75, 0.8],
                "y": [0.1, 0.9, 0.9, 0.5, 0.3, 0.2, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3],
                "pad": 10,
            },  # 10 Pixels
            link={
                "source": [0, 6, 7, 1, 7, 8, 2, 9, 10, 11, 11, 11][:until],
                "target": [6, 7, 1, 2, 8, 9, 10, 10, 11, 3, 4, 5][:until],
                "value": [232, 232, 120, 120, 112, 112, 81, 112, 193, 115, 0.0001, 78][
                    :until
                ],
            },
        )
    )

    fig.show()
    return


@app.cell
def _(nodes):
    nodes.filter(like="METHANE", axis=0)
    nodes.query("id == 42")
    return


@app.cell
def _(nodes):
    [round(x, 2) for x in nodes["x"].tolist()]
    return


@app.cell
def _(nodes):
    nodes["x"]
    return


@app.cell
def _(nodes):
    nodes
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
