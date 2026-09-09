# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Allocate KLIEN river-section inflow energy to plants and model regions.

Given watershed polygons per river section (KLIEN ``hydro_EEPOT_W23.geojson``,
stored as ``catchments_hydro.geojson``) carrying an annual energy value
(``E_current`` — the Regelarbeitsvermögen of Lauf- und Speicherkraftwerke,
*excluding* Pumpspeicherkraftwerke, see KLIEN Langfassung §4.3.2), the hydro
plant fleet and the model region shapes, it distributes each section's energy
to the plants inside the section's catchment (capacity-weighted) and
aggregates plant energies to region × carrier targets. The long-term mean is
then scaled to the weather year of the snapshots with the E-Control annual
generation series (Betriebsstatistik Jahresreihe).

The German treaty halves of the Inn and Danube Grenzkraftwerke take part in
the allocation (KLIEN counts the full border plants), so that only the
Austrian half of their section energy ends up in the Austrian targets.

Outputs
-------

- ``resources/hydro_inflow_targets_{clusters}.csv``:

    ===================  ================  =========================================================
    Field                Index             Description
    ===================  ================  =========================================================
    rav_gwh              bus, carrier      Long-term mean (1991–2020) annual energy from KLIEN
    year_factor          bus, carrier      E-Control generation of the weather year over the mean
    inflow               bus, carrier      Target inflow energy of the weather year in MWh
    ===================  ================  =========================================================

    Empty (header only) when ``mods.update_hydro_capacities_AT.enable`` is
    false, so the DAG does not depend on the configuration.

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
"""

import logging

import geopandas as gpd
import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging, get_snapshots, set_scenario_config

logger = logging.getLogger(__name__)

# Carriers that take KLIEN section energy (PHS is outside ``E_current``)
ELIGIBLE_CARRIERS = ("ror", "hydro")

TECH_TO_CARRIER = {
    "Run-Of-River": "ror",
    "Reservoir": "hydro",
    "Pumped Storage": "PHS",
}

# Projected CRS for the area weighting (Austria Lambert)
KLIEN_CRS = "EPSG:3416"

# Discharge reference period of the KLIEN Regelarbeitsvermögen. The E-Control
# series is annual only from 2000 (five-year steps before), so the reference
# mean uses the years available inside the period; at least
# ``MIN_REFERENCE_YEARS`` must be present.
REFERENCE_PERIOD = (1991, 2020)
MIN_REFERENCE_YEARS = 20

# E-Control annual generation series (sheet ``Erz`` of BStGes-JR1_Bilanz.xlsx):
# first data row and the columns read, in order
ECONTROL_FIRST_ROW = 10
ECONTROL_COLUMNS = [
    "year",
    "lauf_le10",
    "lauf_gt10",
    "lauf",
    "sp_le10",
    "sp_le10_psw",
    "sp_gt10",
    "sp_gt10_psw",
]

# E-Control annual electricity balance (sheet ``Bil`` of the same workbook):
# first data row and the columns read, in order; ``pumping`` is the
# "Verbrauch für Pumpspeicher" column.
BIL_FIRST_ROW = 10
BIL_COLUMNS = [
    "year",
    "gross_generation",
    "imports",
    "supply",
    "exports",
    "gross_consumption",
    "pumping",
    "domestic_consumption",
]

# Share of the electricity consumed for pumping that comes back as generation
# from pumped water. E-Control publishes the generation from pumped water only
# in the Bestandsstatistik (BeStGes-2025_KW2EPLTyp.xlsx: 3,795 GWh in 2025),
# while the Betriebsstatistik year series carries the pumping consumption
# (5,725 GWh in 2025); the ratio of the two is applied to every year.
PUMPED_WATER_SHARE = 3795.0 / 5725.4

OUTPUT_COLUMNS = ["bus", "carrier", "rav_gwh", "year_factor", "inflow"]


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


def _phs_counted_sections(
    sections: pd.DataFrame,
    members: pd.DataFrame,
    capacity_col: str,
    eligible_carriers: tuple[str, ...],
) -> pd.Index:
    """
    Sections whose KLIEN capacity evidently includes the pumped-storage plants.

    KLIEN excludes *Pumpspeicherkraftwerke* from ``E_current``, but its set of
    pumped-storage plants is narrower than the model's ``PHS`` technology:
    large storage groups with pumps (Sellrain-Silz, Zemm-Ziller, ...) are
    counted as Speicherkraftwerke by the study. Where that is the case, the
    section capacity ``capacity_col`` is close to the member capacity
    *including* PHS and far above the eligible members alone. The nearer
    match decides per section.

    Parameters
    ----------
    sections
        Frame indexed by section id with the ``capacity_col`` column.
    members
        Membership rows joined with ``carrier`` and ``p_nom``, with a
        weighted capacity column ``w``.
    capacity_col
        Section column holding the KLIEN current capacity in MW.
    eligible_carriers
        Carriers eligible by default.

    Returns
    -------
    :
        Section ids where PHS members share the section energy.
    """
    capacity = sections[capacity_col].dropna()
    by_section = (
        members.groupby(["section", "carrier"])["w"].sum().unstack(fill_value=0)
    )
    by_section = by_section.reindex(capacity.index, fill_value=0.0)
    default = by_section.reindex(columns=list(eligible_carriers), fill_value=0.0).sum(
        axis=1
    )
    with_phs = default + by_section.get("PHS", 0.0)
    counted = capacity.index[(with_phs - capacity).abs() < (default - capacity).abs()]
    return counted


def allocate_section_energy(
    sections: gpd.GeoDataFrame | pd.DataFrame,
    membership: pd.DataFrame,
    plants: pd.DataFrame,
    energy_col: str = "E_current",
    eligible_carriers: tuple[str, ...] = ELIGIBLE_CARRIERS,
    capacity_col: str | None = None,
) -> tuple[pd.Series, pd.Series]:
    """
    Distribute section energy to plants, capacity-weighted.

    Within each section, energy is split over the member plants of eligible
    carriers proportional to ``membership weight × p_nom``. When
    ``capacity_col`` is given, PHS members additionally take part in the
    sections whose KLIEN capacity evidently counts them (see
    :func:`_phs_counted_sections`); the caller decides what to do with the
    energy attributed to PHS plants.

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
    capacity_col
        Section column holding the KLIEN current capacity; enables the
        per-section PHS eligibility.

    Returns
    -------
    :
        Tuple of (energy per plant, unallocated energy per section). The
        second series lists the energy of sections without (enough)
        eligible member capacity; together both preserve the section total.
    """
    energy = sections[energy_col].dropna()

    m = membership.merge(
        plants[["carrier", "p_nom"]], left_on="plant", right_index=True
    )
    m["w"] = m["weight"] * m["p_nom"]
    eligible = m["carrier"].isin(eligible_carriers)
    if capacity_col is not None:
        phs_sections = _phs_counted_sections(
            sections, m, capacity_col, eligible_carriers
        )
        phs_rows = (m["carrier"] == "PHS") & m["section"].isin(phs_sections)
        if phs_rows.any():
            logger.info(
                f"PHS plants share the section energy in {len(phs_sections)} "
                f"sections whose KLIEN capacity counts them: {sorted(phs_sections)}."
            )
        eligible |= phs_rows
    m = m[eligible]
    member_capacity = m.groupby("section")["w"].sum()
    denominator = member_capacity
    if capacity_col is not None:
        # a plant never takes more than the section's own full-load hours
        # (E / C); the energy of capacity missing from the fleet stays
        # unallocated instead of inflating the plants that are present
        denominator = member_capacity.combine(
            sections[capacity_col].reindex(member_capacity.index).fillna(0.0), max
        )
    m["share"] = m["w"] / m["section"].map(denominator)
    m["energy"] = m["section"].map(energy).fillna(0.0) * m["share"]

    plant_energy = m.groupby("plant")["energy"].sum()

    allocated = m.groupby("section")["energy"].sum().reindex(energy.index, fill_value=0)
    unallocated = (energy - allocated).round(6)
    unallocated = unallocated[unallocated > 0]
    if not unallocated.empty:
        top = unallocated.sort_values(ascending=False).head(10).round(0)
        logger.warning(
            f"{len(unallocated)} sections carry {unallocated.sum():.1f} energy "
            "units without matching plant capacity in the fleet (missing or "
            f"misplaced plants); largest: {top.to_dict()}."
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
    capacity_col: str | None = None,
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
    capacity_col
        Section column with the KLIEN current capacity; enables the
        per-section PHS eligibility of :func:`allocate_section_energy`.
        PHS energy then appears as its own carrier in the targets.

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
        sections, membership, plants, energy_col, eligible_carriers, capacity_col
    )
    targets = aggregate_by_region(plant_energy, plants)
    diagnostics = {
        "plant_energy": plant_energy,
        "membership": membership,
        "unallocated": unallocated,
    }
    return targets, diagnostics


def apply_catchment_corrections(
    sections: pd.DataFrame, corrections: pd.DataFrame
) -> pd.DataFrame:
    """
    Overwrite the study's capacity and energy of individually verified catchments.

    The KLIEN table books, for a few catchments, capacity that is not Austrian
    or not on that stretch (a company total, a Bavarian plant). Left as is,
    that energy is reported as unmatched in every run although no plant is
    missing. The curated list replaces ``C_current`` and ``E_current`` of the
    listed catchments with the operator figures; every row carries a note
    with the rationale and the source.

    Parameters
    ----------
    sections
        KLIEN catchments indexed by ``id`` with ``C_current`` and
        ``E_current`` columns.
    corrections
        Frame with columns ``id``, ``C_current_new``, ``E_current_new`` and
        ``note``.

    Returns
    -------
    :
        A copy of ``sections`` with the corrected values.

    Raises
    ------
    ValueError
        If a listed catchment id is not in the table (changed upstream
        dataset).
    """
    sections = sections.copy()
    ids = corrections["id"].astype(str)
    missing = ids[~ids.isin(sections.index.astype(str))]
    if not missing.empty:
        raise ValueError(
            f"Catchment corrections list catchments that are not in the KLIEN "
            f"table: {missing.tolist()}. KLIEN data changed upstream; re-check "
            "the corrections list."
        )
    index = pd.Series(sections.index, index=sections.index.astype(str))
    for row in corrections.itertuples():
        idx = index[str(row.id)]
        logger.info(
            f"Catchment {row.id}: C_current {sections.at[idx, 'C_current']:.1f} -> "
            f"{row.C_current_new:.1f} MW, E_current "
            f"{sections.at[idx, 'E_current']:.1f} -> {row.E_current_new:.1f} GWh/a."
        )
        sections.at[idx, "C_current"] = row.C_current_new
        sections.at[idx, "E_current"] = row.E_current_new
    return sections


def select_hydro_plants(
    ppl: pd.DataFrame, grenzkraftwerke: pd.DataFrame
) -> pd.DataFrame:
    """
    Austrian hydro plants plus the German treaty halves of the Grenzkraftwerke.

    Parameters
    ----------
    ppl
        Calibrated powerplants table (``powerplants_s_{clusters}.csv``) with
        ``Name``, ``Country``, ``Fueltype``, ``Technology``, ``Capacity`` and
        ``bus`` columns, plus ``lat`` / ``lon`` / ``plz`` where available.
    grenzkraftwerke
        Curated border plant list (``grenzkraftwerke_AT.csv``); its ``DE``
        rows name the German twin entries to include.

    Returns
    -------
    :
        Plant frame with ``bus``, ``carrier``, ``p_nom``, ``name`` and the
        available location columns, indexed like ``ppl``.
    """
    hydro = ppl[ppl["Fueltype"] == "Hydro"]
    de_twins = set(grenzkraftwerke.query("country == 'DE'")["Name"])
    keep = (hydro["Country"] == "AT") | (
        (hydro["Country"] == "DE") & hydro["Name"].isin(de_twins)
    )
    plants = hydro[keep].rename(columns={"Capacity": "p_nom", "Name": "name"})
    plants = plants.assign(carrier=plants["Technology"].map(TECH_TO_CARRIER))
    location = [c for c in ("lat", "lon", "plz") if c in plants.columns]
    return plants[["bus", "carrier", "p_nom", "name", *location]]


def read_econtrol_annual_generation(path: str) -> pd.DataFrame:
    """
    Read the E-Control annual hydro generation series.

    Parameters
    ----------
    path
        ``BStGes-JR1_Bilanz.xlsx`` (Betriebsstatistik Jahresreihe).

    Returns
    -------
    :
        Frame indexed by year with ``lauf`` (Laufkraftwerke), ``speicher``
        (Speicherkraftwerke, including pumped-storage generation) and
        ``phs_natural`` (generation of the pumped-storage plants minus the
        generation from pumped water, i.e. from their natural inflow) in GWh.

    Raises
    ------
    ValueError
        If the sheet layout does not yield the reference period, which
        indicates a changed E-Control file format.
    """
    layout_error = ValueError(
        f"Unexpected layout in {path}: expected {len(ECONTROL_COLUMNS)} columns "
        f"in sheet 'Erz', {len(BIL_COLUMNS)} columns in sheet 'Bil' and at least "
        f"{MIN_REFERENCE_YEARS} years of the reference period {REFERENCE_PERIOD}. "
        "Has the E-Control file format changed?"
    )
    table = _read_econtrol_sheet(path, "Erz", ECONTROL_FIRST_ROW, ECONTROL_COLUMNS)
    balance = _read_econtrol_sheet(path, "Bil", BIL_FIRST_ROW, BIL_COLUMNS)
    if table is None or balance is None:
        raise layout_error
    table["speicher"] = table["sp_le10"] + table["sp_gt10"]
    pumped_storage = table["sp_le10_psw"].fillna(0.0) + table["sp_gt10_psw"]
    table["phs_natural"] = (
        pumped_storage - balance["pumping"].reindex(table.index) * PUMPED_WATER_SHARE
    )
    columns = ["lauf", "speicher", "phs_natural"]
    reference = table.loc[slice(*REFERENCE_PERIOD), columns].dropna()
    if len(reference) < MIN_REFERENCE_YEARS:
        raise layout_error
    return table[columns]


def _read_econtrol_sheet(
    path: str, sheet: str, first_row: int, columns: list[str]
) -> pd.DataFrame | None:
    """Read one year-indexed sheet of the E-Control workbook, ``None`` on a layout mismatch."""
    try:
        raw = pd.read_excel(path, sheet_name=sheet, header=None)
    except ValueError:  # missing worksheet
        return None
    table = raw.iloc[first_row:, : len(columns)].copy()
    if table.shape[1] != len(columns):
        return None
    table.columns = columns
    table = table[pd.to_numeric(table["year"], errors="coerce").notna()]
    table = table.apply(pd.to_numeric, errors="coerce").set_index("year")
    table.index = table.index.astype(int)
    return table.sort_index()


def weather_year_factors(econtrol: pd.DataFrame, year: int) -> dict[str, float]:
    """
    Scale factors from the KLIEN reference period to one weather year.

    Parameters
    ----------
    econtrol
        Annual generation from :func:`read_econtrol_annual_generation`.
    year
        Weather year of the inflow profile (snapshots).

    Returns
    -------
    :
        ``{"ror": Laufkraft(year) / mean, "hydro": Speicherkraft(year) / mean,
        "PHS": natural pumped-storage generation(year) / mean}`` with the
        means taken over the years available in ``REFERENCE_PERIOD``.

    Raises
    ------
    ValueError
        If the weather year is not covered by the series.
    """
    if year not in econtrol.index or econtrol.loc[year].isna().any():
        raise ValueError(
            f"E-Control annual generation has no complete entry for weather "
            f"year {year}; available years {econtrol.dropna().index.min()}-"
            f"{econtrol.dropna().index.max()}."
        )
    reference = econtrol.loc[slice(*REFERENCE_PERIOD)].dropna().mean()
    return {
        "ror": float(econtrol.at[year, "lauf"] / reference["lauf"]),
        "hydro": float(econtrol.at[year, "speicher"] / reference["speicher"]),
        "PHS": float(econtrol.at[year, "phs_natural"] / reference["phs_natural"]),
    }


def phs_inflow_targets(
    econtrol: pd.DataFrame, year: int, plants: pd.DataFrame, at_buses: set[str]
) -> pd.DataFrame:
    """
    Natural inflow of the Austrian pumped-storage plants from E-Control.

    The KLIEN catchment energy excludes pumped-storage plants and the PEMMDB
    *PS Open* inflow for Austria is about twice what E-Control attributes to
    natural inflow. The national figure is E-Control's generation of
    pumped-storage plants minus the generation from pumped water, taken as
    the reference-period mean and scaled to the weather year like the other
    carriers. It is spread over the Austrian regions in proportion to the
    pumped-storage turbine capacity of the calibrated fleet, because the
    statistic knows no regions.

    Parameters
    ----------
    econtrol
        Annual series from :func:`read_econtrol_annual_generation`.
    year
        Weather year of the inflow profile (snapshots).
    plants
        Hydro plants from :func:`select_hydro_plants` with ``bus``,
        ``carrier`` and ``p_nom``.
    at_buses
        Buses that belong to Austria.

    Returns
    -------
    :
        Frame with ``OUTPUT_COLUMNS`` and carrier ``PHS``.
    """
    phs = plants[(plants["carrier"] == "PHS") & plants["bus"].isin(at_buses)]
    share = phs.groupby("bus")["p_nom"].sum()
    share = share / share.sum()
    reference = econtrol.loc[slice(*REFERENCE_PERIOD), "phs_natural"].dropna().mean()
    factor = weather_year_factors(econtrol, year)["PHS"]
    targets = pd.DataFrame(
        {
            "bus": share.index,
            "carrier": "PHS",
            "rav_gwh": (reference * share).to_numpy(),
            "year_factor": factor,
        }
    )
    targets["inflow"] = targets["rav_gwh"] * 1e3 * targets["year_factor"]
    return targets[OUTPUT_COLUMNS]


def main(snakemake: Snakemake) -> pd.DataFrame:
    """
    Build the KLIEN-calibrated inflow targets from the workflow inputs.

    Parameters
    ----------
    snakemake
        The Snakemake workflow object.

    Returns
    -------
    :
        Targets per Austrian region and carrier, or an empty frame when the
        feature is disabled.
    """
    if not snakemake.params.update_hydro_capacities_AT:
        logger.info(
            "Skipping the KLIEN hydro inflow targets for AT. config option "
            "mods.update_hydro_capacities_AT.enable is false."
        )
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    snapshots = get_snapshots(
        snakemake.params.snapshots, snakemake.params.drop_leap_day
    )
    year = pd.DatetimeIndex(snapshots).year.unique().item()

    ppl = pd.read_csv(
        snakemake.input.powerplants, index_col=0, dtype={"plz": str}, low_memory=False
    )
    grenzkraftwerke = pd.read_csv(snakemake.input.grenzkraftwerke)
    plants = select_hydro_plants(ppl, grenzkraftwerke)

    sections = gpd.read_file(snakemake.input.klien_catchments)
    sections.columns = sections.columns.str.strip()
    sections = sections[sections["E_current"].notna()].set_index("id").to_crs(KLIEN_CRS)
    sections = apply_catchment_corrections(
        sections, pd.read_csv(snakemake.input.catchment_corrections)
    )
    regions = (
        gpd.read_file(snakemake.input.regions_onshore)
        .set_index("name")
        .to_crs(KLIEN_CRS)
    )
    overrides = pd.read_csv(snakemake.input.diversion_overrides)

    targets, diagnostics = build_inflow_targets(
        plants, sections, regions, overrides=overrides, capacity_col="C_current"
    )
    # the natural inflow of the model's PHS plants comes from the E-Control
    # pumped-storage statistic below; the KLIEN energy attributed to them in
    # the catchments where the study counts them would double count it
    phs = targets["carrier"] == "PHS"
    if phs.any():
        logger.info(
            f"Dropping {targets.loc[phs, 'energy'].sum():.0f} GWh/a attributed "
            "to PHS plants (replaced by the E-Control pumped-storage inflow)."
        )
        targets = targets[~phs]
    at_buses = set(plants.loc[ppl.loc[plants.index, "Country"] == "AT", "bus"])
    foreign = targets[~targets["bus"].isin(at_buses)]
    if not foreign.empty:
        logger.info(
            f"Dropping {foreign['energy'].sum():.0f} GWh/a allocated to the "
            f"German Grenzkraftwerke halves (buses {sorted(foreign['bus'].unique())})."
        )
    targets = targets[targets["bus"].isin(at_buses)].rename(
        columns={"energy": "rav_gwh"}
    )

    unmatched = diagnostics["unallocated"].sum()
    if unmatched > 0:
        logger.warning(
            f"{unmatched:.0f} GWh/a ({unmatched / sections['E_current'].sum():.1%} "
            "of the KLIEN energy) sit in sections whose capacity is missing from "
            "the fleet; this energy is left out of the targets. Close the gap by "
            "curating the plants of the sections listed above (missing plants, "
            "misplaced coordinates, diversion overrides)."
        )

    econtrol = read_econtrol_annual_generation(snakemake.input.econtrol_annual)
    factors = weather_year_factors(econtrol, year)
    targets["year_factor"] = targets["carrier"].map(factors)
    targets["inflow"] = targets["rav_gwh"] * 1e3 * targets["year_factor"]
    targets = pd.concat(
        [targets[OUTPUT_COLUMNS], phs_inflow_targets(econtrol, year, plants, at_buses)],
        ignore_index=True,
    )

    logger.info(
        f"KLIEN sections carry {sections['E_current'].sum() / 1e3:.2f} TWh/a. "
        f"Weather year {year} factors: ror {factors['ror']:.3f}, "
        f"hydro {factors['hydro']:.3f}, PHS {factors['PHS']:.3f}."
    )
    for carrier, total in targets.groupby("carrier")["inflow"].sum().items():
        logger.info(f"AT {carrier} inflow target for {year}: {total / 1e6:.2f} TWh.")
    return targets[OUTPUT_COLUMNS]


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_hydro_inflow_targets_at",
            run="AT_KN2040",
            clusters="adm",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    logger.info("Building KLIEN-calibrated hydro inflow targets...")
    targets = main(snakemake)
    targets.to_csv(snakemake.output.targets, index=False)
    logger.info(f"Saved hydro inflow targets to {snakemake.output.targets}")
