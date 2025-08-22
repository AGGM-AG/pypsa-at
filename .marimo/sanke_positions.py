import marimo

__generated_with = "0.14.17"
app = marimo.App(width="medium")


@app.cell
def _():
    import pandas as pd

    nodes_dict = {
        "id": {
            "IMPORT": 0,
            "WIND": 1,
            "SOLAR": 2,
            "HYDRO": 3,
            "TRANSFORMATION_IN": 4,
            "TRANSFORMATION_OUT": 5,
            "INDUSTRY": 6,
            "HH_SERVICES": 7,
            "EXPORT": 8,
            "TRANSPORT": 9,
            "AGRICULTURE": 10,
            "TRANSFORMATION_LOSSES": 11,
            "DISTRIBUTION_LOSSES": 12,
            "BIOGAS_PRIMARY_IN": 13,
            "BIOGAS_PRIMARY_OUT": 14,
            "BIOGAS_BYPASS_IN": 15,
            "BIOGAS_BYPASS_OUT": 16,
            "BIOGAS_SECONDARY_IN": 17,
            "BIOGAS_SECONDARY_OUT": 18,
            "ELECTRICITY_PRIMARY_IN": 19,
            "ELECTRICITY_PRIMARY_OUT": 20,
            "ELECTRICITY_BYPASS_IN": 21,
            "ELECTRICITY_BYPASS_OUT": 22,
            "ELECTRICITY_SECONDARY_IN": 23,
            "ELECTRICITY_SECONDARY_OUT": 24,
            "HEAT_PRIMARY_IN": 25,
            "HEAT_PRIMARY_OUT": 26,
            "HEAT_BYPASS_IN": 27,
            "HEAT_BYPASS_OUT": 28,
            "HEAT_SECONDARY_IN": 29,
            "HEAT_SECONDARY_OUT": 30,
            "HYDROGEN_PRIMARY_IN": 31,
            "HYDROGEN_PRIMARY_OUT": 32,
            "HYDROGEN_BYPASS_IN": 33,
            "HYDROGEN_BYPASS_OUT": 34,
            "HYDROGEN_SECONDARY_IN": 35,
            "HYDROGEN_SECONDARY_OUT": 36,
            "LIQUIDS_PRIMARY_IN": 37,
            "LIQUIDS_PRIMARY_OUT": 38,
            "LIQUIDS_BYPASS_IN": 39,
            "LIQUIDS_BYPASS_OUT": 40,
            "LIQUIDS_SECONDARY_IN": 41,
            "LIQUIDS_SECONDARY_OUT": 42,
            "METHANE_PRIMARY_IN": 43,
            "METHANE_PRIMARY_OUT": 44,
            "METHANE_BYPASS_IN": 45,
            "METHANE_BYPASS_OUT": 46,
            "METHANE_SECONDARY_IN": 47,
            "METHANE_SECONDARY_OUT": 48,
            "SOLIDS_PRIMARY_IN": 49,
            "SOLIDS_PRIMARY_OUT": 50,
            "SOLIDS_BYPASS_IN": 51,
            "SOLIDS_BYPASS_OUT": 52,
            "SOLIDS_SECONDARY_IN": 53,
            "SOLIDS_SECONDARY_OUT": 54,
            "URANIUM_PRIMARY_IN": 55,
            "URANIUM_PRIMARY_OUT": 56,
            "URANIUM_BYPASS_IN": 57,
            "URANIUM_BYPASS_OUT": 58,
            "URANIUM_SECONDARY_IN": 59,
            "URANIUM_SECONDARY_OUT": 60,
        },
        "label": {
            "IMPORT": "Import<br>232 TWh Methane",
            "WIND": "Wind Power",
            "SOLAR": "Solar Power",
            "HYDRO": "Hydro Power",
            "TRANSFORMATION_IN": "Transformation<br>& Storage",
            "TRANSFORMATION_OUT": "",
            "INDUSTRY": "Industry",
            "HH_SERVICES": "Households & Services",
            "EXPORT": "Export<br>78 TWh Methane",
            "TRANSPORT": "Transport",
            "AGRICULTURE": "Agriculture",
            "TRANSFORMATION_LOSSES": "Transformation Losses",
            "DISTRIBUTION_LOSSES": "Distribution Losses",
            "BIOGAS_PRIMARY_IN": "",
            "BIOGAS_PRIMARY_OUT": "",
            "BIOGAS_BYPASS_IN": "",
            "BIOGAS_BYPASS_OUT": "",
            "BIOGAS_SECONDARY_IN": "",
            "BIOGAS_SECONDARY_OUT": "",
            "ELECTRICITY_PRIMARY_IN": "",
            "ELECTRICITY_PRIMARY_OUT": "",
            "ELECTRICITY_BYPASS_IN": "",
            "ELECTRICITY_BYPASS_OUT": "",
            "ELECTRICITY_SECONDARY_IN": "",
            "ELECTRICITY_SECONDARY_OUT": "",
            "HEAT_PRIMARY_IN": "",
            "HEAT_PRIMARY_OUT": "",
            "HEAT_BYPASS_IN": "",
            "HEAT_BYPASS_OUT": "",
            "HEAT_SECONDARY_IN": "",
            "HEAT_SECONDARY_OUT": "",
            "HYDROGEN_PRIMARY_IN": "",
            "HYDROGEN_PRIMARY_OUT": "",
            "HYDROGEN_BYPASS_IN": "",
            "HYDROGEN_BYPASS_OUT": "",
            "HYDROGEN_SECONDARY_IN": "",
            "HYDROGEN_SECONDARY_OUT": "",
            "LIQUIDS_PRIMARY_IN": "",
            "LIQUIDS_PRIMARY_OUT": "",
            "LIQUIDS_BYPASS_IN": "",
            "LIQUIDS_BYPASS_OUT": "",
            "LIQUIDS_SECONDARY_IN": "",
            "LIQUIDS_SECONDARY_OUT": "",
            "METHANE_PRIMARY_IN": "232 TWh",
            "METHANE_PRIMARY_OUT": "",
            "METHANE_BYPASS_IN": "112 TWh",
            "METHANE_BYPASS_OUT": "",
            "METHANE_SECONDARY_IN": "193 TWh",
            "METHANE_SECONDARY_OUT": "",
            "SOLIDS_PRIMARY_IN": "",
            "SOLIDS_PRIMARY_OUT": "",
            "SOLIDS_BYPASS_IN": "",
            "SOLIDS_BYPASS_OUT": "",
            "SOLIDS_SECONDARY_IN": "",
            "SOLIDS_SECONDARY_OUT": "",
            "URANIUM_PRIMARY_IN": "",
            "URANIUM_PRIMARY_OUT": "",
            "URANIUM_BYPASS_IN": "",
            "URANIUM_BYPASS_OUT": "",
            "URANIUM_SECONDARY_IN": "",
            "URANIUM_SECONDARY_OUT": "",
        },
        "color": {
            "IMPORT": "#000000",
            "WIND": "#000000",
            "SOLAR": "#000000",
            "HYDRO": "#000000",
            "TRANSFORMATION_IN": "#E19990",
            "TRANSFORMATION_OUT": "#E19990",
            "INDUSTRY": "#000000",
            "HH_SERVICES": "#000000",
            "EXPORT": "#000000",
            "TRANSPORT": "#000000",
            "AGRICULTURE": "#000000",
            "TRANSFORMATION_LOSSES": "#3C3C3C",
            "DISTRIBUTION_LOSSES": "#3C3C3C",
            "BIOGAS_PRIMARY_IN": "#82B973",
            "BIOGAS_PRIMARY_OUT": "#82B973",
            "BIOGAS_BYPASS_IN": "#82B973",
            "BIOGAS_BYPASS_OUT": "#82B973",
            "BIOGAS_SECONDARY_IN": "#82B973",
            "BIOGAS_SECONDARY_OUT": "#82B973",
            "ELECTRICITY_PRIMARY_IN": "#B5C9D5",
            "ELECTRICITY_PRIMARY_OUT": "#B5C9D5",
            "ELECTRICITY_BYPASS_IN": "#B5C9D5",
            "ELECTRICITY_BYPASS_OUT": "#B5C9D5",
            "ELECTRICITY_SECONDARY_IN": "#B5C9D5",
            "ELECTRICITY_SECONDARY_OUT": "#B5C9D5",
            "HEAT_PRIMARY_IN": "#FFDE53",
            "HEAT_PRIMARY_OUT": "#FFDE53",
            "HEAT_BYPASS_IN": "#FFDE53",
            "HEAT_BYPASS_OUT": "#FFDE53",
            "HEAT_SECONDARY_IN": "#FFDE53",
            "HEAT_SECONDARY_OUT": "#FFDE53",
            "HYDROGEN_PRIMARY_IN": "#005082",
            "HYDROGEN_PRIMARY_OUT": "#005082",
            "HYDROGEN_BYPASS_IN": "#005082",
            "HYDROGEN_BYPASS_OUT": "#005082",
            "HYDROGEN_SECONDARY_IN": "#005082",
            "HYDROGEN_SECONDARY_OUT": "#005082",
            "LIQUIDS_PRIMARY_IN": "#B20633",
            "LIQUIDS_PRIMARY_OUT": "#B20633",
            "LIQUIDS_BYPASS_IN": "#B20633",
            "LIQUIDS_BYPASS_OUT": "#B20633",
            "LIQUIDS_SECONDARY_IN": "#B20633",
            "LIQUIDS_SECONDARY_OUT": "#B20633",
            "METHANE_PRIMARY_IN": "#e8cc99",
            "METHANE_PRIMARY_OUT": "#e8cc99",
            "METHANE_BYPASS_IN": "#e8cc99",
            "METHANE_BYPASS_OUT": "#e8cc99",
            "METHANE_SECONDARY_IN": "#e8cc99",
            "METHANE_SECONDARY_OUT": "#e8cc99",
            "SOLIDS_PRIMARY_IN": "#535353",
            "SOLIDS_PRIMARY_OUT": "#535353",
            "SOLIDS_BYPASS_IN": "#535353",
            "SOLIDS_BYPASS_OUT": "#535353",
            "SOLIDS_SECONDARY_IN": "#535353",
            "SOLIDS_SECONDARY_OUT": "#535353",
            "URANIUM_PRIMARY_IN": "#FECB52",
            "URANIUM_PRIMARY_OUT": "#FECB52",
            "URANIUM_BYPASS_IN": "#FECB52",
            "URANIUM_BYPASS_OUT": "#FECB52",
            "URANIUM_SECONDARY_IN": "#FECB52",
            "URANIUM_SECONDARY_OUT": "#FECB52",
        },
        "x": {
            "IMPORT": 0.0,
            "WIND": 0.0,
            "SOLAR": 0.0,
            "HYDRO": 0.0,
            "TRANSFORMATION_IN": 0.4,
            "TRANSFORMATION_OUT": 0.6,
            "INDUSTRY": 1.0,
            "HH_SERVICES": 1.0,
            "EXPORT": 1.0,
            "TRANSPORT": 1.0,
            "AGRICULTURE": 1.0,
            "TRANSFORMATION_LOSSES": 0.7,
            "DISTRIBUTION_LOSSES": 0.9,
            "BIOGAS_PRIMARY_IN": 0.15000000000000002,
            "BIOGAS_PRIMARY_OUT": 0.25,
            "BIOGAS_BYPASS_IN": 0.4,
            "BIOGAS_BYPASS_OUT": 0.6,
            "BIOGAS_SECONDARY_IN": 0.75,
            "BIOGAS_SECONDARY_OUT": 0.8500000000000001,
            "ELECTRICITY_PRIMARY_IN": 0.15000000000000002,
            "ELECTRICITY_PRIMARY_OUT": 0.25,
            "ELECTRICITY_BYPASS_IN": 0.4,
            "ELECTRICITY_BYPASS_OUT": 0.6,
            "ELECTRICITY_SECONDARY_IN": 0.75,
            "ELECTRICITY_SECONDARY_OUT": 0.8500000000000001,
            "HEAT_PRIMARY_IN": 0.15000000000000002,
            "HEAT_PRIMARY_OUT": 0.25,
            "HEAT_BYPASS_IN": 0.4,
            "HEAT_BYPASS_OUT": 0.6,
            "HEAT_SECONDARY_IN": 0.75,
            "HEAT_SECONDARY_OUT": 0.8500000000000001,
            "HYDROGEN_PRIMARY_IN": 0.15000000000000002,
            "HYDROGEN_PRIMARY_OUT": 0.25,
            "HYDROGEN_BYPASS_IN": 0.4,
            "HYDROGEN_BYPASS_OUT": 0.6,
            "HYDROGEN_SECONDARY_IN": 0.75,
            "HYDROGEN_SECONDARY_OUT": 0.8500000000000001,
            "LIQUIDS_PRIMARY_IN": 0.15000000000000002,
            "LIQUIDS_PRIMARY_OUT": 0.25,
            "LIQUIDS_BYPASS_IN": 0.4,
            "LIQUIDS_BYPASS_OUT": 0.6,
            "LIQUIDS_SECONDARY_IN": 0.75,
            "LIQUIDS_SECONDARY_OUT": 0.8500000000000001,
            "METHANE_PRIMARY_IN": 0.15000000000000002,
            "METHANE_PRIMARY_OUT": 0.25,
            "METHANE_BYPASS_IN": 0.4,
            "METHANE_BYPASS_OUT": 0.6,
            "METHANE_SECONDARY_IN": 0.75,
            "METHANE_SECONDARY_OUT": 0.8500000000000001,
            "SOLIDS_PRIMARY_IN": 0.15000000000000002,
            "SOLIDS_PRIMARY_OUT": 0.25,
            "SOLIDS_BYPASS_IN": 0.4,
            "SOLIDS_BYPASS_OUT": 0.6,
            "SOLIDS_SECONDARY_IN": 0.75,
            "SOLIDS_SECONDARY_OUT": 0.8500000000000001,
            "URANIUM_PRIMARY_IN": 0.15000000000000002,
            "URANIUM_PRIMARY_OUT": 0.25,
            "URANIUM_BYPASS_IN": 0.4,
            "URANIUM_BYPASS_OUT": 0.6,
            "URANIUM_SECONDARY_IN": 0.75,
            "URANIUM_SECONDARY_OUT": 0.8500000000000001,
        },
        "y_rank": {
            "IMPORT": 0.1,
            "WIND": 0.3,
            "SOLAR": 0.5,
            "HYDRO": 0.6,
            "TRANSFORMATION_IN": 0.9,
            "TRANSFORMATION_OUT": 0.9,
            "INDUSTRY": 0.5,
            "HH_SERVICES": 0.3,
            "EXPORT": 0.2,
            "TRANSPORT": 0.6,
            "AGRICULTURE": 0.8,
            "TRANSFORMATION_LOSSES": 0.9,
            "DISTRIBUTION_LOSSES": 0.9,
            "BIOGAS_PRIMARY_IN": 0.8,
            "BIOGAS_PRIMARY_OUT": 0.8,
            "BIOGAS_BYPASS_IN": 0.8,
            "BIOGAS_BYPASS_OUT": 0.8,
            "BIOGAS_SECONDARY_IN": 0.8,
            "BIOGAS_SECONDARY_OUT": 0.8,
            "ELECTRICITY_PRIMARY_IN": 0.1,
            "ELECTRICITY_PRIMARY_OUT": 0.1,
            "ELECTRICITY_BYPASS_IN": 0.1,
            "ELECTRICITY_BYPASS_OUT": 0.1,
            "ELECTRICITY_SECONDARY_IN": 0.1,
            "ELECTRICITY_SECONDARY_OUT": 0.1,
            "HEAT_PRIMARY_IN": 0.5,
            "HEAT_PRIMARY_OUT": 0.5,
            "HEAT_BYPASS_IN": 0.5,
            "HEAT_BYPASS_OUT": 0.5,
            "HEAT_SECONDARY_IN": 0.5,
            "HEAT_SECONDARY_OUT": 0.5,
            "HYDROGEN_PRIMARY_IN": 0.4,
            "HYDROGEN_PRIMARY_OUT": 0.4,
            "HYDROGEN_BYPASS_IN": 0.4,
            "HYDROGEN_BYPASS_OUT": 0.4,
            "HYDROGEN_SECONDARY_IN": 0.4,
            "HYDROGEN_SECONDARY_OUT": 0.4,
            "LIQUIDS_PRIMARY_IN": 0.7,
            "LIQUIDS_PRIMARY_OUT": 0.7,
            "LIQUIDS_BYPASS_IN": 0.7,
            "LIQUIDS_BYPASS_OUT": 0.7,
            "LIQUIDS_SECONDARY_IN": 0.7,
            "LIQUIDS_SECONDARY_OUT": 0.7,
            "METHANE_PRIMARY_IN": 0.3,
            "METHANE_PRIMARY_OUT": 0.3,
            "METHANE_BYPASS_IN": 0.3,
            "METHANE_BYPASS_OUT": 0.3,
            "METHANE_SECONDARY_IN": 0.3,
            "METHANE_SECONDARY_OUT": 0.3,
            "SOLIDS_PRIMARY_IN": 0.6,
            "SOLIDS_PRIMARY_OUT": 0.6,
            "SOLIDS_BYPASS_IN": 0.6,
            "SOLIDS_BYPASS_OUT": 0.6,
            "SOLIDS_SECONDARY_IN": 0.6,
            "SOLIDS_SECONDARY_OUT": 0.6,
            "URANIUM_PRIMARY_IN": 0.9,
            "URANIUM_PRIMARY_OUT": 0.9,
            "URANIUM_BYPASS_IN": 0.9,
            "URANIUM_BYPASS_OUT": 0.9,
            "URANIUM_SECONDARY_IN": 0.9,
            "URANIUM_SECONDARY_OUT": 0.9,
        },
    }

    nodes = pd.DataFrame(nodes_dict)
    nodes
    return (nodes,)


@app.cell
def _(nodes):
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

    until = 8

    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            node={
                "label": nodes.index,
                "x": nodes["x"].div(2),
                "y": nodes["y_rank"],
                "pad": 10,
            },  # 10 Pixels
            link={
                "source": [0, 43, 44, 4, 44, 45, 5, 46, 47, 48, 48, 48][:until],
                "target": [43, 44, 4, 5, 45, 46, 47, 47, 48, 6, 7, 8][:until],
                "value": [
                    232.0716390976329,
                    232.07163909763293,
                    120.12636366604998,
                    120.12636366605,
                    111.94527543158293,
                    111.94527543158293,
                    80.57139986029,
                    111.94527543158293,
                    192.51667529187293,
                    114.8922091701,
                    0.0,
                    77.624466121755,
                ][:until],
            },
        )
    )

    fig.show()

    return (fig,)


@app.cell
def _(nodes):
    nodes.filter(like="METHANE", axis=0)
    nodes.query("id == 42")
    return


@app.cell
def _(nodes):
    nodes["x"]
    return


@app.cell
def _(fig):
    fig.data[0]["node"]["label"][43]
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
