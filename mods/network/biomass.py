# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Swiss biomass potential split for the ``modify_prenetwork`` step.

Confusingly, the upstream ``build_biomass_potentials`` exempts Switzerland (CH) from the
``biomass.share_sustainable_potential_available``, because the Eurostat
energy balances contain no CH data and therefore no unsustainable potential is derived.
Instead CH keeps 100 % of its ENSPRESO potential as sustainable biomass in
every planning horizon.

* :func:`apply_ch_biomass_split` — entry point called from
  :func:`mods.network.modify_prenetwork`; splits the unscaled CH ENSPRESO
  potential into a sustainable and an unsustainable part with the configured
  ``share_*`` schedules, as for all other countries.
"""

from logging import getLogger

import pypsa

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
