# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Snakemake script: restore ``Set == "PP"`` on the large German lignite units.

Why this rule is needed
-----------------------
``powerplantmatching`` 0.8.x tags the large German lignite condensing plants
``Set == "CHP"``; the 0.6.1 dataset tagged the same plants ``Set == "PP"``.

The inherited PyPSA-DE powerplant filter (``electricity: powerplants_filter``
in ``config/config.de.yaml``) discards every German CHP::

    (DateOut > 2025 or DateOut != DateOut)
    and not (Country == "DE" and Set == "CHP")
    and (DateIn < 2026 or DateIn != DateIn)

That clause is deliberate: German CHPs are supplied separately from the
Marktstammdatenregister by ``build_existing_chp_de``. Those MaStR rows are
keyed on ``KwkMastrNummer`` and carry only the CHP share of the electrical
capacity (``ElektrischeKwkLeistung``), so the lignite condensing blocks are
not among them.

Filter and dataset together therefore delete the entire German lignite fleet:
19,965 MW survives the filter on the 0.6.1 dataset, 0 MW survives it on 0.8.1.
This is why PyPSA-DE pinned ``powerplantmatching`` to 0.6.1.

Reverting the tag on the affected units *before* ``build_powerplants`` applies
the filter restores the 0.6.1 behaviour without patching the upstream filter
expression or the upstream script, and keeps the fix visible in one place.

Only units above ``MIN_CONDENSING_CAPACITY`` are patched. Every German lignite
unit that the 0.6.1 dataset already tagged ``CHP`` — Schkopau (904 MW) is the
largest, followed by Chemnitz Nord (154 MW), Cologne Merkenich (78 MW),
Cottbus (76 MW) and Sachtleben (28 MW) — stays ``CHP``. Those plants keep
arriving through the MaStR path, so the patch cannot double count them.

This script runs on the *retrieved* ``powerplants.csv``, i.e. before
``build_powerplants`` calls ``convert_country_to_alpha2()``. Country names are
therefore the long form (``"Germany"``), not ``"DE"``.

Delete this rule once ``powerplantmatching`` tags the condensing units ``PP``
again; ``restore_condensing_set`` fails loudly when that happens.
"""

import logging

import pandas as pd

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

DE_LIGNITE_CONDENSING = {
    "Neurath": 4211.0,
    "Niederaussem": 3109.0,
    "Janschwalde": 3000.0,
    "Boxberg": 2470.0,
    "Weissweiler": 1961.0,
    "Lippendorf": 1782.0,
    "Schwarze Pumpe": 1510.0,
}
"""German lignite condensing units mis-tagged ``CHP`` by powerplantmatching
0.8.x, with the capacity [MW] the 0.8.1 dataset reports for each."""

MIN_CONDENSING_CAPACITY = 1000.0
"""Capacity [MW] above which a German lignite unit is treated as condensing.

