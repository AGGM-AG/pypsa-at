# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Module for Sankey diagram."""

# Transformationsblöcke je Energieträger
# Zusammenfassung Energieträger:
#  - AC (low voltage + AC) - uranium similar to primary but with additional step
#  - H2
#  - Gas
#  - Liquids (oil, methanol, NH3, electrobiofuels, naptha)
#  - Solids (waste, biomass, coal, lignite)
#  - Heat (central), connect decentral heat directly to FED
# Alle Losses in Grau und je Tranformationsblock (Energieträger)
# drei Transformationsblöcke P2G, GtP, other
# oder ein Transformationsblock
# BUS_CARRIER_GROUPS = {
#     "biogas": "Biogas",
#     "coal": "Solids",
#     "H2": "Hydrogen",
#     "NH3": "Liquids",
#     "lignite": "Solids",
#     "gas": "Methane",
#     "municipal solid waste": "Solids",
#     "AC": "Electricity",
#     "oil primary": "Liquids",
#     "rural heat": "Heat",
#     "low voltage": "Electricity",
#     "solid biomass": "Solids",
#     "uranium": "Uranium",
#     "urban central heat": "Heat",
#     "urban decentral heat": "Heat",
#     "EV battery": "Electricity",
#     "methanol": "Liquids",
#     "oil": "Liquids",
#     "non-sequestered HVC": "Solids",
#     "agriculture machinery oil": "Liquids",
#     "battery": "Electricity",
#     "ambient heat": "Heat",
#     "home battery": "Electricity",
#     "industry methanol": "Liquids",
#     "kerosene for aviation": "Liquids",
#     "shipping methanol": "Liquids",
#     "gas for industry": "Methane",
#     "naphtha for industry": "Liquids",
#     "solid biomass for industry": "Solids",
#     "rural water tanks": "Heat",
#     "urban central water pits": "Heat",
#     "urban central water tanks": "Heat",
#     "urban decentral water tanks": "Heat",
# }
import logging
from itertools import product

import pandas as pd
from plotly.graph_objs import Figure, Sankey

