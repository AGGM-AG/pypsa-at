"""Module to export IAMC variables using pyam."""

from pathlib import Path

import pandas as pd

from evals.stats import collect_myopic_statistics
from evals.utils import get_transmission_carriers, rename_aggregate


def export_region_coordinates(networks):
    """Export region coordinates using pyam."""
    n = networks["2050"]
    regions = n.buses.index.get_level_values("region")
    coordinates = n.buses.loc[regions, ["x", "y"]]
    coordinates.columns = ["longitude", "latitude"]
    coordinates.index.name = "region"
    coordinates.to_csv("data/region_coordinates.csv")


def export_grid_capacities(networks):
    """
    Export grid capacities using pyam.

    Notes
    -----
    assuming constant network topology over myopic workflow

    waste and solid biomass capacities are not binding. No need to display
    those capacities. Better show flows.
    """
    bus_carrier = ["AC", "gas", "H2", "co2 stored"]
    n = networks["2050"]
    carrier = list(get_transmission_carriers(n, bus_carrier).unique("carrier"))
    capacities = collect_myopic_statistics(
        networks,
        "optimal_capacity",
        components=n.branch_components,
        groupby=["bus0", "bus1", "carrier", "bus_carrier", "unit"],
        carrier=carrier,
        aggregate_across_components=True,
        drop_unit=False,
    )

    unit = capacities.attrs["unit"]
    capacities = rename_aggregate(
        capacities, dict.fromkeys(["MWh_el", "MWh_LHV"], unit), level="unit"
    )
    df = capacities.reset_index(name="value")
    df["variable"] = (
        df["bus_carrier"] + "|" + df["carrier"] + "|" + df["bus0"] + "<->" + df["bus1"]
    )

    df["year"] = pd.to_datetime(df["year"])
    df = df.set_index(["bus0", "variable", "unit", "year"])[["value"]]

    df.index.names = ["region", "variable", "unit", "time"]
    #     model: str
    #     version: str
    #     scenario: str
    #     region: str
    #     variable: str  # Variable name (e.g., "Primary Energy|Coal")
    #     unit: str
    #     time: datetime.datetime  # contains year
    #     value: float  # Numeric value


if __name__ == "__main__":
    from evals.fileio import read_networks

    results_path = Path("results/v2025.04/AT_KN2040")

    networks = read_networks(results_path)

    export_grid_capacities(networks)
