# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Shared utilities used by both `mods.constraints` and `mods.network` subpackages."""

import logging

import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

__all__ = ["get_tyndp_location", "get_relevant_links_and_lines"]


def get_tyndp_location(n: pypsa.Network) -> dict[str, str]:
    """
    Build a mapping from PyPSA bus names to TYNDP country-level location codes.

    Parameters
    ----------
    n : pypsa.Network
        The PyPSA network whose buses are to be mapped.

    Returns
    -------
    dict[str, str]
        Mapping of bus name to TYNDP location code (e.g. ``"AT31"`` → ``"AT"``,
        ``"XK"`` → ``"RS"``).

    Notes
    -----
    The mapping is built in four steps:

    1. Only *spatial* buses are included — those where
       ``n.buses.index == n.buses.location`` (excludes sector-coupling buses
       such as ``"AT31 gas"``).
    2. The synthetic ``"EU"`` aggregation bus is dropped.
    3. All buses whose name starts with ``"AT"`` or ``"DE"`` are collapsed to
       their country code (``"AT"`` or ``"DE"``), because these countries are
       modelled at NUTS2/3 resolution.
    4. ``"XK"`` (Kosovo) is mapped to ``"RS"`` (Serbia) because Kosovo is not
       a standalone ENTSO-E grid zone and shares the RS zone in the TYNDP data.
    """
    buses = n.buses[n.buses.index == n.buses.location].location.drop(
        index="EU", errors="ignore"
    )

    group_countries = ["AT", "DE"]
    for country in group_countries:
        buses.loc[buses.index.str.startswith(country)] = country

    if "XK" in buses.index:
        buses["XK"] = "RS"
    return buses.to_dict()


def get_relevant_links_and_lines(n: pypsa.Network) -> tuple[pd.DataFrame, pd.DataFrame]:
    """


    Parameters
    ----------
    n : pypsa.Network
        PyPSA network containing the grid topology.

    Returns
    -------
    relevant_links : pd.DataFrame
        Active DC Links that cross a TYNDP border, with two extra columns
        ``bus0_tyndp`` and ``bus1_tyndp`` holding the TYNDP location codes.
    relevant_lines : pd.DataFrame
        Active AC Lines that cross a TYNDP border, with two extra columns
        ``bus0_tyndp`` and ``bus1_tyndp`` holding the TYNDP location codes.

    Raises
    ------
    ValueError
        If any model border corridor (derived from active AC Lines and DC Links)
        is absent from ``tyndp_transmission``. This ensures every cross-border
        flow in the model has a corresponding NTC capacity entry.

    Notes
    -----
    * Bus-to-location mapping is performed by :func:`get_tyndp_location`.
    * Only connections where the two endpoints belong to *different* TYNDP
      locations are treated as cross-border.
    * Border direction is normalised (alphabetically smaller node first) before
      deduplication and comparison, matching the normalisation applied when
      building the TYNDP CSV.
    * The check is asymmetric: model borders missing from TYNDP raise an error
      (strict), whereas TYNDP borders missing from the model emit only a warning
      (lenient) — corridors defined in TYNDP but absent from the network are
      accepted because not all interconnectors may be modelled.
    """
    tyndp_location_dict = get_tyndp_location(n)

    relevant_lines = n.lines[(n.lines.carrier == "AC") & n.lines.active].copy()
    relevant_lines["bus0_tyndp"] = relevant_lines["bus0"].map(tyndp_location_dict)
    relevant_lines["bus1_tyndp"] = relevant_lines["bus1"].map(tyndp_location_dict)
    relevant_lines = relevant_lines[
        relevant_lines["bus0_tyndp"] != relevant_lines["bus1_tyndp"]
    ]

    relevant_links = n.links[(n.links.carrier == "DC") & (n.links.active)].copy()
    relevant_links["bus0_tyndp"] = relevant_links["bus0"].map(tyndp_location_dict)
    relevant_links["bus1_tyndp"] = relevant_links["bus1"].map(tyndp_location_dict)
    relevant_links = relevant_links[
        relevant_links["bus0_tyndp"] != relevant_links["bus1_tyndp"]
    ]

    return relevant_links, relevant_lines


def sanity_check_links_and_lines(relevant_links, relevant_lines, tyndp_transmission):
    """
    Validate that all model cross-border corridors are covered by the TYNDP data.

    Maps every active AC Line and DC Link in the network to its TYNDP location
    code, identifies cross-border connections, and checks that the set of model
    corridors is a subset of the corridors defined in the TYNDP CSV.

    Parameters
    ----------
    relevant_links
    relevant_lines
    tyndp_transmission

    Returns
    -------
    :
    """
    border_links = relevant_links[["bus0_tyndp", "bus1_tyndp"]].drop_duplicates()
    border_lines = relevant_lines[["bus0_tyndp", "bus1_tyndp"]].drop_duplicates()
    borders = pd.concat([border_links, border_lines])
    # .values strips the column index so pandas does not attempt to align
    # bus1_tyndp → bus0_tyndp and bus0_tyndp → bus1_tyndp by label, which
    # would produce NaN instead of swapping.
    borders.loc[
        borders.bus0_tyndp > borders.bus1_tyndp, ["bus0_tyndp", "bus1_tyndp"]
    ] = borders.loc[
        borders.bus0_tyndp > borders.bus1_tyndp, ["bus1_tyndp", "bus0_tyndp"]
    ].values
    borders = borders.drop_duplicates().sort_values(["bus0_tyndp", "bus1_tyndp"])

    border_tup = list(borders.itertuples(index=False, name=None))
    df_tup = list(
        tyndp_transmission[["from_node", "to_node"]].itertuples(index=False, name=None)
    )

    df_tup_set = set(df_tup)
    border_tup_set = set(border_tup)
    borders_not_in_tyndp = [bt for bt in border_tup if bt not in df_tup_set]
    tyndp_not_in_borders = [dt for dt in df_tup if dt not in border_tup_set]

    if len(borders_not_in_tyndp) > 0:
        raise ValueError(
            f"The following borders are not part of tyndp: {borders_not_in_tyndp}"
        )

    if len(tyndp_not_in_borders) > 0:
        logger.warning(
            f"The following borders are not part of the model: {tyndp_not_in_borders}"
        )
