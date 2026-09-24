# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for mods/network/biomass.py — Changes in biomass potentials, generation and usage."""

import pytest

# from mods.network.biomass import apply_ch_biomass_split


@pytest.mark.AT
def test_ch_solid_biomass_follows_share_schedule(nc):
    """
    Switzerland splits its solid biomass potential like every other country.

    Upstream ``build_biomass_potentials`` drops CH from the unsustainable
    calculation, because the Eurostat energy balances contain no CH rows, and as a
    consequence also exempts CH from the ``share_sustainable_potential_available``
    phase-in. :func:`mods.network.biomass.apply_ch_biomass_split` restores the split
    during ``modify_prenetwork``, so the solved networks must show both carriers in
    the proportion that the configured ``share_*`` schedules prescribe.

    The check is written as a ratio instead of absolute potentials, because the
    unscaled ENSPRESO base changes between planning horizons and the two shares do
    not necessarily add up to one.
    """
    for n in nc:
        year = n.meta["wildcards"]["planning_horizons"]
        biomass = n.meta["biomass"]
        share_sustainable = biomass["share_sustainable_potential_available"][year]
        share_unsustainable = biomass["share_unsustainable_use_retained"][year]

        generators = n.generators[n.generators.index.str.startswith("CH")]
        sustainable = generators.loc[
            generators.carrier == "solid biomass", "p_nom"
        ].sum()
        unsustainable = generators.loc[
            generators.carrier == "unsustainable solid biomass", "p_nom"
        ].sum()
        total = sustainable + unsustainable

        assert total > 0, f"CH has no solid biomass potential at all in {year}."

        assert (sustainable > 0) == (share_sustainable > 0), (
            f"CH sustainable solid biomass is {sustainable / 1e6:.3f} TWh/a in {year}, "
            f"but share_sustainable_potential_available is {share_sustainable}."
        )
        assert (unsustainable > 0) == (share_unsustainable > 0), (
            f"CH unsustainable solid biomass is {unsustainable / 1e6:.3f} TWh/a in "
            f"{year}, but share_unsustainable_use_retained is {share_unsustainable}."
        )

        expected = share_sustainable / (share_sustainable + share_unsustainable)
        assert sustainable / total == pytest.approx(expected), (
            f"CH sustainable share of solid biomass is {sustainable / total:.4f} in "
            f"{year}, expected {expected:.4f} from the configured schedules."
        )
