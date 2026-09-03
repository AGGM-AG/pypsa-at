# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Snakemake script: overwrite attributes in the matched powerplants table.

Applies the CH nuclear ``DateOut`` override, optionally adds Austrian biogas
plants from the Anlagenregister and optionally corrects the ``Technology`` of
misclassified Austrian hydro plants (``mods.update_hydro_capacities_AT``).
The patched table is consumed by ``add_existing_baseyear`` and by the mods
layer (``prepare_sector_network`` -> ``process_hydro``).
"""

import logging

import pandas as pd
from build_anlagenregister_at import (
    MAX_UNMAPPED_CAPACITY_SHARE,
    add_first_feedin_year,
    clean_plz,
    feedin_columns,
    load_postal_to_nuts,
)

from mods.clustering.utils import map_at_nuts3_to_nuts2
from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

# Real-world / operator retirement years for the four matched CH reactors
CH_NUCLEAR_DATEOUT = {
    "Beznau 1": 2020,
    "Beznau 2": 2020,
    "Goesgen": 2035,  # operation to ~2040; dropped at 2040 horizon
    "Leibstadt": 2040,  # operation to ~2045
}

# Anlagenregister technology code (whitespace-stripped) of the small hydro
# class added per plant; powerplantmatching run-of-river plants below the
# class limit are replaced to avoid double counting.
KLEINWASSERKRAFT_TECHCODE = "Kleinwasserkraft bis 10 MW"
KLEINWASSERKRAFT_MAX_MW = 10.0

# The register publishes no commissioning dates and feed-in only for a six
# year window. Plants whose first feed-in year lies inside the window use it
# as DateIn proxy; older plants get this assumed build year.
KLEINWASSERKRAFT_DEFAULT_DATEIN = 2000

# Name prefix of the synthetic register plants; used by the rescaling step
# to identify them.
KLEINWASSERKRAFT_NAME_PREFIX = "Kleinwasserkraft AT "

# Tolerated relative deviation between the register Kleinwasserkraft class
# capacity and the E-Control Bestandsstatistik total below 10 MW. The known
# class-definition gap is ~12.5 %; anything larger indicates changed or
# broken source data.
KLEINWASSERKRAFT_MAX_SCALE_DEVIATION = 0.15


def _new_powerplant_rows(
    names: "pd.Series | str",
    fueltype: str,
    technology: str,
    date_in: "pd.Series | float",
    capacity_mw: "pd.Series | float",
    bus: "pd.Series | str",
    country: "pd.Series | str" = "AT",
) -> pd.DataFrame:
    """
    Build power plant rows in the ``build_powerplants`` output schema.

    Parameters accept scalars or aligned array-likes; ``Set`` is always
    ``"PP"``.
    """
    return pd.DataFrame(
        {
            "Name": names,
            "Fueltype": fueltype,
            "Technology": technology,
            "Set": "PP",
            "Country": country,
            "DateIn": date_in,
            "Capacity": capacity_mw,
            "bus": bus,
        }
    )


def _match_single_hydro_plant(
    ppl: pd.DataFrame,
    name: str,
    country: str,
    expected_capacity_mw: float,
    expected_bus: str,
    source_file: str,
    technology: str | None = None,
) -> "int | str":
    """
    Locate exactly one hydro plant of a curated list entry and validate it.

    Parameters
    ----------
    ppl
        Powerplants table with ``Name``, ``Country``, ``Fueltype``,
        ``Technology``, ``Capacity`` and ``bus`` columns.
    name
        Plant name to match.
    country
        Two-letter country code to match.
    expected_capacity_mw
        Capacity the curated list expects; deviations above 1 MW raise.
    expected_bus
        Bus the curated list expects; mismatches only warn because differing
        clustering resolutions relabel buses.
    source_file
        Curated CSV referenced in error messages.
    technology
        Optional ``Technology`` the plant must additionally match.

    Returns
    -------
    The matched index label.

    Raises
    ------
    ValueError
        If the plant does not match exactly once or its capacity deviates by
        more than 1 MW — both indicate a changed upstream dataset.
    """
    query = "Country == @country and Fueltype == 'Hydro' and Name == @name"
    if technology is not None:
        query += " and Technology == @technology"
    matches = ppl.query(query).index
    if len(matches) != 1:
        with_technology = f" with Technology {technology!r}" if technology else ""
        raise ValueError(
            f"Expected exactly one {country} hydro plant {name!r}"
            f"{with_technology}, found {len(matches)}. Powerplants data "
            f"changed upstream; re-check {source_file}."
        )
    idx = matches[0]
    if abs(ppl.at[idx, "Capacity"] - expected_capacity_mw) > 1.0:
        raise ValueError(
            f"Capacity mismatch for {name!r} ({country}): powerplants table "
            f"has {ppl.at[idx, 'Capacity']:.1f} MW, the curated list expects "
            f"{expected_capacity_mw:.1f} MW. Re-check {source_file}."
        )
    if ppl.at[idx, "bus"] != expected_bus:
        logger.warning(
            f"{name!r} sits at bus {ppl.at[idx, 'bus']!r} but {source_file} "
            f"expects {expected_bus!r} (differing clustering?). Applying anyway."
        )
    return idx


def overwrite_nuclear_dateout(ppl: pd.DataFrame, dateout: dict) -> pd.DataFrame:
    """
    Set ``DateOut`` on matched CH nuclear reactors that lack a phase-out year.

    Parameters
    ----------
    ppl
        Powerplants table with at least ``Name``, ``Country``, ``Fueltype`` and
        ``DateOut`` columns (as produced by ``build_powerplants``).
    dateout
        Mapping ``{matched Name: DateOut year}`` for the CH nuclear reactors.

    Returns
    -------
    A copy of ``ppl`` with ``DateOut`` overridden on the matched CH nuclear rows.

    Raises
    ------
    ValueError
        If no CH nuclear rows exist, or if any name in ``dateout`` is not found
        among the CH nuclear rows (fail-fast on broken assumptions).
    """
    is_ch_nuclear = (ppl["Country"] == "CH") & (ppl["Fueltype"] == "Nuclear")
    if not is_ch_nuclear.any():
        raise ValueError(
            "No CH nuclear reactors found in the powerplants table; cannot "
            "override DateOut. Has the matching upstream of build_powerplants "
            "changed?"
        )

    found = set(ppl.loc[is_ch_nuclear, "Name"])
    missing = set(dateout) - found
    if missing:
        raise ValueError(
            f"Expected CH nuclear reactor(s) {sorted(missing)} not found among "
            f"CH nuclear rows {sorted(found)}."
        )

    ppl = ppl.copy()
    for name, year in dateout.items():
        ppl.loc[is_ch_nuclear & (ppl["Name"] == name), "DateOut"] = year

    logger.info(f"Overrode DateOut on {len(dateout)} CH nuclear reactors: {dateout}.")

    return ppl


def overwrite_biogas_to_power_plants_at(
    ppl: pd.DataFrame,
    anlagenregister_file: str,
    postal_to_nuts_file: str,
    threshold_capacity: float,
    clustering: str,
) -> pd.DataFrame:
    """
    Add Austrian biogas powerplants from the Anlagenregister (https://anlagenregister.at/).
    Geographical mapping file from European Commission (https://gisco-services.ec.europa.eu/tercet/NUTS-2024/pc2025_AT_NUTS-2024_v1.0.zip).

    Parameters
    ----------
    ppl
        Powerplants table with at least ``Name``, ``Country``, ``Fueltype`` and
        ``Capacity`` columns (as produced by ``build_powerplants``).
    anlagenregister_file
        input file of relevant powerplants published for Austria.
    postal_to_nuts_file
        file that maps all Austrian postal codes (PLZ) to NUTS3 region codes.
    threshold_capacity
        capacity threshold (MW) applied downstream when aggregating existing
        plants per node. Must be <= 5 MW, otherwise the small Austrian biogas
        plants added here would be filtered out again.
    clustering
        clustering identifier, either AT10 (NUTS2) or AT35 (NUTS3). Needed for
        AT10, maps powerplants accordingly using map_at_nuts3_to_nuts2.

    Returns
    -------
    :
        A copy of ``ppl`` with added biogas powerplants for Austria from the Anlagenregister.

    Raises
    ------
    ValueError
        If small biogas powerplants are found in the original powerplant file.
        This indicates a change in the upstream file that warrants investigation.
        Also if ``threshold_capacity`` exceeds 5 MW.
    """
    at_small_bioenergy_ppl = ppl[
        (ppl["Country"] == "AT")
        & (ppl["Fueltype"] == "Bioenergy")
        & (ppl["Capacity"] < 2)
    ]
    if not at_small_bioenergy_ppl.empty:
        raise ValueError(
            "Detected biogas powerplants in powerplantmatching data for Austria."
            "Go and check if dataset has changed upstream!"
        )

    if threshold_capacity > 5:
        raise ValueError(
            f"threshold_capacity for adding existing capacities per node is {threshold_capacity} MW,"
            "but must be <= 5 MW to keep small Austrian biogas plants."
            "Change config.at.yaml setting accordingly."
        )

    postal_to_nuts = pd.read_csv(
        postal_to_nuts_file, dtype=str, names=["nuts3", "plz"], header=0
    ).set_index("plz")["nuts3"]

    anlreg = pd.read_csv(anlagenregister_file)
    anlreg = anlreg.dropna(subset=["Plz"])
    anlreg["Plz"] = anlreg["Plz"].astype("Int64").astype(str).str.zfill(4)
    anlreg["nuts"] = anlreg["Plz"].map(postal_to_nuts)

    missing_plz = anlreg.loc[anlreg["nuts"].isna(), "Plz"].unique()
    if len(missing_plz) > 0:
        raise ValueError(
            f"Postal codes {sorted(missing_plz)} from Anlagenregister not found in"
            f"postal-to-nuts-file. Update mapping or check data."
        )

    # Relabel NUTS3 codes to NUTS2 if run has lower resolution
    if clustering.startswith("AT10"):
        anlreg["nuts"] = anlreg["nuts"].map(map_at_nuts3_to_nuts2)

    new_ppls = _new_powerplant_rows(
        names="Biogas AT " + anlreg["ID"].astype(int).astype(str),
        fueltype="Bioenergy",
        technology="Combustion Engine",
        # assumed build year at the height of Förderung in AT, phase out before 2030
        date_in=2003,
        capacity_mw=anlreg["Engpassleistung (kW <sub>el</sub>)"] / 1000,
        bus=anlreg["nuts"].values,
    )

    logger.info(
        f"Added {len(new_ppls)} Austrian biogas plants with "
        f"{new_ppls['Capacity'].sum():.1f} MW from Anlagenregister."
    )
    return pd.concat([ppl, new_ppls], ignore_index=True)


def _read_small_hydro_anchor_mw(bestandsstatistik_typ_file: str) -> float:
    """
    Read the total hydro Engpassleistung below 10 MW from the Bestandsstatistik.

    Sums the two ``bis 10 MW`` rows (Laufkraftwerke and Speicherkraftwerke) of
    sheet ``EPL_KWTyp`` in E-Control's ``BeStGes-{year}_KW2EPLTyp.xlsx``.
    """
    epl = pd.read_excel(bestandsstatistik_typ_file, sheet_name="EPL_KWTyp", header=None)
    below_10 = epl[epl.iloc[:, 2].astype(str).str.strip() == "bis 10 MW"]
    anchor_mw = pd.to_numeric(below_10.iloc[:, 5], errors="coerce").sum()
    if len(below_10) != 2 or not 500 < anchor_mw < 5000:
        raise ValueError(
            f"Unexpected layout in {bestandsstatistik_typ_file}: found "
            f"{len(below_10)} 'bis 10 MW' rows summing to {anchor_mw:.0f} MW. "
            "Has the E-Control file format changed?"
        )
    return float(anchor_mw)


def add_kleinwasserkraft_to_power_plants_at(
    ppl: pd.DataFrame,
    anlagenregister_plants_file: str,
    postal_to_nuts_file: str,
    clustering: str,
) -> pd.DataFrame:
    """
    Replace the small hydro fleet with Anlagenregister Kleinwasserkraft plants.

    powerplantmatching covers only ~70 MW of Austrian run-of-river plants
    below 10 MW, while the E-Control Anlagenregister lists the full
    ``Kleinwasserkraft bis 10 MW`` class (~3600 plants, ~1.8 GW; E-Control
    Bestandsstatistik: 1.4 GW Laufkraft below 10 MW). This function drops the
    incidental powerplantmatching run-of-river plants up to
    ``KLEINWASSERKRAFT_MAX_MW`` and adds every register plant of the class
    individually, mapped to its NUTS3 bus via postal code
    (see pypsa-at-planning#312).

    Parameters
    ----------
    ppl
        Powerplants table with ``Name``, ``Country``, ``Fueltype``,
        ``Technology``, ``Capacity`` and ``bus`` columns
        (as produced by ``build_powerplants``).
    anlagenregister_plants_file
        Plant-level Anlagenregister CSV (``anlagenregister_plants.csv``).
    postal_to_nuts_file
        file that maps all Austrian postal codes (PLZ) to NUTS3 region codes.
    clustering
        clustering identifier, either AT10 (NUTS2) or AT35 (NUTS3). Needed for
        AT10, maps powerplants accordingly using map_at_nuts3_to_nuts2.

    Returns
    -------
    :
        A copy of ``ppl`` with the register small hydro fleet instead of the
        powerplantmatching one.

    Raises
    ------
    ValueError
        If the register contains no Kleinwasserkraft plants or too much
        capacity has unmappable postal codes (both indicate changed source
        data).
    """
    plants = pd.read_csv(
        anlagenregister_plants_file, dtype={"plz": str}, low_memory=False
    )
    kwk = plants.assign(techcode=plants["techcode"].fillna("").str.strip()).query(
        "typ == 'Strom' and techcode == @KLEINWASSERKRAFT_TECHCODE"
    )
    if kwk.empty:
        raise ValueError(
            f"No {KLEINWASSERKRAFT_TECHCODE!r} plants found in "
            f"{anlagenregister_plants_file}. Has the register format changed?"
        )

    kwk["plz"] = clean_plz(kwk["plz"])
    kwk["nuts"] = kwk["plz"].map(load_postal_to_nuts(postal_to_nuts_file))
    unmapped = kwk["nuts"].isna()
    unmapped_share = (
        kwk.loc[unmapped, "engpassleistung_kw"].sum() / kwk["engpassleistung_kw"].sum()
    )
    if unmapped_share > MAX_UNMAPPED_CAPACITY_SHARE:
        raise ValueError(
            f"{unmapped.sum()} Kleinwasserkraft plants ({unmapped_share:.2%} of "
            "class capacity) have no NUTS3 mapping. Update the postal-to-nuts "
            "file or check the register data."
        )
    if unmapped.any():
        logger.warning(
            f"Dropped {unmapped.sum()} Kleinwasserkraft plants "
            f"({unmapped_share:.3%} of class capacity) with unmappable postal codes."
        )
    kwk = kwk[~unmapped]

    # DateIn proxy: first feed-in year, only meaningful for plants first
    # feeding in after the earliest published year (older plants -> default).
    kwk = add_first_feedin_year(kwk)
    _earliest_year = min(int(c.rsplit("_", 1)[1]) for c in feedin_columns(kwk))
    date_in = (
        kwk["first_feedin_year"]
        .where(kwk["first_feedin_year"] > _earliest_year)
        .fillna(KLEINWASSERKRAFT_DEFAULT_DATEIN)
        .astype(float)
    )

    # Relabel NUTS3 codes to NUTS2 if run has lower resolution
    if clustering.startswith("AT10"):
        kwk["nuts"] = kwk["nuts"].map(map_at_nuts3_to_nuts2)

    small_ror = ppl.query(
        "Country == 'AT' "
        "and Fueltype == 'Hydro' "
        "and Technology == 'Run-Of-River' "
        "and Capacity <= @KLEINWASSERKRAFT_MAX_MW"
    )
    logger.info(
        f"Replaced {len(small_ror)} powerplantmatching run-of-river plants <= "
        f"{KLEINWASSERKRAFT_MAX_MW:.0f} MW ({small_ror['Capacity'].sum():.1f} MW) "
        "with the Anlagenregister Kleinwasserkraft fleet."
    )
    ppl = ppl.drop(index=small_ror.index)

    # register ids are only unique within (typ, bundesland)
    new_ppls = _new_powerplant_rows(
        names=(
            KLEINWASSERKRAFT_NAME_PREFIX
            + kwk["bundesland"].astype(str)
            + "-"
            + kwk["id"].astype(int).astype(str)
        ),
        fueltype="Hydro",
        technology="Run-Of-River",
        date_in=date_in.values,
        capacity_mw=kwk["engpassleistung_kw"].values / 1e3,
        bus=kwk["nuts"].values,
    ).assign(plz=kwk["plz"].values)
    # postal codes are carried over to simplify locating plants

    logger.info(
        f"Added {len(new_ppls)} Austrian Kleinwasserkraft plants with "
        f"{new_ppls['Capacity'].sum():.1f} MW from Anlagenregister."
    )
    return pd.concat([ppl, new_ppls], ignore_index=True)


def scale_kleinwasserkraft_to_bestandsstatistik_at(
    ppl: pd.DataFrame, bestandsstatistik_typ_file: str
) -> pd.DataFrame:
    """
    Scale the added Kleinwasserkraft fleet to the E-Control capacity total.

    The E-Control Bestandsstatistik is used as ground truth for the
    Austria-wide capacity per technology. The register Kleinwasserkraft
    class and E-Control's size-class accounting differ by ~200 MW
    (~12.5 %), so the plants added by
    ``add_kleinwasserkraft_to_power_plants_at`` (identified by
    ``KLEINWASSERKRAFT_NAME_PREFIX``) are scaled uniformly to the
    Bestandsstatistik total below 10 MW, preserving the register's
    regional distribution.

    Parameters
    ----------
    ppl
        Powerplants table including the added Kleinwasserkraft plants.
    bestandsstatistik_typ_file
        E-Control Bestandsstatistik Kraftwerkstypen xlsx.

    Returns
    -------
    A copy of ``ppl`` with scaled Kleinwasserkraft capacities.

    Raises
    ------
    ValueError
        If no Kleinwasserkraft plants are present, or if the scale factor
        deviates by more than ``KLEINWASSERKRAFT_MAX_SCALE_DEVIATION`` from
        1 (both indicate changed or broken source data).
    """
    ppl = ppl.copy()
    kwk_rows = ppl["Name"].str.startswith(KLEINWASSERKRAFT_NAME_PREFIX, na=False)
    if not kwk_rows.any():
        raise ValueError(
            f"No plants with name prefix {KLEINWASSERKRAFT_NAME_PREFIX!r} "
            "found; run add_kleinwasserkraft_to_power_plants_at first."
        )
    class_mw = ppl.loc[kwk_rows, "Capacity"].sum()

    anchor_mw = _read_small_hydro_anchor_mw(bestandsstatistik_typ_file)
    scale = anchor_mw / class_mw
    if abs(1 - scale) > KLEINWASSERKRAFT_MAX_SCALE_DEVIATION:
        raise ValueError(
            f"Kleinwasserkraft scale factor {scale:.3f} deviates more than "
            f"{KLEINWASSERKRAFT_MAX_SCALE_DEVIATION:.0%} from 1: register class "
            f"capacity {class_mw:.0f} MW vs. E-Control Bestandsstatistik "
            f"anchor {anchor_mw:.0f} MW. Check both datasets for changed "
            "content or format."
        )
    ppl.loc[kwk_rows, "Capacity"] *= scale
    logger.info(
        f"Scaled {int(kwk_rows.sum())} Kleinwasserkraft plants by {scale:.3f} "
        f"to the E-Control Bestandsstatistik total below 10 MW of "
        f"{anchor_mw:.0f} MW."
    )
    return ppl


def apply_grenzkraftwerke_shares_at(
    ppl: pd.DataFrame, grenzkraftwerke_file: str
) -> pd.DataFrame:
    """
    Scale the AT/DE border hydro plants to their treaty shares.

    The Inn and Danube Grenzkraftwerke are jointly owned 50/50 with Bavaria
    (OeBK and Donaukraftwerk Jochenstein AG). powerplantmatching lists four
    of them twice (once per country) and every entry at full capacity, so
    both the Austrian and the German bus double count the same machines
    (see pypsa-at-planning#92). Scaling each listed entry by its treaty
    ``share`` assigns every country its energy-rights half.

    Parameters
    ----------
    ppl
        Powerplants table with ``Name``, ``Country``, ``Fueltype``,
        ``Capacity`` and ``bus`` columns.
    grenzkraftwerke_file
        CSV with columns ``Name``, ``country``, ``bus``, ``capacity_mw``,
        ``share``, ``action``, ``date_in``, ``river`` and ``note``.
        ``action`` is either ``scale`` (scale an existing entry to
        ``capacity_mw * share``) or ``add`` (insert a missing run-of-river
        twin at ``capacity_mw * share`` with build year ``date_in``, for
        border plants powerplantmatching lists on one side only).

    Returns
    -------
    :
        A copy of ``ppl`` with border plant capacities scaled to treaty shares.

    Raises
    ------
    ValueError
        If a ``scale`` entry does not match exactly one plant, if the
        matched capacity deviates by more than 1 MW, or if an ``add`` entry
        already exists in the table (changed upstream dataset).
    """
    gkw = pd.read_csv(grenzkraftwerke_file)
    ppl = ppl.copy()

    for row in gkw.query("action == 'scale'").itertuples():
        idx = _match_single_hydro_plant(
            ppl,
            row.Name,
            row.country,
            row.capacity_mw,
            row.bus,
            grenzkraftwerke_file,
        )
        ppl.at[idx, "Capacity"] = row.capacity_mw * row.share

    add_rows = gkw.query("action == 'add'")
    for row in add_rows.itertuples():
        matches = ppl.query(
            "Country == @row.country and Fueltype == 'Hydro' and Name == @row.Name"
        ).index
        if len(matches):
            raise ValueError(
                f"{row.country} hydro plant {row.Name!r} already exists in the "
                f"powerplants table; change its action to 'scale' in "
                f"{grenzkraftwerke_file}."
            )
    if not add_rows.empty:
        new_ppls = _new_powerplant_rows(
            names=add_rows["Name"].to_numpy(),
            fueltype="Hydro",
            technology="Run-Of-River",
            date_in=add_rows["date_in"].astype(float).to_numpy(),
            capacity_mw=(add_rows["capacity_mw"] * add_rows["share"]).to_numpy(),
            bus=add_rows["bus"].to_numpy(),
            country=add_rows["country"].to_numpy(),
        )
        ppl = pd.concat([ppl, new_ppls], ignore_index=True)
        logger.info(
            f"Added {len(new_ppls)} missing Grenzkraftwerke treaty halves with "
            f"{new_ppls['Capacity'].sum():.0f} MW."
        )

    _scaled = gkw.query("action == 'scale'")
    _removed = (
        _scaled.assign(removed=_scaled["capacity_mw"] * (1 - _scaled["share"]))
        .groupby("country")["removed"]
        .sum()
    )
    for country, mw in _removed.items():
        logger.info(
            f"Scaled {int((_scaled['country'] == country).sum())} Grenzkraftwerke "
            f"to treaty shares: removed {mw:.0f} MW from {country}."
        )
    return ppl


def add_missing_hydro_plants_at(
    ppl: pd.DataFrame, missing_plants_file: str
) -> pd.DataFrame:
    """
    Add curated Austrian hydro plants absent from powerplantmatching.

    Some large Austrian hydro plants are missing from the powerplantmatching
    fleet — notably the EVN Kamp storage chain (Ottenstein, Dobra-Krumau,
    Thurnberg-Wegscheid), which left the AT124 (Waldviertel) region without
    the reservoir capacity that carries its river energy (see
    pypsa-at-planning#312). Each curated plant is added with its coordinates
    so downstream catchment lookups place it on the correct river section.

    Parameters
    ----------
    ppl
        Powerplants table with ``Name``, ``Country``, ``Fueltype`` and
        ``Capacity`` columns (as produced by ``build_powerplants``).
    missing_plants_file
        CSV with columns ``Name``, ``bus``, ``technology``, ``capacity_mw``,
        ``date_in``, ``lat``, ``lon`` and ``note``.

    Returns
    -------
    :
        A copy of ``ppl`` with the curated plants appended.

    Raises
    ------
    ValueError
        If a curated plant already exists among the Austrian hydro rows
        (changed upstream dataset — switch it to a reclassification instead).
    """
    missing = pd.read_csv(missing_plants_file)
    existing = set(ppl.query("Country == 'AT' and Fueltype == 'Hydro'")["Name"])
    clash = sorted(set(missing["Name"]) & existing)
    if clash:
        raise ValueError(
            f"Curated missing plant(s) {clash} already exist in the "
            f"powerplants table; remove them from {missing_plants_file} or "
            "handle them via reclassification instead."
        )

    new_ppls = _new_powerplant_rows(
        names=missing["Name"].to_numpy(),
        fueltype="Hydro",
        technology=missing["technology"].to_numpy(),
        date_in=missing["date_in"].astype(float).to_numpy(),
        capacity_mw=missing["capacity_mw"].astype(float).to_numpy(),
        bus=missing["bus"].to_numpy(),
    ).assign(lat=missing["lat"].to_numpy(), lon=missing["lon"].to_numpy())

    summary = missing.groupby("technology")["capacity_mw"].agg(["size", "sum"]).round(1)
    for tech, r in summary.iterrows():
        logger.info(
            f"Added {r['size']:.0f} missing Austrian {tech} plants "
            f"({r['sum']:.1f} MW) from {missing_plants_file}."
        )
    return pd.concat([ppl, new_ppls], ignore_index=True)


def reclassify_hydro_technologies_at(
    ppl: pd.DataFrame, reclassification_file: str
) -> pd.DataFrame:
    """
    Correct the ``Technology`` of misclassified Austrian hydro plants.

    powerplantmatching labels the large Austrian river chains (Danube, Drau,
    Mur, Inn, Salzach, Ill) as ``Reservoir`` although they are run-of-river
    plants, which starves the ``ror`` carrier and inflates ``hydro`` in the
    model. The curated plant list in
    ``data/pypsa-at/hydro_technology_reclassification_AT.csv`` (verified
    against operator data, see pypsa-at-planning#312) moves each plant to its
    correct technology.

    Parameters
    ----------
    ppl
        Powerplants table with ``Name``, ``Country``, ``Fueltype``,
        ``Technology``, ``Capacity`` and ``bus`` columns
        (as produced by ``build_powerplants``).
    reclassification_file
        CSV with columns ``Name``, ``bus``, ``capacity_mw``,
        ``technology_old``, ``technology_new``, ``group``, ``note`` and
        optionally ``capacity_new`` (corrected nameplate capacity in MW,
        applied where set).

    Returns
    -------
    :
        A copy of ``ppl`` with corrected ``Technology`` values.

    Raises
    ------
    ValueError
        If a list entry does not match exactly one Austrian hydro plant, or
        if the matched capacity deviates by more than 1 MW. Both indicate a
        changed upstream dataset that warrants re-checking the list.
    """
    reclassification = pd.read_csv(reclassification_file)
    ppl = ppl.copy()

    for row in reclassification.itertuples():
        idx = _match_single_hydro_plant(
            ppl,
            row.Name,
            "AT",
            row.capacity_mw,
            row.bus,
            reclassification_file,
            technology=row.technology_old,
        )
        ppl.at[idx, "Technology"] = row.technology_new
        if pd.notna(getattr(row, "capacity_new", None)):
            logger.info(
                f"Corrected nameplate capacity of {row.Name!r}: "
                f"{ppl.at[idx, 'Capacity']:.1f} -> {row.capacity_new:.1f} MW."
            )
            ppl.at[idx, "Capacity"] = row.capacity_new

    summary = reclassification.groupby(["technology_old", "technology_new"])[
        "capacity_mw"
    ].agg(["size", "sum"])
    for (old, new), r in summary.iterrows():
        logger.info(
            f"Reclassified {r['size']:.0f} Austrian hydro plants "
            f"({r['sum']:.0f} MW) from {old} to {new}."
        )
    return ppl


def overwrite_powerplants(snakemake):
    """Orchestrator function."""
    _ppl = pd.read_csv(snakemake.input.powerplants, index_col=0)
    ppl_overwrite = overwrite_nuclear_dateout(_ppl, CH_NUCLEAR_DATEOUT)

    if snakemake.params.add_biogas_to_power_plants_AT:
        ppl_overwrite = overwrite_biogas_to_power_plants_at(
            ppl_overwrite,
            anlagenregister_file=snakemake.input.anlagenregister,
            postal_to_nuts_file=snakemake.input.postal_to_nuts,
            threshold_capacity=snakemake.params.threshold_capacity,
            clustering=snakemake.params.clustering,
        )
    else:
        logger.info(
            "Skipping Austrian biogas plant addition. config option add_biogas_to_power_plants_AT is false."
        )

    if snakemake.params.update_hydro_capacities_AT:
        ppl_overwrite = reclassify_hydro_technologies_at(
            ppl_overwrite, snakemake.input.hydro_reclassification
        )
        ppl_overwrite = apply_grenzkraftwerke_shares_at(
            ppl_overwrite, snakemake.input.grenzkraftwerke
        )
        ppl_overwrite = add_missing_hydro_plants_at(
            ppl_overwrite, snakemake.input.missing_hydro_plants
        )
        ppl_overwrite = add_kleinwasserkraft_to_power_plants_at(
            ppl_overwrite,
            anlagenregister_plants_file=snakemake.input.anlagenregister_plants,
            postal_to_nuts_file=snakemake.input.postal_to_nuts,
            clustering=snakemake.params.clustering,
        )
        ppl_overwrite = scale_kleinwasserkraft_to_bestandsstatistik_at(
            ppl_overwrite, snakemake.input.bestandsstatistik_typ
        )
    else:
        logger.info(
            "Skipping Austrian hydro technology reclassification. config option mods.update_hydro_capacities_AT.enable is false."
        )
    return ppl_overwrite


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "overwrite_powerplants_at",
            simpl="",
            clusters="adm",
            opts="",
            ll="v1.25",
            sector_opts="none",
            planning_horizons="2025",
            run="AT_KN2040",
        )

    configure_logging(snakemake)

    result = overwrite_powerplants(snakemake)
    result.to_csv(snakemake.output.powerplants)
