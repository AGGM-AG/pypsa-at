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


def overwrite_biogas_to_power_plants_AT(
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

    new_ppls = pd.DataFrame(
        {
            "Name": "Biogas AT " + anlreg["ID"].astype(int).astype(str),
            "Fueltype": "Bioenergy",
            "Technology": "Combustion Engine",
            "Set": "PP",
            "Country": "AT",
            "DateIn": 2003,  # assumed build year at the height of Förderung in AT, phase out before 2030
            "Capacity": anlreg["Engpassleistung (kW <sub>el</sub>)"] / 1000,
            "bus": anlreg["nuts"].values,
        }
    )

    logger.info(
        f"Added {len(new_ppls)} Austrian biogas plants with "
        f"{new_ppls['Capacity'].sum():.1f} MW from Anlagenregister."
    )
    return pd.concat([ppl, new_ppls], ignore_index=True)


def add_kleinwasserkraft_to_power_plants_at(
    ppl: pd.DataFrame,
    anlagenregister_plants_file: str,
    postal_to_nuts_file: str,
    threshold_capacity: float,
    clustering: str,
) -> pd.DataFrame:
    """
    Replace the small hydro fleet with Anlagenregister Kleinwasserkraft plants.

    powerplantmatching covers only ~70 MW of Austrian run-of-river plants
    below 10 MW, while the E-Control Anlagenregister lists the full
    ``Kleinwasserkraft bis 10 MW`` class (~3600 plants, ~1.8 GW; E-Control
    Bestandsstatistik: 1.4 GW Laufkraft below 10 MW). This function drops the
    incidental powerplantmatching run-of-river plants below
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
    threshold_capacity
        capacity threshold (MW) applied downstream when aggregating existing
        plants per node. Must be <= 5 MW, otherwise the small hydro plants
        added here would be filtered out again.
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
        If the register contains no Kleinwasserkraft plants, if too much
        capacity has unmappable postal codes (both indicate changed source
        data), or if ``threshold_capacity`` exceeds 5 MW.
    """
    if threshold_capacity > 5:
        raise ValueError(
            f"threshold_capacity for adding existing capacities per node is {threshold_capacity} MW,"
            "but must be <= 5 MW to keep small Austrian hydro plants."
            "Change config.at.yaml setting accordingly."
        )

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
        "and Capacity < @KLEINWASSERKRAFT_MAX_MW"
    )
    logger.info(
        f"Replaced {len(small_ror)} powerplantmatching run-of-river plants < "
        f"{KLEINWASSERKRAFT_MAX_MW:.0f} MW ({small_ror['Capacity'].sum():.1f} MW) "
        "with the Anlagenregister Kleinwasserkraft fleet."
    )
    ppl = ppl.drop(index=small_ror.index)

    # register ids are only unique within (typ, bundesland)
    new_ppls = pd.DataFrame(
        {
            "Name": (
                "Kleinwasserkraft AT "
                + kwk["bundesland"].astype(str)
                + "-"
                + kwk["id"].astype(int).astype(str)
            ),
            "Fueltype": "Hydro",
            "Technology": "Run-Of-River",
            "Set": "PP",
            "Country": "AT",
            "DateIn": date_in.values,
            "Capacity": kwk["engpassleistung_kw"].values / 1e3,
            "bus": kwk["nuts"].values,
        }
    )
    logger.info(
        f"Added {len(new_ppls)} Austrian Kleinwasserkraft plants with "
        f"{new_ppls['Capacity'].sum():.1f} MW from Anlagenregister."
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
        ``technology_old``, ``technology_new``, ``group`` and ``note``.

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
        matches = ppl.query(
            "Country == 'AT' "
            "and Fueltype == 'Hydro' "
            "and Name == @row.Name "
            "and Technology == @row.technology_old"
        ).index
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one AT hydro plant {row.Name!r} with "
                f"Technology {row.technology_old!r}, found {len(matches)}. "
                f"Powerplants data changed upstream; re-check "
                f"{reclassification_file}."
            )
        idx = matches[0]
        if abs(ppl.at[idx, "Capacity"] - row.capacity_mw) > 1.0:
            raise ValueError(
                f"Capacity mismatch for {row.Name!r}: powerplants table has "
                f"{ppl.at[idx, 'Capacity']:.1f} MW, the reclassification list "
                f"expects {row.capacity_mw:.1f} MW. Re-check "
                f"{reclassification_file}."
            )
        if ppl.at[idx, "bus"] != row.bus:
            logger.warning(
                f"{row.Name!r} sits at bus {ppl.at[idx, 'bus']!r} but the "
                f"reclassification list expects {row.bus!r} (differing "
                f"clustering?). Reclassifying anyway."
            )
        ppl.at[idx, "Technology"] = row.technology_new

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
        ppl_overwrite = overwrite_biogas_to_power_plants_AT(
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
        ppl_overwrite = add_kleinwasserkraft_to_power_plants_at(
            ppl_overwrite,
            anlagenregister_plants_file=snakemake.input.anlagenregister_plants,
            postal_to_nuts_file=snakemake.input.postal_to_nuts,
            threshold_capacity=snakemake.params.threshold_capacity,
            clustering=snakemake.params.clustering,
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
