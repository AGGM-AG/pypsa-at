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
    name: i / 10
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

# BUS_CARRIER_COLORS = {
#     "biogas": COLOUR.green_sage,
#     "coal": COLOUR.grey_dark,
#     "H2": COLOUR.green_mint,
#     "NH3": COLOUR.yellow_canary,
#     "lignite": COLOUR.brown_dark,
#     "gas": COLOUR.brown_light,
#     "municipal solid waste": COLOUR.grey_light,
#     "AC": COLOUR.blue_celestial,
#     "oil primary": COLOUR.red_deep,
#     "rural heat": COLOUR.yellow_golden,
#     "low voltage": COLOUR.blue_celestial,
#     "solid biomass": COLOUR.green_sage,
#     "uranium": COLOUR.orange_mellow,
#     "urban central heat": COLOUR.yellow_golden,
#     "urban decentral heat": COLOUR.yellow_golden,
#     "EV battery": COLOUR.blue_celestial,
#     "methanol": COLOUR.salmon,
#     "oil": COLOUR.red_deep,
#     "non-sequestered HVC": COLOUR.grey_light,
#     "agriculture machinery oil": COLOUR.red_deep,
#     "battery": COLOUR.blue_celestial,
#     "ambient heat": COLOUR.yellow_golden,
#     "home battery": COLOUR.blue_celestial,
#     "industry methanol": COLOUR.salmon,
#     "kerosene for aviation": COLOUR.red_deep,
#     "shipping methanol": COLOUR.salmon,
#     "gas for industry": COLOUR.brown_light,
#     "naphtha for industry": COLOUR.red_deep,
#     "solid biomass for industry": COLOUR.green_sage,
#     "rural water tanks": COLOUR.yellow_golden,
#     "urban central water pits": COLOUR.yellow_golden,
#     "urban central water tanks": COLOUR.yellow_golden,
#     "urban decentral water tanks": COLOUR.yellow_golden,
#     # Grouped colors
#     "Liquids": COLOUR.red_deep,
#     "Solids": COLOUR.green_sage,
#     "Gas": COLOUR.brown_light,
#     "Heat": COLOUR.yellow_golden,
#     "Waste": COLOUR.grey_light,
# }


