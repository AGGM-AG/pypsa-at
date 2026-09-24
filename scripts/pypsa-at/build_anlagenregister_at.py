# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Aggregate the plant-level Anlagenregister CSV to NUTS3 regions.

Plants are mapped from postal code (PLZ) to NUTS3 via
``data/pypsa-at/AT-Postal-to-NUTS.csv`` and aggregated per
``typ`` (Strom/Gas), ``nuts3``, ``technology`` and ``first_feedin_year``.

The Anlagenregister does not publish commissioning dates (``inbetriebnahme``
is empty). As a proxy for the build year, ``first_feedin_year`` is the first
year with reported feed-in > 0 within the published window (six years). It is
only meaningful for plants commissioned inside that window; plants with feed-in
in the earliest published year are older and get ``first_feedin_year`` set to
that year (lower bound). Plants without any feed-in get ``NA``.

This aggregation runs for both dataset sources: with ``build`` the plant-level
CSV is scraped from the website, with ``archive`` it is the CC-BY-4.0 mirror
retrieved from Zenodo (``data/versions.csv``).
"""

import logging

import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

GROUP_COLUMNS = ["typ", "nuts3", "technology", "first_feedin_year"]

# Unit of ``Engpassleistung`` per Anlagentyp. Strom is electrical output; the
# Anlagenregister does not state the heating value basis for gas injection
# capacity. Austrian gas market rules account energy on a gross calorific
# (Brennwert, HHV) basis, hence MW_HHV. Confirm with E-Control if in doubt.
CAPACITY_UNIT = {"Strom": "MW_el", "Gas": "MW_HHV"}

# Tolerated share of total capacity without a valid postal code (typos).
MAX_UNMAPPED_CAPACITY_SHARE = 1e-3

GAS_TECHCODES = frozenset(
    {
        "Erdgas",
        "Fossil - Natural gas",
        "Fossil - Natural Gas - Gas turbine with heat recovery - Unspecified",
        "Fossil - Natural gas liquids",
        "Gaseous - Gas turbine with heat recovery - Unspecified",
        "Natural Gas - Unspecified - Steam turbine with back-pressure turbine",
        "Thermal - Fossil - Natural gas - unspecified (CHP)",
        "Thermal - Gaseous - unspecified",
    }
)
"""Register ``techcode`` values denoting natural gas, across both taxonomies.

The register mixes a legacy German taxonomy (``Erdgas``) with the newer EECS
English one (``Fossil - Natural gas`` and the ``Thermal - ...`` variants). The
same physical plant can appear under both, which is what
:func:`deduplicate_gas_registrations` removes. Biogenic and non-gas fossil
gases (``Biogas``, ``Deponiegas``, ``Klärgas``, ``Fossil - Oil - gas/diesel``)
are deliberately excluded.

Compare ``techcode`` only after :func:`normalise_techcode`: several register
values carry trailing whitespace.
"""

NON_THERMAL_TECHCODES = frozenset(
    {
        "Batteriespeicher",
        "Energiespeicher - Ausspeisung netzgeladene Batteriespeicher",
        "Energiespeicher/Elektrochemisch - Ausspeisung netzgeladene Batteriespeicher",
        "Energiespeicher/Elektrochemisch - Sonstige (Einspeisung in Batterie)",
        "Geothermie",
        "Hydro power Mixed pumped storage head",
        "Hydro power Pure pumped storage head installation",
        "Hydro power Run-of-river head installation",
        "Hydro power Storage head installation",
        "Kleinwasserkraft bis 10 MW",
        "Photovoltaik",
        "Solar Photovoltaic - Classic silicon",
        "Solar Thermal",
        "Solar Unspecified",
        "Tidal Energy Onshore",
        "Unspecified Renewable Energy",
        "Wasserkraft > 10 MW",
        "Wind Turbine Unspecified",
        "Windenergie",
    }
)
"""Register ``techcode`` values that burn no fuel.

A site that registers one capacity under several *combustion* fuels is a
multi-fuel registration of one plant. A gas plant that happens to share a
postal code and a capacity with a hydro or wind plant is a coincidence, and
collapsing the two would delete a real plant. Presence of any of these codes
in a capacity group therefore disables
:func:`drop_shared_capacity_gas_registrations` for that group.

