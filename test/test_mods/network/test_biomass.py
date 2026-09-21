# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for mods/network/biomass.py — Changes in biomass potentials, generation and usage."""

import pytest

# from mods.network.biomass import apply_ch_biomass_split


@pytest.mark.AT
def test_ch_solid_biomass_expected_sustainable(nc):
    """
    Before implementing the changes to account for Swiss un/sustainable biomass potentials,
    check if upstream has changed. CH must have only sustainable biomass share in all years.
    Unsustainable biomass potentials are not given in EuroStat dataset for CH, therefore
    fallback to only use sustainable biomass potentials.

    Upstream drops CH from the unsustainable calculation in
    ``scripts/build_biomass_potentials.py`` and, as a consequence, also exempts CH
    from the ``share_sustainable_potential_available`` phase-in. The exemption is
    visible in the years where that share is 0: every other country has no
    sustainable solid biomass left, while CH still carries its full ENSPRESO
    potential.
    """
    exempted_years = []

    for n in nc:
        year = n.meta["wildcards"]["planning_horizons"]
        shares = n.meta["biomass"]["share_sustainable_potential_available"]
        generators = n.generators[n.generators.index.str.startswith("CH")]

        sustainable = generators.loc[
            generators.carrier == "solid biomass", "p_nom"
        ].sum()
        unsustainable = generators.loc[
            generators.carrier == "unsustainable solid biomass", "p_nom"
        ].sum()

        assert unsustainable == 0, (
            f"CH has unsustainable solid biomass in {year}.  "
            "Upstream change of biomass data implementation likely, go check."
        )
        assert sustainable > 0, (
            f"CH has no solid biomass potential (sustainable or unsustainable) at all in {year}."
        )

        if shares[year] == 0:
            exempted_years.append(year)

    assert exempted_years, (
        "No planning horizon with share_sustainable_potential_available == 0, so the "
        "upstream exemption of CH cannot be observed in this run."
    )