NODE_DATA = [  # id, label, x, y
    ["IMPORT", "Import", COLOUR.black, 0.01, 0.1],
    ["WIND", "Wind Power", COLOUR.black, 0.01, 0.3],
    ["SOLAR", "Solar Power", COLOUR.black, 0.01, 0.5],
    ["HYDRO", "Hydro Power", COLOUR.black, 0.01, 0.6],
    ["BIOGAS", "Biogas", COLOUR.black, 0.01, 0.7],
    ["SOLIDS", "Solids", COLOUR.black, 0.01, 0.75],
    ["LIQUIDS", "Liquids", COLOUR.black, 0.01, 0.8],
    ["HEAT", "Ambient Heat", COLOUR.black, 0.01, 0.85],
    ["TRANS_IN", "Transformation<br>& Storage", COLOUR.salmon, 0.4, 0.9],
    ["TRANS_OUT", "", COLOUR.salmon, 0.6, 0.9],
    ["INDUSTRY", "Industry", COLOUR.black, 0.99, 0.5],
    ["HH_SERVICES", "Households & Services", COLOUR.black, 0.99, 0.3],
    ["EXPORT", "Export", COLOUR.black, 0.99, 0.01],
    ["TRANSPORT", "Transport", COLOUR.black, 0.99, 0.6],
    ["AGRICULTURE", "Agriculture", COLOUR.black, 0.99, 0.8],
    ["UNUSED", "Ressource Losses", COLOUR.grey_deep, 0.35, 0.99],
    ["TRANS_LOSS", "Transformation Losses", COLOUR.grey_deep, 0.65, 0.99],
    ["DIST_LOSS", "Distribution Losses", COLOUR.grey_deep, 0.8, 0.99],
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

        # temporary cache to store variables between method calls
        self.cache = {}

    def plot(self):
        # plotly draws traces connected first in the background.
        self.connect_methane()
        self.connect_hydrogen()
        self.connect_electricity()
        self.connect_biogas()
        self.connect_liquids()
        self.connect_solids()
        self.connect_uranium()
        # must connect heat last to know FED
        self.connect_heat()

        self.forward_transformation()
        self.connect_transformation_losses()
        # self.check_nodal_balance()
        # self.calculate_node_y_positions()

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
            ]
        )

        title = self.cfg.title.format(location=self.location, unit=self.year)
        self.fig.update_layout(title=dict(text=title))

        self._set_base_layout()

        # import plotly.io as pio
        # pio.show(self.fig)

    def connect_electricity(self):
        bus_carrier = ["AC", "low voltage"]  # ignoring battery, home battery buses
        import_ = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            carrier=[
                "Import Foreign",
                "Import Domestic",
            ],
        )
        self._connect(
            import_,
            "IMPORT",
            "ELECTRICITY_PRIMARY_IN",
            color=self.nodes.loc["ELECTRICITY_PRIMARY_IN", "color"],
        )
        self.nodes.at["IMPORT", "label"] += (
            f"<br>{prettify_number(import_.sum().item())} {self.unit} Electricity"
        )

        generation = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Generator", "StorageUnit"]
        )
        wind = generation.filter(like="wind", axis=0)
        self._connect(
            wind,
            "WIND",
            "ELECTRICITY_PRIMARY_IN",
            color=COLOUR.blue_sky,
        )
        solar = generation.filter(like="solar", axis=0)
        self._connect(
            solar,
            "SOLAR",
            "ELECTRICITY_PRIMARY_IN",
            color=COLOUR.yellow_canary,
        )
        hydro = generation.filter(regex="ror|hydro", axis=0)
        self._connect(
            hydro,
            "HYDRO",
            "ELECTRICITY_PRIMARY_IN",
            color=COLOUR.blue_pastel,
        )

        primary = pd.concat([import_, wind, solar, hydro]).sum().item()
        self._forward(
            "ELECTRICITY_PRIMARY_IN",
            "ELECTRICITY_PRIMARY_OUT",
            primary,
        )
        self.nodes.at["ELECTRICITY_PRIMARY_IN", "label"] = (
            f"{prettify_number(primary)} {self.unit}"
        )

        transformation = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            component=["Link", "Store", "StorageUnit"],
        ).pipe(
            drop_from_multtindex_by_regex,
            "Foreign|Domestic|hydro|decentral|rural",
        )

        transformation_demand = transformation[transformation.lt(0)].dropna().mul(-1)

        # harmonize V2G and hide EV battery to connect electricity demand
        # for transport directly without storage. Increase BEV charger by
        # V2G supply. The BEV Charger will serve as the Transport sectoral
        # demand, effectively hiding the storage systems for EV.
        v2g_demand = transformation.query("carrier == 'V2G'").rename(
            {"V2G": "V2G demand"}
        )
        # bev_charger = transformation_demand.query("carrier == 'BEV charger'")
        # increase BEV charger withdrawal by V2G amounts and drop it from
        # transformation demand since its transport load
        bev = ("Link", "BEV charger", "low voltage")
        transformation_demand.drop(bev, inplace=True)
        if not v2g_demand.empty:
            self._df.loc[bev, "value"] -= v2g_demand["value"].item()
            # add V2G as a transformation (storage) demand
            transformation_demand = pd.concat([transformation_demand, v2g_demand])

        self._connect(
            transformation_demand,
            "ELECTRICITY_PRIMARY_OUT",
            "TRANS_IN",
        )

        bypass = primary - transformation_demand.sum()
        self._forward(
            "ELECTRICITY_PRIMARY_OUT",
            "ELECTRICITY_BYPASS_IN",
            bypass.item(),
        )
        self._forward(
            "ELECTRICITY_BYPASS_IN",
            "ELECTRICITY_BYPASS_OUT",
            bypass.item(),
        )
        self.nodes.at["ELECTRICITY_BYPASS_IN", "label"] = (
            f"{prettify_number(bypass.item())} {self.unit}"
        )

        transformation_supply = transformation[transformation.gt(0)].dropna()
        self._connect(
            transformation_supply,
            "TRANS_OUT",
            "ELECTRICITY_SECONDARY_IN",
            color=self.nodes.loc["ELECTRICITY_PRIMARY_IN", "color"],
        )
        self._forward(
            "ELECTRICITY_BYPASS_OUT",
            "ELECTRICITY_SECONDARY_IN",
            bypass.item(),
        )

        secondary = transformation_supply.sum() + bypass
        self._forward(
            "ELECTRICITY_SECONDARY_IN",
            "ELECTRICITY_SECONDARY_OUT",
            secondary.item(),
        )
        self.nodes.at["ELECTRICITY_SECONDARY_IN", "label"] = (
            f"{prettify_number(secondary.item())} {self.unit}"
        )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()

        industry = final.filter(like="industry", axis=0)
        self._connect(
            industry,
            "ELECTRICITY_SECONDARY_OUT",
            "INDUSTRY",
        )
        export = final.filter(regex="Foreign|Domestic", axis=0)
        self._connect(
            export,
            "ELECTRICITY_SECONDARY_OUT",
            "EXPORT",
        )
        transport = final.filter(like="BEV charger", axis=0)
        bev_charger_losses = filter_by(
            self._df, carrier="BEV charger", bus_carrier="low voltage losses"
        )
        self._connect(
            pd.concat([transport, bev_charger_losses]),
            "ELECTRICITY_SECONDARY_OUT",
            "TRANSPORT",
        )
        agriculture = final.filter(like="agriculture", axis=0)
        self._connect(
            agriculture,
            "ELECTRICITY_SECONDARY_OUT",
            "AGRICULTURE",
        )
        hh_services_heat = final.filter(regex="rural|decentral", axis=0)
        self.cache["electricity_for_heat"] = hh_services_heat
        base_load = final.filter(like="'electricity'", axis=0)
        self._connect(
            pd.concat([hh_services_heat, base_load]),
            "ELECTRICITY_SECONDARY_OUT",
            "HH_SERVICES",
        )
        self.nodes.at["EXPORT", "label"] += (
            f"<br>{prettify_number(export.sum().item())} {self.unit} Electricity"
        )

        remaining = filter_by(self._df, bus_carrier=bus_carrier)
        assert remaining.empty, (
            f"Missing amounts detected for location "
            f"{self.location} and year {self.year}:\n{remaining}"
        )

        distribution_grid_losses = filter_by(
            self._df, carrier="electricity distribution grid"
        )
        self._connect(
            distribution_grid_losses,
            "ELECTRICITY_SECONDARY_OUT",
            "DIST_LOSS",
            color=COLOUR.grey_neutral,
        )

    def connect_hydrogen(self):
        bus_carrier = "H2"
        color = self.nodes.loc["HYDROGEN_PRIMARY_IN", "color"]
        import_ = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            carrier=[
                "Import Foreign",
                "Import Domestic",
                "import H2",
            ],
        )
        self._connect(
            import_,
            "IMPORT",
            "HYDROGEN_PRIMARY_IN",
            color=color,
        )
        self.nodes.at["IMPORT", "label"] += (
            f"<br>{prettify_number(import_.sum().item())} {self.unit} Hydrogen"
        )

        primary = import_.sum().item()
        self._forward(
            "HYDROGEN_PRIMARY_IN",
            "HYDROGEN_PRIMARY_OUT",
            primary,
        )
        self.nodes.at["HYDROGEN_PRIMARY_IN", "label"] = (
            f"{prettify_number(primary)} {self.unit}"
        )

        transformation = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Link", "Store"]
        ).pipe(
            drop_from_multtindex_by_regex,
            "Foreign|Domestic|h2 for industry|decentral|rural",
        )
        transformation_demand = transformation[transformation.lt(0)].dropna().mul(-1)
        self._connect(
            transformation_demand,
            "HYDROGEN_PRIMARY_OUT",
            "TRANS_IN",
        )

        bypass = primary - transformation_demand.sum()
        self._forward(
            "HYDROGEN_PRIMARY_OUT",
            "HYDROGEN_BYPASS_IN",
            bypass.item(),
        )
        self._forward(
            "HYDROGEN_BYPASS_IN",
            "HYDROGEN_BYPASS_OUT",
            bypass.item(),
        )
        self.nodes.at["HYDROGEN_BYPASS_IN", "label"] = (
            f"{prettify_number(bypass.item())} {self.unit}"
        )

        transformation_supply = transformation[transformation.gt(0)].dropna()
        self._connect(
            transformation_supply,
            "TRANS_OUT",
            "HYDROGEN_SECONDARY_IN",
            color=self.nodes.loc["HYDROGEN_PRIMARY_IN", "color"],
        )
        self._forward(
            "HYDROGEN_BYPASS_OUT",
            "HYDROGEN_SECONDARY_IN",
            bypass.item(),
        )

        secondary = transformation_supply.sum() + bypass
        self._forward(
            "HYDROGEN_SECONDARY_IN",
            "HYDROGEN_SECONDARY_OUT",
            secondary.item(),
        )
        self._set_node_label("HYDROGEN_SECONDARY_IN", secondary.item())
        # self.nodes.at["HYDROGEN_SECONDARY_IN", "label"] = (
        #     f"{prettify_number(secondary.item())} {self.unit}"
        # )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()

        loop = (transformation_supply.sum() - final.sum()).item()
        if loop > 0:
            # Some amounts from transformation output are not FED. Those
            # amounts are looped in the transformation input side.
            self._forward("TRANS_OUT", "TRANS_IN", loop, color=color)
            # subtract loop from PRIMARY_OUT to TRANSFORM_IN
            if ("HYDROGEN_PRIMARY_OUT", "TRANS_IN") in self.flows.index:
                self.flows.at[("HYDROGEN_PRIMARY_OUT", "TRANS_IN"), "value"] -= loop
            if ("TRANS_OUT", "HYDROGEN_SECONDARY_IN") in self.flows.index:
                self.flows.at[("TRANS_OUT", "HYDROGEN_SECONDARY_IN"), "value"] -= loop

        industry = final.filter(like="industry", axis=0)
        self._connect(
            industry,
            "HYDROGEN_SECONDARY_OUT",
            "INDUSTRY",
        )
        hh_services = final.filter(regex="rural|decentral", axis=0)
        self.cache["hydrogen_for_heat"] = hh_services
        self._connect(
            hh_services,
            "HYDROGEN_SECONDARY_OUT",
            "HH_SERVICES",
        )
        export = final.filter(regex="Foreign|Domestic", axis=0)
        self._connect(
            export,
            "HYDROGEN_SECONDARY_OUT",
            "EXPORT",
        )
        transport = final.filter(regex="transport", axis=0)
        self._connect(
            transport,
            "HYDROGEN_SECONDARY_OUT",
            "TRANSPORT",
        )
        self.nodes.at["EXPORT", "label"] += (
            f"<br>{prettify_number(export.sum().item())} {self.unit} Hydrogen"
        )

        remaining = filter_by(self._df, bus_carrier=bus_carrier)
        assert remaining.empty, (
            f"Missing amounts detected for location "
            f"{self.location} and year {self.year}:\n{remaining}"
        )

    def connect_methane(self):
        bus_carrier = "gas"
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
        self._connect(
            import_,
            "IMPORT",
            "METHANE_PRIMARY_IN",
            color=self.nodes.loc["METHANE_PRIMARY_IN", "color"],
        )
        self.nodes.at["IMPORT", "label"] += (
            f"<br>{prettify_number(import_.sum().item())} {self.unit} Methane"
        )

        gas_primary = import_.sum().item()
        self._forward(
            "METHANE_PRIMARY_IN",
            "METHANE_PRIMARY_OUT",
            gas_primary,
        )
        self.nodes.at["METHANE_PRIMARY_IN", "label"] = (
            f"{prettify_number(gas_primary)} {self.unit}"
        )

        transform_gas = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Link", "Store"]
        ).pipe(
            drop_from_multtindex_by_regex,
            "Foreign|Domestic|gas for industry|decentral|rural",
        )
        transformation_gas_demand = transform_gas[transform_gas.lt(0)].dropna().mul(-1)
        self._connect(
            transformation_gas_demand,
            "METHANE_PRIMARY_OUT",
            "TRANS_IN",
        )

        bypass_gas = gas_primary - transformation_gas_demand.sum()
        self._forward(
            "METHANE_PRIMARY_OUT",
            "METHANE_BYPASS_IN",
            bypass_gas.item(),
        )
        self._forward(
            "METHANE_BYPASS_IN",
            "METHANE_BYPASS_OUT",
            bypass_gas.item(),
        )
        self.nodes.at["METHANE_BYPASS_IN", "label"] = (
            f"{prettify_number(bypass_gas.item())} {self.unit}"
        )

        transformation_gas_supply = transform_gas[transform_gas.ge(0)].dropna()
        self._connect(
            transformation_gas_supply,
            "TRANS_OUT",
            "METHANE_SECONDARY_IN",
            color=self.nodes.loc["METHANE_PRIMARY_IN", "color"],
        )
        self._forward(
            "METHANE_BYPASS_OUT",
            "METHANE_SECONDARY_IN",
            bypass_gas.item(),
        )

        secondary = transformation_gas_supply.sum() + bypass_gas
        self._forward(
            "METHANE_SECONDARY_IN",
            "METHANE_SECONDARY_OUT",
            secondary.item(),
        )
        self.nodes.at["METHANE_SECONDARY_IN", "label"] = (
            f"{prettify_number(secondary.item())} {self.unit}"
        )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()

        industry = final.filter(like="industry", axis=0)
        self._connect(
            industry,
            "METHANE_SECONDARY_OUT",
            "INDUSTRY",
        )
        hh_services = final.filter(regex="rural|decentral", axis=0)
        self.cache["gas_for_heat"] = hh_services
        self._connect(
            hh_services,
            "METHANE_SECONDARY_OUT",
            "HH_SERVICES",
        )
        export = final.filter(regex="Foreign|Domestic", axis=0)
        self._connect(
            export,
            "METHANE_SECONDARY_OUT",
            "EXPORT",
        )
        self.nodes.at["EXPORT", "label"] += (
            f"<br>{prettify_number(export.sum().item())} {self.unit} Methane"
        )

        remaining = filter_by(self._df, bus_carrier=bus_carrier)
        assert remaining.empty, (
            f"Missing amounts detected for location "
            f"{self.location} and year {self.year}:\n{remaining}"
        )

    def connect_biogas(self):
        bus_carrier = "biogas"
        generation = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            component="Generator",
        )
        self._connect(
            generation,
            "BIOGAS",
            "BIOGAS_PRIMARY_IN",
            color=self.nodes.loc["BIOGAS_PRIMARY_IN", "color"],
        )
        self._forward(
            "BIOGAS_PRIMARY_IN",
            "BIOGAS_PRIMARY_OUT",
            generation.sum().item(),
        )
        self.nodes.at["BIOGAS_PRIMARY_IN", "label"] = (
            f"{prettify_number(generation.sum().item())} {self.unit}"
        )

        processing = filter_by(self._df, bus_carrier=bus_carrier, component="Link")
        self._connect(
            processing,
            "BIOGAS_PRIMARY_OUT",
            "TRANS_IN",
        )

    def connect_solids(self):
        bus_carrier = [
            "coal",
            "lignite",
            "solid biomass",
            "municipal solid waste",
            "non-sequestered HVC",
        ]
        color = self.nodes.loc["SOLIDS_PRIMARY_IN", "color"]
        import_ = filter_by(
            self._df,
            bus_carrier=bus_carrier,
            carrier=[
                "Import Foreign",
                "Import Domestic",
            ],
        )
        self._connect(import_, "IMPORT", "SOLIDS_PRIMARY_IN", color=color)
        self.nodes.at["IMPORT", "label"] += (
            f"<br>{prettify_number(import_.sum().item())} {self.unit} Solids"
        )

        generation = filter_by(
            self._df, bus_carrier=bus_carrier, component=["Generator", "Store"]
        )
        self._connect(
            generation,
            "SOLIDS",
            "SOLIDS_PRIMARY_IN",
            color=color,
        )

        # HVC to air is an unused resource
        primary_losses = filter_by(
            self._df, bus_carrier=bus_carrier, carrier="HVC to air"
        )
        self._connect(
            primary_losses, "SOLIDS_PRIMARY_OUT", "UNUSED", color=COLOUR.grey_neutral
        )

        primary = pd.concat([import_, generation]).sum().item()
        self._forward(
            "SOLIDS_PRIMARY_IN",
            "SOLIDS_PRIMARY_OUT",
            primary,
        )
        self.nodes.at["SOLIDS_PRIMARY_IN", "label"] = (
            f"{prettify_number(primary)} {self.unit}"
        )

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

        transformation_demand = transformation[transformation.lt(0)].dropna().mul(-1)
        self._connect(
            transformation_demand,
            "SOLIDS_PRIMARY_OUT",
            "TRANS_IN",
        )

        bypass = (
            primary
            - transformation_demand.sum().item()
            - primary_losses.sum().abs().item()
        )
        self._forward(
            "SOLIDS_PRIMARY_OUT",
            "SOLIDS_BYPASS_IN",
            bypass,
        )
        self._forward(
            "SOLIDS_BYPASS_IN",
            "SOLIDS_BYPASS_OUT",
            bypass,
        )
        self.nodes.at["SOLIDS_BYPASS_IN", "label"] = (
            f"{prettify_number(bypass)} {self.unit}"
        )

        transformation_supply = transformation[transformation.gt(0)].dropna()
        assert transformation_supply.empty

        self._forward(
            "SOLIDS_BYPASS_OUT",
            "SOLIDS_SECONDARY_IN",
            bypass,
        )

        secondary = transformation_supply.sum().item() + bypass
        self._forward(
            "SOLIDS_SECONDARY_IN",
            "SOLIDS_SECONDARY_OUT",
            secondary,
        )
        self.nodes.at["SOLIDS_SECONDARY_IN", "label"] = (
            f"{prettify_number(secondary)} {self.unit}"
        )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()

        industry = final.filter(like="industry", axis=0)
        self._connect(
            industry,
            "SOLIDS_SECONDARY_OUT",
            "INDUSTRY",
        )
        export = final.filter(regex="Foreign|Domestic", axis=0)
        self._connect(
            export,
            "SOLIDS_SECONDARY_OUT",
            "EXPORT",
        )
        hh_services = final.filter(regex="rural|decentral", axis=0)
        self.cache["solids_for_heat"] = hh_services
        self._connect(
            hh_services,
            "SOLIDS_SECONDARY_OUT",
            "HH_SERVICES",
        )
        self.nodes.at["EXPORT", "label"] += (
            f"<br>{prettify_number(export.sum().item())} {self.unit} Solids"
        )

        remaining = filter_by(self._df, bus_carrier=bus_carrier)
        assert remaining.empty, (
            f"Missing amounts detected for location "
            f"{self.location} and year {self.year}:\n{remaining}"
        )

    def connect_liquids(self):
        name = "LIQUIDS"
        bus_carrier = [
            "oil",
            "methanol",
            "NH3",
            "electrobiofuels",
        ]
        color = self.nodes.loc[f"{name}_PRIMARY_IN", "color"]
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
        self._connect(import_, "IMPORT", f"{name}_PRIMARY_IN", color=color)
        self.nodes.at["IMPORT", "label"] += (
            f"<br>{prettify_number(import_.sum().item())} {self.unit} {name.title()}"
        )

        primary = import_.sum().item()
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
            "Foreign|Domestic|decentral|rural|industry|shipping|agriculture|transport|aviation",
        )

        transformation_demand = transformation[transformation.lt(0)].dropna().mul(-1)
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

        transformation_supply = transformation[transformation.gt(0)].dropna()
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
        export = final.filter(regex="Foreign|Domestic", axis=0).drop(
            "NH3", level="bus_carrier", errors="ignore"
        )  # fixme: contains NH3
        self._connect(
            export,
            f"{name}_SECONDARY_OUT",
            "EXPORT",
        )
        hh_services = final.filter(regex="rural|decentral", axis=0)
        self.cache["liquids_for_heat"] = hh_services
        self._connect(
            hh_services,
            f"{name}_SECONDARY_OUT",
            "HH_SERVICES",
        )
        transport = final.filter(regex="transport|shipping|aviation", axis=0)
        self._connect(
            transport,
            f"{name}_SECONDARY_OUT",
            "TRANSPORT",
        )
        agriculture = final.filter(
            regex="agriculture|NH3", axis=0
        )  # todo: review -> assignment of NH3 to agriculture sector. Is that correct?
        self._connect(
            agriculture,
            f"{name}_SECONDARY_OUT",
            "AGRICULTURE",
        )
        self.nodes.at["EXPORT", "label"] += (
            f"<br>{prettify_number(export.sum().item())} {self.unit} {name.title()}"
        )

        stores = filter_by(self._df, bus_carrier=bus_carrier, component="Store")
        assert stores.sum().abs().item() < 1e-6
        self._df.drop(stores.index, inplace=True)

        remaining = filter_by(self._df, bus_carrier=bus_carrier)
        assert remaining.empty, (
            f"Missing amounts detected for location "
            f"{self.location} and year {self.year}:\n{remaining}"
        )

    def connect_uranium(self):
        bus_carrier = "uranium"
        color = self.nodes.loc["URANIUM_PRIMARY_IN", "color"]

        # abusing nuclear PP demand as regional uranium import
        import_ = filter_by(self._df, bus_carrier=bus_carrier, carrier="nuclear").mul(
            -1
        )
        self._connect(
            import_,
            "IMPORT",
            "URANIUM_PRIMARY_IN",
            color=color,
        )
        self.nodes.at["IMPORT", "label"] += (
            f"<br>{prettify_number(import_.sum().item())} {self.unit} Uranium"
        )

        primary = import_.abs().sum().item()
        self._forward(
            "URANIUM_PRIMARY_IN",
            "URANIUM_PRIMARY_OUT",
            primary,
        )
        self.nodes.at["URANIUM_PRIMARY_IN", "label"] = (
            f"{prettify_number(primary)} {self.unit}"
        )
        self._forward(
            "URANIUM_PRIMARY_OUT",
            "TRANS_IN",
            primary,
        )

        if self.location == "Europe":
            to_drop = filter_by(
                self._df, bus_carrier=bus_carrier, component=["Generator", "Store"]
            )
            self._df.drop(to_drop.index, inplace=True)

        remaining = filter_by(self._df, bus_carrier=bus_carrier)
        assert remaining.empty, (
            f"Missing amounts detected for location "
            f"{self.location} and year {self.year}:\n{remaining}"
        )

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

        # todo: decentral heat distribution losses

        vents = final.filter(like="heat vent", axis=0)
        self._connect(
            vents,
            f"{name}_SECONDARY_OUT",
            "DIST_LOSS",
            color=COLOUR.grey_neutral,
        )

        # heat_loads = filter_by(self._df, bus_carrier=bus_carrier, component="Load")
        # # some heat amounts are metered as electricity, gas, solid biomass, etc.
        # # those amounts must be subtracted from the Load. We connect the Load
        # # component here to check the calculation (We could simply forward all
        # # remaining heat from Secondary Out to Final, but that easily hides bugs).
        # heat_fed = pd.concat(
        #     [
        #         self.cache["gas_for_heat"],
        #         self.cache["electricity_for_heat"],
        #         self.cache["hydrogen_for_heat"],
        #         self.cache["liquids_for_heat"],
        #         self.cache["solids_for_heat"],
        #     ]
        # )
        # load_split = heat_loads / heat_loads.sum()
        # already_delivered = load_split * heat_fed.sum()
        # heat_hh_services = heat_loads.add(already_delivered, fill_value=0)
        hh_services = (
            secondary - industry.sum() - dac.sum() - vents.sum() - agriculture.sum()
        ).item()
        if hh_services <= 0:
            # some amounts of gas/electricity/solid biomass for heat are for agriculture
            logger.warning(
                f"Negative remaining Heat Load detected in "
                f"{self.location} and year {self.year}:\n{hh_services}"
            )
        # assert hh_services >= 0, (
        #     f"Negative remaining Heat Load detected in {self.location} and year {self.year}:\n{hh_services}"
        # )
        # self._connect(
        #     heat_hh_services,
        #     f"{name}_SECONDARY_OUT",
        #     "HH_SERVICES",
        # )
        self._forward(f"{name}_SECONDARY_OUT", "HH_SERVICES", hh_services)
        # hh_services = final.filter(regex="rural|decentral", axis=0)

        # some technologies are connected to FED via their input
        # bus_carrier because this form of energy is metered
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
        losses = filter_by(self._df, bus_carrier=bus_carrier)
        # todo: must exclude rural/decentral losses
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
        to_sankey_groups = {
            item: key for key, values in GROUPS.items() for item in values
        }
        losses = losses.pipe(rename_aggregate, to_bus_carrier).pipe(
            rename_aggregate, to_sankey_groups
        )
        self._connect(
            losses,
            "TRANS_OUT",
            "TRANS_LOSS",
            color=COLOUR.grey_neutral,
        )

    def _connect(self, df, source, target, color: str = None):
        value = df.abs().sum().item()
        if value < self.cfg.cutoff:
            self._df.drop(df.index, inplace=True, errors="ignore")
            return

        df = df.sort_values(by="value", ascending=False)
        customdata = "<br>".join(
            [
                f"{c}: {prettify_number(v)} {self._df.attrs['unit']}"
                for c, v in zip(df.index.get_level_values("carrier"), df["value"])
                if prettify_number(v) != "0.0"
            ]
        )
        customdata += f"<br><br><b>Total: {prettify_number(value)} {self.unit}</b>"

        # add a row with the link's value
        self.flows.loc[(source, target), self.flows.columns] = [
            value,
            color or self.nodes.loc[source, "color"],
            customdata,
        ]
        # drop from the original dataframe
        self._df.drop(df.index, inplace=True, errors="ignore")

    def _forward(self, source, target, value, color: str = None):
        if value < self.cfg.cutoff:
            return
        self.flows.loc[(source, target), self.flows.columns] = [
            value,
            color or self.nodes.loc[source, "color"],
            f"{prettify_number(value)} {self._df.attrs['unit']}",
        ]

    def _set_node_label(self, idx, value, name="", append=False):
        if idx not in self.nodes.index:
            return

        if append:
            self.nodes.at[idx, "label"] += (
                f"<br>{prettify_number(value)} {self.unit} {name}"
            )
        else:
            self.nodes.at[idx, "label"] = f"{prettify_number(value)} {self.unit}"

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
            if abs(diff) > 1e-5:
                print(
                    f"Warning[{self.location} {self.year}]: {node} has a discrepancy of {diff:.2f} {self.unit}"
                )

    # def calculate_node_y_positions(self):
    #     # cols = [*self.nodes.sort_values(by="y_rank").groupby("x")]
    #     for x, node_col in self.nodes.groupby("x"):
    #         for name in node_col.index:
    #             pass
    #             size = "max from left and right side"
    #             print(name)
    #         # print(node)
    #         src = filter_by(self.flows, source=self.nodes.index.tolist())
    #         dst = filter_by(self.flows, target=self.nodes.index.tolist())
    #         if not src.empty and not dst.empty:
    #             size = (src["value"].sum() + dst["value"].sum()) / 2
    #         elif not src.empty:
    #             size = src["value"].sum()
    #         elif not dst.empty:
    #             size = dst["value"].sum()

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
