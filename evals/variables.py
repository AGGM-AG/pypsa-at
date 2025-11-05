"""Module to export IAMC variables using pyam."""

from pathlib import Path

from evals.statistic import collect_myopic_statistics
from evals.utils import rename_aggregate

# use case: dashboard map view
# - export grid capacities to variables data base table
# - export region x and y locations
# - export grid capacities


def export_grid_capacities(networks):
    """Export grid capacities using pyam."""
    # grid_capacity = collect_myopic_statistics(
    #     networks,
    #     statistic="grid_capacity",
    #     drop_zeros=False,
    #     drop_unit=False,
    #     groupby=["bus0", "bus1", "carrier", "bus_carrier", "unit"],
    #     bus_carrier=["AC", "gas", "H2", "co2 stored"],
    #     append_grid=False,
    #     align_edges=False,
    # ).pipe(filter_by, carrier=[""])
    n = networks["2050"]
    bus_carrier = ["AC", "gas", "H2", "co2 stored"]
    from evals.utils import get_transmission_carriers

    carrier = list(get_transmission_carriers(n, bus_carrier).unique("carrier"))
    capacities = n.statistics.optimal_capacity(
        components=n.branch_components,
        groupby=["bus0", "bus1", "carrier", "bus_carrier", "unit"],
        carrier=carrier,
        aggregate_across_components=True,
        # do not filter by bus_carrier -> it drops AC Lines
    )
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

    # waste and solid biomass capacities are not binding. No need to display
    # those capacities. Better show flows.
    df = capacities.reset_index(name="value")
    df["variable"] = (
        df["bus_carrier"] + "|" + df["carrier"] + "|" + df["bus0"] + "<->" + df["bus1"]
    )
    import pandas as pd

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
