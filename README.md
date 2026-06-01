![Version](https://img.shields.io/badge/version-alpha-purple)
![Size](https://img.shields.io/github/repo-size/AGGM-AG/pypsa-at)
[![Test workflows](https://github.com/AGGM-AG/pypsa-at/actions/workflows/test.yaml/badge.svg)](https://github.com/AGGM-AG/pypsa-at/actions/workflows/test.yaml)
[![CodeQL](https://github.com/AGGM-AG/pypsa-at/actions/workflows/codeql.yaml/badge.svg?branch=main&event=push)](https://github.com/AGGM-AG/pypsa-at/actions/workflows/codeql.yaml)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/AGGM-AG/pypsa-at/main.svg)](https://results.pre-commit.ci/latest/github/AGGM-AG/pypsa-at/main)
[![Pixi Badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/prefix-dev/pixi/main/assets/badge/v0.json)](https://pixi.sh)
![pixi](https://img.shields.io/badge/pixi-≥0.68.0-brightgreen)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Snakemake](https://img.shields.io/badge/snakemake-≥9-brightgreen.svg?style=flat)](https://snakemake.readthedocs.io)
![Python](https://img.shields.io/badge/python-≥3.12-blue)
[![Docs](https://img.shields.io/badge/docs-mkdocs-blue)](https://pypsa-at.readthedocs.io/en/latest/)
[![Discord](https://img.shields.io/discord/911692131440148490?logo=discord)](https://discord.gg/AnuJBk23FU)

# PyPSA-AT: A Sector-Coupled Open Optimisation Model of the Austrian Energy System

> [!WARNING]
> PyPSA-AT is under very active early development. Expect things to change rapidly.

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

## ✨ Features

PyPSA-AT extends PyPSA-Eur and PyPSA-DE with Austria-specific network data, regulatory constraints, and energy
system pathways. The full change history is in
[CHANGELOG.AT.md](https://github.com/AGGM-AG/pypsa-at/blob/main/CHANGELOG.AT.md); implementation details are in the
[documentation](https://pypsa-at.readthedocs.io/en/latest/).

### 🧭 Scenarios
- 🔨 Under active development

### 🧮 Carbon Accounting
- 🔨 Under active development

### 🏭 Existing Powerplants
- 🔨 Under active development

### 🚜 Synthetic Fuels
- 🔨 Under active development

### 🎇 Methane Pyrolysis
- `H2 for industry` bus supporting industrial on-site conversion technologies
- Methane pyrolysis (plasma) as an H₂ production pathway
- 🔨 Under active development

### 🎬 Postprocessing
- Statistics for `remaining_capacity` and `technical_potentials`
- 🔨 Under active development

### 💧 Hydrogen Grid
- 🔨 Under active development

### ⚡ Electricity Grid
- Cross-border electricity flow limits via NTCs (TYNDP corridors)
- 🔨 Under active development

### 🌞 Renewable Energy Potentials
- Solar and wind capacity limits based on the KLIEN study
- 🔨 Under active development

### 🔌 Electricity Demand
- 🔨 Under active development

### 💸 Technology Costs
- 🔨 Under active development

### 🪐 Gas Grid
- Austrian brownfield gas grid calibrated with AGGM expert data; pipeline expansion locked until 2040
- Gas storage capacities updated from AGSI and AT-specific data sources
- 🔨 Under active development

### 🏬 Industry Demand
- 🔨 Under active development

### 🔭 Open-TYNDP
- Capacity trajectories enforced as `p_nom_min`/`p_nom_max` bounds for onwind, solar, solar-hsat, battery, home battery, and H₂ electrolysis across EU countries
- 🔨 Under active development

### 🔥 Heat Sector
- 🔨 Under active development

### 🌳 Biomass Usage
- 🔨 Under active development

### 💍 Model Coupling
- 🔨 Under active development

### 🌊 Hydropower
- 🔨 Under active development

### 🛻 Transport Demand
- 🔨 Under active development

### 💂‍♂️ Regulatory Constraints
- EAG §4(2) net-zero annual electricity balance for Austria
- 🔨 Under active development

### 🛢️ Oil Bus
- 🔨 Under active development

## ⌨️ Installation

   ```bash
   git clone https://github.com/AGGM-AG/pypsa-at.git && cd pypsa-at   # Clone repository
   pixi run workflow                                                  # Install environment and start the workflow
   ```

## 🚀 Usage

### Prerequisites
Please note that PyPSA-AT is only supported on **Linux** platforms. Installations on Windows or macOS require
modifications currently not supported.

[Git](https://git-scm.com/install) and [pixi](https://pixi.prefix.dev/latest/#installation) must be installed.


1. Configure your model by adjusting the base scenario in `config/config.at.yaml`
2. Include scenario settings that differ from the base scenario in `config/scenarios.manual.yaml`
3. Run the model’s Snakemake workflow:
   ```bash
   pixi run workflow
   ```

   or activate the virtual environment and call the same workflow using a shorthand
   ```bash
   pixi shell && snakemake -call at_all
   ```

## 📖 Documentation

More detailed documentation of PyPSA-AT is hosted on [pypsa-at.readthedocs.io](https://pypsa-at.readthedocs.io).

## 🤝 Contributing

> [!NOTE]
> The development team focuses on establishing a well-calibrated representation of the Austrian energy system and 
> has limited capacity to review contributions from the community at the moment.

In general, please install the `pre-commit` hooks if you plan to contribute to this project.

```bash
pixi run pre-commit install
```


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
