import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")


@app.cell
def _(mo):
    mo.md(r"""
    ### logs from run:
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ```log
    INFO:mods.constraints:Limiting emissions in country AT to 0.0% of 1990 levels, i.e. 0.00 tCO2/a
    INFO:mods.constraints:For AT adding following link carriers to port 0 CO2 constraint: []
    INFO:mods.constraints:For AT adding following link carriers to port 1 CO2 constraint: ['HVC to air', 'process emissions', 'process emissions CC']
    INFO:mods.constraints:For AT adding following link carriers to port 4 CO2 constraint: []
    INFO:mods.constraints:For AT adding following link carriers to port 3 CO2 constraint: ['BioSNG', 'BioSNG CC', 'CCGT methanol CC', 'allam methanol', 'biogas to gas CC', 'electrobiofuels', 'methanol-to-kerosene', 'solid biomass to hydrogen', 'urban central gas CHP', 'urban central gas CHP CC', 'urban central solid biomass CHP CC', 'waste CHP', 'waste CHP CC']
    INFO:mods.constraints:For AT adding following link carriers to port 2 CO2 constraint: ['CCGT', 'CCGT methanol', 'DAC', 'Methanol steam reforming', 'Methanol steam reforming CC', 'OCGT', 'OCGT methanol', 'SMR', 'SMR CC', 'agriculture machinery oil', 'biogas to gas', 'biomass to liquid', 'biomass to liquid CC', 'biomass-to-methanol', 'biomass-to-methanol CC', 'coal for industry', 'gas for industry', 'gas for industry CC', 'industry methanol', 'land transport oil', 'municipal solid waste', 'residential rural gas boiler', 'residential urban decentral gas boiler', 'services rural gas boiler', 'services urban decentral gas boiler', 'shipping methanol', 'shipping oil', 'solid biomass for industry CC', 'urban central gas boiler']
    INFO:mods.constraints:Adding domestic aviation emissions for AT with a factor of 0.06
    ```
    """)
    return


@app.cell
def _():
    port1 = ["HVC to air", "process emissions", "process emissions CC"]
    port2 = [
        "CCGT",
        "CCGT methanol",
        "DAC",
        "Methanol steam reforming",
        "Methanol steam reforming CC",
        "OCGT",
        "OCGT methanol",
        "SMR",
        "SMR CC",
        "agriculture machinery oil",
        "biogas to gas",
        "biomass to liquid",
        "biomass to liquid CC",
        "biomass-to-methanol",
        "biomass-to-methanol CC",
        "coal for industry",
        "gas for industry",
        "gas for industry CC",
        "industry methanol",
        "land transport oil",
        "municipal solid waste",
        "residential rural gas boiler",
        "residential urban decentral gas boiler",
        "services rural gas boiler",
        "services urban decentral gas boiler",
        "shipping methanol",
        "shipping oil",
        "solid biomass for industry CC",
        "urban central gas boiler",
    ]
    port3 = [
        "BioSNG",
        "BioSNG CC",
        "CCGT methanol CC",
        "allam methanol",
        "biogas to gas CC",
        "electrobiofuels",
        "methanol-to-kerosene",
        "solid biomass to hydrogen",
        "urban central gas CHP",
        "urban central gas CHP CC",
        "urban central solid biomass CHP CC",
        "waste CHP",
        "waste CHP CC",
    ]
    port_all = sorted(set(port1 + port2 + port3))
    assert len(port_all) == len(port1 + port2 + port3), (
        "Some carrier were added multiple times to the constraint."
    )
    return


@app.cell
def _(mo, networks):
    selected_year = mo.ui.radio(options=networks.index, value="2040", label="Year")
    selected_year
    return (selected_year,)


@app.cell
def _(networks, selected_year):
    n = networks[selected_year.value]
    eb = n.statistics.energy_balance(
        groupby=["location", "carrier", "bus_carrier"], bus_carrier="co2"
    )
    at_locations = eb.index.get_level_values("location").str.startswith("AT")
    eb = (
        eb[at_locations]
        .droplevel("location", axis=0)
        .groupby(["carrier", "bus_carrier"])
        .sum()
    )
    eb
    return eb, n


@app.cell
def _(eb):
    eb.sum()
    return


@app.cell
def _(eb):
    emissions = eb[eb > 0].sort_values(ascending=False)
    emissions.loc[("kerosene for aviation", "co2")] = (
        emissions.loc[("kerosene for aviation", "co2")] * 0.06
    )
    emissions
    return (emissions,)


@app.cell
def _(eb):
    deductions = eb[eb < 0].sort_values(ascending=True)
    deductions
    return (deductions,)


@app.cell
def _(eb):
    import pandas as pd

    eb.plot.bar()
    return (pd,)


@app.cell
def _(deductions, emissions, pd):
    bal = pd.concat(
        [emissions.to_frame("emissions").sum(), deductions.to_frame("deductions").sum()]
    )
    bal
    return (bal,)


@app.cell
def _(bal):
    bal.plot.bar()
    return


@app.cell
def _(eb):
    assert not any(eb.index.duplicated())
    return


@app.cell
def _(n):
    n.meta["solving"]["constraints"]["co2_budget_national"]
    return


@app.cell
def _():
    return


@app.cell
def _(read_networks):
    results_path = "results/v2025.04/AT_KN2040"
    networks = read_networks(results_path)
    return (networks,)


@app.cell
def _():
    return


@app.cell
def _():
    import sys

    sys.path.insert(0, ".")

    import marimo as mo

    return (mo,)


@app.cell
def _():
    from evals.fileio import read_networks

    return (read_networks,)


if __name__ == "__main__":
    app.run()
