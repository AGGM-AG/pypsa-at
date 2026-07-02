# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for helpers in ``evals.plots.components``."""

import pytest
from plotly.offline.offline import get_plotlyjs

from evals.plots.components import _CIRCULAR_LOOP_PATTERN, _FILL_GUARD_PATTERN


@pytest.mark.parametrize(
    "pattern", [_CIRCULAR_LOOP_PATTERN, _FILL_GUARD_PATTERN], ids=["loop", "fill"]
)
def test_sankey_patch_pattern_matches_exactly_once(pattern):
    """
    Each JS patch relies on its pattern being unique in the Plotly bundle.

    If a Plotly upgrade changes the minified bundle so a pattern no longer
    matches exactly one location, ``patch_sankey_circular_layout`` must be
    revisited.
    """
    assert len(pattern.findall(get_plotlyjs())) == 1
