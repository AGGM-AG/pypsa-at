# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Interactive Sankey diagram plotting for energy system visualization.

This module provides the SankeyChart class for creating comprehensive energy flow
Sankey diagrams from processed PyPSA network statistics. The diagrams visualize
energy flows from primary sources through transformation processes to final
consumption sectors, including losses and storage operations.

Key Features
------------
- Interactive Plotly-based Sankey diagrams with hover details
- Automatic node positioning with loop detection and adjustment
- Energy carrier grouping and color coding
- Integrated pie charts for primary energy and final energy demand
- Comprehensive flow tracking from import through transformation to consumption
- Balance checking and loss accounting

The main class SankeyChart processes energy statistics and creates a multi-panel
visualization showing the complete energy system flow with accompanying summary charts.

Known Issues and TODOs
----------------------
- Heat sector balancing needs improvement for rural/decentral heat buses
- Central heat storage and distribution losses need better tracking
- Oil refining losses are currently ignored
- Some industrial heat loads may be double-counted
- Decentral heat/gas industry losses need sectoral allocation
- Solid biomass flows to bio energy need separation
- Storage vs transformation flows should be distinguished
"""

import logging
from itertools import product
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.graph_objs import Sankey
from plotly.subplots import make_subplots

from evals.constants import COLOUR, COLOUR_SCHEME, RUN_META_DATA
from evals.constants import DataModel as DM
from evals.utils import (
    drop_from_multtindex_by_regex,
    filter_by,
    prettify_number,
    rename_aggregate,
)

logger = logging.getLogger(__file__)

GROUPS = {
    # the order of keys implicitly determines the vertical (y) alignment of nodes
    "Electricity": ["AC", "low voltage", "EV battery", "battery", "home battery"],
    "Methane": ["gas", "gas for industry"],
    "Heat": [
        "rural heat",
        "urban central heat",
        "urban decentral heat",
        "ambient heat",
        "rural water tanks",
        "urban central water pits",
        "urban central water tanks",
        "urban decentral water tanks",
    ],
    "Solids": [
        "coal",
        "lignite",
        "municipal solid waste",
        "non-sequestered HVC",
        "solid biomass",
        "solid biomass for industry",
    ],
    "Liquids": [
        "NH3",
        "oil primary",
        "methanol",
        "oil",
        "agriculture machinery oil",
        "industry methanol",
        "kerosene for aviation",
        "shipping methanol",
        "naphtha for industry",
    ],
    "Uranium": ["uranium"],
    "Biogas": [
        "biogas",
    ],
    "Hydrogen": ["H2"],
}

# default positions are relative order for the plotly node alignment
# algorithm. In the case of loops, the node positions become adjusted.
GROUP_Y = {name: i / 20 for i, name in enumerate(GROUPS, start=1)}
GROUP_X = {
    ("PRIMARY", "IN"): 0.25,
    ("PRIMARY", "OUT"): 0.3,
    ("BYPASS", "IN"): 0.4,
    ("BYPASS", "OUT"): 0.6,
    ("SECONDARY", "IN"): 0.7,
    ("SECONDARY", "OUT"): 0.75,
}
_BOTTOM = 0.99
NODE_DATA = [  # id, label, colour, x, y
    ["IMPORT", "Import", COLOUR.black, 0.01, 0.01],
    ["WIND", "Wind Power", COLOUR.black, 0.01, 0.1],
    ["SOLAR", "Solar Power", COLOUR.black, 0.01, 0.15],
    ["HYDRO", "Hydro Power", COLOUR.black, 0.01, 0.2],
    ["HEAT", "Ambient Heat", COLOUR.black, 0.01, 0.25],
    ["SOLIDS", "Solids", COLOUR.black, 0.01, 0.3],
    ["LIQUIDS", "Liquids", COLOUR.black, 0.01, 0.35],
    ["BIOGAS", "Biogas", COLOUR.black, 0.01, 0.4],
    [
        "TRANS_IN",
        "Transformation<br>& Storage",
        COLOUR.salmon,
        0.4,
        max(GROUP_Y.values()) + 0.1,
    ],
    ["TRANS_OUT", "", COLOUR.salmon, 0.6, max(GROUP_Y.values()) + 0.1],
    ["EXPORT", "Export", COLOUR.black, 0.99, 0.01],
    ["HH_SERVICES", "Households & Services", COLOUR.black, 0.99, 0.1],
    ["INDUSTRY", "Industry", COLOUR.black, 0.99, 0.15],
    ["TRANSPORT", "Transport", COLOUR.black, 0.99, 0.2],
    ["AGRICULTURE", "Agriculture", COLOUR.black, 0.99, 0.25],
    # Losses are stacked to the very bottom of the plot
    ["UNUSED", "Ressource Losses", COLOUR.grey_deep, 0.35, _BOTTOM],
    ["TRANS_LOSS", "Transformation Losses", COLOUR.grey_deep, 0.65, _BOTTOM],
    ["DIST_LOSS", "Distribution Losses", COLOUR.grey_deep, 0.8, 0.0001],
]
for group, section, side in product(
    GROUPS,
    ("PRIMARY", "BYPASS", "SECONDARY"),
    ("IN", "OUT"),
):
    NODE_DATA.append(
        [
            f"{group.upper()}_{section}_{side}",
            "",
            COLOUR_SCHEME[group],
            GROUP_X[(section, side)],
            GROUP_Y[group],
        ]
    )


class SankeyChart:
    """
    Interactive Sankey diagram for energy system flow visualization.

    Creates comprehensive energy flow diagrams showing the path from primary
    energy sources through transformation and storage to final consumption
    sectors. The chart includes automatic node positioning, loop detection,
    and integrated summary pie charts.

    The visualization groups energy carriers by type (Electricity, Methane, Heat,
    Solids, Liquids, Uranium, Biogas, Hydrogen) and tracks flows through three
    main stages: Primary (import/generation), Transformation & Storage, and
    Secondary (final consumption by sector).

    Attributes
    ----------
    location
        Geographic location being visualized.
    year
        Year of the energy data.
    flows
        Tracking all energy flows between nodes.
    nodes
        Node positions, colors, and labels.
    has_loop
        Flag indicating if transformation block contains loops.
    primary
        Primary energy data for pie chart.
    fed
        Final energy demand data for pie chart.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the SankeyChart with energy flow data.

        Extracts location and year from the input data, sets up node
        and flow tracking structures, and initializes the base chart configuration.
        """
        df, cfg = args[0], args[1]
        self._df = df
        self.cfg = cfg
        self.unit = cfg.unit or df.attrs["unit"]
        self.metric_name = df.attrs["name"]
        self.fig = go.Figure()
        self.col_values = ""
        self.location = self._df.index.unique(DM.LOCATION).item()
        self.year = self._df.index.unique(DM.YEAR).item()
        self._df = self._df.droplevel(DM.YEAR).droplevel(DM.LOCATION)
        self._df.columns = ["value"]
        self.flows = pd.DataFrame(
            index=pd.MultiIndex.from_tuples([], names=["source", "target"]),
            columns=["value", "color", "customdata"],
        )
        self.nodes = pd.DataFrame(
            data=NODE_DATA,
            columns=["name", "label", "color", "x", "y"],
        ).set_index("name")

        # track if the Sankey has a loop in the transformation block
        self.has_loop = False

        # track pie chart data
        self.primary = []
        self.fed = []

    def plot(self) -> None:
        """
        Create the complete Sankey diagram with pie charts.

        Orchestrates the full plotting process by connecting all energy carriers,
        handling transformation flows and losses, positioning nodes, and creating
        the final multi-panel visualization with integrated pie charts.
        """
        # plotly draws traces connected first in the background. The connection
        # order should correspond with the order of keys in GROUP_COLORS.
        self.connect_electricity()
        self.connect_methane()
        self.connect_heat()
        self.connect_solids()
        self.connect_liquids()
        self.connect_uranium()
        self.connect_biogas()
        self.connect_hydrogen()
        self.forward_transformation()
        self.connect_transformation_losses()

        # reduce nodes data frame to prevent misalignment in sankey nodes
        flows_used = self.flows.index.unique("source").union(  # noqa: F841
            self.flows.index.unique("target")
        )
        self.nodes = self.nodes.query("name in @flows_used")
        self.nodes["id"] = [*range(len(self.nodes))]

        if self.has_loop:
            self.fix_node_y_positions()

        self.fig = make_subplots(
            rows=4,
            cols=2,
            specs=[
                [{"type": "domain", "rowspan": 4}, {"type": "xy"}],
                [None, {"type": "domain"}],
                [None, {"type": "domain"}],
                [None, {"type": "domain"}],
            ],
            subplot_titles=("", "", "Primary Energy", "Final Energy Demand", ""),
            column_widths=[0.85, 0.15],
            horizontal_spacing=0.00,
            vertical_spacing=0.1,
        )
        sankey = Sankey(
            name="Energy Carrier",
            arrangement="fixed" if self.has_loop else "snap",
            valuesuffix=self.unit,
            textfont_family="Montserrat, monospaced",
            textfont_weight="bold",
            node=dict(
                line=dict(color="black", width=0.5),
                label=self.nodes["label"],
                color=self.nodes["color"],
                line_width=1,
                hovertemplate="%{label}<extra></extra>",
                x=self.nodes["x"],
                y=self.nodes["y"],
                pad=10,
                thickness=10,
            ),
            link=dict(
                source=self.flows.index.get_level_values("source").map(
                    self.nodes["id"]
                ),
                target=self.flows.index.get_level_values("target").map(
                    self.nodes["id"]
                ),
                value=self.flows["value"],
                color=self.flows["color"],
                customdata=self.flows["customdata"],
                hovertemplate="%{customdata} <extra></extra>",
            ),
        )
        self.fig.add_trace(sankey, row=1, col=1)

        self._add_pie_chart("PRIMARY", row=2, col=2)
        self._add_pie_chart("FED", row=3, col=2)

        self._set_legend()
        self._set_base_layout()
        self._set_title()

        self.check_nodal_balance()

    def connect_electricity(self) -> None:
        """
        Connect electricity flows from generation through transformation to consumption.

        Processes electricity sector including renewable generation (wind, solar, hydro),
        imports, transformation through power plants and storage, bypasses, and final
        consumption by sectors. Handles distribution losses and V2G harmonization.
        """
        bus_carrier = ["AC", "low voltage"]  # ignoring battery, home battery buses
        name = "ELECTRICITY"
        import_ = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            carrier=["Import Foreign", "Import Domestic"],
        )
        self._flow_import(import_, name)
        generation = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Generator", "StorageUnit"]
        )

        wind = generation.filter(like="wind", axis=0)
        self._flow_generation(wind, name, "WIND", COLOUR.blue_moonstone)
        solar = generation.filter(like="solar", axis=0)
        self._flow_generation(solar, name, "SOLAR", COLOUR.yellow_bright)
        hydro = generation.filter(regex="ror|hydro", axis=0)
        self._flow_generation(hydro, name, "HYDRO", COLOUR.blue_persian)

        primary = pd.concat([import_, wind, solar, hydro])
        self._flow_primary(primary, name)

        regex = "Foreign|Domestic|decentral|rural|pipeline"
        transformation = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            component=["Link", "Store", "StorageUnit"],
        ).pipe(drop_from_multtindex_by_regex, regex)

        transformation_demand = self._flow_transformation_in(transformation, name)
        transformation_supply = self._flow_transformation_out(transformation, name)

        bypass = primary.sum() - transformation_demand.sum()
        self._flow_bypass(bypass.item(), name)

        secondary = transformation_supply.sum() + bypass
        self._flow_secondary(secondary.item(), name)

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()
        self._flow_sector(final, "industry", name, "INDUSTRY")
        self._flow_sector(final, "Foreign|Domestic", name, "EXPORT", append_label=True)
        self._flow_sector(final, "agriculture", name, "AGRICULTURE")

        # include losses from decentral heat production technologies
        self._flow_sector(final, "rural|decentral|'electricity'", name, "HH_SERVICES")
        self._flow_sector(final, "BEV charger", name, "TRANSPORT")

        distribution_losses = filter_by(
            self._df,
            carrier=[
                "electricity distribution grid",
                "Transmission Losses",
                "gas pipeline",
                "gas pipeline new",
                "H2 pipeline",
                "H2 pipeline (Kernnetz)",
                "H2 pipeline retrofitted",
            ],
        )
        self._connect(
            distribution_losses,
            "ELECTRICITY_SECONDARY_OUT",
            "DIST_LOSS",
            color=COLOUR.grey_neutral,
        )

        self._check_remainder(bus_carrier)

    def connect_hydrogen(self) -> None:
        """
        Connect hydrogen flows from import/production to final consumption.

        Processes hydrogen sector flows including imports, industrial production,
        transformation through electrolysis and storage, and consumption by
        industry, households, and transport sectors.
        """
        bus_carrier = "H2"
        name = "HYDROGEN"
        color = self.nodes.loc[f"{name}_PRIMARY_IN", "color"]
        import_ = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            carrier=[
                "Import Foreign",
                "Import Domestic",
                "import H2",
            ],
        )
        h2_for_industry = filter_by(
            self._df, bus_carrier=bus_carrier, carrier="H2 for industry"
        )
        if h2_for_industry.sum().item() > 0:
            # industry produces hydrogen in 2020 in some regions.
            # those amounts are assigned to import
            import_ = pd.concat([import_, h2_for_industry])
            self._df.drop(h2_for_industry.index, inplace=True)
        self._flow_import(import_, name)
        self._flow_primary(import_, name)

        regex = "Foreign|Domestic|h2 for industry|decentral|rural"
        transform = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Link", "Store"]
        ).pipe(drop_from_multtindex_by_regex, regex)
        # storage = filter_by(self._df, bus_carrier=bus_carrier, component="Store")
        transformation_demand = self._flow_transformation_in(transform, name)
        transformation_supply = self._flow_transformation_out(transform, name)

        bypass = import_.sum() - transformation_demand.sum()
        self._flow_bypass(bypass.item(), name)

        secondary = transformation_supply.sum() + bypass
        self._flow_secondary(secondary.item(), name)

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()
        self._flow_loop(transformation_supply, final, name, color)
        self._flow_sector(final, "industry", name, "INDUSTRY")
        self._flow_sector(final, "rural|decentral", name, "HH_SERVICES")
        self._flow_sector(final, "transport", name, "TRANSPORT")
        self._flow_sector(final, "Foreign|Domestic", name, "EXPORT", append_label=True)

        self._check_remainder(bus_carrier)

    def connect_methane(self) -> None:
        """
        Connect methane/gas flows from import through transformation to consumption.

        Processes natural gas and synthetic methane flows including pipeline and LNG
        imports, transformation through power plants and industrial processes,
        and consumption by sectors with loop detection for gas-to-gas processes.
        """
        bus_carrier = "gas"
        name = "METHANE"
        color = self.nodes.loc[f"{name}_PRIMARY_IN", "color"]
        import_ = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            carrier=[
                "Import Foreign",
                "Import Domestic",
                "pipeline gas",
                "lng gas",
                "production gas",
                "import gas",
            ],
        )
        self._flow_import(import_, name)
        self._flow_primary(import_, name)

        regex = "Foreign|Domestic|gas for industry|decentral|rural"
        transform = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Link", "Store"]
        ).pipe(drop_from_multtindex_by_regex, regex)
        transformation_demand = self._flow_transformation_in(transform, name)
        transformation_supply = self._flow_transformation_out(transform, name)

        bypass = import_.sum() - transformation_demand.sum()
        self._flow_bypass(bypass.item(), name)

        secondary = transformation_supply.sum() + bypass
        self._flow_secondary(secondary.item(), name)

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()
        self._flow_sector(final, "industry", name, "INDUSTRY")
        self._flow_sector(final, "rural|decentral", name, "HH_SERVICES")
        self._flow_sector(final, "Foreign|Domestic", name, "EXPORT", append_label=True)

        self._flow_loop(transformation_supply, final, name, color)

        self._check_remainder(bus_carrier)

    def connect_biogas(self) -> None:
        """
        Connect biogas flows from generation to transformation.

        Processes biogas generation and direct forwarding to transformation
        processes, typically for conversion to electricity or upgraded gas.
        """
        bus_carrier = "biogas"
        name = "BIOGAS"
        color = self.nodes.loc[f"{name}_PRIMARY_IN", "color"]
        generation = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            component="Generator",
        )
        label = name
        self._flow_generation(generation, name, label, color)
        self._flow_primary(generation, name)

        processing = filter_by(self._df, bus_carrier=bus_carrier, component="Link")
        self._connect(
            processing,
            f"{name}_PRIMARY_OUT",
            "TRANS_IN",
        )

        self._check_remainder(bus_carrier)

    def connect_solids(self) -> None:
        """
        Connect solid fuel flows from import/generation to consumption.

        Processes coal, lignite, biomass, waste, and HVC flows including imports,
        domestic generation, transformation losses, and consumption by industry
        and households. Handles waste-to-energy and resource loss tracking.
        """
        bus_carrier = [
            "coal",
            "lignite",
            "solid biomass",
            "municipal solid waste",
            "non-sequestered HVC",
        ]
        name = "SOLIDS"
        color = self._get_color(f"{name}_PRIMARY_IN")
        import_ = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            carrier=[
                "Import Foreign",
                "Import Domestic",
                "Global Import",
            ],
        )
        self._flow_import(import_, name)
        generation = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Generator", "Store"]
        )
        self._flow_generation(generation, name, name, color)

        # HVC to air is an unused resource. Some countries do not have
        # techs that use waste e.g., waste CHPs
        primary_losses = filter_by(
            self._df, bus_carrier=bus_carrier, carrier="HVC to air"
        )
        self._connect(
            primary_losses, "SOLIDS_PRIMARY_OUT", "UNUSED", color=COLOUR.grey_neutral
        )

        primary = pd.concat([import_, generation])
        self._flow_primary(primary, name)

        # waste to HVC is only used to track CO2 emissions
        waste_to_hvc = filter_by(
            self._df, carrier="municipal solid waste", component="Link"
        )
        assert waste_to_hvc.sum().abs().item() < 1e-6, waste_to_hvc
        self._df.drop(waste_to_hvc.index, inplace=True)

        transformation = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            component="Link",
        ).pipe(
            drop_from_multtindex_by_regex,
            "Foreign|Domestic|decentral|rural|for industry",
        )

        transformation_demand = self._flow_transformation_in(transformation, name)
        transformation_supply = transformation[transformation.gt(0)].dropna()
        assert transformation_supply.empty

        bypass = (
            primary.sum() - transformation_demand.sum() - primary_losses.abs().sum()
        )
        self._flow_bypass(bypass.item(), name)
        secondary = transformation_supply.sum() + bypass
        self._flow_secondary(secondary.item(), name)
        final = filter_by(self._df, bus_carrier=bus_carrier).abs()
        self._flow_sector(final, "industry", name, "INDUSTRY")
        self._flow_sector(final, "Foreign|Domestic", name, "EXPORT", append_label=True)
        self._flow_sector(final, "rural|decentral", name, "HH_SERVICES")
        self._check_remainder(bus_carrier)

    def connect_liquids(self) -> None:
        """
        Connect liquid fuel flows from import through transformation to consumption.

        Processes oil, methanol, NH3, and electrobiofuel flows including imports,
        transformation through refining and synthesis, and consumption by transport,
        industry, shipping, aviation, and agriculture sectors.
        """
        name = "LIQUIDS"
        bus_carrier = [
            "oil",
            "methanol",
            "NH3",
            "electrobiofuels",
        ]
        # WARNING - /IdeaProjects/pypsa-at/evals/plots/sankey.py - Warning[Balearic Islands 2030]: ELECTRICITY_PRIMARY_OUT has a discrepancy of 12.64 TWh
        # WARNING - /IdeaProjects/pypsa-at/evals/plots/sankey.py - Warning[Balearic Islands 2030]: ELECTRICITY_SECONDARY_IN has a discrepancy of -12.64 TWh
        # WARNING - /IdeaProjects/pypsa-at/evals/plots/sankey.py - Warning[Balearic Islands 2030]: LIQUIDS_PRIMARY_OUT has a discrepancy of 55.85 TWh
        # WARNING - /IdeaProjects/pypsa-at/evals/plots/sankey.py - Warning[Balearic Islands 2030]: LIQUIDS_SECONDARY_IN has a discrepancy of -55.85 TWh
        # WARNING - /IdeaProjects/pypsa-at/evals/plots/sankey.py - Warning[Italy 2050]: LIQUIDS_PRIMARY_OUT has a discrepancy of 19.48 TWh
        # WARNING - /IdeaProjects/pypsa-at/evals/plots/sankey.py - Warning[Italy 2050]: LIQUIDS_SECONDARY_IN has a discrepancy of -19.48 TWh
        import_ = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            carrier=[
                "Import Foreign",
                "Import Domestic",
                "Global Import",
                "import NH3",
                "import oil",
                "import methanol",
            ],
        )
        self._flow_import(import_, name)
        self._flow_primary(import_, name)
        transformation = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            component="Link",
        ).pipe(
            drop_from_multtindex_by_regex,
            "decentral|rural|industry|shipping|agriculture|transport|aviation|refining",
        )

        transformation_demand = self._flow_transformation_in(transformation, name)
        transformation_supply = self._flow_transformation_out(transformation, name)

        bypass = import_.sum() - transformation_demand.sum()
        self._flow_bypass(bypass.item(), name)
        secondary = transformation_supply.sum() + bypass.sum()
        self._flow_secondary(secondary.item(), name)

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()
        self._flow_sector(final, "industry|NH3", name, "INDUSTRY")
        self._flow_sector(final, "Foreign|Domestic", name, "EXPORT", append_label=True)
        self._flow_sector(final, "rural|decentral", name, "HH_SERVICES")
        self._flow_sector(final, "transport|shipping|aviation", name, "TRANSPORT")
        self._flow_sector(final, "agriculture", name, "AGRICULTURE")

        if self.location == "Europe":
            # # assign EU Ammonia Loads to agriculture sector
            # nh3_load = filter_by(
            #     self._df, bus_carrier="NH3", carrier="NH3", component="Load"
            # )
            # self._flow_sector(nh3_load, r"NH3", name, "AGRICULTURE")
            # drop oil refining process
            oil_refining = filter_by(
                self._df, bus_carrier="oil", carrier="oil refining", component="Link"
            )
            self._df.drop(oil_refining.index, inplace=True)

        stores = filter_by(self._df, bus_carrier=bus_carrier, component="Store")
        assert stores.sum().abs().item() < 1e-6
        self._df.drop(stores.index, inplace=True)

        self._check_remainder(bus_carrier)

    def connect_uranium(self) -> None:
        """
        Connect uranium flows from import to nuclear transformation.

        Processes uranium imports (treated as nuclear power plant demand)
        and forwards to transformation block for electricity generation.
        """
        bus_carrier = "uranium"
        name = "URANIUM"

        # Global Import is the regionalized carrier for Uranium EU imports
        import_ = filter_by(self._df, bus_carrier=bus_carrier, carrier="Global Import")
        self._flow_import(import_, name)
        self._flow_primary(import_, name)

        transformation = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            component="Link",
        )
        self._flow_transformation_in(transformation, name)
        # # todo: connect Link      nuclear uranium     -35.201016 as transformation IN
        # self._forward(
        #     "URANIUM_PRIMARY_OUT",
        #     "TRANS_IN",
        #     import_.sum().item(),
        # )

        # drop EU components
        if self.location == "Europe":
            to_drop = filter_by(
                self._df, bus_carrier=bus_carrier, component=["Generator", "Store"]
            )
            self._df.drop(to_drop.index, inplace=True)

        self._check_remainder(bus_carrier)

    def connect_heat(self) -> None:
        """
        Connect heat flows from ambient sources through systems to consumption.

        Processes ambient heat, solar thermal, and heat pump flows including
        central and decentral heating systems, storage, distribution losses,
        and consumption by households, industry, and agriculture.
        """
        name = "HEAT"
        bus_carrier = [
            "ambient heat",
            "rural heat",
            "urban central heat",
            "urban decentral heat",
        ]
        color = self._get_color(f"{name}_PRIMARY_IN")

        generation = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Generator", "Link"]
        ).filter(regex="solar thermal|ambient heat", axis=0)
        self._flow_generation(generation, name, name, color)

        self._flow_primary(generation, name)

        regex = "decentral|rural|industry|agriculture|DAC"
        transformation = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            component="Link",
        ).pipe(drop_from_multtindex_by_regex, regex)

        storage_demand = transformation[transformation.lt(0)].dropna().mul(-1)
        central_heat = generation.filter(like=" central ", axis=0)
        storage_supply = transformation[transformation.gt(0)].dropna()
        transformation_supply = pd.concat([storage_supply, central_heat])
        transformation_demand = pd.concat([storage_demand, central_heat])
        # transformation_demand = self._flow_transformation_in(transformation, name)
        # transformation_supply = self._flow_transformation_out(transformation, name)
        self._connect(
            transformation_demand,
            f"{name}_PRIMARY_OUT",
            "TRANS_IN",
        )

        bypass = generation.sum() - transformation_demand.sum()
        self._flow_bypass(bypass.item(), name)
        self._connect(
            transformation_supply,
            "TRANS_OUT",
            f"{name}_SECONDARY_IN",
            color=color,
        )

        # self._forward(f"{name}_BYPASS_OUT", f"{name}_SECONDARY_IN", bypass)
        secondary = transformation_supply.sum() + bypass
        self._flow_secondary(secondary.item(), name)

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()
        self._flow_sector(final, "industry|DAC", name, "INDUSTRY")
        self._flow_sector(final, "agriculture", name, "AGRICULTURE")

        vents = final.filter(like="heat vent", axis=0)
        self._connect(
            vents,
            f"{name}_SECONDARY_OUT",
            "DIST_LOSS",
            color=COLOUR.grey_neutral,
        )

        industry = final.filter(regex="industry|DAC", axis=0)
        agriculture = final.filter(regex="agriculture", axis=0)
        hh_services = secondary - industry.sum() - vents.sum() - agriculture.sum()
        self._forward(f"{name}_SECONDARY_OUT", "HH_SERVICES", hh_services.item())

        # if hh_services <= 0:
        #     # some amounts of gas/electricity/solid biomass for heat are for agriculture
        #     logger.warning(
        #         f"Negative remaining Heat Load detected in "
        #         f"{self.location} and year {self.year}:\n{hh_services}"
        #     )
        #     # assuming that electricity supplies these amounts to the largest load
        # self._forward(f"{name}_SECONDARY_OUT", "HH_SERVICES", hh_services)

        # decentral heat technologies connect to FED via their input
        # bus_carrier because this form of energy is metered. central Load
        # also needs to be dropped.
        to_drop = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Link", "Load", "Generator"]
        ).filter(regex="decentral|rural|central", axis=0)
        self._df.drop(to_drop.index, inplace=True)

        remaining = filter_by(self._df, bus_carrier=bus_carrier)
        assert remaining.empty, (
            f"Missing amounts detected for location "
            f"{self.location} and year {self.year}:\n{remaining}"
        )

    def forward_transformation(self) -> None:
        """
        Connect transformation input to output flows.

        Creates the central transformation flow that aggregates all inputs
        to the transformation block and forwards them to outputs.
        """
        transformation = self.flows.query("target == 'TRANS_IN'")
        self._forward(
            "TRANS_IN",
            "TRANS_OUT",
            transformation["value"].sum(),
        )

    def connect_transformation_losses(self) -> None:
        """
        Connect transformation losses from output to loss sink.

        Processes conversion losses from power plants, storage systems,
        and other transformation technologies, grouping by carrier type
        and connecting to the transformation loss node.
        """
        bus_carrier = [
            bc for bc in self._df.index.unique("bus_carrier") if bc.endswith("losses")
        ]
        regex = "rural|decentral|gas for industry CC"
        losses = filter_by(self._df, bus_carrier=bus_carrier).pipe(
            drop_from_multtindex_by_regex, regex
        )

        # rename losses carrier to shorten the display table by summarizing to bus_carrier
        to_bus_carrier = {
            c: bc
            for c, bc in zip(
                losses.index.get_level_values("carrier"),
                losses.index.get_level_values("bus_carrier").map(
                    lambda x: x.replace(" losses", "")
                ),
            )
        }
        to_groups = {bus_carrier: k for k, v in GROUPS.items() for bus_carrier in v}
        losses = (
            losses.pipe(rename_aggregate, to_bus_carrier)
            .pipe(rename_aggregate, to_groups)
            .pipe(rename_aggregate, "losses", level="bus_carrier")
        )
        self._connect(
            losses,
            "TRANS_OUT",
            "TRANS_LOSS",
            color=COLOUR.grey_neutral,
        )

    def check_nodal_balance(self) -> None:
        """
        Verify energy balance at primary, secondary, and transformation nodes.

        Checks that inflows equal outflows for internal nodes and logs
        warnings for any significant imbalances that exceed the cutoff threshold.
        """
        checks = (
            "PRIMARY",
            "SECONDARY",
            "TRANS_",
        )
        for node in self.nodes.index:
            # skip left and right border nodes because they are never balanced
            if not any([s in node for s in checks]):
                continue

            node_in = filter_by(self.flows, source=node)
            node_out = filter_by(self.flows, target=node)
            diff = node_in["value"].sum() - node_out["value"].sum()
            if abs(diff) > 0.1:  # self.cfg.cutoff
                logger.warning(
                    f"Warning[{self.location} {self.year}]: {node} has a "
                    f"discrepancy of {diff:.2f} {self.unit}"
                )

    def fix_node_y_positions(self) -> None:
        """
        Adjust vertical node positions when transformation loops are detected.

        Recalculates node positions proportional to flow magnitudes to prevent
        visual overlap when the transformation block contains loops. Maintains
        proper spacing and ensures positions stay within plot bounds.
        """
        # Calculate maximum flow for normalization
        maximum = 0
        for x, nodes in self.nodes.groupby("x"):
            idx = nodes.index.tolist()
            src_total = filter_by(self.flows, source=idx)["value"].sum()
            dst_total = filter_by(self.flows, target=idx)["value"].sum()
            maximum = max(maximum, src_total, dst_total)

        # Add padding for visual spacing
        maximum *= 1.05

        for x, nodes in self.nodes.groupby("x"):
            idx = nodes.index.tolist()

            # Skip loss nodes - position them at bottom
            loss_nodes = [i for i in idx if i in ("TRANS_LOSS", "DIST_LOSS", "UNUSED")]
            if loss_nodes:
                # for i, node in enumerate(loss_nodes):
                #     self.nodes.at[node, "y"] = 0.95 + (i * 0.02)
                continue

            # Get flow data for this column
            src_flows = filter_by(self.flows, source=idx)
            dst_flows = filter_by(self.flows, target=idx)

            # Use the side with the larger total flow for positioning
            if src_flows["value"].sum() >= dst_flows["value"].sum():
                flows = src_flows.groupby("source")["value"].sum()
            else:
                flows = dst_flows.groupby("target")["value"].sum()

            # Sort nodes by their original y position to maintain order
            node_order = nodes.sort_values("y").index.tolist()

            # Calculate cumulative positions
            cumulative_pos = 0
            spacing = 0.02  # Small gap between nodes

            for node_name in node_order:
                if node_name in flows.index:
                    node_size = flows[node_name] / maximum
                else:
                    node_size = 0.01  # Minimum size for nodes with no flow

                # Position node at current cumulative position
                self.nodes.at[node_name, "y"] = cumulative_pos + (node_size / 2)

                # Update cumulative position
                cumulative_pos += node_size + spacing

            # Normalize positions to ensure they stay within [0, 0.9] range
            max_y = self.nodes.loc[node_order, "y"].max()
            if max_y > 0.9:
                scale_factor = 0.9 / max_y
                for node_name in node_order:
                    self.nodes.at[node_name, "y"] *= scale_factor

    def _connect(
        self, df: pd.DataFrame, source: str, target: str, color: str | None = None
    ) -> None:
        """
        Create a flow connection between two nodes.

        Parameters
        ----------
        df
            Flow data to connect.
        source
            Source node identifier.
        target
            Target node identifier.
        color
            Color override for the flow.

        Notes
        -----
        Aggregates the data values, creates hover information,
        and removes processed data from the main dataset.
        """
        value = df.abs().sum().item()
        if value < self.cfg.cutoff:
            self._df.drop(df.index, inplace=True, errors="ignore")
            return

        df = df.abs().sort_values(by="value", ascending=False)
        longest_carrier = df.index.get_level_values("carrier").map(len).max() + 1
        customdata = "<br>".join(
            [
                self._format_customdata_line(c, v, self.unit, longest_carrier)
                for c, v in zip(df.index.get_level_values("carrier"), df["value"])
                if prettify_number(v) != "0.0"
            ]
        )
        customdata += f"<br><b>{prettify_number(value)} {self.unit} in Total</b>"

        # add a row with the link's value
        color = color or self.nodes.loc[source, "color"]  # allow explicit override
        self.flows.loc[(source, target), self.flows.columns] = [
            value,
            color,
            customdata,
        ]
        self._df.drop(df.index, inplace=True, errors="ignore")

    def _forward(
        self, source: str, target: str, value: float, color: str | None = None
    ) -> None:
        """
        Create a simple flow connection with a single value.

        Parameters
        ----------
        source
            Source node identifier.
        target
            Target node identifier.
        value
            Flow value to connect.
        color
            Color override for the flow.
        """
        if value < self.cfg.cutoff:
            return
        self.flows.loc[(source, target), self.flows.columns] = [
            value,
            color or self.nodes.loc[source, "color"],
            f"{prettify_number(value)} {self._df.attrs['unit']}",
        ]

    def _flow_loop(
        self,
        transformation_supply: pd.DataFrame,
        final: pd.DataFrame,
        name: str,
        color: str,
    ) -> None:
        """
        Handle loop flows in transformation systems.

        Detects and creates loop flows when transformation output exceeds final consumption,
        indicating internal recycling or feedback loops within the transformation block.
        Adjusts existing flows to prevent double-counting.

        Parameters
        ----------
        transformation_supply
            Transformation output flows.
        final
            Final consumption flows.
        name
            Energy carrier name for flow identification.
        color
            Color for the loop flow visualization.
        """
        loop = (transformation_supply.sum() - final.sum()).item()
        if has_loop := (loop > self.cfg.cutoff):
            self.has_loop = has_loop
            self._forward("TRANS_OUT", "TRANS_IN", loop, color=color)
            # self._forward(f"{name}_SECONDARY_IN", f"{name}_PRIMARY_OUT", loop, color=color)
            if (f"{name}_PRIMARY_OUT", "TRANS_IN") in self.flows.index:
                self.flows.at[(f"{name}_PRIMARY_OUT", "TRANS_IN"), "value"] -= loop
            if ("TRANS_OUT", f"{name}_SECONDARY_IN") in self.flows.index:
                self.flows.at[("TRANS_OUT", f"{name}_SECONDARY_IN"), "value"] -= loop

    def _flow_primary(self, df: pd.DataFrame, name: str) -> None:
        """
        Create primary energy flow connections.

        Establishes the flow from primary input to primary output nodes and
        updates the primary input node label with the total flow value.

        Parameters
        ----------
        df
            Primary energy flow data.
        name
            Energy carrier name for node identification.
        """
        primary = df.sum().item()
        self._forward(
            f"{name}_PRIMARY_IN",
            f"{name}_PRIMARY_OUT",
            primary,
        )
        self.nodes.at[f"{name}_PRIMARY_IN", "label"] = (
            f"{prettify_number(primary)} {self.unit}"
        )

    def _flow_import(self, df: pd.DataFrame, name: str) -> None:
        """
        Create import flow connections to primary energy input.

        Connects import flows to the primary energy input node and updates
        the import node label with carrier-specific import amounts.

        Parameters
        ----------
        df
            Import flow data.
        name
            Energy carrier name for target identification.
        """
        target = f"{name}_PRIMARY_IN"
        self._connect(
            df,
            "IMPORT",
            target,
            color=self._get_color(target),
        )
        value = df.abs().sum().item()
        if value > 0.05:
            self.nodes.at["IMPORT", "label"] += (
                f"<br>{prettify_number(value)} {self.unit} {name.title()}"
            )

    def _flow_generation(
        self, df: pd.DataFrame, name: str, label: str, color: str
    ) -> None:
        """
        Create generation flow connections for renewable sources.

        Connects generation sources (wind, solar, hydro, etc.) to the primary
        energy input and tracks the data for pie chart visualization.

        Parameters
        ----------
        df
            Generation flow data.
        name
            Energy carrier name for target identification.
        label
            Source label for the generation node.
        color
            Color for the flow visualization.
        """
        self.primary.append(df)
        self._connect(
            df,
            label,
            f"{name}_PRIMARY_IN",
            color=color,
        )

    def _flow_transformation_in(self, df: pd.DataFrame, name: str) -> pd.DataFrame:
        """
        Process transformation input flows and connect to the transformation block.

        Extracts negative flows (demand) from transformation data,
        handles special cases like V2G harmonization for electricity,
        and connects to the transformation input node.

        Parameters
        ----------
        df
            Complete transformation flow data.
        name
            Energy carrier name for flow identification.

        Returns
        -------
        :
            Processed transformation demand flows.
        """
        transformation_demand = df[df.lt(0)].dropna().mul(-1)
        if name == "ELECTRICITY":
            transformation_demand = self._harmonize_v2g(df, transformation_demand)

        # separate storage
        # stores = filter_by(transformation_demand, component="Store")
        # charger = transformation_demand.filter(like="charger", axis=0)
        # storage_demand = pd.concat([stores, charger])

        self._connect(
            transformation_demand,
            f"{name}_PRIMARY_OUT",
            "TRANS_IN",
        )

        return transformation_demand

    def _flow_transformation_out(self, df: pd.DataFrame, name: str) -> pd.DataFrame:
        """
        Process transformation output flows and connect from transformation block.

        Extracts positive flows (supply) from transformation data
        and connects them from the transformation output to secondary input.

        Parameters
        ----------
        df
            Complete transformation flow data.
        name
            Energy carrier name for flow identification.

        Returns
        -------
        :
            Processed transformation supply flows.
        """
        transformation_supply = df[df.gt(0)].dropna()
        target = f"{name}_SECONDARY_IN"
        self._connect(
            transformation_supply,
            "TRANS_OUT",
            target,
            self._get_color(target),
        )
        return transformation_supply

    def _flow_bypass(self, value: float, name: str) -> None:
        """
        Create bypass flows that skip transformation.

        Establishes flow paths for energy that bypasses transformation,
        going directly from primary to secondary through bypass nodes.
        Updates bypass the input node label with the flow value.

        Parameters
        ----------
        value
            Bypass flow amount.
        name
            Energy carrier name for node identification.
        """
        self._forward(
            f"{name}_PRIMARY_OUT",
            f"{name}_BYPASS_IN",
            value,
        )
        self._forward(
            f"{name}_BYPASS_IN",
            f"{name}_BYPASS_OUT",
            value,
        )
        self._forward(
            f"{name}_BYPASS_OUT",
            f"{name}_SECONDARY_IN",
            value,
        )
        self.nodes.at[f"{name}_BYPASS_IN", "label"] = (
            f"{prettify_number(value)} {self.unit}"
        )

    def _flow_secondary(self, value: float, name: str) -> None:
        """
        Create secondary energy flow connections.

        Establishes the flow from secondary input to secondary output nodes
        and updates the secondary input node label with the total flow value.

        Parameters
        ----------
        value
            Secondary flow amount.
        name
            Energy carrier name for node identification.
        """
        self._forward(
            f"{name}_SECONDARY_IN",
            f"{name}_SECONDARY_OUT",
            value,
        )
        self.nodes.at[f"{name}_SECONDARY_IN", "label"] = (
            f"{prettify_number(value)} {self.unit}"
        )

    def _flow_sector(
        self,
        df: pd.DataFrame,
        regex: str,
        name: str,
        sector: str,
        append_label: bool = False,
    ) -> None:
        """
        Create sector consumption flow connections.

        Filters flows by regex pattern, connects them to the specified sector,
        and tracks data for the final energy demand pie chart. Optionally appends
        flow information to sector node labels.

        Parameters
        ----------
        df
            Complete flow data to filter.
        regex
            Regular expression pattern for filtering flows.
        name
            Energy carrier name for source identification.
        sector
            Target sector node identifier.
        append_label
            Whether to append flow info to sector label.
        """
        demand = df.filter(regex=regex, axis=0)
        self.fed.append(demand)
        self._connect(
            demand,
            f"{name}_SECONDARY_OUT",
            sector,
        )
        value = demand.sum().item()
        if append_label and value > self.cfg.cutoff:
            self.nodes.at["EXPORT", "label"] += (
                f"<br>{name.title()} {prettify_number(value)} {self.unit}"
            )

    def _set_node_label(
        self, idx: str, value: float, name: str = "", append: bool = False
    ) -> None:
        """
        Set or append node label with flow value.

        Updates node labels with formatted flow values and units.
        Can either replace the existing label or append to it.

        Parameters
        ----------
        idx
            Node identifier.
        value
            Flow value to display.
        name
            Optional name to include in the label.
        append
            Whether to append to the existing label or replace it.
        """
        if idx not in self.nodes.index:
            return

        if append:
            self.nodes.at[idx, "label"] += (
                f"<br>{prettify_number(value)} {self.unit} {name}"
            )
        else:
            self.nodes.at[idx, "label"] = f"{prettify_number(value)} {self.unit}"

    def _set_base_layout(self) -> None:
        """
        Configure the base layout properties for the figure.

        Sets up subplot visibility, grid properties, background colors,
        legend positioning, and embeds run metadata for export.
        """
        self.fig.update_layout(
            height=800,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=-0.1,
                xanchor="left",
                x=0.0,
                font=dict(size=14),
            ),
        )

        # hide scatter plot used to show the legend
        self.fig.update_xaxes(visible=False, row=1, col=2)
        self.fig.update_yaxes(visible=False, row=1, col=2)
        # hide subplot backgrounds
        self.fig.update_layout(
            xaxis2=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis2=dict(showgrid=False, zeroline=False, showticklabels=False),
            plot_bgcolor="rgba(0,0,0,0)",  # applies to all xy subplots
        )

        # export the metadata directly in the Layout property for JSON
        self.fig.update_layout(meta=[RUN_META_DATA])

    def _set_title(self) -> None:
        """
        Set the chart title using location and year information.

        Formats and applies the title based on the configuration template
        with appropriate font sizing.
        """
        title = self.cfg.title.format(location=self.location, unit=self.year)
        self.fig.update_layout(
            title=dict(text=title, font_size=self.cfg.title_font_size)
        )

    def _set_legend(self) -> None:
        """
        Add color-coded legend for energy carrier groups.

        Creates legend entries for each energy carrier group using the
        standardized color scheme and positions them horizontally.
        """
        # add legend for sankey traces
        for carrier_group in GROUPS:
            self.fig.add_trace(
                go.Scatter(
                    x=[None],
                    y=[None],
                    mode="markers",
                    marker=dict(size=10, color=COLOUR_SCHEME[carrier_group]),
                    name=carrier_group,
                    showlegend=True,
                ),
                row=1,
                col=2,
            )

    def _add_pie_chart(self, kind: str, row: int, col: int) -> None:
        """
        Add a pie chart to the subplot layout.

        Parameters
        ----------
        kind
            Chart type - 'PRIMARY' for primary energy or 'FED' for final energy demand.
        row
            Subplot row position.
        col
            Subplot column position.

        Notes
        -----
        Creates proportional pie charts showing energy breakdown by carrier type
        with matching colors and hover information.
        """
        if kind == "PRIMARY":
            df = pd.concat(self.primary)
            domain_id = 1
        elif kind == "FED":
            df = pd.concat(self.fed)
            domain_id = 2
        else:
            raise ValueError(f"Unknown kind: {kind}")

        to_groups = {bus_carrier: k for k, v in GROUPS.items() for bus_carrier in v}
        data = (
            rename_aggregate(df, to_groups, level="bus_carrier")
            .groupby("bus_carrier")
            .sum()
            .reset_index()
        )
        data = data[data["value"] >= self.cfg.cutoff]
        pie = go.Pie(
            values=data["value"],
            labels=data["bus_carrier"],
            customdata=[prettify_number(v) for v in data["value"]],
            hovertemplate="%{label}<br>%{customdata} " + self.unit + "<extra></extra>",
            marker=dict(colors=[COLOUR_SCHEME[x] for x in data["bus_carrier"]]),
            showlegend=False,
            hole=0.6,
            texttemplate="%{percent:.1%}",
            textposition="inside",
            text=data["value"].map(prettify_number),
            textinfo="percent+label+text",
        )
        self.fig.add_trace(pie, row=row, col=col)

        # Add annotation in the donut hole
        domain = self.fig.data[domain_id].domain
        self.fig.add_annotation(
            text=self.unit,
            xref="paper",
            yref="paper",
            x=(domain.x[0] + domain.x[1]) / 2,
            y=(domain.y[0] + domain.y[1]) / 2,
            showarrow=False,
            font=dict(size=12),
        )

    def _get_color(self, node_id: str) -> str:
        """
        Get the color assigned to a specific node.

        Parameters
        ----------
        node_id
            Node identifier to look up.

        Returns
        -------
        :
            Color value for the specified node.
        """
        return self.nodes.at[node_id, "color"]

    def _harmonize_v2g(
        self, transformation: pd.DataFrame, transformation_demand: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Harmonize vehicle-to-grid flows with BEV charging demand.

        Moves V2G and hides EV battery to connect electricity demand
        for transport directly without storage. Increase BEV charger by
        V2G supply. The BEV Charger will serve as the Transport sectoral
        demand, effectively hiding the storage systems for EV.

        Parameters
        ----------
        transformation
            Full transformation data.
        transformation_demand
            Transformation demand data.

        Returns
        -------
        :
            Modified transformation demand with V2G flows properly allocated.

        Notes
        -----
        Adjusts BEV charger demand by V2G supply amounts and treats V2G as
        storage demand to avoid double-counting in the transport sector.
        """
        v2g_demand = transformation.query("carrier == 'V2G'").rename(
            {"V2G": "V2G demand"}
        )
        # increase BEV charger withdrawal by V2G amounts and drop it from
        # transformation demand since its transport load
        bev = ("Link", "BEV charger", "low voltage")
        transformation_demand.drop(bev, inplace=True, errors="ignore")
        if not v2g_demand.empty:
            self._df.loc[bev, "value"] -= v2g_demand["value"].item()
            # add V2G as a transformation (storage) demand
            transformation_demand = pd.concat([transformation_demand, v2g_demand])

        return transformation_demand

    def _check_remainder(self, bus_carrier: str | list[str]) -> None:
        """
        Verify all flows for a bus carrier have been processed.

        Parameters
        ----------
        bus_carrier
            Bus carrier name(s) to check for remaining unprocessed flows.

        Raises
        ------
        AssertionError
            If any flows remain unprocessed for the specified bus carrier(s).
        """
        remaining = filter_by(self._df, bus_carrier=bus_carrier)
        assert remaining.empty, (
            f"Missing amounts detected for location "
            f"{self.location} and year {self.year}:\n{remaining}"
        )

    @staticmethod
    def _format_customdata_line(
        carrier: str, value: float, unit: str, target_length: int
    ) -> str:
        """
        Format a single line of hover information for energy flows.

        Parameters
        ----------
        carrier
            Energy carrier name.
        value
            Flow value.
        unit
            Unit string.
        target_length
            Target length for formatting alignment (currently unused).

        Returns
        -------
        :
            Formatted string for hover display.
        """
        # padding = target_length - len(carrier)
        # return carrier + " " * padding + f"{prettify_number(value)} {unit}"
        return f"{prettify_number(value)} {unit} {carrier}"