Two real collisions motivate the guard: Salzburg (PLZ 5020) has a 13.7 MW gas
plant and a 13.7 MW ``Wasserkraft > 10 MW`` plant, both feeding in; Gratkorn
(PLZ 8101) has a ``Hydro power Run-of-river head installation`` row inside its
140 MW group.
"""

GAS_DEDUP_MIN_KW = 1_000.0
"""Capacity [kW] above which gas registrations are deduplicated.

The duplication artefact is confined to the large registrations that were
migrated between taxonomies. Below 1 MW the register holds thousands of small
CHP units where equal capacities at one postal code are common and genuine.
"""

GAS_DEDUP_KEEP = (("1110", 278_000.0),)
"""``(plz, engpassleistung_kw)`` groups of equal gas capacities to keep intact.

Simmering (PLZ 1110) registers two separate ~278 MW units, each reporting its
own feed-in over the published window (2 329.3 GWh and 2 305.4 GWh), so the
pair is a real double unit rather than a double registration.

Every entry must match a group, otherwise :func:`drop_duplicate_gas_registrations`
raises: a register revision must not silently disable an exemption.
"""

GAS_DEDUP_KEEP_TOLERANCE_KW = 1.0
"""Capacity [kW] tolerance when matching :data:`GAS_DEDUP_KEEP` and
:data:`GAS_DEDUP_DROP` entries."""

GAS_DEDUP_DROP = (
    {
        "typ": "Strom",
        "bundesland": "ST",
        "id": 44405,
        "plz": "8402",
        "engpassleistung_kw": 430_000.0,
    },
    {
        "typ": "Strom",
        "bundesland": "ST",
        "id": 65332,
        "plz": "8402",
        "engpassleistung_kw": 246_000.0,
    },
)
"""Register rows to drop as cross-postal-code duplicates.

Each entry names the row by ``(typ, bundesland, id)`` and pins its ``plz`` and
``engpassleistung_kw``. The register ``id`` is a scrape row number that
restarts per ``typ`` and Bundesland query and shifts whenever a registration
is added or removed, so a re-scrape can move it onto an unrelated plant; the
pinned fields make :func:`drop_curated_gas_registrations` fail loudly in that
case instead of dropping the wrong row.

Unlike the rule-based passes this list is not restricted to natural gas rows:
the second entry is a hard coal registration.

GDK Mellach and the Fernheizkraftwerk Mellach sit on one site that the Mur
splits between two postal codes -- Verbund's environmental statement calls it
"ein Doppelstandort, welcher räumlich lediglich durch den Fluss Mur getrennt
ist". Both plants are registered under PLZ 8410 (Wildon, NUTS3 AT225) *and*
under PLZ 8402 (Werndorf, NUTS3 AT221):

``ST-44405``
    430.000 MW "Fossil - Natural gas" at PLZ 8402, a second registration of
    GDK Mellach, which appears at PLZ 8410 as ``ST-32020`` (832.000 MW).
``ST-65332``
    246.000 MW "Steinkohle - Hard coal unspecified" at PLZ 8402, a second
    registration of the Fernheizkraftwerk, which appears at PLZ 8410 as
    ``ST-44404`` (246.000 MW, same techcode).

Keeping both sides would add 676 MW of phantom capacity and split the site
across two NUTS3 regions. The PLZ 8410 rows are kept because that is where
:data:`~scripts.pypsa-at.overwrite_powerplants.GAS_OVERRIDES_AT` locates the
site.
"""


def load_postal_to_nuts(path: str) -> pd.Series:
    """
    Load the PLZ -> NUTS3 mapping.

    Parameters
    ----------
    path
        CSV with columns ``NUTS3`` and ``CODE`` (postal code).

    Returns
    -------
    Series indexed by 4-digit postal code string with NUTS3 values.
    """
    df = pd.read_csv(path, dtype=str, names=["nuts3", "plz"], header=0)
    df["plz"] = df["plz"].str.zfill(4)
    return df.drop_duplicates("plz").set_index("plz")["nuts3"]


def feedin_columns(df: pd.DataFrame) -> list[str]:
    """Return the ``feedin_kwh_{year}`` columns sorted ascending by year."""
    return sorted(c for c in df.columns if c.startswith("feedin_kwh_"))


def add_first_feedin_year(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add ``first_feedin_year``: earliest year with feed-in > 0 (build-year proxy).

    Parameters
    ----------
    df
        Plant table with ``feedin_kwh_{year}`` columns.

    Returns
    -------
    Copy of ``df`` with an ``Int64`` column ``first_feedin_year``
    (``<NA>`` if a plant never reported feed-in).
    """
    cols = feedin_columns(df)
    years = [int(c.rsplit("_", 1)[1]) for c in cols]
    positive = df[cols].fillna(0).gt(0).to_numpy()
    # first True per row; rows without any True get NA
    has_any = positive.any(axis=1)
    first_idx = positive.argmax(axis=1)
    first_year = pd.array(
        [years[i] if ok else pd.NA for i, ok in zip(first_idx, has_any)],
        dtype="Int64",
    )
    out = df.copy()
    out["first_feedin_year"] = first_year
    return out


