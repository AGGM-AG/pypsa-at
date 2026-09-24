# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Snakemake script: patch the powerplants table and prepare Austrian biogas plants.

Reads the matched powerplants table, applies the CH nuclear DateOut override
and the Austrian gas brownfield calibration, and writes the patched table
consumed by ``add_existing_baseyear`` and ``add_electricity``.
The Austrian biogas plants from the Anlagenregister are written to a separate
table consumed by ``mods.network.biogas`` in ``modify_prenetwork_at``; they
must not enter the powerplants table, where ``add_existing_baseyear`` would
model them as solid biomass CHPs.
"""

import logging

import pandas as pd
from build_anlagenregister_at import (
    GAS_TECHCODES,
    deduplicate_gas_registrations,
    feedin_columns,
    load_postal_to_nuts,
    map_plants_to_nuts3,
    normalise_techcode,
)

from mods.clustering.utils import map_at_nuts3_to_nuts2
from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

# Real-world / operator retirement years for the matched CH reactors. Names
# follow the powerplantmatching 0.8.1 dataset pinned in data/versions.csv
# (0.6.1 spelled them "Kkb Kernkw Beznau"/"Kernkraftwerk Gosgen"/
# "Kkl Kernkw Leibstadt Ag", and matched both Beznau units into one row).
CH_NUCLEAR_DATEOUT = {
    "Beznau 1": 2020,
    "Beznau 2": 2020,
    "Goesgen": 2035,  # operation to ~2040; dropped at 2040 horizon
    "Leibstadt": 2040,  # operation to ~2045
}


RENEWABLE_GAS_TECHNOLOGIES = ("Biogas", "Klärgas", "Deponiegas")
"""Anlagenregister ``techcode`` values of electricity from renewable gas."""

LARGE_PLANT_THRESHOLD_MW = 5
"""
Capacity split between the Anlagenregister and powerplantmatching for
Austrian biogas-to-power plants. Register plants at or below this size are
added from the Anlagenregister; larger ones are assumed to already be
captured by powerplantmatching under their true fuel type. For example, the
Gratkorn paper mill is registered in the Anlagenregister as 140 MW "Biogas"
but is already modelled via powerplantmatching as a 70 MW gas CCGT CHP.
"""

BIOGAS_BUILD_YEAR = 2003
"""Assumed build year: height of the Austrian Förderung, phase-out before 2030."""

BIOGAS_PLANT_COLUMNS = [
    "Name",
    "Country",
    "Fueltype",
    "Technology",
    "DateIn",
    "Capacity",
    "bus",
]


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


def build_biogas_plants_AT(
    ppl: pd.DataFrame,
    anlagenregister_file: str,
    postal_to_nuts_file: str,
    threshold_capacity: float,
    clustering: str,
) -> pd.DataFrame:
    """
    Prepare Austrian biogas powerplants from the E-Control Anlagenregister.
    Geographical mapping file from European Commission (https://gisco-services.ec.europa.eu/tercet/NUTS-2024/pc2025_AT_NUTS-2024_v1.0.zip).

    Parameters
    ----------
    ppl
        Powerplants table with at least ``Name``, ``Country``, ``Fueltype`` and
        ``Capacity`` columns (as produced by ``build_powerplants``). Only used
        to guard against small Austrian bioenergy plants appearing upstream.
    anlagenregister_file
        Plant-level Anlagenregister CSV (``anlagenregister_plants.csv`` of the
        ``anlagenregister`` dataset in ``data/versions.csv``). Electricity
        plants (``typ == "Strom"``) with a ``techcode`` in
        ``RENEWABLE_GAS_TECHNOLOGIES`` and a capacity at or below
        ``LARGE_PLANT_THRESHOLD_MW`` are used; larger ones are dropped, see
        ``LARGE_PLANT_THRESHOLD_MW``.
    postal_to_nuts_file
        file that maps all Austrian postal codes (PLZ) to NUTS3 region codes.
    threshold_capacity
        capacity threshold (MW) applied downstream when aggregating existing
        plants per node. Must be <= ``LARGE_PLANT_THRESHOLD_MW``, otherwise
        the small Austrian biogas plants would be filtered out again.
    clustering
        clustering identifier, either AT10 (NUTS2) or AT35 (NUTS3). Needed for
        AT10, maps powerplants accordingly using _map_at_nuts3_to_nuts2.

    Returns
    -------
    One row per Anlagenregister plant with ``Name``, ``Country``, ``Fueltype``,
    ``Technology``, ``DateIn``, ``Capacity`` (MW) and ``bus`` (node), consumed
    by ``mods.network.biogas.add_existing_biogas_chp_at``.

    Raises
    ------
    ValueError
        If small biogas powerplants are found in the original powerplant file.
        This indicates a change in the upstream file that warrants investigation.
        Also if ``threshold_capacity`` exceeds ``LARGE_PLANT_THRESHOLD_MW``, if
        the register holds no renewable-gas plants, or if a postal code is not
        in the mapping.
    """
    at_small_bioenergy_ppl = ppl[
        (ppl["Country"] == "AT")
        & (ppl["Fueltype"] == "Bioenergy")
        & (ppl["Capacity"] < LARGE_PLANT_THRESHOLD_MW)
    ]
    if not at_small_bioenergy_ppl.empty:
        raise ValueError(
            "Detected biogas powerplants in powerplantmatching data for Austria."
            "Go and check if dataset has changed upstream!"
        )

    if threshold_capacity > LARGE_PLANT_THRESHOLD_MW:
        raise ValueError(
            f"threshold_capacity for adding existing capacities per node is {threshold_capacity} MW,"
            f"but must be <= {LARGE_PLANT_THRESHOLD_MW} MW to keep small Austrian biogas plants."
            "Change config.at.yaml setting accordingly."
        )

    postal_to_nuts = pd.read_csv(
        postal_to_nuts_file, dtype=str, names=["nuts3", "plz"], header=0
    ).set_index("plz")["nuts3"]

    register = pd.read_csv(anlagenregister_file, low_memory=False)
    register["techcode"] = register["techcode"].fillna("").str.strip()
    anlreg = register[
        (register["typ"] == "Strom")
        & register["techcode"].isin(RENEWABLE_GAS_TECHNOLOGIES)
    ].copy()
    if anlreg.empty:
        raise ValueError(
            f"No electricity plants with techcode in {RENEWABLE_GAS_TECHNOLOGIES} "
            f"found in {anlagenregister_file}. Has the Anlagenregister changed?"
        )

    too_large = anlreg["engpassleistung_kw"] / 1000 > LARGE_PLANT_THRESHOLD_MW
    if too_large.any():
        logger.warning(
            f"Dropped {int(too_large.sum())} renewable-gas plants "
            f"({anlreg.loc[too_large, 'engpassleistung_kw'].sum() / 1e3:.1f} MW) "
            f"above {LARGE_PLANT_THRESHOLD_MW} MW; assumed to already be "
            "captured by powerplantmatching under their true fuel type."
        )
        anlreg = anlreg[~too_large]

    # the register holds free-text postal codes ("4600 ", "5431 Kuchl", ...);
    # take the first run of exactly four digits, like build_anlagenregister_at
    anlreg["Plz"] = (
        anlreg["plz"].fillna("").astype(str).str.extract(r"(?<!\d)(\d{4})(?!\d)")[0]
    )
    without_plz = anlreg["Plz"].isna()
    if without_plz.any():
        logger.warning(
            f"Dropped {int(without_plz.sum())} renewable-gas plants "
            f"({anlreg.loc[without_plz, 'engpassleistung_kw'].sum() / 1e3:.2f} MW) "
            "without a postal code."
        )
        anlreg = anlreg[~without_plz]
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

    plants = pd.DataFrame(
        {
            # register ids are scrape row numbers, not stable across versions
            "Name": "Biogas AT " + anlreg["id"].astype(int).astype(str),
            "Country": "AT",
            "Fueltype": "Biogas",
            "Technology": anlreg["techcode"].values,
            "DateIn": BIOGAS_BUILD_YEAR,
            "Capacity": anlreg["engpassleistung_kw"].to_numpy(dtype=float) / 1000,
            "bus": anlreg["nuts"].values,
        }
    )

    logger.info(
        f"Prepared {len(plants)} Austrian biogas plants with "
        f"{plants['Capacity'].sum():.1f} MW from Anlagenregister."
    )
    return plants


GAS_OVERRIDE_ACTIONS = ("update", "add", "drop")
"""Actions understood in ``gas_powerplant_overrides_AT.csv``."""

GAS_TECHNOLOGIES = ("OCGT", "CCGT")
"""``Technology`` values ``add_existing_baseyear`` accepts for natural gas.

``scripts/add_existing_baseyear.py`` selects gas brownfield rows on
``Technology`` rather than ``Fueltype`` and silently drops the third
powerplantmatching value ``"CCGT, Thermal"``, so every row this module writes
must carry one of these two.
"""

GAS_CALIBRATION_BASE_YEAR = 2025
"""Year the Austrian gas fleet is calibrated against E-Control statistics."""

GAS_NATIONAL_TOLERANCE = 0.02
"""Relative overshoot of the national Bestandsstatistik total tolerated.

The test is one-sided: the modelled fleet must not *exceed* the statistic.
A shortfall is expected and itemised, because plants that never supply the
public grid are deliberately out of scope.
"""

GAS_FULL_LOAD_HOUR_BAND = (1500.0, 2500.0)
"""Plausible range [h] for the Austrian gas fleet's annual full load hours.

Brackets every year of the E-Control series in
``data/pypsa-at/gas_calibration_targets_AT.csv`` from 2015 to 2025 (minimum
1 540.6 h in 2015, maximum 2 482.5 h in 2019, mean 1 994 h). 2013 and 2014 sit
below it at 1 249 h and 1 057 h, when gas was pushed out of the merit order by
cheap coal and CO2 prices; those two years are excluded deliberately, so a
modelled fleet that lands there is flagged rather than accepted.
"""

GAS_PLANT_TOLERANCE = 0.10
"""Relative per-region deviation from the register reported without comment."""

GAS_PLANT_TOLERANCE_MW = 50.0
"""Absolute per-region deviation [MW] reported without comment.

A region is flagged when it exceeds *both* this and
:data:`GAS_PLANT_TOLERANCE`, i.e. the looser of the two applies.
"""


def _required(row: pd.Series, fields: tuple[str, ...], action: str) -> None:
    """Raise if an override row leaves a field required by its action empty."""
    missing = [f for f in fields if pd.isna(row.get(f)) or row.get(f) == ""]
    if missing:
        raise ValueError(
            f"Gas override row {row['name']!r} with action {action!r} is missing "
            f"required field(s) {missing}. Every added or updated value needs a "
            "figure and a source; see data/pypsa-at/gas_powerplant_overrides_AT.csv."
        )


def apply_gas_overrides_at(
    ppl: pd.DataFrame,
    overrides_file: str,
    clustering: str = "AT35DE5",
) -> pd.DataFrame:
    """
    Apply the curated Austrian gas corrections to the powerplants table.

    Reads ``data/pypsa-at/gas_powerplant_overrides_AT.csv``, whose every row
    carries the source and the evidence behind the value it sets, and applies
    the three actions:

    ``update``
        Overwrite the listed fields on the matched powerplantmatching row.
    ``add``
        Append a unit powerplantmatching does not carry.
    ``drop``
        Remove a row that does not belong in the natural gas fleet.

    Multi-unit sites are split into one row per unit so that
    ``add_existing_baseyear`` bins each unit into its own vintage instead of
    assigning the whole site the vintage of one of its units.

    Parameters
    ----------
    ppl
        Powerplants table as produced by ``build_powerplants``, with at least
        ``Name``, ``Country``, ``Fueltype``, ``Technology``, ``Capacity``,
        ``DateIn``, ``DateOut``, ``Set`` and ``bus`` columns.
    overrides_file
        Path to the curated override CSV.
    clustering
        Clustering identifier, either ``AT10`` (NUTS2) or ``AT35`` (NUTS3). At
        NUTS2 the NUTS3 bus of an added row is mapped up, mirroring
        :func:`build_biogas_plants_AT`.

    Returns
    -------
    A copy of ``ppl`` with the Austrian natural gas fleet corrected.

    Raises
    ------
    ValueError
        If the Austrian gas fleet is absent, if an override references a plant
        powerplantmatching does not carry or carries more than once, if an
        action is unknown, if a required field is empty, or if a technology is
        not one of :data:`GAS_TECHNOLOGIES`. Every case means the override file
        and the upstream dataset drifted apart.
    """
    overrides = pd.read_csv(overrides_file)

    is_at_gas = (ppl["Country"] == "AT") & (ppl["Fueltype"] == "Natural Gas")
    if not is_at_gas.any():
        raise ValueError(
            "No Austrian natural gas plants found in the powerplants table; "
            "cannot apply the gas overrides. Has powerplantmatching changed the "
            "Country or Fueltype spelling, or did powerplants_filter remove them?"
        )

    unknown = sorted(set(overrides["action"]) - set(GAS_OVERRIDE_ACTIONS))
    if unknown:
        raise ValueError(
            f"Unknown action(s) {unknown} in {overrides_file}; expected one of "
            f"{list(GAS_OVERRIDE_ACTIONS)}."
        )

    referenced = overrides.loc[overrides["ppm_name"].notna(), "ppm_name"]
    counts = ppl.loc[is_at_gas, "Name"].value_counts()
    for ppm_name in referenced:
        if counts.get(ppm_name, 0) != 1:
            raise ValueError(
                f"Gas override references powerplantmatching plant "
                f"{ppm_name!r}, which matches {counts.get(ppm_name, 0)} Austrian "
                "natural gas rows, expected exactly 1. The dataset renamed, "
                "split or dropped it; re-identify the plant before updating "
                "data/pypsa-at/gas_powerplant_overrides_AT.csv."
            )

    ppl = ppl.copy()
    if "autoproducer" not in ppl.columns:
        ppl["autoproducer"] = False

    before = ppl.loc[is_at_gas, "Capacity"].sum()
    added, updated, dropped = [], [], []

    for _, row in overrides.iterrows():
        action = row["action"]

        if action == "drop":
            match = ppl.index[is_at_gas & (ppl["Name"] == row["ppm_name"])]
            ppl = ppl.drop(index=match)
            is_at_gas = is_at_gas.drop(index=match)
            dropped.append(row["name"])
            continue

        if action == "update":
            idx = ppl.index[is_at_gas & (ppl["Name"] == row["ppm_name"])][0]
            for field, column in (
                ("name", "Name"),
                ("technology", "Technology"),
                ("capacity_mw_net", "Capacity"),
                ("date_in", "DateIn"),
                ("date_out", "DateOut"),
                ("set", "Set"),
                ("autoproducer", "autoproducer"),
            ):
                value = row.get(field)
                if pd.isna(value) or value == "":
                    continue
                ppl.loc[idx, column] = value
            updated.append(row["name"])
            continue

        _required(
            row, ("technology", "capacity_mw_net", "date_in", "bus", "set"), action
        )
        bus = row["bus"]
        if clustering.startswith("AT10"):
            bus = map_at_nuts3_to_nuts2(bus)
        ppl.loc[row["name"]] = pd.Series(
            {
                "Name": row["name"],
                "Country": "AT",
                "Fueltype": "Natural Gas",
                "Technology": row["technology"],
                "Set": row["set"],
                "Capacity": float(row["capacity_mw_net"]),
                "DateIn": float(row["date_in"]),
                "DateOut": row["date_out"] if pd.notna(row["date_out"]) else pd.NA,
                "bus": bus,
                "autoproducer": row.get("autoproducer", False),
            }
        )
        added.append(row["name"])

    is_at_gas = (ppl["Country"] == "AT") & (ppl["Fueltype"] == "Natural Gas")
    bad_tech = sorted(
        set(ppl.loc[is_at_gas, "Technology"].dropna()) - set(GAS_TECHNOLOGIES)
    )
    if bad_tech:
        raise ValueError(
            f"Austrian natural gas rows carry Technology {bad_tech}, but "
            f"add_existing_baseyear only keeps {list(GAS_TECHNOLOGIES)} and drops "
            "everything else, including 'CCGT, Thermal'. Set an explicit "
            "technology in data/pypsa-at/gas_powerplant_overrides_AT.csv."
        )

    after = ppl.loc[is_at_gas, "Capacity"].sum()
    logger.info(
        f"Applied Austrian gas overrides: {len(updated)} updated, {len(added)} "
        f"added, {len(dropped)} dropped. Fleet {before:,.1f} MW -> {after:,.1f} MW "
        f"({after - before:+,.1f} MW). Added: {added}. Dropped: {dropped}."
    )
    return ppl


def build_gas_deviations_at(
    ppl: pd.DataFrame,
    ppl_raw: pd.DataFrame,
    anlagenregister_file: str,
    postal_to_nuts_file: str,
) -> pd.DataFrame:
    """
    Compare the corrected fleet with powerplantmatching and the register.

    Builds the three-way deviation table per NUTS3 region: the raw
    powerplantmatching capacity, the corrected model capacity and the
    deduplicated E-Control Anlagenregister capacity. Regions whose model and
    register capacities differ by more than the looser of
    :data:`GAS_PLANT_TOLERANCE` and :data:`GAS_PLANT_TOLERANCE_MW` are logged
    as warnings.

    The comparison is per region rather than per plant because the register
    publishes no plant names, only postal codes.

    This is a diagnostic: the register keeps dormant registrations that no
    mechanical rule can separate from operating plants, so a deviation is
    information, not a failure.

    Parameters
    ----------
    ppl
        Corrected powerplants table.
    ppl_raw
        Powerplants table before the gas overrides.
    anlagenregister_file
        Plant-level Anlagenregister CSV.
    postal_to_nuts_file
        PLZ to NUTS3 mapping.

    Returns
    -------
    One row per NUTS3 region with Austrian gas capacity in any of the sources.
    """
    register = pd.read_csv(anlagenregister_file, dtype={"plz": str}, low_memory=False)
    register = deduplicate_gas_registrations(register)
    register = map_plants_to_nuts3(register, load_postal_to_nuts(postal_to_nuts_file))
    techcode = normalise_techcode(register["techcode"])
    register = register[(register["typ"] == "Strom") & techcode.isin(GAS_TECHCODES)]
    feedin = feedin_columns(register)

    per_region = register.groupby("nuts3").agg(
        capacity_mw_register=("engpassleistung_kw", lambda s: s.sum() / 1e3),
        plants_register=("engpassleistung_kw", "size"),
        feedin_gwh_register=(feedin[-1], lambda s: s.fillna(0).sum() / 1e6),
    )

    def _fleet(df: pd.DataFrame, column: str) -> pd.DataFrame:
        gas = df[(df["Country"] == "AT") & (df["Fueltype"] == "Natural Gas")]
        return gas.groupby("bus").agg(
            **{
                column: ("Capacity", "sum"),
                column.replace("capacity_mw", "plants"): ("Capacity", "size"),
            }
        )

    out = (
        _fleet(ppl_raw, "capacity_mw_ppm")
        .join(_fleet(ppl, "capacity_mw_model"), how="outer")
        .join(per_region, how="outer")
        .fillna(0.0)
    )
    out.index.name = "nuts3"
    out["delta_model_minus_register_mw"] = (
        out["capacity_mw_model"] - out["capacity_mw_register"]
    )
    out["delta_model_minus_register_pct"] = (
        100.0
        * out["delta_model_minus_register_mw"]
        / out["capacity_mw_register"].where(out["capacity_mw_register"] > 0)
    )

    flagged = out[
        (out["delta_model_minus_register_mw"].abs() > GAS_PLANT_TOLERANCE_MW)
        & (out["delta_model_minus_register_pct"].abs() > GAS_PLANT_TOLERANCE * 100)
    ]
    if not flagged.empty:
        logger.warning(
            f"{len(flagged)} NUTS3 region(s) deviate from the deduplicated "
            f"Anlagenregister by more than {GAS_PLANT_TOLERANCE:.0%} and "
            f"{GAS_PLANT_TOLERANCE_MW:.0f} MW:\n"
            + flagged[
                [
                    "capacity_mw_model",
                    "capacity_mw_register",
                    "delta_model_minus_register_mw",
                    "delta_model_minus_register_pct",
                ]
            ]
            .round(1)
            .to_string()
        )

    return out.round(3).reset_index()


def check_gas_calibration_at(
    ppl: pd.DataFrame,
    targets_file: str,
    base_year: int = GAS_CALIBRATION_BASE_YEAR,
) -> None:
    """
    Calibrate the Austrian gas fleet against the E-Control statistics.

    Two checks against ``data/pypsa-at/gas_calibration_targets_AT.csv``:

    Capacity, one-sided
        The modelled fleet must not exceed the Bestandsstatistik
        Brutto-Engpassleistung by more than :data:`GAS_NATIONAL_TOLERANCE`.
        A shortfall only warrants an entry in the log: industrial plants that
        never supply the public grid are out of scope by design, so the
        modelled fleet is expected to sit below the statistic.

    Full load hours, two-sided
        The Betriebsstatistik gross generation of the base year divided by the
        modelled fleet must fall inside :data:`GAS_FULL_LOAD_HOUR_BAND`. This
        is the check that a capacity error in either direction shows up in:
        too little capacity inflates the implied utilisation, too much
        deflates it.

    Only units operating in ``base_year`` are summed: a unit whose ``DateOut``
    precedes it, or whose ``DateIn`` follows it, is not in the statistic either.

    Capacities are summed gross, because the Bestandsstatistik publishes
    Brutto-Engpassleistung. Where a source gives only one figure the override
    file records it as both net and gross, which biases the modelled total
    slightly low; see ``docs-at/explanations/brownfield/gas-power-plants-AT.md``.

    Parameters
    ----------
    ppl
        Corrected powerplants table.
    targets_file
        Path to the E-Control calibration targets CSV.
    base_year
        Year to calibrate against.

    Raises
    ------
    ValueError
        If ``base_year`` is absent from the targets file, or if the implied
        full load hours fall outside :data:`GAS_FULL_LOAD_HOUR_BAND`.
    """
    targets = pd.read_csv(targets_file).set_index("year")
    if base_year not in targets.index:
        raise ValueError(
            f"Calibration base year {base_year} is not in {targets_file}; it "
            f"covers {targets.index.min()}-{targets.index.max()}."
        )
    target = targets.loc[base_year]

    is_at_gas = (ppl["Country"] == "AT") & (ppl["Fueltype"] == "Natural Gas")
    # The statistic counts the plants operating in the base year, so units that
    # retired before it or are commissioned after it must not be summed here.
    # add_existing_baseyear applies the same two cuts when it builds the fleet.
    operating = is_at_gas & ~(ppl["DateOut"] < base_year) & ~(ppl["DateIn"] > base_year)
    fleet_mw = ppl.loc[operating, "Capacity"].sum()
    retired = ppl.loc[is_at_gas & (ppl["DateOut"] < base_year)]
    if not retired.empty:
        logger.info(
            f"Excluded {len(retired)} retired Austrian gas unit(s) "
            f"({retired['Capacity'].sum():,.1f} MW) from the {base_year} "
            f"calibration: {sorted(retired['Name'])}."
        )

    deviation = (fleet_mw - target["capacity_mw_gross"]) / target["capacity_mw_gross"]
    message = (
        f"Austrian gas fleet {fleet_mw:,.1f} MW vs E-Control Bestandsstatistik "
        f"{target['capacity_mw_gross']:,.1f} MW ({base_year}): "
        f"{fleet_mw - target['capacity_mw_gross']:+,.1f} MW ({deviation:+.1%})."
    )
    if deviation > GAS_NATIONAL_TOLERANCE:
        logger.warning(
            f"{message} The fleet exceeds the national statistic by more than "
            f"{GAS_NATIONAL_TOLERANCE:.0%}, which the register cannot explain: "
            "check data/pypsa-at/gas_powerplant_overrides_AT.csv for a double "
            "count."
        )
    else:
        logger.info(message)

    full_load_hours = target["generation_gwh_gross"] * 1e3 / fleet_mw
    low, high = GAS_FULL_LOAD_HOUR_BAND
    if not low <= full_load_hours <= high:
        raise ValueError(
            f"Austrian gas fleet of {fleet_mw:,.1f} MW implies "
            f"{full_load_hours:,.0f} full load hours against the E-Control "
            f"{base_year} gross generation of "
            f"{target['generation_gwh_gross']:,.1f} GWh, outside the plausible "
            f"band {low:,.0f}-{high:,.0f} h. E-Control reports "
            f"{target['full_load_hours']:,.0f} h for the same year, so the "
            "modelled capacity is wrong by roughly "
            f"{abs(1 - full_load_hours / target['full_load_hours']):.0%}."
        )
    logger.info(
        f"Austrian gas fleet implies {full_load_hours:,.0f} full load hours in "
        f"{base_year} (E-Control: {target['full_load_hours']:,.0f} h, band "
        f"{low:,.0f}-{high:,.0f} h)."
    )


GAS_DEVIATION_COLUMNS = [
    "nuts3",
    "capacity_mw_ppm",
    "plants_ppm",
    "capacity_mw_model",
    "plants_model",
    "capacity_mw_register",
    "plants_register",
    "feedin_gwh_register",
    "delta_model_minus_register_mw",
    "delta_model_minus_register_pct",
]
"""Columns of the gas deviations table, also used for the empty table."""


def overwrite_powerplants() -> pd.DataFrame:
    """Patch the powerplants table."""
    _ppl = pd.read_csv(snakemake.input.powerplants, index_col=0)
    return overwrite_nuclear_dateout(_ppl, CH_NUCLEAR_DATEOUT)


def gas_powerplants_AT(ppl: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Calibrate the Austrian gas fleet, or pass the table through when disabled.

    Returns the corrected powerplants table and the three-way deviation table.
    The deviation table is written either way, so that the Snakemake DAG does
    not depend on the configuration.
    """
    if not snakemake.params.update_gas_capacities_AT:
        logger.info(
            "Skipping the Austrian gas brownfield calibration. config option "
            "mods: update_gas_capacities_AT: enable is false."
        )
        return ppl, pd.DataFrame(columns=GAS_DEVIATION_COLUMNS)

    corrected = apply_gas_overrides_at(
        ppl,
        overrides_file=snakemake.input.gas_overrides,
        clustering=snakemake.params.clustering,
    )
    check_gas_calibration_at(corrected, targets_file=snakemake.input.gas_targets)
    deviations = build_gas_deviations_at(
        corrected,
        ppl,
        anlagenregister_file=snakemake.input.anlagenregister,
        postal_to_nuts_file=snakemake.input.postal_to_nuts,
    )
    return corrected, deviations


def biogas_plants(ppl: pd.DataFrame) -> pd.DataFrame:
    """Prepare the Austrian biogas plants, or an empty table when disabled."""
    if not snakemake.params.add_biogas_to_power_plants_AT:
        logger.info(
            "Skipping Austrian biogas plant addition. config option add_biogas_to_power_plants_AT is false."
        )
        return pd.DataFrame(columns=BIOGAS_PLANT_COLUMNS)
    return build_biogas_plants_AT(
        ppl,
        anlagenregister_file=snakemake.input.anlagenregister,
        postal_to_nuts_file=snakemake.input.postal_to_nuts,
        threshold_capacity=snakemake.params.threshold_capacity,
        clustering=snakemake.params.clustering,
    )


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

    result = overwrite_powerplants()
    result, gas_deviations = gas_powerplants_AT(result)
    result.to_csv(snakemake.output.powerplants)
    gas_deviations.to_csv(snakemake.output.gas_deviations, index=False)
    biogas_plants(result).to_csv(snakemake.output.biogas_plants, index=False)
