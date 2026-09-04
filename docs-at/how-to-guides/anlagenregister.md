# E-Control Anlagenregister

The [Anlagenregister](https://anlagenregister.at) of the Austrian regulator
E-Control lists every electricity generation plant and every biomethane
injection plant in Austria. PyPSA-AT uses it as a regional inventory of
existing generation capacity: how much is installed, of which technology,
in which region, and — for recent plants — since when.

## What the dataset contains

For each plant the register publishes:

| Field                    | Meaning                                                                          |
|--------------------------|----------------------------------------------------------------------------------|
| Postal code, town        | Location. PyPSA-AT maps the postal code to a NUTS3 region.                      |
| Bundesland               | Federal state.                                                                   |
| Technology               | For electricity: e.g. *Photovoltaik*, *Windenergie*, *Kleinwasserkraft bis 10 MW*, *Erdgas*. For gas: the injected energy carrier (*Erneuerbare Gase*). |
| Bottleneck capacity      | *Engpassleistung* — the maximum continuous output of the plant.                  |
| Annual feed-in           | Energy fed into the grid in each of the last six calendar years.                 |

Plant names, operators and commissioning dates are **not** published.

The register is split into an electricity part (*Strom*, roughly 600,000 plants,
almost all of them rooftop photovoltaics) and a gas part (*Gas*, a few dozen
biomethane plants). PyPSA-AT downloads both.

!!! note "Units"
    Bottleneck capacity is electrical output for *Strom* plants and gas
    injection capacity for *Gas* plants. The aggregated file carries the unit
    in a separate column (`MW_el` and `MW_HHV`, the latter on a gross calorific
    value basis as customary in the Austrian gas market). Do not sum the two
    parts.

## What PyPSA-AT does with it

1. **Download.** All plants are downloaded from the website. This takes
   roughly 15 minutes because the electricity part is large.
2. **Map to regions.** Each plant is assigned to its NUTS3 region by postal
   code. A few hundred plants (about 0.01 % of the capacity) have unreadable
   postal codes and are left out; a warning in the log tells how many. If the
   unreadable share ever exceeded 0.1 % of the capacity, the workflow would
   stop so the cause can be investigated.
3. **Aggregate.** Plants are summed per *typ* (Strom/Gas), NUTS3 region,
   technology and first feed-in year (see below). The result is a small table
   with the number of plants, the capacity, and the annual feed-in per group.

The aggregated table is the file used by the model. The plant-level CSV is
the artifact mirrored on Zenodo; the aggregation always runs locally, for both 
dataset sources.

### Build years

The register does not publish commissioning dates. As a substitute, PyPSA-AT
records for each plant the **first year with feed-in greater than zero** within
the six published years:

- A plant commissioned within the last six years gets its actual first
  operating year.
- An older plant gets the earliest published year. This is only a lower bound —
  the plant may be decades older.
- A plant without any feed-in in the six years gets no year.

For decommissioning of existing assets in the myopic workflow this substitute
is therefore only reliable for recent additions, which covers most of the
photovoltaic and wind capacity built during the recent expansion. Older
vintages (large hydro, thermal plants) need another source such as the
powerplantmatching database or per-technology age assumptions.

## Data versions and updating

The dataset is registered as `anlagenregister` in `data/versions.csv` and
selected through the `data` section of `config/config.at.yaml`:

| Source    | Behaviour                                                                                            |
|-----------|------------------------------------------------------------------------------------------------------|
| `archive` | Download the mirrored plant-level CSV from Zenodo and aggregate locally. Fast and reproducible — the default once a mirrored version is published. |
| `build`   | Scrape the website and aggregate. Use this only to create a new version.                             |

Creating and publishing a new version is a developer task; the procedure is
described in the docstring of `scripts/pypsa-at/retrieve_anlagenregister_at.py`.
