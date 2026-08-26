# Data Sources

PyPSA-AT uses the data sources inherited from [PyPSA-Eur](https://pypsa-eur.readthedocs.io/en/latest/data_sources) and [PyPSA-DE](https://ariadneprojekt.de/modell-dokumentation-pypsa/), in addition to the sources listed in the AT data inventory below.

The upstream documentation explains how data sources are retrieved, versioned and, where licensing permits, mirrored. The central registry is [`data/versions.csv`](https://github.com/AGGM-AG/pypsa-at/blob/main/data/versions.csv). Dataset selection is controlled through the `data` section of the configuration. For reproducible runs, use the version and source configured in `config/config.at.yaml` rather than downloading files manually.

## Data inventory

{{ read_csv("data_inventory.csv") }}
