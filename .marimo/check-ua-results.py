import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import pypsa
    import pypsa.statistics

    return (pypsa,)


@app.cell
def _(pypsa):
    # read the relevant result network - base network in 2025
    file = r"results/v2025.04/AT_KN2040/networks/base_s_adm__none_2020.nc"
    n = pypsa.Network(file)
    n
    return (n,)


@app.cell
def _(n):
    gas_pipelines = n.links[n.links.carrier == "gas pipeline"]
    gas_pipelines
    return


@app.cell
def _(n):
    countries = n.buses.location.unique()
    countries
    return (countries,)


@app.cell
def _(countries):
    len(countries)
    return


@app.cell
def _(n):
    # check if the countries that should no longer receive Ukrainian imports really do not:

    cc_list = ["PL", "SK", "RO", "HU"]  # Poland, Slovakia, Romania, Hungary
    for cc in cc_list:
        generator_capacity = n.generators.loc[f"{cc} gas pipeline import", "p_nom"]
        print(generator_capacity)
    return


@app.cell
def _():
    # done :)
    return


if __name__ == "__main__":
    app.run()
