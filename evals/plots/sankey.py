# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Module for Sankey diagram."""

import dataclasses

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
import enum
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
)


@dataclasses.dataclass
class Node:
    label: str
    color: str
    # bus_carrier: tuple


class Nodes(enum.Enum):
    WASTE = Node("Waste", COLOUR.grey_light)
    IMPORT = Node("Import", COLOUR.black)
    GAS_PRIMARY_IN = Node("Gas Primary In", COLOUR.brown)


BUS_CARRIER_GROUPS = {
    "biogas": "Biogas",
    "coal": "Solids",
    "H2": "Hydrogen",
    "NH3": "Liquids",
    "lignite": "Solids",
    "gas": "Methane",
    "municipal solid waste": "Solids",
    "AC": "Electricity",
    "oil primary": "Liquids",
    "rural heat": "Heat",
    "low voltage": "Electricity",
    "solid biomass": "Solids",
    "uranium": "Uranium",
    "urban central heat": "Heat",
    "urban decentral heat": "Heat",
    "EV battery": "Electricity",
    "methanol": "Liquids",
    "oil": "Liquids",
    "non-sequestered HVC": "Solids",
    "agriculture machinery oil": "Liquids",
    "battery": "Electricity",
    "ambient heat": "Heat",
    "home battery": "Electricity",
    "industry methanol": "Liquids",
    "kerosene for aviation": "Liquids",
    "shipping methanol": "Liquids",
    "gas for industry": "Methane",
    "naphtha for industry": "Liquids",
    "solid biomass for industry": "Solids",
    "rural water tanks": "Heat",
    "urban central water pits": "Heat",
    "urban central water tanks": "Heat",
    "urban decentral water tanks": "Heat",
}

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
    "Electricity": 0.1,  # zero is reserved for Transformation
    "Methane": 0.3,
    "Hydrogen": 0.4,
    "Heat": 0.5,
    "Solids": 0.6,
    "Liquids": 0.7,
    "Biogas": 0.8,
    "Uranium": 0.9,
}
GROUP_X = {
    ("PRIMARY", "IN"): 0.25,
    ("PRIMARY", "OUT"): 0.3,
    ("BYPASS", "IN"): 0.4,
    ("BYPASS", "OUT"): 0.6,
    ("SECONDARY", "IN"): 0.7,
    ("SECONDARY", "OUT"): 0.75,
}

BUS_CARRIER_COLORS = {
    "biogas": COLOUR.green_sage,
    "coal": COLOUR.grey_dark,
    "H2": COLOUR.green_mint,
    "NH3": COLOUR.yellow_canary,
    "lignite": COLOUR.brown_dark,
    "gas": COLOUR.brown_light,
    "municipal solid waste": COLOUR.grey_light,
    "AC": COLOUR.blue_celestial,
    "oil primary": COLOUR.red_deep,
    "rural heat": COLOUR.yellow_golden,
    "low voltage": COLOUR.blue_celestial,
    "solid biomass": COLOUR.green_sage,
    "uranium": COLOUR.orange_mellow,
    "urban central heat": COLOUR.yellow_golden,
    "urban decentral heat": COLOUR.yellow_golden,
    "EV battery": COLOUR.blue_celestial,
    "methanol": COLOUR.salmon,
    "oil": COLOUR.red_deep,
    "non-sequestered HVC": COLOUR.grey_light,
    "agriculture machinery oil": COLOUR.red_deep,
    "battery": COLOUR.blue_celestial,
    "ambient heat": COLOUR.yellow_golden,
    "home battery": COLOUR.blue_celestial,
    "industry methanol": COLOUR.salmon,
    "kerosene for aviation": COLOUR.red_deep,
    "shipping methanol": COLOUR.salmon,
    "gas for industry": COLOUR.brown_light,
    "naphtha for industry": COLOUR.red_deep,
    "solid biomass for industry": COLOUR.green_sage,
    "rural water tanks": COLOUR.yellow_golden,
    "urban central water pits": COLOUR.yellow_golden,
    "urban central water tanks": COLOUR.yellow_golden,
    "urban decentral water tanks": COLOUR.yellow_golden,
    # Grouped colors
    "Liquids": COLOUR.red_deep,
    "Solids": COLOUR.green_sage,
    "Gas": COLOUR.brown_light,
    "Heat": COLOUR.yellow_golden,
    "Waste": COLOUR.grey_light,
}


