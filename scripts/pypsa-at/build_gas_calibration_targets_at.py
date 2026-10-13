# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Build the E-Control calibration targets for the Austrian gas power plant fleet.

Reads the natural gas ("Erdgas und Derivate") year series from two E-Control
workbooks registered in ``data/versions.csv``:

- Bestandsstatistik ``BeStGes-JR_KWEPL.xlsx``, sheet ``Leistung``: gross
  bottleneck capacity (Brutto-Engpassleistung) in MW.
- Betriebsstatistik ``BStGes-JR1_Bilanz.xlsx``, sheet ``Erz``: gross
  generation (Brutto-Stromerzeugung) in GWh.

and writes one row per year with both figures and the implied full load hours.
``overwrite_powerplants_at`` checks the corrected gas fleet against them.
"""

import logging

import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

GAS_COLUMN = "Erdgas und Derivate"
"""Header of the natural gas column in both E-Control sheets."""

CAPACITY_SHEET = "Leistung"
GENERATION_SHEET = "Erz"


def _normalise(value) -> str:
    """Collapse the line breaks and repeated spaces E-Control headers carry."""
    return " ".join(str(value).split())


def read_econtrol_series(path: str, sheet: str, unit: str) -> pd.Series:
    """
    Read the natural gas year series from an E-Control year-series sheet.

    The column is located by its header text and the unit printed below it, so
    a reordered or extended sheet still parses and a renamed column fails.

    Parameters
    ----------
    path
        Path to the E-Control workbook.
    sheet
        Sheet name.
    unit
        Unit the sheet prints below the header, ``MW`` or ``GWh``.

    Returns
    -------
    :
        Values indexed by year. Years E-Control marks with ``-`` are dropped.

    Raises
    ------
    ValueError
        If the sheet does not carry exactly one :data:`GAS_COLUMN` header, or
        if the unit below it is not ``unit``.
    """
    raw = pd.read_excel(path, sheet_name=sheet, header=None)
    cells = raw.map(_normalise)
    hits = list(zip(*(cells == GAS_COLUMN).to_numpy().nonzero()))
    if len(hits) != 1:
        raise ValueError(
            f"Expected exactly one {GAS_COLUMN!r} header in sheet {sheet!r} of "
            f"{path}, found {len(hits)}. Has E-Control changed the layout?"
        )
    row, col = hits[0]
    if cells.iat[row + 1, col] != unit:
        raise ValueError(
            f"Expected unit {unit!r} below {GAS_COLUMN!r} in sheet {sheet!r} of "
            f"{path}, found {cells.iat[row + 1, col]!r}."
        )

    years = pd.to_numeric(raw.iloc[row + 2 :, 0], errors="coerce")
    values = pd.to_numeric(raw.iloc[row + 2 :, col], errors="coerce")
    series = values[years.notna()].set_axis(years.dropna().astype(int))
    return series.dropna()


def build_gas_calibration_targets(
    capacity_file: str, generation_file: str
) -> pd.DataFrame:
    """
    Combine the E-Control capacity and generation series for natural gas.

    Parameters
    ----------
    capacity_file
        Bestandsstatistik year series ``BeStGes-JR_KWEPL.xlsx``.
    generation_file
        Betriebsstatistik year series ``BStGes-JR1_Bilanz.xlsx``.

    Returns
    -------
    :
        One row per year both series cover, with ``year``,
        ``capacity_mw_gross``, ``generation_gwh_gross`` and
        ``full_load_hours``.
    """
    targets = pd.concat(
        {
            "capacity_mw_gross": read_econtrol_series(
                capacity_file, CAPACITY_SHEET, "MW"
            ),
            "generation_gwh_gross": read_econtrol_series(
                generation_file, GENERATION_SHEET, "GWh"
            ),
        },
        axis=1,
        join="inner",
    )
    targets = targets[targets["capacity_mw_gross"] > 0].round(3)
    targets["full_load_hours"] = (
        targets["generation_gwh_gross"] * 1e3 / targets["capacity_mw_gross"]
    ).round(1)
    targets.index.name = "year"
    return targets.reset_index()


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake: Snakemake = mock_snakemake("build_gas_calibration_targets_at")

    configure_logging(snakemake)

    targets = build_gas_calibration_targets(
        snakemake.input.bestandsstatistik, snakemake.input.betriebsstatistik
    )
    targets.to_csv(snakemake.output.targets, index=False)
    logger.info(
        f"Wrote Austrian gas calibration targets for {targets['year'].min()}-"
        f"{targets['year'].max()} to {snakemake.output.targets}."
    )