def clean_plz(plz: pd.Series) -> pd.Series:
    """
    Extract the 4-digit Austrian postal code from free-text register entries.

    The register contains entries like ``"4600 "``, ``"6933,"``, ``"5431 Kuchl"``,
    ``"23253"`` or plain town names. The first run of exactly four digits is
    taken; anything else becomes ``NaN``.
    """
    return plz.fillna("").astype(str).str.extract(r"(?<!\d)(\d{4})(?!\d)")[0]


def normalise_techcode(techcode: pd.Series) -> pd.Series:
    """
    Strip whitespace from ``techcode`` so it can be compared to the constants.

    Several register values carry trailing spaces, for example
    ``"Thermal - Fossil - Natural gas - unspecified (CHP) "``.
    """
    return techcode.fillna("").astype(str).str.strip()


def _total_feedin(df: pd.DataFrame) -> pd.Series:
    """Total reported feed-in [kWh] per row over the published window."""
    cols = feedin_columns(df)
    if not cols:
        return pd.Series(0.0, index=df.index)
    return df[cols].fillna(0).sum(axis=1)


def _dedup_order(df: pd.DataFrame) -> pd.DataFrame:
    """
    Order rows so that the row to keep within a group comes first.

    Sorted by total feed-in descending, then by the register key
    ``(bundesland, id)`` ascending. The key only breaks exact feed-in ties --
    common among dormant registrations that never reported -- and makes the
    choice deterministic across runs and platforms. A tie leaves the *fuel*
    attribution arbitrary but the *capacity* correct, which is what this
    deduplication is for.
    """
    out = df.copy()
    out["_feedin"] = _total_feedin(out)
    return out.sort_values(
        ["_feedin", "bundesland", "id"], ascending=[False, True, True]
    ).drop(columns="_feedin")


def drop_duplicate_gas_registrations(
    df: pd.DataFrame,
    keep: tuple[tuple[str, float], ...] = GAS_DEDUP_KEEP,
    min_kw: float = GAS_DEDUP_MIN_KW,
    tolerance_kw: float = GAS_DEDUP_KEEP_TOLERANCE_KW,
) -> pd.DataFrame:
    """
    Collapse gas plants registered more than once under the same capacity.

    Rows are grouped on ``(plz, engpassleistung_kw)`` with the postal code
    passed through :func:`clean_plz`, since the register spells it freely.
    Where a group holds more than one natural gas row, only the row with the
    highest total feed-in is kept; see :func:`_dedup_order` for the tie-break.
    Groups listed in ``keep`` are left intact.

    Parameters
    ----------
    df
        Plant table with ``typ``, ``plz``, ``techcode``, ``bundesland``, ``id``,
        ``engpassleistung_kw`` and ``feedin_kwh_{year}`` columns.
    keep
        ``(plz, engpassleistung_kw)`` groups that hold genuinely separate units.
    min_kw
        Only registrations at or above this capacity are deduplicated.
    tolerance_kw
        Capacity tolerance when matching ``keep`` entries.

    Returns
    -------
    ``df`` without the superseded duplicate gas rows.

    Raises
    ------
    ValueError
        If an entry of ``keep`` matches no group. The register moved and the
        exemption needs review rather than silent deactivation.
    """
    tech = normalise_techcode(df["techcode"])
    is_gas = (df["typ"] == "Strom") & tech.isin(GAS_TECHCODES)
    candidates = df[is_gas & (df["engpassleistung_kw"] >= min_kw)].assign(
        plz=lambda d: clean_plz(d["plz"])
    )

    groups = candidates.groupby(["plz", "engpassleistung_kw"], dropna=False)
    duplicated = {key: idx for key, idx in groups.groups.items() if len(idx) > 1}

    exempt = set()
    for plz, kw in keep:
        matched = [
            key
            for key in duplicated
            if key[0] == plz and abs(key[1] - kw) <= tolerance_kw
        ]
        if not matched:
            raise ValueError(
                f"GAS_DEDUP_KEEP entry (plz={plz!r}, {kw / 1e3:.3f} MW) matches no "
                "duplicated gas registration. The Anlagenregister changed: verify "
                "whether the units were merged, re-rated or renumbered, then "
                "update GAS_DEDUP_KEEP."
            )
        exempt.update(matched)

    to_drop = []
    for key, idx in duplicated.items():
        if key in exempt:
            continue
        ordered = _dedup_order(df.loc[idx])
        to_drop.extend(ordered.index[1:])

    if to_drop:
        dropped = df.loc[to_drop]
        logger.info(
            f"Dropped {len(to_drop)} duplicate gas registrations "
            f"({dropped['engpassleistung_kw'].sum() / 1e3:,.1f} MW) at postal codes "
            f"{sorted(dropped['plz'].unique())}."
        )
    return df.drop(index=to_drop)


