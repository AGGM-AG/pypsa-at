# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Allocate KLIEN river-section inflow energy to plants and model regions.

Carved-out core of the future ``build_hydro_inflow_targets`` rule: given
watershed polygons per river section (KLIEN ``hydro_EEPOT_W23.geojson``)
carrying an annual energy value (``E_current`` — the Regelarbeitsvermögen of
Lauf- und Speicherkraftwerke, *excluding* Pumpspeicherkraftwerke, see KLIEN
Langfassung §4.3.2), the hydro plant fleet and the model region shapes, it
distributes each section's energy to the plants inside the section's
catchment (capacity-weighted) and aggregates plant energies to
region × carrier targets.

Location logic
--------------

- Plants with coordinates are placed by point-in-polygon into the section
  catchments. This is what resolves border sections
  (``BUNDESLAND = "anteilig …"``, e.g. the Danube chain) correctly: the
  energy follows the dam, not the catchment area.
- Plants without coordinates (small Anlagenregister entries) are located
  through a cascade of polygon lookups: first any ``extra_lookups`` layers
  (e.g. PLZ or Gemeinde polygons keyed by a plant column such as ``plz``),
  then the ``bus`` region as last resort. Within each lookup, the plant is
  spread over the sections intersecting its polygon, weighted by overlap
  area — a polygon fully inside one section yields a unique assignment.

TODO: the Snakemake rule wiring (retrieve rule + ``data/versions.csv`` entries) is
  still need to be added (currently on in marimo notebook).
