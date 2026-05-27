import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import pypsa

    return (pypsa,)


@app.cell
def _(pypsa):
    file = r"results/feat-brownfield-pipeline-network-update/AT_KN2040/networks/base_s_adm__none_2025.nc"
    n = pypsa.Network(file)
    return (n,)


@app.cell
def _(n):
    n
    return


@app.cell
def _(n):
    gas_pipelines = n.links[n.links.carrier == "gas pipeline"]
    gas_pipelines_AT = gas_pipelines[
        (
            gas_pipelines.bus0.str.startswith("AT")
            | gas_pipelines.bus1.str.startswith("AT")
        )
    ]
    gas_pipelines_AT
    return (gas_pipelines_AT,)


@app.cell
def _(gas_pipelines_AT):
    gas_pipelines_AT_TAG1 = gas_pipelines_AT[
        gas_pipelines_AT.bus0.str.startswith("IT0")
    ]
    gas_pipelines_AT_TAG1
    return


@app.cell
def _(gas_pipelines_AT):
    gas_pipelines_AT_TAG2 = gas_pipelines_AT[
        (gas_pipelines_AT.bus0.str.startswith("AT211"))
    ]
    gas_pipelines_AT_TAG2 = gas_pipelines_AT_TAG2[
        gas_pipelines_AT_TAG2.bus1.str.startswith("AT213")
    ]
    gas_pipelines_AT_TAG2
    return


@app.cell
def _(gas_pipelines_AT_TAG):
    gas_pipelines_AT_TAG.columns
    return


@app.cell
def _(gas_pipelines_AT_TAG):
    gas_pipelines_AT_TAG.location
    return


if __name__ == "__main__":
    app.run()