def drop_shared_capacity_gas_registrations(
    df: pd.DataFrame,
    min_kw: float = GAS_DEDUP_MIN_KW,
) -> pd.DataFrame:
    """
    Drop gas rows whose capacity is really another fuel's, by realised feed-in.

    A multi-fuel plant is registered once per fuel, each time at the *plant*
    capacity, so summing the register over fuels multiplies one plant's
    capacity. Where a ``(plz, engpassleistung_kw)`` group (postal code via
    :func:`clean_plz`) mixes natural gas with other combustion fuels, the fuel
    with the highest realised feed-in
    over the published window is taken as the primary one; if that is not gas,
    the gas rows are dropped.

    Only gas rows are ever removed, so the register totals of every other fuel
    are untouched and the same treatment can be extended to them later
    (pypsa-at-planning#323).

    Groups containing a non-combustion technology are skipped entirely --- see
    :data:`NON_THERMAL_TECHCODES`.

    A tie leaves the gas rows in place: equal feed-in, and in particular a
    group in which nothing ever fed in, is no evidence that the capacity
    belongs to another fuel.

    Parameters
    ----------
    df
        Plant table, as for :func:`drop_duplicate_gas_registrations`.
    min_kw
        Only registrations at or above this capacity are considered.

    Returns
    -------
    ``df`` without the gas rows that another fuel outproduced.
    """
    strom = df[(df["typ"] == "Strom") & (df["engpassleistung_kw"] >= min_kw)].assign(
        plz=lambda d: clean_plz(d["plz"])
    )
    tech = normalise_techcode(strom["techcode"])
    is_gas = tech.isin(GAS_TECHCODES)
    is_non_thermal = tech.isin(NON_THERMAL_TECHCODES)
    feedin = _total_feedin(strom)

    to_drop = []
    for _, idx in strom.groupby(
        ["plz", "engpassleistung_kw"], dropna=False
    ).groups.items():
        gas = [i for i in idx if is_gas[i]]
        if not gas or len(idx) == len(gas):
            continue
        if any(is_non_thermal[i] for i in idx):
            continue
        other = [i for i in idx if i not in gas]
        if feedin[other].max() > feedin[gas].max():
            to_drop.extend(gas)

    if to_drop:
        dropped = df.loc[to_drop]
        logger.info(
            f"Dropped {len(to_drop)} gas registrations "
            f"({dropped['engpassleistung_kw'].sum() / 1e3:,.1f} MW) whose capacity "
            f"another fuel outproduced at postal codes "
            f"{sorted(dropped['plz'].unique())}."
        )
    return df.drop(index=to_drop)


