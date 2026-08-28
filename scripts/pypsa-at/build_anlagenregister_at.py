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

The aggregated file is the artefact that is uploaded to Zenodo (``archive``
source in ``data/versions.csv``).
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
