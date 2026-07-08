# TYNDP 2024 Hydrogen Import Infrastructure

Hydrogen imports from outside Europe are a pivotal supply-side lever in long-term
decarbonisation scenarios. PyPSA-AT represents these imports using corridor-level data
from the ENTSO-E / ENTSOG [TYNDP 2024 Scenarios](https://2024.entsos-tyndp-scenarios.eu/),
which provides per-corridor capacity limits, annual energy budgets, and supply costs.
This replaces the upstream PyPSA-Eur default of simple uniform-cost generators.

## Why Explicit Import Corridors Matter

Europe cannot decarbonise purely through domestic renewable build-out; external hydrogen
supply — from North Africa, the Middle East, or Norway — is expected to play a
significant role after 2030. Austria is entirely landlocked, so it receives imported
hydrogen only via the evolving European H₂ backbone network. Without spatially and
economically differentiated import corridors, the model cannot distinguish:

- **Pipeline imports** (low transport loss, infrastructure-intensive) from
  **shipping** routes (liquefied H₂ or ammonia carriers, higher reconversion cost)
- **Low-cost bands** representing the most competitive renewable-rich origin regions,
  which are limited in annual volume
- **Higher-cost bands** that can deliver larger volumes but at greater expense

The TYNDP 2024 data encodes all of this in a single dataset, structured around
**import corridors** with stepped **supply bands** (sections 14.2.2 and 15.1 of
the [TYNDP 2024 Scenarios Methodology Report](https://2024.entsos-tyndp-scenarios.eu/wp-content/uploads/2025/01/TYNDP_2024_Scenarios_Methodology_Report_Final_Version_250128.pdf)).

## TYNDP 2024 Data Structure

### Corridors and Supply Bands

Each row in the raw source file (`H2 IMPORTS GENERATORS PROPERTIES.xlsx`) represents
one **supply band** of one import corridor. A corridor connects a source node outside
Europe (`NODE FROM`) to a European destination node (`NODE TO`). Multiple rows with the
same origin-destination pair but different band suffixes form a **stepped supply curve**:
cheaper tranches are limited in volume; more expensive tranches unlock additional supply.

| Source column | PyPSA attribute | Unit | Meaning |
|---|---|---|---|
| `NODE FROM` | `bus0` (country code) | — | Origin country or hub (e.g. `DZ` = Algeria, `NO` = Norway, `Ammonia` = dedicated NH₃ import node) |
| `NODE TO` | `bus1` | — | European destination network node |
| `MAX CAPACITY [MW]` | `p_nom` | MW | Peak delivery power of this supply band |
| `OFFER PRICE [€/MWh]` | `marginal_cost` | €/MWh_H₂ | Levelised cost of this supply tranche |
| `MAX ENERGY YEAR [GWh]` | `e_sum_max` | MWh/year | Maximum annual energy deliverable via this band |
| `CORRIDOR` | index + `Band` | — | Full corridor identifier; the band suffix encodes the supply tranche |

The **band** is extracted from the last segment of the `CORRIDOR` string and is used
both to create a unique row index and to set the PyPSA Link `carrier` (e.g.,
`"H2 import pipeline"`, `"H2 import lh2"`).

### Scenarios

The import dataset contains entries for three TYNDP 2024 scenarios:

| Scenario code | TYNDP name | Description |
|---|---|---|
| `GA` | Global Ambition | High international cooperation; large import volumes at competitive costs |
| `DE` | Distributed Energy | More self-sufficient Europe; smaller but still significant imports |
| `NT` | National Trends | Modest ambition; no interzonal H₂ pipeline capacities defined |

Rows with `Scenario == "All"` are included regardless of the selected scenario and
represent supply options assumed available in every pathway.

### Supply Band Methodology

TYNDP 2024 does not model each import corridor as a single supply option at one price.
Instead, each corridor is split into two **supply bands** — a low-price tranche and a
high-price tranche — each with its own annual volume limit and marginal cost. Together
they form a stepped supply curve: the model exhausts the cheaper band first before
drawing on the more expensive one.

The band structure and prices are derived from **base prices** (from the
European Hydrogen Backbone study, reproduced in Table 26 of the methodology report)
and then adjusted by scenario and by band:

| Base price (€/MWh) | North Africa | Ukraine | Norway |
|---|---:|---:|---:|
| 2030 | 63 | 78 | 48 |
| 2040 | 42 | 51 | 48 |
| 2050 | 42 | 51 | 48 |

**Scenario adjustments** shift the base price up or down to reflect each scenario's
storyline on international cooperation and import competitiveness:

| Scenario | 2040 adjustment | 2050 adjustment |
|---|---|---|
| DE (Distributed Energy) | +15 % | +15 % (same) |
| GA (Global Ambition) | −15 % | −20 % |
| NT+ (National Trends) | fixed quantities only (see below) | — |

**Band price modifiers** are then applied symmetrically around the adjusted base price:
the low-price band receives a −25 % discount; the high-price band a +25 % premium.
For shipped carriers (LH2, ammonia), the low band always has a price of zero.

The **volume split** between bands differs by scenario:

| Scenario | Low band share | High band share |
|---|---|---|
| DE | 30 % of corridor potential | 70 % |
| GA | 50 % of corridor potential | 50 % |

This is reflected directly in the `e_sum_max` values in the Excel file: the low-band
row carries 30 % (DE) or 50 % (GA) of the total annual energy budget for that
corridor, and the high-band row carries the remainder.

!!! example "Worked example — North Africa → Europe, DE scenario, 2040"
    Base price: 42 €/MWh × 1.15 = **48.3 €/MWh** (adjusted)

    | Band | Price | Annual volume |
    |---|---|---|
    | Low | 48.3 × 0.75 = **36.2 €/MWh** | 86.7 TWh/yr (≈ 30 %) |
    | High | 48.3 × 1.25 = **60.4 €/MWh** | 217.1 TWh/yr (≈ 70 %) |

    These match Table 28 of the methodology report exactly.

#### National Trends+ (NT+) fixed-quantity logic

The NT+ scenario uses a different approach for 2030 and 2035, grounded in the
**National Energy and Climate Plans (NECPs)**. Rather than priced supply bands, a
**fixed quantity** is established for each corridor and these imports carry no price
(i.e. `marginal_cost = 0`). The logic is:

- In 2030 and 2035 the fixed quantity is **30 % of the corridor's import potential**.
  Imports cannot exceed this predetermined share.
- Exception: the Algeria → Italy corridor uses **51 %**, reflecting the
  PCI SouthH2 Corridor (450 GWh/day, approved 2022).
- Liquefied import segments are adjusted to match specific NECP figures.

For 2040 in NT+, a minimum fixed import is again set to 30 % of the total import
(zero price, NECP-aligned), while the **residual potential** (the remaining 70 %) is
available at the base price with a +25 % premium.

How this reaches PyPSA-AT: the NT+ fixed-quantity rows in the source Excel have a
non-numeric value in the `OFFER PRICE [€/MWh]` column (the text "Fixed quantity").
`clean_tyndp_h2_imports.py` coerces non-numeric price values to `NaN` and fills them
with `0.0` (lines 104–107), so these rows enter the model as zero-marginal-cost
generators bounded only by `e_sum_max`.

#### Ammonia: fixed minimum import

Ammonia has a **fixed minimum import quantity** in every time horizon to ensure
Security of Supply diversity. The fixed low-band volume is set at scenario level
(e.g. DE 2040: 135 TWh/yr, GA 2040: 135 TWh/yr per Table 28). The low-price ammonia
band always has `marginal_cost = 0` regardless of scenario; the high-price ammonia
band carries a positive price (e.g. DE 2040: 104 €/MWh, GA 2050: 69 €/MWh).

!!! note "`OFFER QUANTITY [MW]` is not currently used"
    The source Excel also contains an `OFFER QUANTITY [MW]` column representing a
    sustainable (non-peak) delivery rate, distinct from `MAX CAPACITY [MW]`. The
    cleaning script preserves this as `offer_quantity` in the prepped CSV, but
    `prepare_sector_network.py:add_import_options` does not pass it to `n.add()`.
    Only `p_nom` (max capacity), `marginal_cost`, and `e_sum_max` are attached to
    the network. The `offer_quantity` field is available for future use.

### Ammonia as a Hydrogen Carrier

The `Ammonia` source node represents imports via an **ammonia shipping route**.
Ammonia (NH₃) is a dense liquid carrier for hydrogen that can be transported by sea
without cryogenic infrastructure. At the European port of entry, ammonia is
catalytically cracked back into H₂. The TYNDP dataset treats this as an
"H₂ import" corridor with higher conversion cost embedded in the offer price.
The source coordinates are placed near the Faroe Islands (an ENTSO-E convention for
the ammonia hub) in `clean_tyndp_h2_imports.py:match_centroids`.

## Data Processing Pipeline

Four sequential steps transform the raw TYNDP Excel file into network components:

```
data/tyndp/Hydrogen/H2 IMPORTS GENERATORS PROPERTIES.xlsx
        │
        ▼  clean_tyndp_h2_imports  (scripts/open-tyndp/clean_tyndp_h2_imports.py)
resources/h2_import_potentials_prepped.csv
        │   • rename columns to PyPSA conventions
        │   • convert e_sum_max from GWh → MWh
        │   • coerce marginal_cost to numeric (NaN → 0)
        │   • extract Band from corridor string
        │   • snap source node to country centroid coordinates
        │
        ▼  build_tyndp_h2_imports  (scripts/open-tyndp/build_tyndp_h2_imports.py)
resources/h2_import_potentials_{planning_horizons}.csv
        │   • filter by planning year (wildcards.planning_horizons)
        │   • filter by scenario (Scenario == 'All' or selected scenario)
        │
        ▼  modify_prenetwork  (mods/network/h2.py:add_h2_imports)
Network components attached to n
```

**Step 1 — `clean_tyndp_h2_imports`**
Reads the raw Excel file and produces a scenario- and year-agnostic cleaned CSV.
Country centroid coordinates are resolved from `data/countries_centroids.geojson` and
assigned to each source node so that import buses have valid geographic positions.
The rule requires `data/countries_centroids.geojson` (retrieved by
`retrieve_countries_centroids` from a public GeoJSON of world country centroids).

**Step 2 — `build_tyndp_h2_imports`**
Filters the prepped CSV to the specific planning year and TYNDP scenario.
The output is `resources/h2_import_potentials_{planning_horizons}.csv` — one file
per planning horizon, fed directly into `prepare_sector_network` as a conditional
Snakemake input.

**Step 3 — `add_h2_imports`**
Reads the filtered CSV and attaches one Generator per corridor band directly to the
domestic H₂ bus. See the [PyPSA topology section](#pypsa-network-topology) below.

## PyPSA Network Topology

Each supply band is represented as a single Generator:

```
[import Generator]─►[domestic H2 bus]
  carrier="import H2"
  p_nom (MW)
  e_sum_max (MWh/yr)
  marginal_cost (€/MWh)
  p_nom_extendable=False
```

**Import Generator**
One Generator per corridor band, attached directly to the domestic H₂ bus of
the destination country. Key properties:

- `bus`: `"{bus1} H2"` (or `"{bus1} H2 Z2"` when `sector.h2_zones_tyndp=True`).
- `p_nom_extendable=False`: import capacity is fixed at the TYNDP value, not
  a decision variable for the optimiser.
- `p_nom`: maximum delivery power from the TYNDP `MAX CAPACITY` column.
- `e_sum_max`: annual energy cap from the TYNDP `MAX ENERGY YEAR` column (converted
  to MWh). This prevents the model from over-using a low-cost band in every hour
  of the year — the budget constraint is the primary mechanism enforcing supply
  band logic.
- `marginal_cost`: the TYNDP offer price in €/MWh_H₂.
- `carrier`: `"import H2"` for all bands.

!!! note experimental, untested: "H2 bus zone suffix"
    When `sector.h2_zones_tyndp=True`, the model uses a two-zone H₂ topology
    (upstream TYNDP convention: Zone 1 for domestic production, Zone 2 for
    long-distance transport). Import generators connect to the Zone 2 bus
    (`H2 Z2`). When the flag is `False` (default in PyPSA-AT), all H₂
    flows on a single `H2` bus.

## Fallback Mode

When `sector.h2_topology_tyndp=False`, the TYNDP corridor data is ignored entirely.
Instead, H₂ import generators are placed at every gas pipeline node (using
`gas_input_nodes["pipeline"]`), with a uniform marginal cost from
`sector.imports.price.H2` and no annual energy cap. This is the upstream
PyPSA-Eur default — it provides H₂ supply flexibility but gives no information
about where imports originate or their infrastructure cost structure.

```python
# Fallback path (prepare_sector_network.py lines 6596–6607)
p_nom = gas_input_nodes["pipeline"].dropna()
p_nom.rename(lambda x: x + " H2", inplace=True)
n.add("Generator", p_nom.index, suffix=" import",
      bus=p_nom.index, carrier="import H2",
      p_nom=p_nom, marginal_cost=import_options["H2"])
```

## Configuration

```yaml
# config/config.at.yaml
sector:
  imports:
    enable: true
    carriers_tyndp:
      - H2                   # include H2 in the import options
  h2_topology_tyndp: true    # use TYNDP corridor data; false = fallback mode
```

`h2_topology_tyndp` is the only switch. When it is `true`, the rule
`build_tyndp_h2_imports` is included in the DAG and
`resources/h2_import_potentials_{planning_horizons}.csv` is passed to
`modify_prenetwork_at` as a Snakemake input (see
`rules/pypsa-at/modify.smk`). The Snakemake `branch()` helper
passes an empty list when the flag is `false`, so the fallback path is
taken automatically.

The TYNDP scenario used for H₂ imports is controlled by the scenario selection
in `build_tyndp_h2_imports.py`. The AT default is `DE` (Distributed Energy),
consistent with the base scenario lineage from PyPSA-DE.