def drop_curated_gas_registrations(
    df: pd.DataFrame,
    drops: tuple[dict, ...] = GAS_DEDUP_DROP,
    tolerance_kw: float = GAS_DEDUP_KEEP_TOLERANCE_KW,
) -> pd.DataFrame:
    """
    Drop the registrations that no rule on ``(plz, capacity)`` can reach.

    These are plants registered under two postal codes, so they share neither
    a postal code nor, necessarily, a capacity. Each entry is identified by the
    register key ``(typ, bundesland, id)`` and verified against its pinned
    ``plz`` and ``engpassleistung_kw``; see :data:`GAS_DEDUP_DROP` for the
    evidence behind each one. This pass is not restricted to natural gas rows.

    Parameters
    ----------
    df
        Plant table with ``typ``, ``bundesland``, ``id``, ``plz`` and
        ``engpassleistung_kw`` columns.
    drops
        Entries as in :data:`GAS_DEDUP_DROP`.
    tolerance_kw
        Capacity tolerance when verifying ``engpassleistung_kw``.

    Returns
    -------
    ``df`` without the curated rows.

    Raises
    ------
    ValueError
        If an entry matches no row or more than one row, or if the matched row
        does not carry the pinned postal code and capacity.
    """
    plz = clean_plz(df["plz"])
    to_drop = []
    for entry in drops:
        label = f"{entry['bundesland']}-{entry['id']}"
        matched = df.index[
            (df["typ"] == entry["typ"])
            & (df["bundesland"].astype(str) == entry["bundesland"])
            & (df["id"] == entry["id"])
        ]
        if len(matched) != 1:
            raise ValueError(
                f"GAS_DEDUP_DROP entry {label} matched {len(matched)} rows, "
                "expected exactly 1. The Anlagenregister renumbered or removed "
                "it; re-identify the duplicate before updating GAS_DEDUP_DROP."
            )
        idx = matched[0]
        kw = df.at[idx, "engpassleistung_kw"]
        if (
            plz[idx] != entry["plz"]
            or abs(kw - entry["engpassleistung_kw"]) > tolerance_kw
        ):
            raise ValueError(
                f"GAS_DEDUP_DROP entry {label} now points at a {kw / 1e3:.3f} MW "
                f"row at PLZ {plz[idx]!r}, expected "
                f"{entry['engpassleistung_kw'] / 1e3:.3f} MW at PLZ "
                f"{entry['plz']!r}. The register id is a scrape row number that "
                "a re-scrape renumbers; re-identify the duplicate before "
                "updating GAS_DEDUP_DROP."
            )
        to_drop.append(idx)

    if to_drop:
        dropped = df.loc[to_drop]
        logger.info(
            f"Dropped {len(to_drop)} curated cross-postal-code duplicates "
            f"({dropped['engpassleistung_kw'].sum() / 1e3:,.1f} MW): "
            f"{sorted(dropped['bundesland'] + '-' + dropped['id'].astype(str))}."
        )
    return df.drop(index=to_drop)


def deduplicate_gas_registrations(
    df: pd.DataFrame,
    keep: tuple[tuple[str, float], ...] = GAS_DEDUP_KEEP,
    drops: tuple[dict, ...] = GAS_DEDUP_DROP,
) -> pd.DataFrame:
    """
    Remove the natural gas double counting from the plant-level register.

    Applies, in order, :func:`drop_curated_gas_registrations`,
    :func:`drop_duplicate_gas_registrations` and
    :func:`drop_shared_capacity_gas_registrations`. The curated drops come
    first so that a cross-postal-code duplicate cannot win a feed-in
    comparison against the row that supersedes it.

    The two rule-based passes only ever remove natural gas rows, so every
    other fuel's register total is untouched; see pypsa-at-planning#323 for
    the remaining fuels. The curated pass is fuel-agnostic and currently also
    drops the second registration of the coal-fired Fernheizkraftwerk Mellach.
    The before/after log line reports the natural gas total only.

    Parameters
    ----------
    df
        Plant-level Anlagenregister table.
    keep
        Passed to :func:`drop_duplicate_gas_registrations`.
    drops
        Passed to :func:`drop_curated_gas_registrations`.

    Returns
    -------
    ``df`` without the duplicate gas registrations.
    """
    tech = normalise_techcode(df["techcode"])
    before = df.loc[
        (df["typ"] == "Strom") & tech.isin(GAS_TECHCODES), "engpassleistung_kw"
    ].sum()

    df = drop_curated_gas_registrations(df, drops=drops)
    df = drop_duplicate_gas_registrations(df, keep=keep)
    df = drop_shared_capacity_gas_registrations(df)

    tech = normalise_techcode(df["techcode"])
    after = df.loc[
        (df["typ"] == "Strom") & tech.isin(GAS_TECHCODES), "engpassleistung_kw"
    ].sum()
    logger.info(
        f"Gas deduplication: {before / 1e3:,.1f} MW -> {after / 1e3:,.1f} MW "
        f"({(after - before) / 1e3:+,.1f} MW)."
    )
    return df


