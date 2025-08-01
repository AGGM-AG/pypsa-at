# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Evaluate nodal prices per energy bus carrier."""

from pathlib import Path

from evals.fileio import Exporter


def view_price_map(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Export nodal prices to file using Folium.

    Parameters
    ----------
    result_path : str | Path
        The path to the results directory.
    networks : dict
        A dictionary of networks.
    config : dict
        Configuration dictionary.
    """
    statistics = []

    # marginal_cost = collect_myopic_statistics(networks, "")

    exporter = Exporter(statistics=statistics, view_config=config["view"])
    exporter.export(result_path, subdir=config["view"]["subdir"])
