# Retrieve and update the E-Control Anlagenregister

The [E-Control Anlagenregister](https://anlagenregister.at) lists all electricity
(*Strom*) and gas (*Gas*) generation plants in Austria with postal code,
technology, bottleneck capacity (*Engpassleistung*) and annual feed-in for the
last six years. PyPSA-AT ships it as the `anlagenregister` dataset in
`data/versions.csv` with two sources:

| Source    | What happens                                                                                                           |
|-----------|------------------------------------------------------------------------------------------------------------------------|
| `build`   | `retrieve_anlagenregister_at` scrapes the website, `build_anlagenregister_at` aggregates the plants to NUTS3 regions. |
| `archive` | `retrieve_anlagenregister_at` downloads the NUTS3-aggregated CSV from Zenodo.                                          |

Both sources end at `data/anlagenregister/<source>/<version>/anlagenregister_nuts3.csv`.

## How the scraping works

The website is a single page application. The *Export als Excel* button
exports the data grid in the browser; there is no download endpoint. The grid
is filled by a POST to `/Home/SearchAnlagenregisterUebersicht` with the search
form values (`Anlagentyp`: 1 = Strom, 2 = Gas; `Bundesland`: `B`, `K`, `NO`,
`OO`, `S`, `ST`, `T`, `V`, `W`). `scripts/pypsa-at/retrieve_anlagenregister_at.py`
replays this request once per Bundesland for *Strom* and once for all of
Austria for *Gas* (empty `Bundesland`, only a few dozen plants) and writes one
plant-level CSV (`anlagenregister_plants.csv`, several hundred thousand rows,
mostly photovoltaics).

The feed-in columns are relative (`Jahressumme_Minus_1` … `_6`); the
reference year is parsed from the landing page and the columns are renamed to
`feedin_kwh_<year>`.

!!! warning "Slow queries"
    A *Strom* query for a large Bundesland takes several minutes on the
    server side. The full retrieval takes roughly 10–30 minutes.

## Aggregation

`scripts/pypsa-at/build_anlagenregister_at.py` maps plants from postal code to
NUTS3 via `data/pypsa-at/AT-Postal-to-NUTS.csv`. Postal codes are cleaned
(whitespace, trailing commas, appended town names); plants whose code is still
invalid are dropped with a warning as long as they are below 0.1 % of total
capacity (about 0.01 % in practice), otherwise the rule fails. It then
aggregates to

`typ` × `nuts3` × `technology` × `first_feedin_year`

with `n_plants`, `capacity_mw` and `feedin_gwh_<year>`. `technology` is the
`TechCode` for Strom (e.g. *Photovoltaik*, *Kleinwasserkraft bis 10 MW*) and the
`Energieträger` for Gas.

### Build years

The register does **not** publish commissioning dates (`Inbetriebnahme` is
empty in the API). As a proxy, `first_feedin_year` is the first year with
feed-in > 0 within the published six-year window:

- plants commissioned inside the window get their actual first operating year,
- older plants get the earliest published year (a lower bound only),
- plants without any feed-in get `NA`.

For decommissioning of brownfield assets in the myopic workflow this proxy is
only usable for recent additions; older vintages need another source (e.g.
powerplantmatching `DateIn` for large plants, or statistical vintage
assumptions per technology).

## Updating the archived dataset

1. Set `data.anlagenregister.source: build` in `config/config.at.yaml` and run

    ```bash
    pixi run snakemake -c1 data/anlagenregister/build/<version>/anlagenregister_nuts3.csv
    ```

2. Upload `anlagenregister_nuts3.csv` to Zenodo.
3. Add an `archive` row for the same version to `data/versions.csv` with the
   Zenodo `.../files` base URL and run `pixi run python test/test_data_versions_layer.py`.
4. Switch `source` back to `archive`.
