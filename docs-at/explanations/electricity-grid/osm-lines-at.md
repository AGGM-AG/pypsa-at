# OSM-AT Data Processing Pipeline

## OSM as a Source for the Austrian Electricity Network

OpenStreetMap (OSM) is the primary data source for the electricity network in
PyPSA-Eur. For Austria, OSM provides a particularly reliable foundation: a
recent validation study by Gaumnitz et al. (2024) compared OSM-derived network
data against official TSO records and found that OSM contains a highly accurate
representation of the Austrian high-voltage transmission grid, with strong
agreement at both the 220 kV and 380 kV levels
([Gaumnitz et al., 2024](https://www.sciencedirect.com/science/article/pii/S016740482400347X?via%3Dihub)).

## The OSM-AT Archive

The pre-processed AT-specific OSM dataset is published on Zenodo:

> **Zenodo record 19235142** — [https://zenodo.org/records/19235142](https://zenodo.org/records/19235142)

This archive is the default data source when `data.osm.source: archive` is set
in the config. It is fetched automatically by the `retrieve_osm_archive` rule:

```yaml title="config/config.at.yaml"
data:
  osm:
    source: archive
    version: 0.2-at
```

The archive was produced by applying the same processing steps described in this
page to an OSM snapshot. Switching to `source: build` and `version: unknown` re-runs the full pipeline
from scratch using the PyPSA-Eur `build_osm_network` outputs.

## The Build Pipeline

When `data.osm.source: build` and `data.osm.version: unknown` is configured, PyPSA-AT adds a second rule
`build_osm_network_at` immediately after the PyPSA-Eur `build_osm_network` rule:

```
build_osm_network  →  build_osm_network_at  →  base_network
  (PyPSA-Eur)           (PyPSA-AT)
  resources/osm/build/  resources/osm/build-at/
```

`build_osm_network_at` reads the five network CSV files produced by
`build_osm_network` (`buses`, `lines`, `links`, `converters`, `transformers`),
applies AT-specific filtering, and writes the results to
`resources/osm/build-at/`. The downstream `base_network` rule is automatically
redirected to consume from `build-at/` by the `input_base_network` override in
`rules/pypsa-at/modify.smk`.

??? info "Running the snakemake rule"

    ```sh
    pixi run snakemake build_osm_network_at -call
    ```

    The `--rerun-triggers mtime` flag prevents re-downloading existing files when
    `data/osm/build/unknown` already partly exists:

    ```sh
    pixi run snakemake build_osm_network_at -call --rerun-triggers mtime
    ```


## Line Selection Rules

The Austrian 110 kV network is not a homogeneous transmission grid. It mixes
railway traction lines that are electrically separate from the public grid,
distribution assets belonging to nine different DSOs, and radial feeders that
carry no transit power. Modelling all of it as transmission capacity would let
the optimiser move bulk power along paths that do not exist in reality — in
particular, it would create cross-regional corridors at 110 kV where the real
network only has a distribution connection.

Six rules decide whether a line is kept. They are evaluated **in order and the
first match wins**, so every line carries exactly one reason.

| #   | Rule              | Condition                                                   | Result     |
|-----|-------------------|-------------------------------------------------------------|------------|
| R0  | `TRACTION`        | 16.7 Hz, or ÖBB-operated without an explicit 50 Hz tag       | **drop**   |
| R1  | `CROSS_BORDER_LV` | below 220 kV with exactly one endpoint in Austria, unless TSO-operated | **drop** |
| R2  | `TRANSMISSION`    | 220 kV and above                                             | **keep**   |
| R2b | `APG_TSO`         | operated by Austrian Power Grid, at any voltage              | **keep**   |
| R3  | `INTRA_REGION`    | both endpoints in the same NUTS3 region                      | **keep**   |
| R4  | `SOLE_FEED`       | documented feed of a region without a ≥220 kV substation     | **keep**   |
| R5  | `INTER_REGION`    | any remaining 110 kV line crossing a NUTS3 boundary          | **drop**   |

Applied to `osm-at v0.3`, this keeps 688 of 763 Austrian lines.

### Railway traction (R0)

The Austrian railway network runs at 16.7 Hz on its own galvanically separate
grid. Its lines cannot exchange power with the 50 Hz system and do not belong in
the model at all. They are nonetheless present in the source data, because the
upstream OSM cleaning overwrites the frequency tag with `50` and thereby
relabels traction as ordinary AC. PyPSA-AT therefore recovers the original
frequency tag from the raw OSM data and drops the affected lines — 93 in
`v0.3`, mostly ÖBB-Infrastruktur.

One exception matters: ÖBB also owns a small number of genuine 50 Hz lines that
feed its converter stations from the public grid. An explicit 50 Hz tag
therefore always wins over the operator name, so those lines are kept.

### Cross-border 110 kV lines (R1)

Cross-border lines below 220 kV are not TSO interconnectors. They are either
distribution tie-lines between neighbouring DSO grids, or radial connections
from a power plant to a substation across the border. Keeping them would
inflate Austria's cross-border exchange capacity with capacity that cannot be
scheduled. Cross-border lines at 220 kV and above are genuine interconnectors
and are always kept.

TSO-operated lines are exempt: an APG-operated 110 kV interconnector is
scheduled transmission infrastructure, not a distribution tie, so it stays in
the dataset (four such lines in `v0.3`, all towards Germany).

This rule is applied when the archive is built, so a line matching it never
appears in the published dataset.

### TSO-operated lines (R2b)

APG operates a number of lines at 110 kV. These are part of the transmission
system irrespective of their voltage level and are kept unconditionally, ahead
of any of the regional rules below. The operator is read from the OSM
`operator` tag, which is spelled inconsistently — `Austrian Power Grid AG`,
`APG`, `Verbund / APG` and several variants all map onto a single canonical
name. Verbund Hydro Power is deliberately **not** treated as the TSO.

### Cross-regional corridors (R3, R5)

A 110 kV line with both endpoints inside the same NUTS3 region cannot carry
inter-regional transit and is always kept — it represents the local
distribution topology within the region.

A 110 kV line crossing a NUTS3 boundary is dropped. Because regions are the
model's spatial resolution, such a line would become a transmission corridor
between two model nodes, letting power flow between regions on a voltage level
that in reality is fragmented between DSOs, is separated by transformers, and
is partly switched out of service ("gelöschte Netze"). The transmission grid at
220 kV and above already provides the real inter-regional paths.

### Regions without a transmission substation (R4)

Four NUTS3 regions host no substation at 220 kV or above and would be left
without any supply if every cross-regional 110 kV line were dropped:

| Region                   | Fed via                | Source                     |
|--------------------------|------------------------|----------------------------|
| AT111 Mittelburgenland   | UW Mattersburg         | OSM topology (only line)   |
| AT315 Traunviertel       | UW Lambach (two lines) | Netz OÖ, NEP 2024          |
| AT321 Lungau             | UW Reitdorf            | Salzburg Netz, NEP 2024    |
| AT331 Außerfern          | UW Imst                | OSM topology (only line)   |

For these regions a small number of 110 kV lines is kept explicitly, so that
each region retains exactly the connection through which it is supplied in
reality. The lines are selected manually, guided by the DSOs' network
development plans.

### Where the rules are applied

| Rule       | Applied in                                                     |
|------------|----------------------------------------------------------------|
| R0, R1     | `build_osm_network_at`, when the archive is built               |
| R2 – R5    | `filter_osm_lines_at`, on the retrieved archive before `base_network` |

Rules R0 and R1 remove lines from the dataset itself, so the published archive
already excludes traction and cross-border low-voltage lines. The regional
rules are modelling decisions applied by `mods.filter_inter_regional_lines`
each time the network is built, which means they can be revised without
republishing the archive. The documented region feeds live in
`data/pypsa-at/electricity_network_overrides.csv` — the same file the notebook
renders — and a per-line report of every decision is written to
`resources/osm/model/line_rules.csv`.

### Implementation

The dataset-level filtering lives in `scripts/pypsa-at/build_osm_network_at.py`.
The script also recovers two attributes that upstream OSM processing discards —
the line `operator` and the original `frequency` tag — without which rules R0
and R2b could not be evaluated. It raises a `ValueError` at startup if `110.0`
is absent from `config.electricity.voltages`, since building the AT dataset
without the 110 kV level would simply reproduce the default PyPSA-Eur data.
