[![CodeQL](https://github.com/AGGM-AG/pypsa-at/actions/workflows/codeql.yaml/badge.svg?branch=main&event=push)](https://github.com/AGGM-AG/pypsa-at/actions/workflows/codeql.yaml)
[![Test workflows](https://github.com/AGGM-AG/pypsa-at/actions/workflows/test.yaml/badge.svg?branch=main&event=push)](https://github.com/AGGM-AG/pypsa-at/actions/workflows/test.yaml)
[![Validator Bot](https://github.com/AGGM-AG/pypsa-at/actions/workflows/validate.yaml/badge.svg?branch=main&event=push)](https://github.com/AGGM-AG/pypsa-at/actions/workflows/validate.yaml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Pixi Badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/prefix-dev/pixi/main/assets/badge/v0.json)](https://pixi.sh)
[![MkDocs](https://img.shields.io/badge/docs-mkdocs-blue)](https://www.mkdocs.org/)

# PyPSA-AT: A Sector-Coupled Open Optimisation Model of the Austrian Energy System

**PyPSA-AT** is an Austrian adaptation of the open European energy system model [PyPSA-Eur](https://github.com/pypsa/pypsa-eur). It provides a detailed sector-coupled model of the Austrian energy system, including electricity, heating, and transport sectors.

The project builds upon the methodologies developed in [PyPSA-DE](https://github.com/pypsa/pypsa-de) - the German adaptation of PyPSA-Eur - while incorporating Austrian-specific network topology, energy system characteristics, and regulatory frameworks.

For comprehensive documentation on the underlying PyPSA-Eur framework, model decisions, and implementation details, please refer to the [PyPSA-Eur documentation](https://pypsa-eur.readthedocs.io/) and [PyPSA-DE documentation](https://pypsa.readthedocs.io/en/stable/examples/sector-coupled-de.html).

## Features

PyPSA-AT extends the PyPSA-Eur model with Austrian-specific enhancements:

### Network Modifications
- **Austrian Transmission Capacity Calibration**: Accurate representation of Austrian high-voltage transmission grid capacities based on AGGM data
- **Enhanced Spatial Resolution**: Custom administrative clustering for Austrian regions (AT10/AT35) while maintaining European context
- **Gas Import and Production Differentiation**: Separate modeling of LNG, pipeline gas, and domestic production with realistic cost structures

### Demand Calibration
- **Industrial Demand Updates**: Austrian-specific industrial energy demand profiles
- **Electricity Base Load Disaggregation**: Detailed sectoral breakdown of base electricity consumption

### Data Integration
- **AGGM-Provided Input Data**: All necessary input data is either included in the repository under `/data` or retrieved automatically through workflow rules
- **Population Layout Modifications**: Custom Austrian population distribution for improved spatial accuracy
- **NUTS3 Shape Adjustments**: Refined administrative boundaries for Austrian regions

For detailed implementation information, see the [mods module documentation](https://pypsa-at.readthedocs.io/en/latest/reference/mods/).

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/AGGM-AG/pypsa-at.git
   cd pypsa-at
   ```

2. Installation using pixi (recommended):
   ```bash
   pixi install
   ```

## Usage

1. Configure your model by adjusting the base scenario in `config/config.at.yaml`
2. Include scenario settings that differ from the base scenario in `config/scenarios.manual.yaml`
3. Generate the scenarios file picked up by the snakemake workflow:
   ```bash
   snakemake build_scenarios -f --cores 'all'
   ```
   This will populate `config/scenarios.automated.yaml`.

4. Run the model using the default rule `all`:
   ```bash
   snakemake -call all --cores 'all'
   ```
   or simply:
   ```bash
   snakemake
   ```

## Documentation

Detailed documentation is available at [pypsa-at.readthedocs.io](https://pypsa-at.readthedocs.io).

## Contributing

**Note**: This project is currently in pre-release development. Pull requests are not being accepted until the first official release. After the initial release, we welcome contributions from the community.

## License

This project is licensed under the MIT License - see the [LICENSE.txt](LICENSE.txt) file for details.

Parts of the code that originate from [PyPSA-DE](https://github.com/pypsa/pypsa-de) or [PyPSA-Eur](https://github.com/pypsa/pypsa-eur) remain under their original MIT licenses. The copyright and attribution notices from these original projects are preserved in the respective source files.

## Acknowledgments

PyPSA-AT builds upon [PyPSA-Eur](https://github.com/pypsa/pypsa-eur) and [PyPSA-DE](https://github.com/pypsa/pypsa-de), developed by the PyPSA team at TU Berlin and other contributors.

## Citation

If you use PyPSA-AT in your research, please cite it as:

```
Worschischek, Philip; Avetisjan, Vartan; Wernhart, Helmut (2025):
PyPSA-AT - Sektorgekoppeltes Energiesystemmodell des österreichischen Energiesystems.
Version 0.0.0. Austrian Gas Grid Management AG.
https://github.com/AGGM-AG/pypsa-at
```