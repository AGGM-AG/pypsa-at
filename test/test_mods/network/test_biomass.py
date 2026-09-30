# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for mods/network/biomass.py — Changes in biomass potentials, generation and usage."""

from types import SimpleNamespace

import pypsa
import pytest

from mods.network.biomass import (
    apply_ch_biomass_split,
    assert_upstream_ch_exemption,
    split_ch_solid_biomass,
)


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


BASE = 10e6  # MWh/a, unscaled CH ENSPRESO solid biomass potential
AT_UNSUSTAINABLE = 5e6  # MWh/a, must stay untouched by the CH correction


def build_network(ch_unsustainable: float = 0.0, ch: bool = True) -> pypsa.Network:
    """
    Build the biomass generators the way ``prepare_sector_network`` leaves them.

    Parameters
    ----------
    ch_unsustainable
        Potential on the CH unsustainable generator. Upstream leaves this at 0,
        so a positive value stands for an upstream change.
    ch
        Whether to add Swiss generators at all.

    Returns
    -------
    :
        Network with one Austrian and, optionally, one Swiss biomass node.
    """
    n = pypsa.Network()
    nodes = ["AT", "CH"] if ch else ["AT"]

    for node in nodes:
        n.add("Bus", f"{node} solid biomass", carrier="solid biomass")
        n.add(
            "Generator",
            f"{node} solid biomass",
            bus=f"{node} solid biomass",
            carrier="solid biomass",
            p_nom=BASE if node == "CH" else 20e6,
            e_sum_min=0,
            e_sum_max=BASE if node == "CH" else 20e6,
        )

    potentials = {"AT": AT_UNSUSTAINABLE, "CH": ch_unsustainable}
    for node in nodes:
        n.add(
            "Generator",
            f"{node} unsustainable solid biomass",
            bus=f"{node} solid biomass",
            carrier="unsustainable solid biomass",
            p_nom=potentials[node],
            e_sum_min=potentials[node],
            e_sum_max=potentials[node],
        )

    return n


class TestAssertUpstreamChExemption:
    """Guard against an upstream change that would double count the potential."""

    def test_passes_while_ch_has_no_unsustainable_potential(self):
        assert_upstream_ch_exemption(build_network())

    def test_raises_once_upstream_provides_a_ch_potential(self):
        with pytest.raises(ValueError, match="Expected no unsustainable solid biomass"):
            assert_upstream_ch_exemption(build_network(ch_unsustainable=1.0))

    def test_ignores_transport_helper_generators(self):
        """
        The ``" transported"`` generators carry a dispatch capacity, not a potential.

        Upstream adds them for the ``biomass_spatial`` option and gives them a
        ``p_nom`` of 10 GW, which must not be mistaken for a Swiss potential.
        """
        n = build_network()
        n.add(
            "Generator",
            "CH unsustainable solid biomass transported",
            bus="CH solid biomass",
            carrier="unsustainable solid biomass",
            p_nom=10000,
        )

        assert_upstream_ch_exemption(n)


class TestSplitChSolidBiomass:
    """The Swiss potential follows the configured phase-in shares."""

    @pytest.mark.parametrize(
        ("share_sustainable", "share_unsustainable"),
        [(0, 1), (0.33, 0.66), (0.66, 0.33)],
    )
    def test_both_carriers_scale_with_their_share(
        self, share_sustainable, share_unsustainable
    ):
        n = build_network()

        split_ch_solid_biomass(n, share_sustainable, share_unsustainable)

        generators = n.generators
        assert generators.at["CH solid biomass", "p_nom"] == pytest.approx(
            BASE * share_sustainable
        )
        assert generators.at["CH solid biomass", "e_sum_max"] == pytest.approx(
            BASE * share_sustainable
        )
        assert generators.at[
            "CH unsustainable solid biomass", "p_nom"
        ] == pytest.approx(BASE * share_unsustainable)

    def test_unsustainable_potential_is_forced(self):
        """Upstream pins the unsustainable generators to their full potential."""
        n = build_network()

        split_ch_solid_biomass(n, 0, 1)

        forced = n.generators.loc[
            "CH unsustainable solid biomass", ["p_nom", "e_sum_min", "e_sum_max"]
        ]
        assert (forced == BASE).all()

    def test_sustainable_potential_stays_an_upper_bound(self):
        """``e_sum_min`` is not written, so the solver may leave the potential unused."""
        n = build_network()

        split_ch_solid_biomass(n, 0.33, 0.66)

        assert n.generators.at["CH solid biomass", "e_sum_min"] == 0

    def test_fully_sustainable_horizon_keeps_the_whole_potential(self):
        """Upstream removes the unsustainable generators once no country retains one."""
        n = build_network()
        n.remove("Generator", "CH unsustainable solid biomass")
        n.remove("Generator", "AT unsustainable solid biomass")

        split_ch_solid_biomass(n, 1, 0)

        assert n.generators.at["CH solid biomass", "p_nom"] == BASE

    def test_raises_when_a_positive_share_has_no_generator(self):
        n = build_network()
        n.remove("Generator", "CH unsustainable solid biomass")

        with pytest.raises(ValueError, match="upstream did not add them"):
            split_ch_solid_biomass(n, 0.33, 0.66)

    def test_other_countries_are_untouched(self):
        n = build_network()
        before = n.generators.filter(like="AT", axis=0).copy()

        split_ch_solid_biomass(n, 0, 1)

        assert n.generators.filter(like="AT", axis=0).compare(before).empty

    def test_network_without_switzerland_is_skipped(self):
        n = build_network(ch=False)
        before = n.generators.copy()

        split_ch_solid_biomass(n, 0, 1)

        assert n.generators.compare(before).empty


class TestApplyChBiomassSplit:
    """The entry point reads both shares for the planning horizon from the config."""

    @staticmethod
    def snakemake(year: int) -> SimpleNamespace:
        return SimpleNamespace(
            config={
                "biomass": {
                    # The config keeps integer year keys, unlike n.meta.
                    "share_sustainable_potential_available": {2025: 0, 2030: 0.33},
                    "share_unsustainable_use_retained": {2025: 1, 2030: 0.66},
                }
            },
            wildcards=SimpleNamespace(planning_horizons=str(year)),
        )

    def test_applies_the_shares_of_the_planning_horizon(self):
        n = build_network()

        apply_ch_biomass_split(n, self.snakemake(2030))

        assert n.generators.at["CH solid biomass", "p_nom"] == pytest.approx(
            BASE * 0.33
        )
        assert n.generators.at[
            "CH unsustainable solid biomass", "p_nom"
        ] == pytest.approx(BASE * 0.66)

    def test_checks_the_upstream_exemption_before_writing(self):
        n = build_network(ch_unsustainable=1.0)

        with pytest.raises(ValueError, match="Expected no unsustainable solid biomass"):
            apply_ch_biomass_split(n, self.snakemake(2025))

        assert n.generators.at["CH solid biomass", "p_nom"] == BASE
