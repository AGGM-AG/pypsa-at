import marimo

__generated_with = "0.23.9"
app = marimo.App(width="medium")


@app.cell
def _():
    import pypsa

    return (pypsa,)


@app.cell
def _(pypsa):
    n2025_file = r"results/feat-biogas-brownfield-austria/AT_KN2040/networks/base_s_adm__none_2025.nc"
    n2025 = pypsa.Network(n2025_file)
    return (n2025,)


@app.cell
def _(n2025):
    n2025
    return


@app.cell
def _(n2025):
    n2025.links[n2025.links["carrier"] == "biogas"]
    return


@app.cell
def _(n2025):
    n2025.generators.carrier.unique()
    return


@app.cell
def _(n2025):
    n2025.generators[n2025.generators.carrier == "biogas"].p_nom
    return


if __name__ == "__main__":
    app.run()
