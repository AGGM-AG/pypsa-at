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

> **Zenodo record 18799980** — [https://zenodo.org/records/18799980](https://zenodo.org/records/18799980)

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
`rules/modify.smk`.

??? info "Running the snakemake rule"

    ```sh
    pixi run snakemake build_osm_network_at -call
    ```

    The `--rerun-triggers mtime` flag prevents re-downloading existing files when
    `data/osm/build/unknown` already partly exists:

    ```sh
    pixi run snakemake build_osm_network_at -call --rerun-triggers mtime
    ```

## Cross-Border Line Drop Logic

### Why cross-border 110 kV lines are removed

Not all 110 kV lines in the OSM dataset are part of the inter-regional
transmission grid. Some cross-border lines at this voltage level are:

- **DSO distribution tie-lines** — low-voltage interconnections between
  neighboring distribution grids, operated below the TSO level.
- **Generation tie-lines** — radial connections from a power plant on one side
  of the border to a substation on the other side, carrying no transit capacity.

These lines are **not TSO interconnectors** and should not be modeled as
cross-border transmission capacity. Including them would artificially inflate
the cross-border exchange capacity between Austria and its neighbors at
voltages below 220 kV.

### What is dropped

A line is removed when **both** of the following conditions hold:

1. **Cross-border**: exactly one of its endpoints (`bus0` / `bus1`) belongs to
   an Austrian bus (i.e. `country == "AT"`).
2. **Low voltage**: `voltage < 220 kV`.

In the current OSM-AT dataset `osm-at v0.2` this removes **18 lines**, all at 110 kV, that
connect Austrian substations to substations in Germany, Switzerland, or Italy.

|    |   index | line_id                    | bus0              | bus1               |   voltage |   circuits |   length | tags                                 |
|---:|--------:|:---------------------------|:------------------|:-------------------|----------:|-----------:|---------:|:-------------------------------------|
|  0 |     277 | way/96001615-110           | way/273300969-110 | way/95975628-110   |       110 |          1 | 14471.5  | way/96001615-110                     |
|  1 |    3134 | way/48442852-110           | way/93982415-110  | way/92320586-110   |       110 |          2 | 25408    | way/48442852-110                     |
|  2 |   24336 | way/36969924-110           | way/26703085-110  | way/1075075893-110 |       110 |          2 | 11656    | way/36969924-110                     |
|  3 |   24337 | way/61112955-110           | way/92293213-110  | AT70-110           |       110 |          2 | 13432.4  | way/61112955-110                     |
|  4 |   24338 | way/92299558-110           | DE1342-110        | way/94406313-110   |       110 |          2 |  5638.39 | way/92299558-110                     |
|  5 |   24339 | way/93129480-110           | way/81540198-110  | way/133669362-110  |       110 |          1 |  8266.06 | way/93129480-110                     |
|  6 |   24340 | way/94177573-110           | AT70-110          | DE1342-110         |       110 |          4 |  3717.27 | way/94177573-110                     |
|  7 |   24341 | way/105180509-110          | AT64-110          | way/33463751-110   |       110 |          2 |  2559.07 | way/105180509-110                    |
|  8 |   24342 | way/114873667-110          | way/116021711-110 | way/86351876-110   |       110 |          2 |  2471.58 | way/114873667-110                    |
|  9 |   24344 | way/123810051-110          | way/95972388-110  | way/95978048-110   |       110 |          1 |  7178.79 | way/123810051-110                    |
| 10 |   24346 | way/353715115-110          | way/24886281-110  | way/118248006-110  |       110 |          2 | 11323.3  | way/353715115-110                    |
| 11 |   24410 | way/169471085-110          | way/116021711-110 | way/114873634-110  |       110 |          1 | 10540    | way/169471085-110                    |
| 12 |   24412 | way/368155120-110          | way/50729129-110  | way/888593883-110  |       110 |          1 |  4880.52 | way/368155120-110                    |
| 13 |   36618 | merged_way/32493449-110+1  | way/32493406-110  | DE1299-110         |       110 |          2 | 26385.1  | way/30023326-110;way/32493449-110    |
| 14 |   36664 | merged_way/93129482-110+1  | way/81540198-110  | way/133669362-110  |       110 |          2 | 13629.1  | way/105431204-2-110;way/93129482-110 |
| 15 |   36668 | merged_way/169635581-110+1 | way/40641599-110  | DE1347-110         |       110 |          1 | 12885.5  | way/169635581-110;way/116009750-110  |
| 16 |   36677 | merged_way/147059434-110+1 | way/42352281-110  | way/1155210065-110 |       110 |          1 | 10679.7  | way/147059434-110;way/996088216-110  |
| 17 |   36678 | merged_way/30712473-110+1  | way/194983924-110 | way/1154201243-110 |       110 |          2 | 39639.9  | way/30712473-110;way/147563006-110   |

### What is kept

Domestic Austrian lines below 220 kV are **not affected**. A line with both
endpoints inside Austria — regardless of its voltage — is never removed. This
preserves the full 110 kV intra-Austrian network that enables NUTS3-level
clustering and captures the domestic transmission topology between regional
load centres.

Cross-border lines at **220 kV and above** are also always kept. Those are
genuine TSO interconnectors (e.g. the 380 kV ties to Germany, Switzerland, and
Italy) that represent real cross-border transmission capacity.

The table below summarizes which lines survive the filter:

| Line type                         | Voltage  | Action   |
|-----------------------------------|----------|----------|
| Domestic AT–AT line               | any      | **keep** |
| Cross-border TSO interconnector   | ≥ 220 kV | **keep** |
| Cross-border DSO / generation tie | < 220 kV | **drop** |

### Implementation

The filtering is implemented in
`scripts/pypsa-at/build_osm_network_at.py::drop_cross_border_lines_lv`:

Note that the script raises a `ValueError` at startup if `110.0` is absent from
`config.electricity.voltages`:

Building the AT dataset without the 110 kV level would produce the default PyPSA-Eur data set. 
```yaml title="config/config.at.yaml"
data:
  osm:
    source: archive
    version: 0.7 (or latest)
```

### Notebook 

A marimo notebook contains additional infos, graphs and calculation steps that may 
be useful for debugging or deeper exploration. ``.marimo/validate-electricity-network-at.py``. 


