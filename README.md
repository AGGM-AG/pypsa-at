![Version](https://img.shields.io/badge/version-v0.1.0-purple)
![Size](https://img.shields.io/github/repo-size/AGGM-AG/pypsa-at)
[![Test workflows](https://github.com/AGGM-AG/pypsa-at/actions/workflows/test.yaml/badge.svg)](https://github.com/AGGM-AG/pypsa-at/actions/workflows/test.yaml)
[![CodeQL](https://github.com/AGGM-AG/pypsa-at/actions/workflows/codeql.yaml/badge.svg?branch=main&event=push)](https://github.com/AGGM-AG/pypsa-at/actions/workflows/codeql.yaml)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/AGGM-AG/pypsa-at/main.svg)](https://results.pre-commit.ci/latest/github/AGGM-AG/pypsa-at/main)
[![Pixi Badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/prefix-dev/pixi/main/assets/badge/v0.json)](https://pixi.sh)
![pixi](https://img.shields.io/badge/pixi-≥0.23-brightgreen)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Snakemake](https://img.shields.io/badge/snakemake-≥9-brightgreen.svg?style=flat)](https://snakemake.readthedocs.io)
![Python](https://img.shields.io/badge/python-≥3.10-blue)
[![Docs](https://img.shields.io/badge/docs-mkdocs-blue)](https://pypsa-at.readthedocs.io/en/latest/)
[![Discord](https://img.shields.io/discord/911692131440148490?logo=discord)](https://discord.gg/AnuJBk23FU)

# PyPSA-AT: A Sector-Coupled Open Optimisation Model of the Austrian Energy System

> [!WARNING]
> PyPSA-AT is under very active early development. Pull requests are not being accepted until the first official release
> due to limited resources. After the initial release, we welcome contributions from the community.

**PyPSA-AT** is an Austrian adaptation of the open European energy system
model [PyPSA-Eur](https://github.com/pypsa/pypsa-eur).
It provides a detailed sector-coupled model of the Austrian energy system, including the majority of relevant energy
carriers (electricity, gas, hydrogen, biomass, heat, coal, oil, methanol and ammonia) and demand profiles for the
industry, transport, residential, commercial, and agriculture sectors.

The project builds upon the methodologies developed in [PyPSA-DE](https://github.com/pypsa/pypsa-de) - the adaptation of
PyPSA-Eur for the German energy system - while incorporating Austria-specific network topology, energy system
characteristics, and regulatory frameworks.

For more comprehensive documentation on the underlying PyPSA-Eur/DE framework, model decisions, and implementation
details, please refer to the [PyPSA-Eur documentation](https://pypsa-eur.readthedocs.io/)
and [PyPSA-DE documentation](https://ariadneprojekt.de/modell-dokumentation-pypsa/), respectively.

---

### 🟥⬜🟥 **Deutschsprachige Beschreibung**:

**PyPSA-AT** ist eine österreichische Adaption des europäischen
Energiesystemmodells [PyPSA-Eur](https://github.com/pypsa/pypsa-eur).
Es liefert ein detailliertes, sektorgekoppeltes Modell des österreichischen Energiesystems und inkludiert den Großteil
der wichtigsten Energieträger (Elektrizität, Gas, Wasserstoff, Biomasse, Wärme, Kohle, Öl, Methanol und Ammoniak) sowie
Lastprofile für die Bedarfe von Industrie, Transport, Haushalten, Gewerbe und Landwirtschaft.

Das Projekt baut auf den methodischen Ansätzen auf, die in [PyPSA-DE](https://github.com/pypsa/pypsa-de) - der Adaption
von PyPSA-Eur für das Energiesystem Deutschlands - entwickelt wurden. Gleichzeitig enthält PyPSA-AT
österreichischspezifische Netzwerktopologien mit höherer räumlicher Auflösung innerhalb der Landesgrenzen,
Energiesystemcharakteristika und den regulatorischen Rahmen des Landes.

Für eine umfassendere Beschreibung der zugrundeliegenden Modelle sei hier auf die entsprechenden Dokumentationen
von [PyPSA-Eur](https://pypsa-eur.readthedocs.io/) und [PyPSA-DE](https://ariadneprojekt.de/modell-dokumentation-pypsa/)
verwiesen.

---

## ✨ Features

PyPSA-AT extends the PyPSA-Eur model with Austria-specific enhancements. \
While some features have already been implemented (✅), some are being actively worked on (🔨) or discussed (💡) and many
more are planned in the future (📌).
An overview of our planned and active features can be found in the following table. \
For more detailed implementation information, see
the [mods module documentation](https://pypsa-at.readthedocs.io/en/latest/reference/mods/).

|      TOPIC      |                                                                                                                                                                                                                                                                   FEATURE                                                                                                                                                                                                                                                                    |                                                                                                              DESCRIPTION                                                                                                              | PR | STATUS |
|:---------------:|:--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------:|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------:|:--:|:------:|
|  **Modeling**   |                                                                                                                                                                                                                                                  High spatial and temporal resolution in AT                                                                                                                                                                                                                                                  |                                            Maintain NUTS2 and NUTS3 spatial resolution using administrative clustering in AT and at 1H and 3H temporal resolution in the myopic workflow.                                             | -  |   ✅    |
|                 |                                                                                                                                                                                                                                                       Improve Hydropower technologies                                                                                                                                                                                                                                                        |                                             Differentiate Open- and Closed Loop PHS, reservoirs with and without inflows and improve inflow time series for Austrian hydro power plants.                                              | -  |   📌   |
|                 |                                                                                                                                                                                                                                                                Model coupling                                                                                                                                                                                                                                                                |                                                                       Improve biomass sector accuracy by coupling PyPSA-AT with a dedicated carbon cycle model.                                                                       | -  |   📌   |
|                 |                                                                                                                                                                                                                                                         Endogenous industry demands                                                                                                                                                                                                                                                          |                                                                   Replace the exogenous energy modal split per industry sub-sector with optimized production paths.                                                                   | -  |   📌   |
|                 |                                                                                                                                                                                                                                                            Austrian climate goals                                                                                                                                                                                                                                                            |                                                                      Introduce regional CO2 budgets to comply with Austria's climate goals (CO2 neutral by 2040)                                                                      | -  |   ✅    |
|                 |                                                                                                                                                                                                                                                           Depict Austrian policies                                                                                                                                                                                                                                                           |                                                   Include EAG targets for net renewable electricity production by 2030 and other regulatory requirements in the baseline scenario.                                                    | -  |   🔨   |
| **Calibration** |                                                                                                                                                                                                                                  Enhanced energy demand profiles for all sectors and Austrian NUTS3 regions                                                                                                                                                                                                                                  |                                                        Update demand curves for industry, transport, domestic, commercial and agriculture sectors with NUTS3 resolution in AT.                                                        | -  |   📌   |
|                 |                                                                                                                                                                                                                                       Calibrate renewable energy production capacity potentials in AT                                                                                                                                                                                                                                        |  Limit RES deployment in accordance with [Studie Erneuerbaren Energiepotenziale](https://www.aee-intec.at/project/erneuerbare-energiepotenziale-oesterreich-studie-erneuerbare-energiepotenziale-in-oesterreich-fuer-2030-und-2040/)  | -  |   📌   |
|                 |                                                                                                                                                                                                                                                       Restrict technology occurrences                                                                                                                                                                                                                                                        |                                                             Review technology occurrences such as V2G, SynGas, Pyrolysis, etc. and restrict their first appearance years.                                                             | -  |   📌   |
|                 |                                                                                                                                                                                                                                                            Calibrate Heat sector                                                                                                                                                                                                                                                             |                                            Review and calibrate heat sector including existing capacities per heat system, demand profiles, and endogenous building thermal retrofitting.                                             | -  |   📌   |
| **Validation**  | Compare model results with [Eurostat Energy Balance](https://ec.europa.eu/eurostat/cache/visualisations/energy-balances/enbal.html?geo=EU27_2020&unit=KTOE&language=EN&year=&fuel=fuelMainFuel&siec=TOTAL&details=1&chartOptions=0&stacking=normal&chartBal=&chart=&full=0&chartBalText=&order=DESC&siecs=&dataset=nrg_bal_c&decimals=0&agregates=0&share=false&fuelList=fuelElectricity%2CfuelCombustible%2CfuelNonCombustible%2CfuelOtherPetroleum%2CfuelMainPetroleum%2CfuelOil%2CfuelOtherFossil%2CfuelFossil%2CfuelCoal%2CfuelMainFuel) |                                             Compare PyPSA-AT baseline scenario results with historical energy demands reported in the Eurostat Energy Balance to validate model results.                                              | -  |   🔨   |
| **Input Data**  |                                                                                                                                                                                                                   Improved brownfield data for gas and hydrogen infrastructure provided by [AGGM](https://www.aggm.at/en)                                                                                                                                                                                                                    |                                              Include accurate data on the Austrian methane and hydrogen grids, storage infrastructure, trade volumes and retrofit potentials and costs.                                               | -  |   🔨   |
|                 |                                                                                                                                                                                                                                                         Austrian biomass potentials                                                                                                                                                                                                                                                          | Include Austrian wet and solid biomass potentials as reported by [UBA](https://www.umweltbundesamt.at/energie/erneuerbare-energie/nachhaltige-biomasse-brennstoffe) and [BeST](https://best-research.eu/de/startseite), respectively. | -  |   📌   |
|                 |                                                                                                                                                                                                                                                      Electricity grid brownfield update                                                                                                                                                                                                                                                      |                                                             Update 380 kV network topology and improve resolution of electricity transmission grid for Austrian regions.                                                              | -  |   📌   |

## ⌨️ Installation

Please note that PyPSA-AT is only supported on **Linux** platforms. Installations on Windows or macOS require
modifications currently not supported.

1. Clone the repository:
   ```bash
   git clone https://github.com/AGGM-AG/pypsa-at.git
   cd pypsa-at
   ```

2. Installation using pixi (optional):

   Explicit package installation may be skipped since running commands with `pixi run` installs and activates all
   dependencies in `pixi.toml`.

   ```bash
   pixi install
   ```

## 🚀 Usage

1. Configure your model by adjusting the base scenario in `config/config.at.yaml`
2. Include scenario settings that differ from the base scenario in `config/scenarios.manual.yaml`
3. Generate the scenarios file picked up by the snakemake workflow:
   ```bash
   pixi run snakemake build_scenarios -f --cores 'all'
   ```
   This will populate `config/scenarios.automated.yaml`.

4. Run the model using the default rule `all`:
   ```bash
   pixi run snakemake all --cores 'all' 
   ```

   or activate the virtual environment and call the same workflow using a shorthand
   ```bash
   pixi shell && snakemake -call all 
   ```

## 📖 Documentation

More detailed documentation of PyPSA-AT is hosted on [pypsa-at.readthedocs.io](https://pypsa-at.readthedocs.io).

## 🤝 Contributing

> [!NOTE]
> The development team focuses on establishing a well calibrated representation of the Austrian energy system and does
> not have capacities available to review contributions from the community at the moment. We hope that this will change
> end of 2026 when a first stable version with tests and quality checks has been released.

In general, please install the `pre-commit` hooks if you plan to contribute to this project.

```bash
pixi run pre-commit install
```   

## 🗄️ Data sources

### Scenario data: Ariadne

`ariadne-data/ariadne-database.csv`

* **Source:** Kopernikus Projekt Ariadne
* **Link:** [Ariadne Scenario Explorer](https://ariadne2.apps.ece.iiasa.ac.at/en/explorer?type=line-chart)
* **License:** CC-BY 4.0
* **Description:** Results from
  the [Ariadne Report: Die Energiewende kosteneffizient gestalten](https://ariadneprojekt.de/publikation/report-szenarien-zur-klimaneutralitat-2045/)

## ⚖️ License

This project is licensed under the MIT License - see the [LICENSE.txt](LICENSE.txt) file for details.

Parts of the code that originate from [PyPSA-DE](https://github.com/pypsa/pypsa-de)
or [PyPSA-Eur](https://github.com/pypsa/pypsa-eur) remain under their original MIT licenses. The copyright and
attribution notices from these original projects are preserved in the respective source files.

## 🏅 Acknowledgments

PyPSA-AT builds upon [PyPSA-Eur](https://github.com/pypsa/pypsa-eur) and [PyPSA-DE](https://github.com/pypsa/pypsa-de),
developed by the PyPSA team at TU Berlin and other contributors.

## ✏️ Citation

If you use PyPSA-AT in your research, please cite it as:

```
Worschischek, Philip; Zechner, Nicole; Awetisjan, Vartan; Wernhart, Helmut (2026):
PyPSA-AT - A sector-coupled open optimisation model of the Austrian energy system.
Version 0.1.0. Austrian Gas Grid Management AG.
https://github.com/AGGM-AG/pypsa-at
```

Or in the German version:

```
Worschischek, Philip; Zechner, Nicole; Awetisjan, Vartan; Wernhart, Helmut (2026):
PyPSA-AT - Sektorgekoppeltes Energiesystemmodell des österreichischen Energiesystems.
Version 0.1.0. Austrian Gas Grid Management AG.
https://github.com/AGGM-AG/pypsa-at
```
