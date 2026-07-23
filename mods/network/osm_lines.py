# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Filter inter-regional 110 kV lines from the AT OSM dataset.

The Austrian 110 kV level mixes DSO distribution assets with genuine
transmission infrastructure. Modelled at NUTS3 resolution, every 110 kV line
crossing a region boundary would become a transmission corridor between two
model nodes — capacity that does not exist in reality, where the level is
fragmented between DSOs and partly switched out of service.

Rules, evaluated in order with the first match winning:

===== =============== ======================================================
rule  effect          condition
===== =============== ======================================================
R1b   drop            TSO-operated cross-border line (kept in the archive,
                      excluded from the model until validated)
R2    keep            transmission level (voltage >= 220 kV)
R2b   keep            operated by the TSO (APG), any voltage, domestic
R3    keep            both endpoints in the same NUTS3 region
R4    keep            documented feed of a region without a >=220 kV
                      substation (``data/pypsa-at/electricity_network_overrides.csv``)
R5    drop            any remaining sub-220 kV line crossing a region border
===== =============== ======================================================

Railway traction (R0) and cross-border sub-220 kV lines (R1, except
TSO-operated interconnectors) are removed earlier, when the archive itself is
built (``build_osm_network_at``); this
module assumes an archive version >= ``0.3-at`` that carries the recovered
``operator_clean`` column and raises if it is absent.

