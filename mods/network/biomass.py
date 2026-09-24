# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Biomass potential corrections for the ``modify_prenetwork`` step.

Collects modifications to the biomass potentials that upstream
``build_biomass_potentials`` leaves inconsistent, e.g. because a data source does
not cover a country or a commodity. Each correction rewrites the affected
generators on the pre-network rather than the upstream resource files.

Currently the only correction concerns Switzerland (CH):

* :func:`apply_ch_biomass_split` — upstream exempts CH from the
  ``biomass.share_sustainable_potential_available`` phase-in, because the Eurostat
  energy balances contain no CH rows and no unsustainable potential can be derived.
  CH therefore keeps 100 % of its ENSPRESO potential as sustainable biomass in every
  planning horizon. This splits the unscaled CH potential into a sustainable and an
  unsustainable part with the configured ``share_*`` schedules, as for all other
  countries.
"""

from logging import getLogger

import pandas as pd
import pypsa
from snakemake.script import Snakemake

logger = getLogger(__name__)

COUNTRY = "CH"
SUSTAINABLE_CARRIER = "solid biomass"
UNSUSTAINABLE_CARRIER = "unsustainable solid biomass"


def assert_upstream_ch_exemption(n: pypsa.Network) -> None:
    """
    Fail if upstream no longer exempts Switzerland from the biomass phase-in.
    Once PyPSA-Eur changes something about the biomass data source or finds another
    workaround for Switzerland, this fix should be removed.

    Parameters
    ----------
    n
        The network to check, before the split is applied.

    Returns
    -------
    :
        Returns nothing if the upstream exemption still holds.

    Raises
    ------
    ValueError
        If CH unsustainable solid biomass generators already carry a potential.
    """
    generators = n.generators[
        n.generators.index.str.startswith(COUNTRY)
        & (n.generators["carrier"] == UNSUSTAINABLE_CARRIER)
        & ~n.generators.index.str.endswith(" transported")
    ]

    potential = generators["p_nom"].sum()
    if potential > 0:
        raise ValueError(
            f"Expected no {UNSUSTAINABLE_CARRIER} potential in country {COUNTRY}, but"
            f"found {potential / 1e6:.3f} TWh/a in {list(generators.index)}. Upstream "
            "data has changed, so this modification needs to be reviewed."
        )


def _select_ch_generators(n: pypsa.Network, carrier: str) -> pd.Index:
    """
    Return the Swiss generators of one carrier.

    Parameters
    ----------
    n
        The network to select from.
    carrier
        The generator carrier to select.

    Returns
    -------
    :
        Index of the matching generators, empty if there are none.
    """
    generators = n.generators
    return generators.index[
        generators.index.str.startswith(COUNTRY)
        & (generators["carrier"] == carrier)
        & ~generators.index.str.endswith(" transported")
    ]


def split_ch_solid_biomass(
    n: pypsa.Network,
    share_sustainable: float,
    share_unsustainable: float,
) -> None:
    """
    Split the Swiss solid biomass potential along the configured shares.

    Parameters
    ----------
    n
        The pre-network to modify in place.
    share_sustainable
        Share of the ENSPRESO potential available as sustainable biomass.
    share_unsustainable
        Share of the ENSPRESO potential retained as unsustainable biomass.

    Returns
    -------
    :
        Modifies the network in place.

    Raises
    ------
    ValueError
        If the network has no generator to write the unsustainable part to,
        although the configured share asks for one.
    """
    sustainable_i = _select_ch_generators(n, SUSTAINABLE_CARRIER)
    if sustainable_i.empty:
        logger.info(f"No {COUNTRY} {SUSTAINABLE_CARRIER} generators found. Skipping.")
        return

    base = n.generators.loc[sustainable_i, "p_nom"]

    n.generators.loc[sustainable_i, "p_nom"] = base * share_sustainable
    n.generators.loc[sustainable_i, "e_sum_max"] = base * share_sustainable

    if share_unsustainable == 0:
        # after given year, no unsustainable biomass is available anywhere anymore
        logger.info("No unsustainable share in this horizon. Scaled {COUNTRY} ")
        return

    # Generators are named "<node> <carrier>", so the counterpart of
    # "CH solid biomass" is "CH unsustainable solid biomass".
    unsustainable = base.set_axis(
        pd.Index(sustainable_i.str.removesuffix(SUSTAINABLE_CARRIER))
        + UNSUSTAINABLE_CARRIER
    ).mul(share_unsustainable)

    missing = unsustainable.index.difference(
        _select_ch_generators(n, UNSUSTAINABLE_CARRIER)
    )
    if not missing.empty:
        raise ValueError(
            f"Expected {list(missing)} in the network to receive "
            f"{share_unsustainable:.0%} of the {COUNTRY} biomass potential, but "
            "upstream did not add them. Upstream only adds unsustainable "
            "generators when their network wide potential is positive."
        )

    for attribute in ("p_nom", "e_sum_min", "e_sum_max"):
        n.generators.loc[unsustainable.index, attribute] = unsustainable

    logger.info(
        f"Split {base.sum() / 1e6:.3f} TWh/a of {COUNTRY} {SUSTAINABLE_CARRIER} into "
        f"{(base.sum() * share_sustainable) / 1e6:.3f} TWh/a sustainable and "
        f"{(base.sum() * share_unsustainable) / 1e6:.3f} TWh/a unsustainable potential."
    )


def apply_ch_biomass_split(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Apply the Swiss sustainable/unsustainable biomass split.

    Parameters
    ----------
    n
        The pre-network to modify in place.
    snakemake
        The Snakemake workflow object providing config and wildcards.

    Returns
    -------
    :
        Modifies the network in place.
    """
    assert_upstream_ch_exemption(n)

    year = int(snakemake.wildcards.planning_horizons)
    biomass = snakemake.config["biomass"]

    split_ch_solid_biomass(
        n,
        share_sustainable=biomass["share_sustainable_potential_available"][year],
        share_unsustainable=biomass["share_unsustainable_use_retained"][year],
    )
