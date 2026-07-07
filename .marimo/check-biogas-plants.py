import marimo

__generated_with = "0.23.9"
app = marimo.App(width="medium")


@app.cell
def _():
    import pypsa

    return (pypsa,)


@app.cell
def _(pypsa):
    n2025_file = r"results/biogas-global-threshold-2MW/AT_KN2040/networks/base_s_adm__none_2025.nc"
    n2025 = pypsa.Network(n2025_file)
    return (n2025,)


@app.cell
def _(n2025):
    n2025.links[n2025.links["carrier"] == "biogas"]
    return


@app.cell
def _(n2025):
    n2025.generators[n2025.generators["carrier"] == "biogas"]
    return


@app.cell
def _(n2025):
    n2025.generators[n2025.generators["carrier"] == "unsustainable biogas"]
    return


@app.cell
def _(n2025):
    n2025.statistics.installed_capacity(
        groupby=["location", "carrier"], carrier="unsustainable biogas", drop_zero=False
    )
    return


@app.cell
def _(pypsa):
    b2025_file = r"resources/biogas-global-threshold-2MW/AT_KN2040/networks/base_s_adm__none_2025_brownfield.nc"
    base2025 = pypsa.Network(b2025_file)
    return (base2025,)


@app.cell
def _(base2025):
    base2025.links[base2025.links["carrier"] == "biogas"]
    return


@app.cell
def _(base2025):
    base2025.generators[base2025.generators["carrier"] == "unsustainable biogas"]
    return


if __name__ == "__main__":
    app.run()
