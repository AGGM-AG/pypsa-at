# NUTS3 Clustering and the Austrian OSM Network Dataset

## Background

PyPSA-Eur builds its electricity network from OpenStreetMap (OSM) data, by
default including only **high-voltage** transmission lines (≥ 220 kV). For most
European countries this is a reasonable approximation: high-voltage lines connect
the major load centres and the clustering algorithm can assign nodes to
administrative regions without ambiguity.

In PyPSA-AT, Austria is resolved at signifficantly higher spatial resolution:
Its **NUTS3 spatial resolution** (35 regions) is finer than the node density 
of the default 220 kV network. The following regions become combined when 
clustering at NUTS3 regions, and considering ≥ 220 kV only:

| Region           | NUTS code | Merged into             |
|------------------|-----------|-------------------------|  
| Mittelburgenland | AT111     | Nodburgenland           |
| Innviertel       | AT311     | Traunviertel            | 
| Lungau           | AT321     | Pinzgau-Pongau          |
| Oststeiermark    | AT224     | West- und Südsteiermark |
| Außerfern        | AT331     | Tiroler Oberland        |

Clustering at NUTS3 level with only the high-voltage network
would merge geographically distant regions or leave nodes unassigned.

## The Solution: 110 kV Network Data for Austria

To support true NUTS3 clustering, PyPSA-AT uses a dedicated OSM archive that
includes **sub-220 kV lines** (down to 110 kV) **only for Austrian regions**:

```yaml title="config/config.at.yaml"
electricity:
  voltages: [ 110., 220., 300., 330., 380., 400., 500., 750. ]

data:
  osm:
    source: archive
    version: v0.2-at
```

The archive dataset `v0.2-at` is published on Zenodo
([records/18797490](https://zenodo.org/records/18797490)) and is fetched
automatically by the `retrieve_osm_archive` Snakemake rule.

## Clustering Configurations

PyPSA-AT defines four ready-to-use spatial configurations that combine different
NUTS resolution levels for Austria and Germany. The configuration is selected
via `config.at.yaml`:

```yaml title="config/config.at.yaml"
mods:
  modify_nuts3_shapes: AT35DE5   # or AT10DE5 | AT10DE16 | AT35DE16
```

| Configuration | Austria            | Germany           | Total AT nodes |
|---------------|--------------------|-------------------|----------------|
| `AT10DE5`     | NUTS2 (10 regions) | 5 macro-regions   | 10             |
| `AT10DE16`    | NUTS2 (10 regions) | NUTS1 (16 states) | 10             |
| `AT35DE5`     | NUTS3 (35 regions) | 5 macro-regions   | 35             |
| `AT35DE16`    | NUTS3 (35 regions) | NUTS1 (16 states) | 35             |

The "DE5" configurations aggregate German NUTS3 codes into five macro-regions:

| Region code | States included                                           |
|-------------|-----------------------------------------------------------|
| `DE1`       | Baden-Württemberg                                         |
| `DE2`       | Bavaria                                                   |
| `DE3`       | Midwest (Hesse, Rhineland-Palatinate, Saarland, NRW)      |
| `DE4`       | Mideast (Brandenburg, Berlin, MV, Saxony, SA, Thuringia)  |
| `DE5`       | North (Schleswig-Holstein, Hamburg, Bremen, Lower Saxony) |

Other countries (Italy, Denmark, Great Britain, France, Spain) are always split
into 2–3 regions to separate mainland from islands (e.g. Corsica, Sardinia,
Sicily, Sjaelland, Northern Ireland, Balearic Islands).

## How the Clustering Pipeline Works

The custom clustering is applied before PyPSA-Eur's network simplification in
two Snakemake rules:

```
retrieve_osm_archive  →  build_osm_network  →  modify_nuts3_shapes  →  simplify_network  →  cluster_network
```

### `modify_nuts3_shapes`

This rule reads the raw NUTS3 GeoJSON file and reassigns region codes in the
`level1`/`level2`/`level3` columns. The actual implementation lives in
[`mods.clustering.apply_custom_clustering`](../../reference/mods/clustering.md)
so that it is importable and testable independently of Snakemake.

The Snakemake script at `scripts/pypsa-at/modify_nuts3_shapes.py` is a thin
wrapper that reads the input shapefile, calls the mods function, and writes the
result:

```python
from mods.clustering import apply_custom_clustering

nuts3_regions = apply_custom_clustering(
    nuts3_regions,
    custom_clustering=config["mods"]["modify_nuts3_shapes"],
    admin_levels=snakemake.params["admin_levels"],
    run_prefix=config["run"]["prefix"],
)
```

### Special case: AT333 (Osttirol)

At NUTS2 resolution (AT10), the district of Osttirol (NUTS3 code `AT333`) shares
its NUTS2 prefix `AT33` with the Tyrolean districts. Without special handling,
Osttirol would be merged with the broader Tyrol NUTS2 region, effectively hiding 
electricity lines from Corinthia that transport electricity between Osttirol `AT333` 
and Oberkärnten `AT212`.

PyPSA-AT maps `AT333 → AT333` (self-reference at level2) to preserve it as its
own region at NUTS2 clustering resolution.

## Configuration Consistency Check

`apply_custom_clustering` cross-checks the `admin_levels` dictionary in the
config against the requested configuration name. For example, requesting
`AT35DE5` while having `AT: 2` in `admin_levels` will raise an
`AssertionError` at script runtime rather than silently producing wrong
cluster assignments.

```yaml title="Example: consistent config for AT35DE5"
clustering:
  administrative:
    level: 0
    AT: 3   # ← must match "AT35" in the configuration name
    DE: 3   # ← must match "DE5" (NUTS3-proxy for 5 regions)
    IT: 1
    DK: 1
    GB: 1
    FR: 1
    ES: 1

# ... 

mods:
  modify_nuts3_shapes: AT35DE5  # or AT10DE5, AT10DE19, AT35DE19
```

## Function Reference

- [`mods.clustering.apply_custom_clustering`](../../reference/mods/clustering.md) — main entry point
- [`mods.clustering.override_nuts`](../../reference/mods/clustering.md) — low-level NUTS code reassignment
- [`mods.clustering.assert_expected_region_count`](../../reference/mods/clustering.md) — post-condition check