Chosen so that Schkopau (904 MW) stays below it: the 0.6.1 dataset already
tagged Schkopau ``CHP``, and it is supplied by ``build_existing_chp_de``.
"""

CAPACITY_TOLERANCE = 0.05
"""Relative capacity drift tolerated per unit before the rule fails."""


def restore_condensing_set(
    ppl: pd.DataFrame,
    expected: dict[str, float] | None = None,
    min_capacity: float = MIN_CONDENSING_CAPACITY,
    tolerance: float = CAPACITY_TOLERANCE,
) -> pd.DataFrame:
    """
    Set ``Set = "PP"`` on the large German lignite condensing units.

    Parameters
    ----------
    ppl
        Retrieved powerplantmatching table, with at least ``Name``, ``Country``,
        ``Fueltype``, ``Capacity`` and ``Set`` columns. ``Country`` holds long
        country names, as in the published ``powerplants.csv``.
    expected
        Mapping ``{Name: Capacity [MW]}`` of the units to patch. Defaults to
        :data:`DE_LIGNITE_CONDENSING`.
    min_capacity
        Capacity [MW] above which a German lignite unit must appear in
        ``expected``. Guards against a new large unit being missed silently.
    tolerance
        Relative capacity drift tolerated per unit.

    Returns
    -------
    A copy of ``ppl`` with ``Set`` set to ``"PP"`` on the matched rows.

    Raises
    ------
    ValueError
        If the German lignite fleet is absent, if an expected unit is missing
        or ambiguous, if its capacity drifted beyond ``tolerance``, if it is
        already tagged ``PP`` (upstream fixed the tagging — drop this rule), if
        it carries an unknown ``Set`` value, or if a large German lignite unit
        shows up that ``expected`` does not cover. Every case means the
        upstream dataset moved and the assumptions here need review.
    """
    if expected is None:
        expected = DE_LIGNITE_CONDENSING

    is_de_lignite = (ppl["Country"] == "Germany") & (ppl["Fueltype"] == "Lignite")
    if not is_de_lignite.any():
        raise ValueError(
            "No German lignite units found in the powerplantmatching table; "
            "cannot restore the condensing Set. Has the upstream dataset "
            "changed the Country or Fueltype spelling?"
        )

    fleet = ppl.loc[is_de_lignite]

    missing = sorted(set(expected) - set(fleet["Name"]))
    if missing:
        raise ValueError(
            f"Expected German lignite condensing unit(s) {missing} not found "
            f"among the German lignite units {sorted(fleet['Name'])}. The "
            "powerplantmatching dataset renamed or dropped them."
        )

    duplicated = sorted(
        fleet.loc[fleet["Name"].isin(expected), "Name"]
        .value_counts()
        .loc[lambda s: s > 1]
        .index
    )
    if duplicated:
        raise ValueError(
            f"German lignite condensing unit(s) {duplicated} matched more than "
            "one row. The powerplantmatching dataset split them; update "
            "DE_LIGNITE_CONDENSING."
        )

    unexpected = sorted(
        fleet.loc[
            (fleet["Capacity"] > min_capacity) & ~fleet["Name"].isin(expected), "Name"
        ]
    )
    if unexpected:
        raise ValueError(
            f"German lignite unit(s) {unexpected} exceed {min_capacity:.0f} MW "
            "but are not listed in DE_LIGNITE_CONDENSING. Decide whether they "
            "are condensing plants and extend the mapping, or raise "
            "MIN_CONDENSING_CAPACITY."
        )

    to_patch = fleet[fleet["Name"].isin(expected)]

    drifted = {
        name: (row["Capacity"], expected[name])
        for name, row in to_patch.set_index("Name").iterrows()
        if abs(row["Capacity"] - expected[name]) > tolerance * expected[name]
    }
    if drifted:
        raise ValueError(
            "Capacity drift beyond "
            f"{tolerance:.0%} on German lignite condensing unit(s): "
            + ", ".join(
                f"{name} is {found:,.0f} MW, expected {want:,.0f} MW"
                for name, (found, want) in sorted(drifted.items())
            )
            + ". Verify the units against the dataset and update "
            "DE_LIGNITE_CONDENSING."
        )

    unknown_set = sorted(set(to_patch["Set"].dropna()) - {"PP", "CHP"})
    if unknown_set:
        raise ValueError(
            f"Unknown Set value(s) {unknown_set} on German lignite condensing "
            "units; expected 'PP' or 'CHP'."
        )

    already_pp = sorted(to_patch.loc[to_patch["Set"] == "PP", "Name"])
    if already_pp:
        raise ValueError(
            f"German lignite condensing unit(s) {already_pp} are already tagged "
            "'PP'. powerplantmatching fixed the tagging upstream, so this rule "
            "is obsolete: drop patch_powerplants_set_at and build_powerplants_at."
        )

    ppl = ppl.copy()
    patched = is_de_lignite & ppl["Name"].isin(expected)
    ppl.loc[patched, "Set"] = "PP"

    logger.info(
        f"Restored Set='PP' on {patched.sum()} German lignite condensing units "
        f"({ppl.loc[patched, 'Capacity'].sum():,.0f} MW): "
        f"{sorted(ppl.loc[patched, 'Name'])}."
    )

    return ppl


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("patch_powerplants_set_at")

    configure_logging(snakemake)

    _ppl = pd.read_csv(snakemake.input.powerplants, index_col=0)
    restore_condensing_set(_ppl).to_csv(snakemake.output.powerplants)