from evals.constants import COLOUR, RUN_META_DATA
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
    "Biogas": ["biogas"],
    "Electricity": ["AC", "low voltage", "EV battery", "battery", "home battery"],
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
    "Hydrogen": ["H2"],
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
    "Methane": ["gas", "gas for industry"],
    "Solids": [
        "coal",
        "lignite",
        "municipal solid waste",
        "solid biomass",
        "non-sequestered HVC",
        "solid biomass for industry",
    ],
    "Uranium": ["uranium"],
}
GROUP_COLORS = {
    "Biogas": COLOUR.green_sage,
    "Electricity": COLOUR.blue_pastel,
    "Heat": COLOUR.yellow_canary,
    "Hydrogen": COLOUR.blue_cerulean,
    "Liquids": COLOUR.red_deep,
    "Methane": COLOUR.brown_light,
    "Solids": COLOUR.grey_dark,
    "Uranium": COLOUR.orange_mellow,
}
GROUP_Y = {
    name: i / 20
    for i, name in enumerate(
        (
            "Electricity",
            "Methane",
            "Heat",
            "Liquids",
            "Solids",
            "Biogas",
            "Uranium",
            "Hydrogen",
        ),
        start=1,
    )
}
GROUP_X = {
    ("PRIMARY", "IN"): 0.25,
    ("PRIMARY", "OUT"): 0.3,
    ("BYPASS", "IN"): 0.4,
    ("BYPASS", "OUT"): 0.6,
    ("SECONDARY", "IN"): 0.7,
    ("SECONDARY", "OUT"): 0.75,
}
NODE_DATA = [  # id, label, x, y
    ["IMPORT", "Import", COLOUR.black, 0.01, 0.01],
    ["WIND", "Wind Power", COLOUR.black, 0.01, 0.05],
    ["SOLAR", "Solar Power", COLOUR.black, 0.01, 0.1],
    ["HYDRO", "Hydro Power", COLOUR.black, 0.01, 0.15],
    ["BIOGAS", "Biogas", COLOUR.black, 0.01, 0.2],
    ["SOLIDS", "Solids", COLOUR.black, 0.01, 0.25],
    ["LIQUIDS", "Liquids", COLOUR.black, 0.01, 0.3],
    ["HEAT", "Ambient Heat", COLOUR.black, 0.01, 0.35],
    ["TRANS_IN", "Transformation<br>& Storage", COLOUR.salmon, 0.4, 0.6],
    ["TRANS_OUT", "", COLOUR.salmon, 0.6, 0.6],
    # ["LOOP_IN", "", COLOUR.salmon, 0.4, 0.65],
    # ["LOOP_OUT", "", COLOUR.salmon, 0.6, 0.65],
    ["EXPORT", "Export", COLOUR.black, 0.99, 0.02],
    ["HH_SERVICES", "Households & Services", COLOUR.black, 0.99, 0.05],
    ["INDUSTRY", "Industry", COLOUR.black, 0.99, 0.1],
    ["TRANSPORT", "Transport", COLOUR.black, 0.99, 0.15],
    ["AGRICULTURE", "Agriculture", COLOUR.black, 0.99, 0.2],
    ["UNUSED", "Ressource Losses", COLOUR.grey_deep, 0.35, 0.99],
    ["TRANS_LOSS", "Transformation Losses", COLOUR.grey_deep, 0.65, 0.99],
    ["DIST_LOSS", "Distribution Losses", COLOUR.grey_deep, 0.8, 0.01],
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
            GROUP_COLORS[group],
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

        # instance constants
        self.pad = 10

    def plot(self):
        # plotly draws traces connected first in the background.
        self.connect_methane()
        self.connect_hydrogen()
        self.connect_electricity()
        self.connect_biogas()
        self.connect_liquids()
        self.connect_solids()
        self.connect_uranium()
        self.connect_heat()  # must connect heat last to know FED

        self.forward_transformation()
        self.connect_transformation_losses()

        # self.check_nodal_balance()
        # self.fix_node_y_positions()

        # reduce nodes data frame to prevent misalignment in sankey nodes
        flows_used = self.flows.index.unique("source").union(  # noqa: F841
            self.flows.index.unique("target")
        )
        self.nodes = self.nodes.query("name in @flows_used")
        self.nodes["id"] = [*range(len(self.nodes))]

        self.fig = Figure(
            data=[
                Sankey(
                    # name="Legend Name",
                    arrangement="snap",  # snap, perpendicular, freeform, fixed
                    valuesuffix=self.unit,
                    textfont_family="Montserrat",
                    textfont_weight="bold",
                    node=dict(
                        # align="justify",
                        line=dict(color="black", width=0.5),
                        label=self.nodes["label"],
                        color=self.nodes["color"],
                        line_width=1,
                        hovertemplate="%{label}<extra></extra>",
                        x=self.nodes["x"],
                        y=self.nodes["y"],
                        pad=self.pad,
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
            ]
        )

        self._set_base_layout()
        title = self.cfg.title.format(location=self.location, unit=self.year)
        self.fig.update_layout(
            title=dict(text=title, font_size=self.cfg.title_font_size)
        )

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
        self._flow_generation(wind, name, "WIND", COLOUR.blue_sky)
        solar = generation.filter(like="solar", axis=0)
        self._flow_generation(solar, name, "SOLAR", COLOUR.yellow_canary)
        hydro = generation.filter(regex="ror|hydro", axis=0)
        self._flow_generation(hydro, name, "HYDRO", COLOUR.blue_pastel)

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
        # transport = final.filter(like="BEV charger", axis=0)
        # # bev_charger_losses = filter_by(
        # #     self._df, carrier="BEV charger", bus_carrier="low voltage losses"
        # # )
        # self._flow_sector(pd.concat([transport, bev_charger_losses]), r"[*az,AZ,\s]", name, "TRANSPORT")

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
        self._flow_import(import_, name)
        self._flow_primary(import_, name)

        regex = "Foreign|Domestic|h2 for industry|decentral|rural"
        transform = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Link", "Store"]
        ).pipe(drop_from_multtindex_by_regex, regex)
        # todo: track and connect transformation and storage amounts separately
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

        self._flow_loop(transformation_supply, final, name, color)

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
        # transformation_demand = transformation[transformation.lt(0)].dropna().mul(-1)
        # self._connect(
        #     transformation_demand,
        #     "SOLIDS_PRIMARY_OUT",
        #     "TRANS_IN",
        # )

        # bypass = (
        #     primary
        #     - transformation_demand.sum().item()
        #     - primary_losses.sum().abs().item()
        # )
        # self._forward(
        #     "SOLIDS_PRIMARY_OUT",
        #     "SOLIDS_BYPASS_IN",
        #     bypass,
        # )
        # self._forward(
        #     "SOLIDS_BYPASS_IN",
        #     "SOLIDS_BYPASS_OUT",
        #     bypass,
        # )
        # self.nodes.at["SOLIDS_BYPASS_IN", "label"] = (
        #     f"{prettify_number(bypass)} {self.unit}"
        # )
        #
        # transformation_supply = transformation[transformation.gt(0)].dropna()
        # assert transformation_supply.empty
        #
        # self._forward(
        #     "SOLIDS_BYPASS_OUT",
        #     "SOLIDS_SECONDARY_IN",
        #     bypass,
        # )

        secondary = transformation_supply.sum() + bypass
        self._flow_secondary(secondary.item(), name)
        # self._forward(
        #     "SOLIDS_SECONDARY_IN",
        #     "SOLIDS_SECONDARY_OUT",
        #     secondary,
        # )
        # self.nodes.at["SOLIDS_SECONDARY_IN", "label"] = (
        #     f"{prettify_number(secondary)} {self.unit}"
        # )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()
        self._flow_sector(final, "industry", name, "INDUSTRY")
        self._flow_sector(final, "Foreign|Domestic", name, "EXPORT", append_label=True)
        self._flow_sector(final, "rural|decentral", name, "HH_SERVICES")
        # industry = final.filter(like="industry", axis=0)
        # self._connect(
        #     industry,
        #     "SOLIDS_SECONDARY_OUT",
        #     "INDUSTRY",
        # )

        # export = final.filter(regex="Foreign|Domestic", axis=0)
        # self._connect(
        #     export,
        #     "SOLIDS_SECONDARY_OUT",
        #     "EXPORT",
        # )
        # hh_services = final.filter(regex="rural|decentral", axis=0)
        # self._connect(
        #     hh_services,
        #     "SOLIDS_SECONDARY_OUT",
        #     "HH_SERVICES",
        # )
        # self.nodes.at["EXPORT", "label"] += (
        #     f"<br>{prettify_number(export.sum().item())} {self.unit} Solids"
        # )

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
        # self._connect(import_, "IMPORT", f"{name}_PRIMARY_IN", color=color)
        # self.nodes.at["IMPORT", "label"] += (
        #     f"<br>{prettify_number(import_.sum().item())} {self.unit} {name.title()}"
        # )
        self._flow_primary(import_, name)
        # primary = import_.sum().item()
        # self._forward(
        #     f"{name}_PRIMARY_IN",
        #     f"{name}_PRIMARY_OUT",
        #     primary,
        # )
        # self.nodes.at[f"{name}_PRIMARY_IN", "label"] = (
        #     f"{prettify_number(primary)} {self.unit}"
        # )
        #
        transformation = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            component="Link",
        ).pipe(
            drop_from_multtindex_by_regex,
            "Foreign|Domestic|decentral|rural|industry|shipping|agriculture|transport|aviation",
        )

        transformation_demand = self._flow_transformation_in(transformation, name)
        transformation_supply = self._flow_transformation_out(transformation, name)
        #
        # transformation_demand = transformation[transformation.lt(0)].dropna().mul(-1)
        # self._connect(
        #     transformation_demand,
        #     f"{name}_PRIMARY_OUT",
        #     "TRANS_IN",
        # )
        bypass = import_.sum() - transformation_demand.sum()
        self._flow_bypass(bypass.item(), name)
        # self._forward(
        #     f"{name}_PRIMARY_OUT",
        #     f"{name}_BYPASS_IN",
        #     bypass.item(),
        # )
        # self._forward(
        #     f"{name}_BYPASS_IN",
        #     f"{name}_BYPASS_OUT",
        #     bypass,
        # )
        # self.nodes.at[f"{name}_BYPASS_IN", "label"] = (
        #     f"{prettify_number(bypass)} {self.unit}"
        # )
        #
        # transformation_supply = transformation[transformation.gt(0)].dropna()
        # self._connect(
        #     transformation_supply,
        #     "TRANS_OUT",
        #     f"{name}_SECONDARY_IN",
        #     color=color,
        # )
        #
        # self._forward(f"{name}_BYPASS_OUT", f"{name}_SECONDARY_IN", bypass)

        secondary = transformation_supply.sum() + bypass.sum()
        self._flow_secondary(secondary.item(), name)
        # self._forward(f"{name}_SECONDARY_IN", f"{name}_SECONDARY_OUT", secondary)
        # self.nodes.at[f"{name}_SECONDARY_IN", "label"] = (
        #     f"{prettify_number(secondary)} {self.unit}"
        # )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()
        self._flow_sector(final, "industry", name, "INDUSTRY")
        export = final.filter(regex="Foreign|Domestic", axis=0).drop(
            "NH3", level="bus_carrier", errors="ignore"
        )
        self._flow_sector(export, r"[*az,AZ,\s]", name, "EXPORT", append_label=True)
        self._flow_sector(final, "rural|decentral", name, "HH_SERVICES")
        self._flow_sector(final, "transport|shipping|aviation", name, "TRANSPORT")
        self._flow_sector(final, "agriculture|NH3", name, "AGRICULTURE")

        # industry = final.filter(like="industry", axis=0)
        # self._connect(
        #     industry,
        #     f"{name}_SECONDARY_OUT",
        #     "INDUSTRY",
        # )
        # export = final.filter(regex="Foreign|Domestic", axis=0).drop(
        #     "NH3", level="bus_carrier", errors="ignore"
        # )
        # self._connect(
        #     export,
        #     f"{name}_SECONDARY_OUT",
        #     "EXPORT",
        # )
        # hh_services = final.filter(regex="rural|decentral", axis=0)
        # self._connect(
        #     hh_services,
        #     f"{name}_SECONDARY_OUT",
        #     "HH_SERVICES",
        # )
        # transport = final.filter(regex="transport|shipping|aviation", axis=0)
        # self._connect(
        #     transport,
        #     f"{name}_SECONDARY_OUT",
        #     "TRANSPORT",
        # )
        # agriculture = final.filter(
        #     regex="agriculture|NH3", axis=0
        # )  # todo: review -> assignment of NH3 to agriculture sector. Is that correct?
        # self._connect(
        #     agriculture,
        #     f"{name}_SECONDARY_OUT",
        #     "AGRICULTURE",
        # )
        # self.nodes.at["EXPORT", "label"] += (
        #     f"<br>{prettify_number(export.sum().item())} {self.unit} {name.title()}"
        # )

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
        # self._connect(
        #     import_,
        #     "IMPORT",
        #     "URANIUM_PRIMARY_IN",
        #     color=color,
        # )
        # self.nodes.at["IMPORT", "label"] += (
        #     f"<br>{prettify_number(import_.sum().item())} {self.unit} Uranium"
        # )
        self._flow_primary(import_, name)
        # primary = import_.abs().sum().item()
        # self._forward(
        #     "URANIUM_PRIMARY_IN",
        #     "URANIUM_PRIMARY_OUT",
        #     primary,
        # )
        # self.nodes.at["URANIUM_PRIMARY_IN", "label"] = (
        #     f"{prettify_number(primary)} {self.unit}"
        # )

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
        color = self.nodes.loc[f"{name}_PRIMARY_IN", "color"]

        generation = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Generator", "Link"]
        ).filter(regex="solar thermal|ambient heat", axis=0)

        self._connect(generation, "HEAT", "HEAT_PRIMARY_IN", color=color)

        primary = generation.sum().item()
        self._forward(
            f"{name}_PRIMARY_IN",
            f"{name}_PRIMARY_OUT",
            primary,
        )
        self.nodes.at[f"{name}_PRIMARY_IN", "label"] = (
            f"{prettify_number(primary)} {self.unit}"
        )

        transformation = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            component="Link",
        ).pipe(
            drop_from_multtindex_by_regex,
            "decentral|rural|industry|agriculture|DAC",
        )

        storage_demand = transformation[transformation.lt(0)].dropna().mul(-1)
        central_heat = generation.filter(like=" central ", axis=0)
        transformation_demand = pd.concat([storage_demand, central_heat])
        self._connect(
            transformation_demand,
            f"{name}_PRIMARY_OUT",
            "TRANS_IN",
        )

        bypass = primary - transformation_demand.sum().item()
        self._forward(
            f"{name}_PRIMARY_OUT",
            f"{name}_BYPASS_IN",
            bypass,
        )
        self._forward(
            f"{name}_BYPASS_IN",
            f"{name}_BYPASS_OUT",
            bypass,
        )
        self.nodes.at[f"{name}_BYPASS_IN", "label"] = (
            f"{prettify_number(bypass)} {self.unit}"
        )

        storage_supply = transformation[transformation.gt(0)].dropna()
        transformation_supply = pd.concat([storage_supply, central_heat])
        self._connect(
            transformation_supply,
            "TRANS_OUT",
            f"{name}_SECONDARY_IN",
            color=color,
        )

        self._forward(f"{name}_BYPASS_OUT", f"{name}_SECONDARY_IN", bypass)

        secondary = transformation_supply.sum().item() + bypass
        self._forward(f"{name}_SECONDARY_IN", f"{name}_SECONDARY_OUT", secondary)
        self.nodes.at[f"{name}_SECONDARY_IN", "label"] = (
            f"{prettify_number(secondary)} {self.unit}"
        )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()

        industry = final.filter(like="industry", axis=0)
        self._connect(
            industry,
            f"{name}_SECONDARY_OUT",
            "INDUSTRY",
        )
        dac = final.filter(regex="DAC", axis=0)
        self._connect(
            dac,
            f"{name}_SECONDARY_OUT",
            "INDUSTRY",
        )
        agriculture = final.filter(regex="agriculture", axis=0)
        self._connect(
            agriculture,
            f"{name}_SECONDARY_OUT",
            "AGRICULTURE",
        )

        # todo: heat storage losses
        # todo: decentral heat distribution losses

        vents = final.filter(like="heat vent", axis=0)
        self._connect(
            vents,
            f"{name}_SECONDARY_OUT",
            "DIST_LOSS",
            color=COLOUR.grey_neutral,
        )

        hh_services = (
            secondary - industry.sum() - dac.sum() - vents.sum() - agriculture.sum()
        ).item()
        if hh_services <= 0:
            # some amounts of gas/electricity/solid biomass for heat are for agriculture
            logger.warning(
                f"Negative remaining Heat Load detected in "
                f"{self.location} and year {self.year}:\n{hh_services}"
            )
            # assuming that electricity supplies these amounts to the largest load
        self._forward(f"{name}_SECONDARY_OUT", "HH_SERVICES", hh_services)

        # decentral heat technologies connect to FED via their input
        # bus_carrier because this form of energy is metered. central Load
        # also needs to be dropped.
        to_drop = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Link", "Load"]
        ).filter(regex="decentral|rural|central", axis=0)
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
        regex = (
            "rural|decentral|gas for industry CC"  # todo: respect those in FED charts
        )
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
                print(
                    f"Warning[{self.location} {self.year}]: {node} has a discrepancy of {diff:.2f} {self.unit}"
                )

    def fix_node_y_positions(self):
        # get max column size
        # scale all y ranks to that size
        if not self.has_loop:
            # let the plotly node alignment algorithm handle y position adjustments
            return
        # x = self.nodes.at["TRANS_OUT", "x"]
        # nodes = self.nodes.query("x == @x")
        # flows = filter_by(self.flows, source=nodes.index.tolist())
        # total_flow = flows["value"].sum()
        # padding = self.pad * (flows.shape[0] - 1)  # in px
        # # x and y are from the top-left canvas corner. We want to position
        # # the transformation box at 95% y and the same x.
        # needed_space = (total_flow + padding) * (1 / 0.95)
        # scale all other columns to that size

        # scale all y values to 95% of max per column
        to_concat = []
        for x, nodes in self.nodes.groupby("x"):
            nodes["y"] /= nodes["y"].max() / 0.95
            to_concat.append(nodes)
        self.nodes = pd.concat(to_concat)

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
        customdata += f"<br><b>Total: {prettify_number(value)} {self.unit}</b>"

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
        if has_loop := (loop > 0):
            self.has_loop = has_loop
            # Some amounts from transformation output are not FED. Those
            # amounts are looped in the transformation input side.
            self._forward("TRANS_OUT", "TRANS_IN", loop, color=color)
            # self._forward("LOOP_OUT", "LOOP_IN", loop, color=color)
            # self._forward("TRANS_IN", "LOOP_IN", loop, color=color)
            # subtract loop from PRIMARY_OUT to TRANSFORM_IN
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
        self._connect(
            demand,
            f"{name}_SECONDARY_OUT",
            sector,
        )
        value = demand.sum().item()
        if append_label and value > 0.05:
            self.nodes.at["EXPORT", "label"] += (
                f"<br>{prettify_number(value)} {self.unit} {name.title()}"
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
            # font_family="Calibri",
            plot_bgcolor="#ffffff",
            legend_title_text=self.cfg.legend_header,
        )
        # update axes
        self.fig.update_yaxes(
            showgrid=self.cfg.yaxes_showgrid, visible=self.cfg.yaxes_visible
        )
        self.fig.update_layout(
            xaxis={"categoryorder": "category ascending"},
            # hovermode="x",  # show all categories on mouse-over
        )
        # trace order always needs to be reversed to show correct order
        # of legend entries for relative bar charts
        self.fig.update_layout(legend={"traceorder": "reversed"})

        # export the metadata directly in the Layout property for JSON
        self.fig.update_layout(meta=[RUN_META_DATA])

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
        # todo: clean up
        # return carrier + " " * padding + f"{prettify_number(value)} {unit}"
        return f"{prettify_number(value)} {unit} {carrier}"
