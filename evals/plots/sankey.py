# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Module for Sankey diagram.

# Improvements:
# todo: solid biomass from solids to bio energy
# todo: separate storage and transformation into two flows from same nodes to preserve information on the amounts.

# Known issues:
# Fixme: Heat sector is imbalanced. Need to assume a heat supply share per sector to
#        distribute AC/gas/oil/biomass to sectors that have Loads on rural or decentral
#        heat buses.
# Todo: central heat storage losses are not being tracked in transformation and storage block
# todo: central heat distribution losses are not included in distribution losses
# todo: oil refining losses are ignored, while losses from HVC to waste are tracked in resource losses
# Fixme: Loads from "low-temperature heat for industry" are produced using electricity, gas or something else.
#        Those amounts are counted twice if connected as Heat to Industry!
# Fixme: Similarly, "agriculture heat" Loads at "rural heat" bus are produced using electricity,
#        gas or something else.
#        Those amounts are counted twice if connected as Heat to Agriculture!
# Fixme: Include decentral heat and gas for industry losses in the sectoral amounts
"""

import logging
from itertools import product

import pandas as pd
import plotly.graph_objects as go
from plotly.graph_objs import Sankey
from plotly.subplots import make_subplots

from evals.constants import COLOUR, COLOUR_SCHEME, RUN_META_DATA
from evals.constants import DataModel as DM
from evals.plots._base import ESMChart
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
_BOTTOM = 0.99  # max(GROUP_Y.values()) + (1 -  max(GROUP_Y.values())) / 2
NODE_DATA = [  # id, label, x, y
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
    # 5 outgoing nodes distributed evenly
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


class SankeyChart(ESMChart):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    def plot(self):
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

    def connect_electricity(self):
        bus_carrier = ["AC", "low voltage"]  # ignoring battery, home battery buses
        name = "ELECTRICITY"
        import_ = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            carrier=[
                "Import Foreign",
                "Import Domestic",
            ],
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

        regex = "Foreign|Domestic|hydro|decentral|rural|pipeline"
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
                "gas pipeline",
                "H2 pipeline",
                "H2 pipeline (Kernnetz)",
            ],
        )
        self._connect(
            distribution_losses,
            "ELECTRICITY_SECONDARY_OUT",
            "DIST_LOSS",
            color=COLOUR.grey_neutral,
        )

        self._check_remainder(bus_carrier)

    def connect_hydrogen(self):
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

    def connect_methane(self):
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

    def connect_biogas(self):
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

    def connect_solids(self):
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

    def connect_liquids(self):
        name = "LIQUIDS"
        bus_carrier = [
            "oil",
            "methanol",
            "NH3",
            "electrobiofuels",
        ]
        import_ = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            carrier=[
                "Import Foreign",
                "Import Domestic",
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
            "Foreign|Domestic|decentral|rural|industry|shipping|agriculture|transport|aviation|refining",
        )

        transformation_demand = self._flow_transformation_in(transformation, name)
        transformation_supply = self._flow_transformation_out(transformation, name)

        bypass = import_.sum() - transformation_demand.sum()
        self._flow_bypass(bypass.item(), name)
        secondary = transformation_supply.sum() + bypass.sum()
        self._flow_secondary(secondary.item(), name)

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()
        self._flow_sector(final, "industry", name, "INDUSTRY")
        self._flow_sector(final, "Foreign|Domestic", name, "EXPORT", append_label=True)
        self._flow_sector(final, "rural|decentral", name, "HH_SERVICES")
        self._flow_sector(final, "transport|shipping|aviation", name, "TRANSPORT")
        self._flow_sector(final, "agriculture", name, "AGRICULTURE")

        if self.location == "Europe":
            # assign EU Ammonia Loads to agriculture sector
            nh3_load = filter_by(
                self._df, bus_carrier="NH3", carrier="NH3", component="Load"
            )
            self._flow_sector(nh3_load, r"NH3", name, "AGRICULTURE")
            # drop oil refining process
            oil_refining = filter_by(
                self._df, bus_carrier="oil", carrier="oil refining", component="Link"
            )
            self._df.drop(oil_refining.index, inplace=True)

        stores = filter_by(self._df, bus_carrier=bus_carrier, component="Store")
        assert stores.sum().abs().item() < 1e-6
        self._df.drop(stores.index, inplace=True)

        self._check_remainder(bus_carrier)

    def connect_uranium(self):
        bus_carrier = "uranium"
        name = "URANIUM"

        # abusing nuclear PP demand as regional uranium import
        import_ = filter_by(self._df, bus_carrier=bus_carrier, carrier="nuclear").mul(
            -1
        )
        self._flow_import(import_, name)
        self._flow_primary(import_, name)
        self._forward(
            "URANIUM_PRIMARY_OUT",
            "TRANS_IN",
            import_.sum().item(),
        )

        # drop EU components
        if self.location == "Europe":
            to_drop = filter_by(
                self._df, bus_carrier=bus_carrier, component=["Generator", "Store"]
            )
            self._df.drop(to_drop.index, inplace=True)

        self._check_remainder(bus_carrier)

    def connect_heat(self):
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
        # self._connect(generation, "HEAT", "HEAT_PRIMARY_IN", color=color)

        # primary = generation.sum().item()
        self._flow_primary(generation, name)
        # self._forward(
        #     f"{name}_PRIMARY_IN",
        #     f"{name}_PRIMARY_OUT",
        #     primary,
        # )
        # self.nodes.at[f"{name}_PRIMARY_IN", "label"] = (
        #     f"{prettify_number(primary)} {self.unit}"
        # )
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
        # bypass = primary - transformation_demand.sum().item()
        # self._forward(
        #     f"{name}_PRIMARY_OUT",
        #     f"{name}_BYPASS_IN",
        #     bypass,
        # )
        # self._forward(
        #     f"{name}_BYPASS_IN",
        #     f"{name}_BYPASS_OUT",
        #     bypass,
        # )
        # self.nodes.at[f"{name}_BYPASS_IN", "label"] = (
        #     f"{prettify_number(bypass)} {self.unit}"
        # )
        self._connect(
            transformation_supply,
            "TRANS_OUT",
            f"{name}_SECONDARY_IN",
            color=color,
        )

        # self._forward(f"{name}_BYPASS_OUT", f"{name}_SECONDARY_IN", bypass)
        secondary = transformation_supply.sum() + bypass
        self._flow_secondary(secondary.item(), name)
        # secondary = transformation_supply.sum().item() + bypass
        # self._forward(f"{name}_SECONDARY_IN", f"{name}_SECONDARY_OUT", secondary)
        # self.nodes.at[f"{name}_SECONDARY_IN", "label"] = (
        #     f"{prettify_number(secondary)} {self.unit}"
        # )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()
        self._flow_sector(final, "industry|DAC", name, "INDUSTRY")
        # self._connect(
        #     industry,
        #     f"{name}_SECONDARY_OUT",
        #     "INDUSTRY",
        # )
        # dac = final.filter(regex="DAC", axis=0)
        # self._connect(
        #     dac,
        #     f"{name}_SECONDARY_OUT",
        #     "INDUSTRY",
        # )
        self._flow_sector(final, "agriculture", name, "AGRICULTURE")
        # agriculture = final.filter(regex="agriculture", axis=0)
        # self._connect(
        #     agriculture,
        #     f"{name}_SECONDARY_OUT",
        #     "AGRICULTURE",
        # )

        vents = final.filter(like="heat vent", axis=0)
        self._connect(
            vents,
            f"{name}_SECONDARY_OUT",
            "DIST_LOSS",
            color=COLOUR.grey_neutral,
        )

        industry = final.filter(regex="industry|DAC", axis=0)
        agriculture = final.filter(regex="agriculture", axis=0)
        # hh_services = (
        #         secondary - industry.sum() - dac.sum() - vents.sum() - agriculture.sum()
        # ).item()
        hh_services = secondary - industry.sum() - vents.sum() - agriculture.sum()
        self._forward(f"{name}_SECONDARY_OUT", "HH_SERVICES", hh_services.item())
        # self._flow_sector(hh_services, r"[*az,AZ,\s]", name, "HH_SERVICES")

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
        ).filter(regex="decentral|rural|central", axis=0)  # |central
        self._df.drop(to_drop.index, inplace=True)

        remaining = filter_by(self._df, bus_carrier=bus_carrier)
        assert remaining.empty, (
            f"Missing amounts detected for location "
            f"{self.location} and year {self.year}:\n{remaining}"
        )

    def forward_transformation(self):
        transformation = self.flows.query("target == 'TRANS_IN'")
        self._forward(
            "TRANS_IN",
            "TRANS_OUT",
            transformation["value"].sum(),
        )

    def connect_transformation_losses(self):
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

    def check_nodal_balance(self):
        checks = (
            "PRIMARY",
            "SECONDARY",
            "TRANSFORMATION",
        )
        for node in self.nodes.index:
            # skip left and right border nodes because they are never balanced
            if not any([s in node for s in checks]):
                continue

            node_in = filter_by(self.flows, source=node)
            node_out = filter_by(self.flows, target=node)
            diff = node_in["value"].sum() - node_out["value"].sum()
            if abs(diff) > self.cfg.cutoff:
                logger.warning(
                    f"Warning[{self.location} {self.year}]: {node} has a "
                    f"discrepancy of {diff:.2f} {self.unit}"
                )

    def fix_node_y_positions(self):
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

    def _connect(self, df, source, target, color: str = None):
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

    def _forward(self, source, target, value, color: str = None):
        if value < self.cfg.cutoff:
            return
        self.flows.loc[(source, target), self.flows.columns] = [
            value,
            color or self.nodes.loc[source, "color"],
            f"{prettify_number(value)} {self._df.attrs['unit']}",
        ]

    def _flow_loop(self, transformation_supply, final, name, color):
        loop = (transformation_supply.sum() - final.sum()).item()
        if has_loop := (loop > self.cfg.cutoff):
            self.has_loop = has_loop
            self._forward("TRANS_OUT", "TRANS_IN", loop, color=color)
            # self._forward(f"{name}_SECONDARY_IN", f"{name}_PRIMARY_OUT", loop, color=color)
            if (f"{name}_PRIMARY_OUT", "TRANS_IN") in self.flows.index:
                self.flows.at[(f"{name}_PRIMARY_OUT", "TRANS_IN"), "value"] -= loop
            if ("TRANS_OUT", f"{name}_SECONDARY_IN") in self.flows.index:
                self.flows.at[("TRANS_OUT", f"{name}_SECONDARY_IN"), "value"] -= loop

    def _flow_primary(self, df, name):
        primary = df.sum().item()
        self._forward(
            f"{name}_PRIMARY_IN",
            f"{name}_PRIMARY_OUT",
            primary,
        )
        self.nodes.at[f"{name}_PRIMARY_IN", "label"] = (
            f"{prettify_number(primary)} {self.unit}"
        )

    def _flow_import(self, df, name):
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

    def _flow_generation(self, df, name, label, color):
        self.primary.append(df)
        self._connect(
            df,
            label,
            f"{name}_PRIMARY_IN",
            color=color,
        )

    def _flow_transformation_in(self, df, name):
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

    def _flow_transformation_out(self, df, name):
        transformation_supply = df[df.gt(0)].dropna()
        target = f"{name}_SECONDARY_IN"
        self._connect(
            transformation_supply,
            "TRANS_OUT",
            target,
            self._get_color(target),
        )
        return transformation_supply

    def _flow_bypass(self, value, name):
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

    def _flow_secondary(self, value, name):
        self._forward(
            f"{name}_SECONDARY_IN",
            f"{name}_SECONDARY_OUT",
            value,
        )
        self.nodes.at[f"{name}_SECONDARY_IN", "label"] = (
            f"{prettify_number(value)} {self.unit}"
        )

    def _flow_sector(self, df, regex, name, sector, append_label=False):
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

    def _set_node_label(self, idx, value, name="", append=False):
        if idx not in self.nodes.index:
            return

        if append:
            self.nodes.at[idx, "label"] += (
                f"<br>{prettify_number(value)} {self.unit} {name}"
            )
        else:
            self.nodes.at[idx, "label"] = f"{prettify_number(value)} {self.unit}"

    def _set_base_layout(self):
        """Set various figure properties."""
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

    def _set_title(self):
        title = self.cfg.title.format(location=self.location, unit=self.year)
        self.fig.update_layout(
            title=dict(text=title, font_size=self.cfg.title_font_size)
        )

    def _set_legend(self):
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

    def _add_pie_chart(self, kind, row, col):
        """Add a pie chart to the figure."""
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

    def _get_color(self, node_id):
        return self.nodes.at[node_id, "color"]

    def _harmonize_v2g(self, transformation, transformation_demand):
        # harmonize V2G and hide EV battery to connect electricity demand
        # for transport directly without storage. Increase BEV charger by
        # V2G supply. The BEV Charger will serve as the Transport sectoral
        # demand, effectively hiding the storage systems for EV.
        v2g_demand = transformation.query("carrier == 'V2G'").rename(
            {"V2G": "V2G demand"}
        )
        # increase BEV charger withdrawal by V2G amounts and drop it from
        # transformation demand since its transport load
        bev = ("Link", "BEV charger", "low voltage")
        transformation_demand.drop(bev, inplace=True)
        if not v2g_demand.empty:
            self._df.loc[bev, "value"] -= v2g_demand["value"].item()
            # add V2G as a transformation (storage) demand
            transformation_demand = pd.concat([transformation_demand, v2g_demand])

        return transformation_demand

    def _check_remainder(self, bus_carrier):
        remaining = filter_by(self._df, bus_carrier=bus_carrier)
        assert remaining.empty, (
            f"Missing amounts detected for location "
            f"{self.location} and year {self.year}:\n{remaining}"
        )

    @staticmethod
    def _format_customdata_line(carrier, value, unit, target_length):
        # padding = target_length - len(carrier)
        # return carrier + " " * padding + f"{prettify_number(value)} {unit}"
        return f"{prettify_number(value)} {unit} {carrier}"