"""

import logging

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)

# Carriers that take KLIEN section energy (PHS is outside ``E_current``)
ELIGIBLE_CARRIERS = ("ror", "hydro")


def _require_matching_crs(*gdfs: gpd.GeoDataFrame) -> None:
    crs_set = {str(g.crs) for g in gdfs}
    if len(crs_set) != 1 or "None" in crs_set:
        raise ValueError(
            f"All GeoDataFrames need one shared projected CRS, got {crs_set}."
        )


def _overlap_membership(
    plants: pd.DataFrame,
    key: str,
    polygons: gpd.GeoDataFrame,
    sections: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """
    Membership weights from the overlap of a plant's lookup polygon.

    Each plant is spread over the sections intersecting the polygon(s) of
    its ``key`` value, weighted by overlap area. A key mapping to several
    polygons (n:m relations such as PLZ ↔ Gemeinde) uses their union.

    Parameters
    ----------
    plants
        Plants to locate, with a ``key`` column; index identifies the
        plant.
    key
        Plant column holding the lookup value (e.g. ``plz`` or ``bus``).
    polygons
        Lookup polygons indexed by the key values (duplicate index entries
        allowed), in the CRS of ``sections``.
    sections
        Section catchment polygons, indexed by section id.

    Returns
    -------
    :
        Long-format frame with columns ``plant``, ``section`` and
        ``weight``; only plants whose polygon overlaps a section appear.
    """
    overlap = gpd.overlay(
        sections[["geometry"]].reset_index(names="section"),
        polygons[["geometry"]].reset_index(names=key),
        how="intersection",
        keep_geom_type=True,
    )
    overlap["area"] = overlap.geometry.area
    overlap = overlap.groupby([key, "section"], as_index=False)["area"].sum()
    overlap["weight"] = overlap["area"] / overlap.groupby(key)["area"].transform("sum")
    return (
        plants[[key]]
        .dropna()
        .reset_index()
        .merge(overlap[[key, "section", "weight"]], on=key, how="inner")
    )[["plant", "section", "weight"]]


def _override_membership(
    plants: pd.DataFrame,
    overrides: pd.DataFrame,
    sections: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """
    Curated plant to section (Gemeinde) membership for inter-catchment diversions.

    Point-in-polygon cannot place plants that turbine water diverted across
    watershed boundaries — e.g. the Kaunertal station Prutz sits on the Inn
    but turbines Faggenbach water dammed at Gepatsch. ``overrides`` pins
    such plants to the section(s) they physically turbine, keyed by plant
    ``name``; the pinned membership replaces their point-in-polygon result.

    Parameters
    ----------
    plants
        Plant frame with a ``name`` column; index identifies the plant.
    overrides
        Frame with columns ``name``, ``section`` and optional ``weight``
        (equal split when absent). Section ids must exist in ``sections``.
    sections
        Section catchment polygons, indexed by section id.

    Returns
    -------
    :
        Long-format frame with columns ``plant``, ``section`` and
        ``weight`` (summing to one per matched plant).

    Raises
    ------
    ValueError
        If ``plants`` has no ``name`` column, or an override references a
        section id absent from ``sections``.
    """
    if "name" not in plants.columns:
        raise ValueError(
            "Plant to section overrides require a 'name' column in plants."
        )
    ov = overrides.copy()
    if "weight" not in ov.columns:
        ov["weight"] = 1.0

    valid = pd.Series(sections.index, index=sections.index.astype(str))
    unknown = set(ov["section"].astype(str)) - set(valid.index)
    if unknown:
        raise ValueError(
            f"Diversion overrides reference unknown section id(s) {sorted(unknown)}."
        )
    ov["section"] = ov["section"].astype(str).map(valid)

    rows = []
    missing = []
    for name, grp in ov.groupby("name"):
        idxs = plants.index[plants["name"] == name]
        if len(idxs) == 0:
            missing.append(name)
            continue
        w = grp.groupby("section")["weight"].sum()
        w = w / w.sum()
        for pidx in idxs:
            for section, weight in w.items():
                rows.append((pidx, section, weight))
    if missing:
        logger.warning(
            f"{len(missing)} diversion-override name(s) not in the fleet: "
            f"{missing}; ignored (absent in this clustering?)."
        )
    return pd.DataFrame(rows, columns=["plant", "section", "weight"])


def assign_plants_to_sections(
    plants: pd.DataFrame,
    sections: gpd.GeoDataFrame,
    regions: gpd.GeoDataFrame,
    extra_lookups: list[tuple[str, gpd.GeoDataFrame]] | None = None,
    overrides: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build plant to section membership weights.

    Plants with coordinates are matched point-in-polygon; a plant matching
    several (overlapping) sections is split evenly. Plants without
    coordinates — or whose point falls outside every section — go through a
    cascade of polygon lookups (:func:`_overlap_membership`): every entry
    of ``extra_lookups`` in order, then ``("bus", regions)`` as last
    resort. A plant advances in the cascade while its key is missing, its
    key value is absent from the lookup layer, or its polygon overlaps no
    section.

    Parameters
    ----------
    plants
        One row per plant with columns ``bus``, ``carrier``, ``p_nom`` and
        optionally ``lat``/``lon`` (EPSG:4326) plus any lookup key columns.
        The index identifies the plant.
    sections
        Section catchment polygons, indexed by section id, in a projected
        CRS.
    regions
        Model region polygons, indexed by region id (``bus`` values), in
        the same CRS as ``sections``.
    extra_lookups
        Ordered ``(key_column, polygons)`` pairs tried before the ``bus``
        fallback, e.g. ``[("plz", plz_polygons)]`` with polygons indexed by
        PLZ value in the CRS of ``sections``.
    overrides
        Curated ``name`` → ``section`` (+ optional ``weight``) assignments
        for inter-catchment diversion plants (see
        :func:`_override_membership`). Overridden plants skip the
        point-in-polygon and cascade steps entirely; requires a ``name``
        column in ``plants``.

    Returns
    -------
    :
        Long-format frame with columns ``plant``, ``section`` and
        ``weight``; weights sum to one per locatable plant.

    TODO: needs review. I suspect this can be more simple and less convoluted.
    TODO: raise errors instead of warning.
    """
    extra_lookups = list(extra_lookups or [])
    _require_matching_crs(sections, regions, *(g for _, g in extra_lookups))
    plants = plants.copy()
    plants.index.name = "plant"
    sections = sections.copy()
    sections.index.name = "section"
    regions = regions.copy()
    regions.index.name = "bus"

    parts = []
    overridden = plants.index[[]]
    if overrides is not None and len(overrides):
        override_rows = _override_membership(plants, overrides, sections)
        parts.append(override_rows)
        overridden = pd.Index(override_rows["plant"].unique())
    remaining = plants.drop(index=overridden)

    has_xy = (
        remaining[["lat", "lon"]].notna().all(axis=1)
        if {"lat", "lon"}.issubset(remaining.columns)
        else pd.Series(False, index=remaining.index)
    )
    if has_xy.any():
        points = gpd.GeoDataFrame(
            remaining.loc[has_xy, []],
            geometry=gpd.points_from_xy(
                remaining.loc[has_xy, "lon"], remaining.loc[has_xy, "lat"]
            ),
            crs="EPSG:4326",
        ).to_crs(sections.crs)
        matched = gpd.sjoin(
            points, sections[["geometry"]], how="inner", predicate="within"
        ).rename(columns={"index_right": "section"})
        by_point = (
            matched.reset_index()
            .groupby(["plant", "section"])
            .size()
            .rename("n")
            .reset_index()
        )
        by_point["weight"] = 1.0 / by_point.groupby("plant")["n"].transform("sum")
        parts.append(by_point[["plant", "section", "weight"]])
        unmatched = has_xy.index[has_xy].difference(matched.index)
        if len(unmatched):
            logger.info(
                f"{len(unmatched)} plants with coordinates fall outside every "
                "section catchment; falling back to the lookup cascade."
            )
    else:
        unmatched = remaining.index[[]]

    pending = remaining.index[~has_xy].union(unmatched)
    for lookup_key, lookup_polygons in [*extra_lookups, ("bus", regions)]:
        if not len(pending):
            break
        if lookup_key not in remaining.columns:
            logger.info(f"Skipping lookup '{lookup_key}': column not in plants.")
            continue
        rows = _overlap_membership(
            remaining.loc[pending], lookup_key, lookup_polygons, sections
        )
        if rows.empty:
            continue
        parts.append(rows)
        pending = pending.difference(rows["plant"].unique())

    membership = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame(columns=["plant", "section", "weight"])
    )

    unlocatable = plants.index.difference(membership["plant"])
    if len(unlocatable):
        logger.warning(
            f"{len(unlocatable)} plants could not be located in any section "
            f"(sum p_nom: {plants.loc[unlocatable, 'p_nom'].sum():.1f} MW)."
        )
    return membership


