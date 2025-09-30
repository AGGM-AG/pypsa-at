# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
from pathlib import Path

from evals.views.common import (
    simple_optimal_capacity,
    simple_storage_capacity,
)


def view_capacity_gas_storage(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate optimal storage capacities for gas stores (CH4, H2).

    Parameters
    ----------
    result_path
        Directory path where results will be saved
    networks
        Dictionary containing PyPSA network objects for analysis
    config
        Configuration dictionary containing model parameters

    Notes
    -----
    FixMe: No Hydrogen Storage with current config?
    """
    simple_storage_capacity(networks, config, result_path)


def view_capacity_hydrogen_production(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate the optimal capacity for technologies that produce hydrogen.

    Parameters
    ----------
    result_path
        Directory path where results will be saved
    networks
        Dictionary containing PyPSA network objects for analysis
    config
        Configuration dictionary containing model parameters
    """
    simple_optimal_capacity(networks, config, result_path, kind="production")


def view_capacity_gas_production(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate the optimal capacity for technologies that produce methane.

    Parameters
    ----------
    result_path
        Directory path where results will be saved
    networks
        Dictionary containing PyPSA network objects for analysis
    config
        Configuration dictionary containing model parameters
    """
    simple_optimal_capacity(networks, config, result_path, kind="production")


def view_capacity_electricity_production(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate the optimal capacity for AC technologies that produce electricity.

    Parameters
    ----------
    result_path
        Directory path where results will be saved
    networks
        Dictionary containing PyPSA network objects for analysis
    config
        Configuration dictionary containing model parameters
    """
    simple_optimal_capacity(networks, config, result_path, kind="production")


def view_capacity_electricity_demand(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate the optimal capacity for AC technologies that withdraw electricity.

    Parameters
    ----------
    result_path
        Directory path where results will be saved
    networks
        Dictionary containing PyPSA network objects for analysis
    config
        Configuration dictionary containing model parameters
    """
    simple_optimal_capacity(networks, config, result_path, kind="demand")


def view_capacity_electricity_storage(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate the optimal capacity for AC technologies that store electricity.

    Parameters
    ----------
    result_path
        Directory path where results will be saved
    networks
        Dictionary containing PyPSA network objects for analysis
    config
        Configuration dictionary containing model parameters
    """
    simple_storage_capacity(networks, config, result_path)


def view_capacity_heat_production(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate the optimal capacity for technologies that produce heat.

    Parameters
    ----------
    result_path
        Directory path where results will be saved
    networks
        Dictionary containing PyPSA network objects for analysis
    config
        Configuration dictionary containing model parameters
    """
    simple_optimal_capacity(networks, config, result_path, kind="production")
