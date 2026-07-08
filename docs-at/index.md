---
hide:
  - toc
---

# PyPSA-AT: A Sector-Coupled Open Optimisation Model of the Austrian Energy System

**PyPSA-AT** is an Austrian adaptation of the open European energy system model [PyPSA-Eur](https://github.com/pypsa/pypsa-eur). It provides a detailed sector-coupled model of the Austrian energy system, including electricity, gas, transport, heating and agriculture sectors.

The project builds upon the methodologies developed in [PyPSA-DE](https://github.com/pypsa/pypsa-de) - the German adaptation of PyPSA-Eur - while incorporating Austrian-specific network topology, energy system characteristics, and regulatory frameworks.

For comprehensive documentation on the underlying PyPSA-Eur framework, model decisions, and implementation details, please refer to the [PyPSA-Eur documentation](https://pypsa-eur.readthedocs.io/) and [PyPSA-DE documentation](https://pypsa.readthedocs.io/en/stable/examples/sector-coupled-de.html).

## Features

PyPSA-AT extends the PyPSA-Eur model with Austria-specific enhancements. \
While some features have already been implemented (✅), some are being actively worked on (🔨) or discussed (💡) and many
more are planned in the future (📌).
An overview of planned and active features can be found in the following table. \
For more detailed implementation information, see the [mods module documentation](reference/mods/index.md).

|      TOPIC      |                                                            FEATURE                                                             |                                                                                                              DESCRIPTION                                                                                                              |                         PR                         | STATUS |
|:---------------:|:------------------------------------------------------------------------------------------------------------------------------:|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------:|:--------------------------------------------------:|:------:|
|  **Modeling**   |                           High spatial and temporal resolution in AT                                                           |                                            Maintain NUTS2 and NUTS3 spatial resolution using administrative clustering in AT and at 1H and 3H temporal resolution in the myopic workflow.                                             | [#53](https://github.com/AGGM-AG/pypsa-at/pull/55) |   ✅    |
|                 |                      Methane Pyrolysis (Plasma) — turquoise hydrogen                                                           |                                        Add methane pyrolysis (plasma variant) as a configurable H₂ production pathway. CH₄ is split into H₂ and solid carbon black; no CO₂ is emitted. Cost data from DEA sheet 104 (2024).          | [#73](https://github.com/AGGM-AG/pypsa-at/pull/73)  |   🔨   |
|                 |                                Improve Hydropower technologies                                                                 |                                             Differentiate open- and closed-loop PHS, reservoirs with and without inflows, and improve inflow time series for Austrian hydropower plants.                                              |                         -                          |   📌   |
|                 |                                          Model coupling                                                                        |                                                                       Improve biomass sector accuracy by coupling PyPSA-AT with a dedicated carbon cycle model.                                                                       |                         -                          |   📌   |
|                 |                                       Endogenous industry demands                                                              |                                                                   Replace the exogenous energy modal split per industry sub-sector with optimized production paths.                                                                   |                         -                          |   📌   |
|                 |                                         Austrian climate goals                                                                 |                                                                      Introduce regional CO2 budgets to comply with Austria's climate goals (CO2 neutral by 2040)                                                                      |                         -                          |   ✅    |
|                 |                                          Depict Austrian policies                                                              |                                                   Include EAG targets for net renewable electricity production by 2030 and other regulatory requirements in the baseline scenario.                                                    |                         -                          |   🔨   |
| **Calibration** |                   Enhanced energy demand profiles for all sectors and Austrian NUTS3 regions                                   |                                                        Update demand curves for industry, transport, domestic, commercial and agriculture sectors with NUTS3 resolution in AT.                                                        |                         -                          |   📌   |
|                 |                   Calibrate renewable energy production capacity potentials in AT                                              |  Limit RES deployment in accordance with [Studie Erneuerbaren Energiepotenziale](https://www.aee-intec.at/project/erneuerbare-energiepotenziale-oesterreich-studie-erneuerbare-energiepotenziale-in-oesterreich-fuer-2030-und-2040/)  |                         -                          |   📌   |
|                 |                                     Restrict technology occurrences                                                            |                                                             Review technology occurrences such as V2G, SynGas, Pyrolysis, etc. and restrict their first appearance years.                                                             |                         -                          |   📌   |
|                 |                                          Calibrate Heat sector                                                                 |                                            Review and calibrate heat sector including existing capacities per heat system, demand profiles, and endogenous building thermal retrofitting.                                             |                         -                          |   📌   |
| **Validation**  |                    Compare model results with Eurostat Energy Balance                                                          |                                             Compare PyPSA-AT baseline scenario results with historical energy demands reported in the Eurostat Energy Balance to validate model results.                                              |                         -                          |   🔨   |
| **Input Data**  |       Improved brownfield data for gas and hydrogen infrastructure provided by [AGGM](https://www.aggm.at/en)                  |                                              Include accurate data on the Austrian methane and hydrogen grids, storage infrastructure, trade volumes and retrofit potentials and costs.                                               |                         -                          |   🔨   |
|                 |                                    Austrian biomass potentials                                                                 | Include Austrian wet and solid biomass potentials as reported by [UBA](https://www.umweltbundesamt.at/energie/erneuerbare-energie/nachhaltige-biomasse-brennstoffe) and [BeST](https://best-research.eu/de/startseite), respectively. |                         -                          |   📌   |
|                 |                                  Electricity grid brownfield update                                                            |                                                             Update 380 kV network topology and improve resolution of electricity transmission grid for Austrian regions.                                                              |                         -                          |   📌   |

## Installation

Please note that PyPSA-AT is only supported on **Linux** platforms. Installations on Windows or macOS require
modifications currently not supported.

1. Clone the repository:
   ```bash
   git clone https://github.com/AGGM-AG/pypsa-at.git
   cd pypsa-at
   ```

2. Installation using pixi (optional):

   Explicit package installation may be skipped since running commands with `pixi run` installs and activates all dependencies in `pixi.toml`.

   ```bash
   pixi install
   ```

## Usage

1. Configure your model by adjusting the base scenario in `config/config.at.yaml`
2. Include scenario settings that differ from the base scenario in `config/scenarios.manual.yaml`
3. Run the model's Snakemake workflow:
   ```bash
   pixi run workflow
   ```
   or activate your virtual environment and run snakemake using a shorthand:
   ```bash
   pixi shell
   snakemake all_at -call
   ```

## Contributing

!!! note "Limited contribution capacity"
    The development team focuses on establishing a well-calibrated representation of the Austrian energy system and
    has limited capacity to review contributions from the community at the moment.

In general, please install the `pre-commit` hooks if you plan to contribute to this project.

```bash
pixi run pre-commit install
```

## License

This project is licensed under the MIT License - see the [LICENSE.txt](https://github.com/AGGM-AG/pypsa-at/blob/main/LICENSE.txt) file for details.

Parts of the code that originate from [PyPSA-DE](https://github.com/pypsa/pypsa-de) or [PyPSA-Eur](https://github.com/pypsa/pypsa-eur) remain under their original MIT licenses. The copyright and attribution notices from these original projects are preserved in the respective source files.

## Acknowledgments

PyPSA-AT builds upon [PyPSA-Eur](https://github.com/pypsa/pypsa-eur) and [PyPSA-DE](https://github.com/pypsa/pypsa-de), developed by the PyPSA team at TU Berlin and other contributors.

## Citation

If you use PyPSA-AT in your research, please cite it as:

```
Worschischek, Philip; Zechner, Nicole; Avetisjan, Vartan; Wernhart, Helmut (2026):
PyPSA-AT - Sektorgekoppeltes Energiesystemmodell des österreichischen Energiesystems.
Version 0.1.0. Austrian Gas Grid Management AG.
https://github.com/AGGM-AG/pypsa-at
```

## Documentation Structure

The documentation follows the best practice for project documentation as described in the [Diátaxis documentation framework](https://diataxis.fr/) and consists of four separate parts:

1. [How-To Guides](how-to-guides/index.md)
2. [Tutorials](tutorials/index.md)
3. [Reference](reference/evals/index.md)
4. [Explanation](explanations/index.md)

Quickly find what you're looking for depending on your use case by looking at the different pages.

This documentation is built using [MkDocs](https://www.mkdocs.org/), [mkdocstrings](https://mkdocstrings.github.io/python/), and the [Material for MkDocs theme](https://squidfunk.github.io/mkdocs-material/getting-started/).