def allocate_section_energy(
    sections: gpd.GeoDataFrame | pd.DataFrame,
    membership: pd.DataFrame,
    plants: pd.DataFrame,
    energy_col: str = "E_current",
    eligible_carriers: tuple[str, ...] = ELIGIBLE_CARRIERS,
) -> tuple[pd.Series, pd.Series]:
    """
    Distribute section energy to plants, capacity-weighted.

    Within each section, energy is split over the member plants of eligible
    carriers proportional to ``membership weight × p_nom``.

    Parameters
    ----------
    sections
        Frame indexed by section id with the ``energy_col`` column.
    membership
        Plant → section weights from :func:`assign_plants_to_sections`.
    plants
        Plant frame with ``carrier`` and ``p_nom``, indexed like the
        ``plant`` column of ``membership``.
    energy_col
        Section column holding annual energy.
    eligible_carriers
        Carriers allowed to take section energy.

    Returns
    -------
    :
        Tuple of (energy per plant, unallocated energy per section). The
        second series lists sections with energy but no eligible member
        plant; together both preserve the section total.
    """
    energy = sections[energy_col].dropna()

    m = membership.merge(
        plants[["carrier", "p_nom"]], left_on="plant", right_index=True
    )
    m = m[m["carrier"].isin(eligible_carriers)]
    m["w"] = m["weight"] * m["p_nom"]
    m = m[m["w"] > 0]
    m["share"] = m["w"] / m.groupby("section")["w"].transform("sum")
    m["energy"] = m["section"].map(energy).fillna(0.0) * m["share"]

    plant_energy = m.groupby("plant")["energy"].sum()

    covered = energy.index.intersection(m["section"].unique())
    unallocated = energy.drop(covered)
    unallocated = unallocated[unallocated > 0]
    if not unallocated.empty:
        logger.warning(  # todo: raise Error instead
            f"{len(unallocated)} sections carry {unallocated.sum():.1f} energy "
            "units but have no eligible plant; energy left unallocated."
        )
    return plant_energy, unallocated


def aggregate_by_region(plant_energy: pd.Series, plants: pd.DataFrame) -> pd.DataFrame:
    """
    Roll plant energies up to region × carrier.

    Parameters
    ----------
    plant_energy
        Energy per plant from :func:`allocate_section_energy`.
    plants
        Plant frame with ``bus`` and ``carrier``, indexed like
        ``plant_energy``.

    Returns
    -------
    :
        Frame with columns ``bus``, ``carrier`` and ``energy``.
    """
    df = plants[["bus", "carrier"]].join(plant_energy.rename("energy"), how="inner")
    return df.groupby(["bus", "carrier"], as_index=False)["energy"].sum()


def build_inflow_targets(
    plants: pd.DataFrame,
    sections: gpd.GeoDataFrame,
    regions: gpd.GeoDataFrame,
    energy_col: str = "E_current",
    eligible_carriers: tuple[str, ...] = ELIGIBLE_CARRIERS,
    extra_lookups: list[tuple[str, gpd.GeoDataFrame]] | None = None,
    overrides: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Plant-location based section to region energy targets.

    Composes :func:`assign_plants_to_sections`,
    :func:`allocate_section_energy` and :func:`aggregate_by_region`.

    Parameters
    ----------
    plants
        Plant frame with ``bus``, ``carrier``, ``p_nom`` and optional
        ``lat``/``lon``.
    sections
        Section catchments with ``energy_col``, projected CRS.
    regions
        Region polygons indexed by region id, same CRS.
    energy_col
        Section column holding annual energy.
    eligible_carriers
        Carriers allowed to take section energy.
    extra_lookups
        Ordered ``(key_column, polygons)`` pairs for locating coordless
        plants, tried before the ``bus`` fallback (see
        :func:`assign_plants_to_sections`).
    overrides
        Curated diversion-plant ``name`` → ``section`` assignments (see
        :func:`_override_membership`).

    Returns
    -------
    :
        Tuple of (targets frame with ``bus``/``carrier``/``energy``,
        diagnostics dict with ``plant_energy``, ``membership`` and
        ``unallocated`` per section).
    """
    membership = assign_plants_to_sections(
        plants, sections, regions, extra_lookups, overrides
    )
    plant_energy, unallocated = allocate_section_energy(
        sections, membership, plants, energy_col, eligible_carriers
    )
    targets = aggregate_by_region(plant_energy, plants)
    diagnostics = {
        "plant_energy": plant_energy,
        "membership": membership,
        "unallocated": unallocated,
    }
    return targets, diagnostics