The same rules are documented for human review in the marimo notebook
``.marimo/electricity-grid-NUTS3-110kV.py``, which reads the identical
overrides file.
"""

from logging import getLogger

import geopandas as gpd
import pandas as pd

logger = getLogger(__name__)

#: Voltage (kV) at and above which a line is transmission level (rule R2).
TRANSMISSION_KV = 220.0

#: Canonical TSO alias produced by ``build_osm_network_at.OPERATOR_ALIASES``.
TSO_ALIAS = "APG"

#: Metric CRS used for nearest-region fallback distances.
_METRIC_CRS = 3035


def assign_nuts3_regions(
    buses: pd.DataFrame,
    nuts3_shapes: gpd.GeoDataFrame,
) -> pd.Series:
    """
    Map Austrian buses onto NUTS3 region ids.

    Buses are matched point-in-polygon; buses that fall just outside the
    generalised region outlines (border simplification) are assigned to the
    nearest region instead.

    Parameters
    ----------
    buses
        Buses DataFrame (index = ``bus_id``) with coordinate columns ``x``/``y``
        and a ``country`` column.
    nuts3_shapes
        NUTS3 shapes with columns ``index`` (region id), ``country`` and
        ``geometry`` in EPSG:4326, as produced by ``modify_nuts3_shapes``.

    Returns
    -------
    :
        Region id per Austrian bus id. Non-Austrian buses are not included.
    """
    at_buses = buses.query("country == 'AT'")
    at_shapes = nuts3_shapes.query("country == 'AT'")[["index", "geometry"]]

    points = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(at_buses["x"], at_buses["y"]),
        index=at_buses.index,
        crs="EPSG:4326",
    )

    joined = gpd.sjoin(points, at_shapes, predicate="within")
    regions = joined["index"].groupby(level=0).first()

    missing = points.index.difference(regions.index)
    if len(missing):
        nearest = (
            gpd.sjoin_nearest(
                points.loc[missing].to_crs(_METRIC_CRS),
                at_shapes.to_crs(_METRIC_CRS),
            )["index"]
            .groupby(level=0)
            .first()
        )
        regions = pd.concat([regions, nearest])
        logger.info(
            f"Assigned {len(missing)} buses outside the NUTS3 outlines to their "
            "nearest region."
        )

    return regions.reindex(at_buses.index)


def regions_without_transmission(
    buses: pd.DataFrame,
    bus_regions: pd.Series,
) -> set[str]:
    """
    Return NUTS3 regions that host no substation at or above 220 kV.

    Parameters
    ----------
    buses
        Buses DataFrame (index = ``bus_id``) with a ``voltage`` column.
    bus_regions
        Region id per Austrian bus, from :func:`assign_nuts3_regions`.

    Returns
    -------
    :
        Region ids without a transmission-level substation.
    """
    hv_buses = buses.index[buses["voltage"] >= TRANSMISSION_KV]
    hv_regions = set(bus_regions.reindex(hv_buses).dropna())
    return set(bus_regions.dropna()) - hv_regions


def validate_feed_overrides(
    overrides: pd.DataFrame,
    lines: pd.DataFrame,
    regions0: pd.Series,
    regions1: pd.Series,
) -> None:
    """
    Fail early when the overrides file no longer matches the dataset.

    A stale override would silently disconnect a region, so any mismatch is a
    hard error rather than a warning.

    Parameters
    ----------
    overrides
        The feed overrides table with columns ``region`` and ``line_id``.
    lines
        Lines DataFrame (index = ``line_id``).
    regions0, regions1
        Region ids of each line's endpoints.

    Raises
    ------
    ValueError
        If an override references a missing line or a line that does not touch
        its stated region.
    """
    problems = []
    for row in overrides.itertuples():
        if row.line_id not in lines.index:
            problems.append(f"{row.line_id} ({row.region}): not present in the dataset")
        elif row.region not in (regions0.get(row.line_id), regions1.get(row.line_id)):
            problems.append(
                f"{row.line_id}: does not touch its stated region {row.region}"
            )
        elif regions0.get(row.line_id) == regions1.get(row.line_id):
            problems.append(
                f"{row.line_id}: has identical regions and will be removed by the clustering."
            )
    if problems:
        raise ValueError(
            "Stale entries in electricity_network_overrides.csv — the OSM archive has "
            f"changed under the overrides: {problems}. Update the file "
            "(see .marimo/electricity-grid-NUTS3-110kV.py for candidates)."
        )


def designate_feeds(
    overrides: pd.DataFrame,
    feedless: set[str],
    candidates: pd.DataFrame,
    regions0: pd.Series,
    regions1: pd.Series,
) -> dict[str, str]:
    """
    Designate the 110 kV feed lines of regions without transmission access.

    Documented overrides win. Feed-less regions not covered by the overrides
    fall back to a heuristic (most circuits, then shortest length) and are
    logged loudly, because the heuristic knows nothing about where the region
    is actually supplied from.

    Parameters
    ----------
    overrides
        The feed overrides table with columns ``region`` and ``line_id``.
    feedless
        Regions without a >=220 kV substation.
    candidates
        Inter-regional sub-220 kV lines (index = ``line_id``) with columns
        ``circuits`` and ``length``.
    regions0, regions1
        Region ids of each candidate's endpoints.

    Returns
    -------
    :
        Mapping of designated ``line_id`` to the region it feeds.
    """
    feeds = dict(zip(overrides["line_id"], overrides["region"]))

    for region in sorted(feedless - set(overrides["region"])):
        touching = candidates[
            (regions0.reindex(candidates.index) == region)
            | (regions1.reindex(candidates.index) == region)
        ]
        if touching.empty:
            logger.warning(f"Region {region} has no feed candidate at all.")
            continue
        best = touching.sort_values(
            ["circuits", "length"], ascending=[False, True]
        ).index[0]
        feeds[best] = region
        logger.warning(
            f"Region {region} has no documented feed; heuristically keeping "
            f"{best}. Document it in electricity_network_overrides.csv."
        )

    return feeds


def filter_inter_regional_lines(
    lines: pd.DataFrame,
    buses: pd.DataFrame,
    nuts3_shapes: gpd.GeoDataFrame,
    overrides: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Apply the corridor rules R2-R5 to the AT OSM lines.

    Parameters
    ----------
    lines
        Lines DataFrame (index = ``line_id``) from an ``osm-at`` archive
        >= ``0.3-at``, carrying ``voltage``, ``circuits``, ``length`` and
        ``operator_clean``.
    buses
        Buses DataFrame (index = ``bus_id``) with ``x``, ``y``, ``voltage`` and
        ``country``.
    nuts3_shapes
        NUTS3 shapes as produced by ``modify_nuts3_shapes``.
    overrides
        The feed overrides table
        (``data/pypsa-at/electricity_network_overrides.csv``).

    Returns
    -------
    :
        ``(kept_lines, report)`` — the filtered lines, and a per-line report
        with columns ``active``, ``rule`` and ``reason`` for every input line.
    """
    if "operator_clean" not in lines.columns:
        raise ValueError(
            "Lines table has no 'operator_clean' column. The corridor filter "
            "requires an osm-at archive >= 0.3-at (or the build-at output); "
            f"found columns: {lines.columns.tolist()}"
        )

    bus_regions = assign_nuts3_regions(buses, nuts3_shapes)
    regions0 = lines["bus0"].map(bus_regions)
    regions1 = lines["bus1"].map(bus_regions)

    is_transmission = lines["voltage"] >= TRANSMISSION_KV
    is_tso = (
        lines["operator_clean"].fillna("").str.contains(rf"\b{TSO_ALIAS}\b", regex=True)
    )
    is_intra = (regions0 == regions1) & regions0.notna()

    # Every sub-220 kV line must have two Austrian endpoints by construction:
    # foreign sub-220 kV components are removed at archive build time. The one
    # exception are TSO-operated cross-border lines, which the archive keeps
    # (their foreign endpoint has no NUTS3 region) and R2b keeps here.
    unassigned = ~is_transmission & ~is_tso & (regions0.isna() | regions1.isna())
    if unassigned.any():
        raise ValueError(
            f"{int(unassigned.sum())} sub-{TRANSMISSION_KV:.0f} kV lines have an "
            "endpoint outside the Austrian NUTS3 regions, e.g. "
            f"{lines.index[unassigned][:5].tolist()}. The archive is expected to "
            "contain only domestic lines below the transmission level."
        )

    feedless = regions_without_transmission(buses, bus_regions)
    candidates = lines[~is_transmission & ~is_tso & ~is_intra]
    validate_feed_overrides(overrides, lines, regions0, regions1)
    feeds = designate_feeds(overrides, feedless, candidates, regions0, regions1)
    is_feed = lines.index.isin(feeds)

    # TSO-operated cross-border lines stay in the archive but are excluded
    # from the model until the cross-border 110 kV exchange is validated.
    is_tso_cross_border = (
        ~is_transmission & is_tso & (regions0.isna() | regions1.isna())
    )

    rule = pd.Series("R5 INTER_REGION", index=lines.index)
    rule[is_feed] = "R4 SOLE_FEED"
    rule[is_intra] = "R3 INTRA_REGION"
    rule[is_tso] = "R2b APG_TSO"
    rule[is_transmission] = "R2 TRANSMISSION"
    rule[is_tso_cross_border] = "R1b CROSS_BORDER_TSO"

    reason = {
        "R1b CROSS_BORDER_TSO": "TSO-operated cross-border line; kept in the "
        "archive but excluded from the model until the sub-220 kV cross-border "
        "exchange is validated.",
        "R2 TRANSMISSION": "Transmission level (>= 220 kV).",
        "R2b APG_TSO": "Operated by the TSO (APG); part of the transmission system.",
        "R3 INTRA_REGION": "Both endpoints in the same NUTS3 region; no transit.",
        "R4 SOLE_FEED": "Documented feed of a region without transmission access.",
        "R5 INTER_REGION": "Sub-220 kV line crossing a NUTS3 border; would form "
        "a transmission corridor that does not exist in reality.",
    }
    report = pd.DataFrame(
        {
            "voltage": lines["voltage"],
            "region0": regions0,
            "region1": regions1,
            "operator_clean": lines["operator_clean"],
            "rule": rule,
            "reason": rule.map(reason),
            "active": ~rule.isin(["R5 INTER_REGION", "R1b CROSS_BORDER_TSO"]),
        }
    )

    counts = report.groupby("rule")["active"].count()
    dropped = int((~report["active"]).sum())
    logger.info(
        f"Corridor filter: dropping {dropped}/{len(lines)} lines.\n{counts.to_string()}"
    )

    return lines[report["active"]].copy(), report
