# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
"""Integration tests verifying TYNDP NTC cross-border flow constraints on solved networks."""

import pandas as pd
import pytest

from mods.tyndp_utils import get_relevant_links_and_lines


def _sum_flows(flows_t: pd.DataFrame, idx: pd.Index) -> pd.Series:
    """
    Sum component flows across columns, returning zeros for an empty index.

    Parameters
    ----------
    flows_t : pd.DataFrame
        Time-indexed flow DataFrame (e.g. ``n.lines_t.p0`` or
        ``n.links_t.p0``).  Columns are component names.
    idx : pd.Index
        Column labels to select and sum.  Must be a subset of
        ``flows_t.columns``; a mismatch will raise ``KeyError``.

    Returns
    -------
    pd.Series
        Per-snapshot summed flow.  All zeros when ``idx`` is empty,
        with the same index as ``flows_t``.
    """
    if idx.empty:
        return pd.Series(0.0, index=flows_t.index)
    return flows_t[idx].sum(axis=1)


@pytest.mark.AT
def test_tyndp_ntc_flow_limits_satisfied(nc, pytestconfig):
    """Per-snapshot net flow on every TYNDP corridor must not exceed NTC capacity."""
    ntc_path = (
        pytestconfig.rootpath / "resources" / "tyndp_transmission_trajectories.csv"
    )
    ntc_df = pd.read_csv(ntc_path)

    for year_str, n in nc.networks.items():
        if not n.meta["mods"]["tyndp_cross_border_flow_limits"]["enable"]:
            continue

        year_int = int(year_str)
        df_year = ntc_df[ntc_df["year"] == year_int]

        relevant_links, relevant_lines = get_relevant_links_and_lines(n)

        for row in df_year.itertuples():
            from_node: str = row.from_node
            to_node: str = row.to_node

            lines_dir_idx = relevant_lines[
                (relevant_lines["bus0_tyndp"] == from_node)
                & (relevant_lines["bus1_tyndp"] == to_node)
            ].index
            lines_indir_idx = relevant_lines[
                (relevant_lines["bus0_tyndp"] == to_node)
                & (relevant_lines["bus1_tyndp"] == from_node)
            ].index
            links_dir_idx = relevant_links[
                (relevant_links["bus0_tyndp"] == from_node)
                & (relevant_links["bus1_tyndp"] == to_node)
            ].index
            links_indir_idx = relevant_links[
                (relevant_links["bus0_tyndp"] == to_node)
                & (relevant_links["bus1_tyndp"] == from_node)
            ].index

            if (
                lines_dir_idx.empty
                and lines_indir_idx.empty
                and links_dir_idx.empty
                and links_indir_idx.empty
            ):
                continue

            net_flow_dir = (
                -_sum_flows(n.lines_t.p1, lines_dir_idx)
                - _sum_flows(n.lines_t.p0, lines_indir_idx)
                - _sum_flows(n.links_t.p1, links_dir_idx)
                - _sum_flows(n.links_t.p0, links_indir_idx)
            )

            net_flow_indir = (
                -_sum_flows(n.lines_t.p0, lines_dir_idx)
                - _sum_flows(n.lines_t.p1, lines_indir_idx)
                - _sum_flows(n.links_t.p0, links_dir_idx)
                - _sum_flows(n.links_t.p1, links_indir_idx)
            )

            # 1e-3 MW tolerance accounts for HiGHS primal feasibility residual (~1e-7)
            assert net_flow_dir.max() <= row.direct_capacity + 1e-3, (
                f"NTC violation in {year_int}: {from_node}→{to_node} "
                f"max flow {net_flow_dir.max():.1f} MW exceeds "
                f"capacity {row.direct_capacity:.1f} MW"
            )
            assert net_flow_indir.max() <= row.indirect_capacity + 1e-3, (
                f"NTC violation in {year_int}: {to_node}→{from_node} "
                f"max flow {net_flow_indir.max():.1f} MW exceeds "
                f"capacity {row.indirect_capacity:.1f} MW"
            )