def map_plants_to_nuts3(
    df: pd.DataFrame,
    postal_to_nuts: pd.Series,
    max_unmapped_share: float = MAX_UNMAPPED_CAPACITY_SHARE,
) -> pd.DataFrame:
    """
    Attach a ``nuts3`` column via postal code and drop unmappable plants.

    Parameters
    ----------
    df
        Plant table with ``plz`` and ``engpassleistung_kw`` columns.
    postal_to_nuts
        PLZ -> NUTS3 mapping from ``load_postal_to_nuts``.
    max_unmapped_share
        Tolerated share of total capacity without a valid postal code. The
        register has a few hundred plants with typos (~0.01 % of capacity);
        those are dropped with a warning.

    Raises
    ------
    ValueError
        If the unmapped capacity exceeds ``max_unmapped_share``, which
        indicates a broken mapping file or changed source data rather than
        a handful of typos.
    """
    out = df.copy()
    out["plz"] = clean_plz(out["plz"])
    out["nuts3"] = out["plz"].map(postal_to_nuts)

    unmapped = out["nuts3"].isna()
    total_kw = out["engpassleistung_kw"].sum()
    unmapped_kw = out.loc[unmapped, "engpassleistung_kw"].sum()
    share = unmapped_kw / total_kw if total_kw else 0.0
    if share > max_unmapped_share:
        missing = out.loc[unmapped, "plz"].dropna().unique()
        raise ValueError(
            f"{unmapped.sum()} plants ({unmapped_kw / 1e3:.1f} MW, {share:.2%} of "
            f"capacity) have no NUTS3 mapping; postal codes {sorted(missing)} are "
            "missing in the postal-to-nuts file. Update mapping or check data."
        )
    if unmapped.any():
        logger.warning(
            f"Dropped {unmapped.sum()} plants ({unmapped_kw / 1e3:.1f} MW, "
            f"{share:.3%} of capacity) with invalid or unmapped postal codes."
        )
    return out[~unmapped]


def aggregate_to_nuts3(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate plants to ``GROUP_COLUMNS``.

    Parameters
    ----------
    df
        Plant table with ``nuts3``, ``first_feedin_year``, ``techcode``,
        ``energietraeger``, ``engpassleistung_kw`` and ``feedin_kwh_*`` columns.

    Returns
    -------
    Table with ``n_plants``, ``capacity_mw``, ``capacity_unit`` and
    ``feedin_gwh_{year}`` per group. ``technology`` is ``techcode`` for Strom
    and ``energietraeger`` for Gas; ``capacity_unit`` is ``CAPACITY_UNIT[typ]``.
    """
    out = df.copy()
    out["technology"] = (
        out["techcode"]
        .where(out["typ"] == "Strom", out["energietraeger"])
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "unknown")
    )
    out["first_feedin_year"] = out["first_feedin_year"].astype("Int64")

    cols = feedin_columns(out)
    agg = (
        out.groupby(GROUP_COLUMNS, dropna=False)
        .agg(
            n_plants=("engpassleistung_kw", "size"),
            capacity_mw=("engpassleistung_kw", "sum"),
            **{c: (c, "sum") for c in cols},
        )
        .reset_index()
    )
    agg["capacity_mw"] = agg["capacity_mw"] / 1e3
    agg.insert(
        agg.columns.get_loc("capacity_mw") + 1,
        "capacity_unit",
        agg["typ"].map(CAPACITY_UNIT),
    )
    for c in cols:
        agg[c.replace("feedin_kwh_", "feedin_gwh_")] = agg.pop(c) / 1e6
    return agg


def main(snakemake: Snakemake) -> None:
    """Build the NUTS3-aggregated Anlagenregister CSV."""
    plants = pd.read_csv(snakemake.input.plants, dtype={"plz": str}, low_memory=False)
    postal_to_nuts = load_postal_to_nuts(snakemake.input.postal_to_nuts)

    plants = deduplicate_gas_registrations(plants)
    plants = map_plants_to_nuts3(plants, postal_to_nuts)
    plants = add_first_feedin_year(plants)
    agg = aggregate_to_nuts3(plants)
    agg.insert(0, "reference_year", plants["reference_year"].iloc[0])

    agg.to_csv(snakemake.output.nuts3, index=False)
    logger.info(
        f"Aggregated {len(plants)} plants ({agg['capacity_mw'].sum() / 1e3:.2f} GW) "
        f"into {len(agg)} NUTS3 groups -> {snakemake.output.nuts3}"
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("build_anlagenregister_at")

    configure_logging(snakemake)
    main(snakemake)