NODE_DATA = [
    ["IMPORT", "Import", COLOUR.black, 0.05, 0.1],
    ["WIND", "Wind Power", COLOUR.black, 0.05, 0.3],
    ["SOLAR", "Solar Power", COLOUR.black, 0.05, 0.5],
    ["HYDRO", "Hydro Power", COLOUR.black, 0.05, 0.6],
    ["BIOGAS", "Biogas", COLOUR.black, 0.05, 0.8],
    [
        "TRANSFORMATION_IN",
        "Transformation<br>& Storage",
        COLOUR.salmon,
        0.4,
        0.9,
    ],
    ["TRANSFORMATION_OUT", "", COLOUR.salmon, 0.6, 0.9],
    ["INDUSTRY", "Industry", COLOUR.black, 0.99, 0.5],
    ["HH_SERVICES", "Households & Services", COLOUR.black, 0.99, 0.3],
    ["EXPORT", "Export", COLOUR.black, 0.99, 0.01],
    ["TRANSPORT", "Transport", COLOUR.black, 0.99, 0.6],
    ["AGRICULTURE", "Agriculture", COLOUR.black, 0.99, 0.8],
    [
        "TRANSFORMATION_LOSSES",
        "Transformation Losses",
        COLOUR.grey_deep,
        0.65,
        0.9,
    ],
    ["DISTRIBUTION_LOSSES", "Distribution Losses", COLOUR.grey_deep, 0.8, 0.99],
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
            columns=["source", "target", "value", "color", "customdata"]
        )
        self.nodes = (
            pd.DataFrame(
                data=NODE_DATA,
                columns=["name", "label", "color", "x", "y"],
            )
            .reset_index()
            .set_index("name")
            .rename({"index": "id"}, axis=1)
        )

    def plot(self):
        # plotly draws traces connected first in the background.
        self.connect_methane()
        self.connect_hydrogen()
        self.connect_electricity()
        self.connect_biogas()
        # self.connect_heat()
        # self.connect_liquids()
        # self.connect_solids()
        # self.connect_uranium()

        # self.check_nodal_balance()
        # self.calculate_node_y_positions()
        flows_used = set(self.flows["source"]).union(set(self.flows["target"]))  # noqa: F841
        self.nodes = self.nodes.query("name in @flows_used")
        self.nodes["id"] = [*range(len(self.nodes))]

        self.fig = Figure(
            data=[
                Sankey(
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
                        source=self.flows["source"].map(self.nodes["id"]),
                        target=self.flows["target"].map(self.nodes["id"]),
                        value=self.flows["value"],
                        color=self.flows["color"],
                        customdata=self.flows["customdata"],
                        hovertemplate="%{customdata} <extra></extra>",
                    ),
                )
            ]
        )

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
            self.nodes.loc["IMPORT"],
            self.nodes.loc["ELECTRICITY_PRIMARY_IN"],
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
            self.nodes.loc["WIND"],
            self.nodes.loc["ELECTRICITY_PRIMARY_IN"],
            color=COLOUR.blue_sky,
        )
        solar = generation.filter(like="solar", axis=0)
        self._connect(
            solar,
            self.nodes.loc["SOLAR"],
            self.nodes.loc["ELECTRICITY_PRIMARY_IN"],
            color=COLOUR.yellow_canary,
        )
        hydro = generation.filter(regex="ror|hydro", axis=0)
        self._connect(
            hydro,
            self.nodes.loc["HYDRO"],
            self.nodes.loc["ELECTRICITY_PRIMARY_IN"],
            color=COLOUR.blue_pastel,
        )

        primary = pd.concat([import_, wind, solar, hydro]).sum().item()
        self._forward(
            self.nodes.loc["ELECTRICITY_PRIMARY_IN"],
            self.nodes.loc["ELECTRICITY_PRIMARY_OUT"],
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
            self.nodes.loc["ELECTRICITY_PRIMARY_OUT"],
            self.nodes.loc["TRANSFORMATION_IN"],
        )
        self._forward(
            self.nodes.loc["TRANSFORMATION_IN"],
            self.nodes.loc["TRANSFORMATION_OUT"],
            transformation_demand.sum().item(),
        )

        bypass = primary - transformation_demand.sum()
        self._forward(
            self.nodes.loc["ELECTRICITY_PRIMARY_OUT"],
            self.nodes.loc["ELECTRICITY_BYPASS_IN"],
            bypass.item(),
        )
        self._forward(
            self.nodes.loc["ELECTRICITY_BYPASS_IN"],
            self.nodes.loc["ELECTRICITY_BYPASS_OUT"],
            bypass.item(),
        )
        self.nodes.at["ELECTRICITY_BYPASS_IN", "label"] = (
            f"{prettify_number(bypass.item())} {self.unit}"
        )

        transformation_supply = transformation[transformation.gt(0)].dropna()
        self._connect(
            transformation_supply,
            self.nodes.loc["TRANSFORMATION_OUT"],
            self.nodes.loc["ELECTRICITY_SECONDARY_IN"],
            color=self.nodes.loc["ELECTRICITY_PRIMARY_IN", "color"],
        )
        self._forward(
            self.nodes.loc["ELECTRICITY_BYPASS_OUT"],
            self.nodes.loc["ELECTRICITY_SECONDARY_IN"],
            bypass.item(),
        )

        secondary = transformation_supply.sum() + bypass
        self._forward(
            self.nodes.loc["ELECTRICITY_SECONDARY_IN"],
            self.nodes.loc["ELECTRICITY_SECONDARY_OUT"],
            secondary.item(),
        )
        self.nodes.at["ELECTRICITY_SECONDARY_IN", "label"] = (
            f"{prettify_number(secondary.item())} {self.unit}"
        )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()

        industry = final.filter(like="industry", axis=0)
        self._connect(
            industry,
            self.nodes.loc["ELECTRICITY_SECONDARY_OUT"],
            self.nodes.loc["INDUSTRY"],
        )
        export = final.filter(regex="Foreign|Domestic", axis=0)
        self._connect(
            export,
            self.nodes.loc["ELECTRICITY_SECONDARY_OUT"],
            self.nodes.loc["EXPORT"],
        )
        transport = final.filter(like="BEV charger", axis=0)
        bev_charger_losses = filter_by(
            self._df, carrier="BEV charger", bus_carrier="low voltage losses"
        )
        self._connect(
            pd.concat([transport, bev_charger_losses]),
            self.nodes.loc["ELECTRICITY_SECONDARY_OUT"],
            self.nodes.loc["TRANSPORT"],
        )
        agriculture = final.filter(like="agriculture", axis=0)
        self._connect(
            agriculture,
            self.nodes.loc["ELECTRICITY_SECONDARY_OUT"],
            self.nodes.loc["AGRICULTURE"],
        )
        hh_services = final.filter(regex="rural|decentral|'electricity'", axis=0)
        self._connect(
            hh_services,
            self.nodes.loc["ELECTRICITY_SECONDARY_OUT"],
            self.nodes.loc["HH_SERVICES"],
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
            self.nodes.loc["ELECTRICITY_SECONDARY_OUT"],
            self.nodes.loc["DISTRIBUTION_LOSSES"],
            color=COLOUR.grey_neutral,
        )

    def connect_hydrogen(self):
        bus_carrier = "H2"
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
            self.nodes.loc["IMPORT"],
            self.nodes.loc["HYDROGEN_PRIMARY_IN"],
            color=self.nodes.loc["HYDROGEN_PRIMARY_IN", "color"],
        )
        self.nodes.at["IMPORT", "label"] += (
            f"<br>{prettify_number(import_.sum().item())} {self.unit} Hydrogen"
        )

        primary = import_.sum().item()
        self._forward(
            self.nodes.loc["HYDROGEN_PRIMARY_IN"],
            self.nodes.loc["HYDROGEN_PRIMARY_OUT"],
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
            self.nodes.loc["HYDROGEN_PRIMARY_OUT"],
            self.nodes.loc["TRANSFORMATION_IN"],
        )
        self._forward(
            self.nodes.loc["TRANSFORMATION_IN"],
            self.nodes.loc["TRANSFORMATION_OUT"],
            transformation_demand.sum().item(),
        )

        bypass = primary - transformation_demand.sum()
        self._forward(
            self.nodes.loc["HYDROGEN_PRIMARY_OUT"],
            self.nodes.loc["HYDROGEN_BYPASS_IN"],
            bypass.item(),
        )
        self._forward(
            self.nodes.loc["HYDROGEN_BYPASS_IN"],
            self.nodes.loc["HYDROGEN_BYPASS_OUT"],
            bypass.item(),
        )
        self.nodes.at["HYDROGEN_BYPASS_IN", "label"] = (
            f"{prettify_number(bypass.item())} {self.unit}"
        )

        transformation_supply = transformation[transformation.gt(0)].dropna()
        self._connect(
            transformation_supply,
            self.nodes.loc["TRANSFORMATION_OUT"],
            self.nodes.loc["HYDROGEN_SECONDARY_IN"],
            color=self.nodes.loc["HYDROGEN_PRIMARY_IN", "color"],
        )
        self._forward(
            self.nodes.loc["HYDROGEN_BYPASS_OUT"],
            self.nodes.loc["HYDROGEN_SECONDARY_IN"],
            bypass.item(),
        )

        secondary = transformation_supply.sum() + bypass
        self._forward(
            self.nodes.loc["HYDROGEN_SECONDARY_IN"],
            self.nodes.loc["HYDROGEN_SECONDARY_OUT"],
            secondary.item(),
        )
        self.nodes.at["HYDROGEN_SECONDARY_IN", "label"] = (
            f"{prettify_number(secondary.item())} {self.unit}"
        )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()

        if (final.sum() < transformation_supply.sum()).item():
            # Some amounts from transformation output are not FED. Those
            # amounts are looped in the transformation input side.
            diff = transformation_supply.sum() - final.sum()
            self._forward(
                self.nodes.loc["HYDROGEN_SECONDARY_IN"],
                self.nodes.loc["HYDROGEN_PRIMARY_OUT"],
                diff.item(),
            )

        industry = final.filter(like="industry", axis=0)
        self._connect(
            industry,
            self.nodes.loc["HYDROGEN_SECONDARY_OUT"],
            self.nodes.loc["INDUSTRY"],
        )
        hh_services = final.filter(regex="rural|decentral", axis=0)
        self._connect(
            hh_services,
            self.nodes.loc["HYDROGEN_SECONDARY_OUT"],
            self.nodes.loc["HH_SERVICES"],
        )
        export = final.filter(regex="Foreign|Domestic", axis=0)
        self._connect(
            export,
            self.nodes.loc["HYDROGEN_SECONDARY_OUT"],
            self.nodes.loc["EXPORT"],
        )
        transport = final.filter(regex="transport", axis=0)
        self._connect(
            transport,
            self.nodes.loc["HYDROGEN_SECONDARY_OUT"],
            self.nodes.loc["TRANSPORT"],
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
            self.nodes.loc["IMPORT"],
            self.nodes.loc["METHANE_PRIMARY_IN"],
            color=self.nodes.loc["METHANE_PRIMARY_IN", "color"],
        )
        self.nodes.at["IMPORT", "label"] += (
            f"<br>{prettify_number(import_.sum().item())} {self.unit} Methane"
        )

        gas_primary = import_.sum().item()
        self._forward(
            self.nodes.loc["METHANE_PRIMARY_IN"],
            self.nodes.loc["METHANE_PRIMARY_OUT"],
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
            self.nodes.loc["METHANE_PRIMARY_OUT"],
            self.nodes.loc["TRANSFORMATION_IN"],
        )
        self._forward(
            self.nodes.loc["TRANSFORMATION_IN"],
            self.nodes.loc["TRANSFORMATION_OUT"],
            transformation_gas_demand.sum().item(),
        )

        bypass_gas = gas_primary - transformation_gas_demand.sum()
        self._forward(
            self.nodes.loc["METHANE_PRIMARY_OUT"],
            self.nodes.loc["METHANE_BYPASS_IN"],
            bypass_gas.item(),
        )
        self._forward(
            self.nodes.loc["METHANE_BYPASS_IN"],
            self.nodes.loc["METHANE_BYPASS_OUT"],
            bypass_gas.item(),
        )
        self.nodes.at["METHANE_BYPASS_IN", "label"] = (
            f"{prettify_number(bypass_gas.item())} {self.unit}"
        )

        transformation_gas_supply = transform_gas[transform_gas.ge(0)].dropna()
        self._connect(
            transformation_gas_supply,
            self.nodes.loc["TRANSFORMATION_OUT"],
            self.nodes.loc["METHANE_SECONDARY_IN"],
            color=self.nodes.loc["METHANE_PRIMARY_IN", "color"],
        )
        self._forward(
            self.nodes.loc["METHANE_BYPASS_OUT"],
            self.nodes.loc["METHANE_SECONDARY_IN"],
            bypass_gas.item(),
        )

        secondary = transformation_gas_supply.sum() + bypass_gas
        self._forward(
            self.nodes.loc["METHANE_SECONDARY_IN"],
            self.nodes.loc["METHANE_SECONDARY_OUT"],
            secondary.item(),
        )
        self.nodes.at["METHANE_SECONDARY_IN", "label"] = (
            f"{prettify_number(secondary.item())} {self.unit}"
        )

        final = filter_by(self._df, bus_carrier=bus_carrier).abs()

        industry = final.filter(like="industry", axis=0)
        self._connect(
            industry,
            self.nodes.loc["METHANE_SECONDARY_OUT"],
            self.nodes.loc["INDUSTRY"],
        )
        hh_services = final.filter(regex="rural|decentral", axis=0)
        self._connect(
            hh_services,
            self.nodes.loc["METHANE_SECONDARY_OUT"],
            self.nodes.loc["HH_SERVICES"],
        )
        export = final.filter(regex="Foreign|Domestic", axis=0)
        self._connect(
            export,
            self.nodes.loc["METHANE_SECONDARY_OUT"],
            self.nodes.loc["EXPORT"],
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
            # carrier=[
            #     "Import Foreign",
            #     "Import Domestic",
            #     "biogas",
            # ],
        )
        self._connect(
            generation,
            self.nodes.loc["BIOGAS"],
            self.nodes.loc["BIOGAS_PRIMARY_IN"],
            color=self.nodes.loc["BIOGAS_PRIMARY_IN", "color"],
        )
        self._forward(
            self.nodes.loc["BIOGAS_PRIMARY_IN"],
            self.nodes.loc["BIOGAS_PRIMARY_OUT"],
            generation.sum().item(),
        )

        processing = filter_by(self._df, bus_carrier=bus_carrier, component="Link")
        self._connect(
            processing,
            self.nodes.loc["BIOGAS_PRIMARY_OUT"],
            self.nodes.loc["TRANSFORMATION_IN"],
        )
        self._forward(
            self.nodes.loc["TRANSFORMATION_IN"],
            self.nodes.loc["TRANSFORMATION_OUT"],
            processing.sum().item(),
        )

    def _connect(
        self, df, source, target, color: str = None, extend_node_label: str = None
    ):
        if df.abs().sum().item() < 1e-6:  # todo: magic number to config
            self._df.drop(df.index, inplace=True, errors="ignore")
            return

        df = df.sort_values(by="value", ascending=False)
        customdata = "<br>".join(
            [
                f"{c}: {prettify_number(v)} {self._df.attrs['unit']}"
                for c, v in zip(df.index.get_level_values("carrier"), df["value"])
                if v >= 0.05  # todo: magic number to config
            ]
        )
        customdata += f"<br><br>Total: {prettify_number(df.sum().item())} {self.unit}"

        # add a row with the link's value
        row = self.flows.shape[0]  # next index
        self.flows.loc[row, self.flows.columns] = [
            source.name,
            target.name,
            df.abs().sum().item(),
            color or source.color,
            customdata,
        ]
        # drop from the original dataframe
        self._df.drop(df.index, inplace=True, errors="ignore")

    def _forward(self, source, target, value, color: str = None):
        if value < 1e-6:  # todo: magic number to config
            return

        row = self.flows.shape[0]  # next index
        self.flows.loc[row, self.flows.columns] = [
            source.name,
            target.name,
            value,
            color or source.color,
            f"{prettify_number(value)} {self._df.attrs['unit']}",
        ]

    def check_nodal_balance(self):
        checks = (
            "PRIMARY",
            "SECONDARY",
            "TRANSFORMATION",
        )
        for node in self.nodes.index:
            # skip left and right border nodes because they are not balanced
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
