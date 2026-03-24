# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT evaluation package for energy system analysis visualization.

This package provides tools to evaluate PyPSA network results and generate
visualizations including interactive charts, maps, and comprehensive energy
flow diagrams.

Main Modules
------------
views
    View functions for different energy carrier balances and demands.
plots
    Plotly-based interactive chart classes.
fileio
    Input/output utilities for reading networks and exporting results.
statistic
    Extended statistics for energy system modeling evaluations.
utils
    Helper functions for data manipulation and aggregation.

Examples
--------
>>> from evals import views
>>> views.view_balance_electricity(result_path, nc, config)
"""
