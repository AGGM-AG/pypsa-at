# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for the Sankey chart helpers in ``evals.plots.sankey``."""

import logging

import pandas as pd

from evals.plots.sankey import SankeyChart


def _make_chart(node_names: list[str], flows: list[tuple[str, str, float]]):
    """
    Build a bare ``SankeyChart`` with crafted nodes and flows.

    ``check_nodal_balance`` only reads ``nodes``, ``flows``, ``location``,
    ``year`` and ``unit``, so the heavy ``__init__`` is bypassed.
    """
    chart = SankeyChart.__new__(SankeyChart)
    chart.location = "Testland"
    chart.year = 2050
    chart.unit = "TWh"
    chart.nodes = pd.DataFrame(index=pd.Index(node_names, name="name"))
    chart.flows = pd.DataFrame(
        {"value": [v for _, _, v in flows]},
        index=pd.MultiIndex.from_tuples(
            [(s, t) for s, t, _ in flows], names=["source", "target"]
        ),
    )
    return chart


def test_terminal_loss_sink_does_not_warn(caplog):
    """A loss sink only ever receives flow, so it must not be balance-checked."""
    chart = _make_chart(
        node_names=["TRANS_OUT", "TRANS_LOSS"],
        flows=[("TRANS_OUT", "TRANS_LOSS", 5.0)],
    )

    with caplog.at_level(logging.WARNING):
        chart.check_nodal_balance()

    assert "TRANS_LOSS" not in caplog.text


def test_internal_node_imbalance_still_warns(caplog):
    """Genuine imbalances at internal transformation nodes still warn."""
    chart = _make_chart(
        node_names=["A", "TRANS_OUT", "B"],
        flows=[("A", "TRANS_OUT", 10.0), ("TRANS_OUT", "B", 7.0)],
    )

    with caplog.at_level(logging.WARNING):
        chart.check_nodal_balance()

    assert "TRANS_OUT has a discrepancy" in caplog.text


def test_balanced_internal_node_does_not_warn(caplog):
    """A balanced internal node produces no warning."""
    chart = _make_chart(
        node_names=["A", "TRANS_OUT", "B"],
        flows=[("A", "TRANS_OUT", 10.0), ("TRANS_OUT", "B", 10.0)],
    )

    with caplog.at_level(logging.WARNING):
        chart.check_nodal_balance()

    assert "discrepancy" not in caplog.text
