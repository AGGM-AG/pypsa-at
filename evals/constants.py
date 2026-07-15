# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Constants and identifiers for PyPSA-AT energy system evaluations.

This module centralizes all constant values, color schemes, carrier names,
and data model specifications used throughout the evaluation package.
Values here should remain unchanged during runtime.

Key Components
--------------
- DataModel: Column and index level name constants
- BusCarrier: Bus carrier technology identifiers
- Group: Nice names for carrier groupings
- Regex: Regular expression patterns for parsing
- COLOUR: Hex color code definitions
- COLOUR_SCHEME: Carrier-to-color mapping
- ALIAS_*: Location code to name mappings
- UNITS: Unit conversion factors
"""

import re
from datetime import datetime as dt
from subprocess import CalledProcessError

import git
from frozendict import frozendict

# represents constants import time
NOW: str = dt.now().strftime("%Y%m%d%H%M%S")


class DataModel:
    """Metric data model constants."""

    LOCATION: str = "location"
    COMPONENT: str = "component"
    CARRIER: str = "carrier"
    BUS_CARRIER: str = "bus_carrier"
    METRIC: str = "metric"
    YEAR: str = "year"
    SNAPSHOTS: str = "snapshots"
    IDX_NAMES: list = [LOCATION, CARRIER, BUS_CARRIER]
    YEAR_IDX_NAMES: list = [YEAR, LOCATION, CARRIER, BUS_CARRIER]


class BusCarrier:
    """Container to collect all bus carrier names."""

    AC: str = "AC"
    DC: str = "DC"
    CH4: str = "gas"
    H2: str = "H2"
    OIL: str = "oil"
    LIGNITE: str = "lignite"
    COAL: str = "coal"
    NH3: str = "NH3"
    METHANOL: str = "methanol"
    URANIUM: str = "uranium"
    # TRANSPORT_P: str = "passenger transport"
    # TRANSPORT_P_LONG: str = "passenger transport long"
    FT: str = "Fischer-Tropsch"
    FT_1: str = "Fischer-Tropsch 1"
    FT_2: str = "Fischer-Tropsch 2"
    HEAT_URBAN_CENTRAL: str = "urban central heat"
    HEAT_URBAN_DECENTRAL: str = "urban decentral heat"
    HEAT_RURAL: str = "rural heat"
    # ESM heat buses:
    # HEAT_URBAN_SERVICES: str = "services urban decentral heat"
    # HEAT_URBAN_RESIDENTIAL: str = "residential urban decentral heat"
    # HEAT_RURAL_SERVICES: str = "services rural heat"
    # HEAT_RURAL_RESIDENTIAL: str = "residential rural heat"
    LI_ION: str = "Li ion"
    BATTERY: str = "battery"
    HOME_BATTERY: str = "home battery"
    EV_BATTERY: str = "EV battery"
    SOLID_BIOMASS: str = "solid biomass"

    @classmethod
    def ac_stores(cls) -> list[str]:
        """
        Return all AC-connected storage bus carriers.

        Returns
        -------
        List of bus carrier names for AC-connected storage systems
        including batteries and EV batteries.
        """
        return [
            cls.AC,
            cls.DC,
            cls.LI_ION,
            cls.BATTERY,
            cls.HOME_BATTERY,
            cls.EV_BATTERY,
        ]

    @classmethod
    def heat_buses(cls) -> list[str]:
        """
        Return all heat-related bus carriers.

        Returns
        -------
        List of bus carrier names for heating systems including
        central, decentral, and rural heat networks.
        """
        return [cls.HEAT_URBAN_CENTRAL, cls.HEAT_URBAN_DECENTRAL, cls.HEAT_RURAL]

    @classmethod
    def eu_buses(cls) -> list[str]:
        """
        Return bus carriers that only exist at EU-level locations.

        These carriers represent centralized EU-wide resources that are
        not regionalized to individual countries.

        Returns
        -------
        List of EU-level bus carrier names for fuels and uranium.
        """
        return [cls.OIL, cls.LIGNITE, cls.COAL, cls.METHANOL, cls.URANIUM]


class Group:
    """Container to collect carrier nice names used in PyPSA-AT evaluations."""

    # Biomass
    biomass: str = "Biomass"
    chp_biomass: str = "Biomass CHP"
    solid_biomass_boiler: str = "Solid Biomass Boiler"

    # Coal
    coal: str = "Coal"
    chp_coal: str = "Coal CHP"
    chp_coal_cc: str = "Coal CHP CC"
    pp_coal: str = "Coal PP"

    # Gas/Methane
    chp_ch4: str = "Gas CHP"
    chp_ch4_cc: str = "Gas CHP CC"

    # Import/Export
    export_domestic: str = "Export Domestic"
    export_foreign: str = "Export Foreign"
    export_net: str = "Net Export"
    import_domestic: str = "Import Domestic"
    import_foreign: str = "Import Foreign"
    import_global: str = "Import Global"
    import_net: str = "Net Import"

    # Storage
    storage_in: str = "Storage In"
    storage_out: str = "Storage Out"

    # Hydro metrics
    inflow_cum: str = "Accumulated Natural Inflow"
    pumping_cum: str = "Accumulated Pumping"
    soc: str = "State of Charge"
    soc_max: str = "Max State of Charge"
    spill_cum: str = "Accumulated Outflow Spill"
    turbine_cum: str = "Accumulated Turbining"

    # Market
    global_market: str = "Global Market"

    # Other
    power_disconnect: str = "Power Disconnect"


class Regex:
    """A collection of regular expression patterns."""

    # ends with 4 digits
    year: re.Pattern = re.compile(r"\d{4}$")

    # matches:
    # ^ : startswith
    # [A-Z]{2} : 2 capital letters,
    # [\d,A-G,+]{0,3} : up to 3 digits, letter (German NUTS2 codes),
    # [+1]? : optional '+1' literal to match Austrian NUTS3 regions
    # \s?\d* : 1 optional space, and any number of digits for subnets.
    region: re.Pattern = re.compile(r"^(?!.*CH4)[A-Z]{2}[\d,A-G]{0,3}[+1]?\s?\d*")

    # matches: startswith 2 capital letters, followed by up to 3 digits,
    # groups: only the first 2 letters that are the country code
    country: re.Pattern = re.compile(r"^([A-Z]{2})[\d,A-G]{0,3}\s*")

    # match anything inside parenthesis.
    unit: re.Pattern = re.compile(r"\([^()]*\)")


TITLE_SUFFIX: str = " {location} in {unit}"

UNITS: frozendict = frozendict(
    {
        "W": 1e-6,
        "Wh": 1e-6,
        "KW": 1e-3,
        "kW": 1e-3,  # alias
        "KWh": 1e-3,
        "kWh": 1e-3,  # alias
        "MW": 1,  # model base unit
        "MWh": 1,  # model base unit
        "GW": 1e3,
        "GWh": 1e3,
        "TW": 1e6,
        "TWh": 1e6,
        "PW": 1e9,
        "PWh": 1e9,
        "currency": 1,
        "EUR": 1,  # base currency
        "t_co2": 1,
        "t": 1,  # alias
        "kt_co2": 1e3,
        "Mt_co2": 1e6,
    }
)


class TradeTypes:
    """Collect trade type names."""

    LOCAL: str = "local"  # same node
    DOMESTIC: str = "domestic"  # same country, but different node
    FOREIGN: str = "foreign"  # different country


class COLOUR:
    """Container to collect colour codes in hex format."""

    coral: str = "#E8B5B1"
    raspberry: str = "#961454"
    salmon: str = "#E19990"
    rose: str = "#C13A2A"
    peach: str = "#EBBFBA"

    red: str = "#CA0638"
    red_chestnut: str = "#96332C"
    red_bright: str = "#E53212"
    red_deep: str = "#B20633"
    red_fire: str = "#E63313"
    red_liquid: str = "#A7003F"

    green: str = "#619159"
    green_light: str = "#509554"
    green_ocean: str = "#3DCCBF"
    green_mint: str = "#B0D4B2"
    green_sage: str = "#82B973"
    turquoise: str = "#e8e8e8"

    grey_light: str = "#ECECEC"
    grey_dark: str = "#535353"
    grey_charcoal: str = "#485055"
    grey_deep: str = "#3C3C3C"
    grey_cool: str = "#919699"
    grey_silver: str = "#D0D0D0"
    grey_neutral: str = "#9F9F9F"

    black: str = "#000000"

    brown: str = "#AE8020"
    brown_dark: str = "#b37400"
    brown_sallow: str = "#bf9c5c"
    brown_light: str = "#e8cc99"
    brown_deep: str = "#4d3200"

    blue_pastel: str = "#B5C9D5"
    blue_moonstone: str = "#74AABA"
    blue_dark: str = "#5F5F5F"
    blue_persian: str = "#34629B"
    blue_celestial: str = "#4F8FCD"
    blue_cerulean: str = "#005082"
    blue_sky: str = "#99C1DA"
    blue_lavender: str = "#636EFA"
    blue_deepdark: str = "#1C3049"

    orange: str = "#FF6600"
    orange_mellow: str = "#FECB52"

    yellow_bright: str = "#EDD820"
    yellow_vivid: str = "#FEC500"
    yellow_canary: str = "#FFDE53"
    yellow_golden: str = "#FFB200"


ALIAS_COUNTRY: frozendict = frozendict(
    {
        "EU": "Europe",
        "AL": "Albania",
        "AT": "Austria",
        "BA": "Bosnia and Herzegovina",
        "BE": "Belgium",
        "BG": "Bulgaria",
        "CH": "Switzerland",
        "CZ": "Czech Republic",
        "DE": "Germany",
        "DK": "Denmark",
        "EE": "Estonia",
        "ES": "Spain",
        "FI": "Finland",
        "FR": "France",
        "GB": "Great Britain",
        "GR": "Greece",
        "HR": "Croatia",
        "HU": "Hungary",
        "IE": "Ireland",
        "IT": "Italy",
        "LT": "Lithuania",
        "LU": "Luxembourg",
        "LV": "Latvia",
        "ME": "Montenegro",
        "MK": "North Macedonia",
        "NL": "Netherlands",
        "NO": "Norway",
        "PL": "Poland",
        "PT": "Portugal",
        "RO": "Romania",
        "RS": "Serbia",
        "SE": "Sweden",
        "SI": "Slovenia",
        "SK": "Slovakia",
        "XK": "Kosovo",
    }
)
ALIAS_COUNTRY_REV: frozendict = frozendict({v: k for k, v in ALIAS_COUNTRY.items()})
COLOUR_SCHEME: dict = {
    # dark blue - coal
    "Solids": COLOUR.blue_deepdark,
    Group.coal: COLOUR.blue_dark,
    Group.pp_coal: COLOUR.blue_dark,
    Group.chp_coal: COLOUR.blue_dark,
    Group.chp_coal_cc: COLOUR.turquoise,
    "Coal Import": COLOUR.blue_dark,
    # red - oil
    "Oil": COLOUR.red,
    "Oil PP": COLOUR.red,
    "Fischer-Tropsch": COLOUR.red,
    "Oil Import": COLOUR.red,
    "Oil CHP": COLOUR.red,
    "Oil Boiler": COLOUR.red,
    "Liquids": COLOUR.red_liquid,
    # dark green - biogas
    "Biogas": COLOUR.green,
    "Biogas (CC)": COLOUR.green,
    "Bio Methane Processing": COLOUR.green,
    "Bioliquids": COLOUR.green_ocean,
    "Bioliquids (CC)": COLOUR.green_ocean,
    "Biofuels": COLOUR.red_deep,
    "SynGas": COLOUR.green_light,
    "SynGas (CC)": COLOUR.green_light,
    # light green - biomass
    Group.biomass: COLOUR.green_light,
    "Wet Biomass": COLOUR.green_light,
    "Solid Biomass": COLOUR.green_light,
    "Unsustainable Solid Biomass": COLOUR.green_sage,
    Group.chp_biomass: COLOUR.green_light,
    Group.solid_biomass_boiler: COLOUR.green,
    "Biomass Boiler": COLOUR.green,
    # brown - methane
    "Methane": COLOUR.brown,
    "Methane Store": COLOUR.brown,
    "Gas PP": COLOUR.brown,
    "Methane Compressors": COLOUR.brown_sallow,
    "Methane Pyrolysis": COLOUR.turquoise,
    Group.chp_ch4: COLOUR.brown_dark,
    "CHP": COLOUR.brown,
    "Thermal Powerplant": COLOUR.brown_light,
    "CHP (CC)": COLOUR.brown_dark,
    "Methanation": COLOUR.brown,
    "Gas Boiler": COLOUR.brown_sallow,
    Group.chp_ch4_cc: COLOUR.brown_light,
    "Methane Import": COLOUR.brown,
    "Gas Production": COLOUR.brown,
    "Production": COLOUR.brown,
    "LNG Import": COLOUR.brown_light,
    "Pipeline Import": COLOUR.brown_sallow,
    "Thermal Powerplants": COLOUR.brown,
    "OCGT": COLOUR.brown,
    # light grey - hydrogen
    "Hydrogen": COLOUR.blue_pastel,
    "Hydrogen Store": COLOUR.blue_pastel,
    "H2": COLOUR.blue_pastel,
    "H2 CHP": COLOUR.blue_sky,
    "Electrolysis": COLOUR.blue_pastel,
    "SMR": COLOUR.yellow_bright,
    "Hydrogen Tube Storage": COLOUR.blue_pastel,
    "Hydrogen Underground Storage": COLOUR.grey_charcoal,
    "SMR CC": COLOUR.grey_cool,
    "Hydrogen Import": COLOUR.blue_pastel,
    # teal - wind power
    "Wind Power": COLOUR.blue_moonstone,
    "Onshore": COLOUR.blue_moonstone,
    "Offshore": COLOUR.green_ocean,
    # blue - hydro
    "Hydro Power": COLOUR.blue_persian,
    "Run-of-River": COLOUR.blue_persian,
    "Reservoir": COLOUR.blue_cerulean,
    "Pumped Hydro Storage": COLOUR.red_chestnut,
    "Pumped Hydro Storage Inflow": COLOUR.blue_cerulean,
    "Inflow Hydro Storage": COLOUR.blue_cerulean,
    # blue - heat
    "Resistive Heater": COLOUR.blue_persian,
    "Heat Pump": COLOUR.blue_celestial,
    "Air Heat Pump": COLOUR.blue_celestial,
    "Ground Heat Pump": COLOUR.blue_deepdark,
    "Fuel Cell (Heat)": COLOUR.blue_pastel,
    "Demand": COLOUR.grey_neutral,
    # yellow - solar
    "Solar Power": COLOUR.yellow_bright,
    "Solar Rooftop": COLOUR.yellow_vivid,
    "Solar Hsat": COLOUR.yellow_canary,
    "Photovoltaics": COLOUR.yellow_bright,
    "PV-Utility": COLOUR.yellow_bright,
    "PV-Rooftop": COLOUR.yellow_vivid,
    "Solar Thermal": COLOUR.yellow_canary,
    # red - nuclear
    "Nuclear": COLOUR.orange,
    "Nuclear Power": COLOUR.orange,
    "Uranium": COLOUR.orange,
    # light blue - electricity
    "Electricity": COLOUR.blue_celestial,
    "AC": COLOUR.blue_celestial,
    "Electricity CHP": COLOUR.blue_celestial,
    "Battery Storage": COLOUR.coral,
    "Home Battery": COLOUR.coral,
    "Car Battery": COLOUR.coral,
    "Electricity Import": COLOUR.blue_celestial,
    "Electricity OCGT": COLOUR.blue_celestial,
    # purple - heat supply
    "District Heat": COLOUR.raspberry,
    "Decentral Heat": COLOUR.salmon,
    "Heat": COLOUR.rose,
    # light pink
    # "HH and Services (Heat)": COLOUR.salmon,
    "HH & Services": COLOUR.salmon,
    # orange - ambient heat
    "Ambient Heat": COLOUR.red_bright,
    # light green - DAC, Fuel cell
    "Heat for DAC": COLOUR.green_mint,
    "Fuel Cell": COLOUR.blue_celestial,
    "Hydrogen Fuel Cell": COLOUR.blue_celestial,
    # grey - losses, misc
    "Transformation Losses": COLOUR.grey_silver,
    "Distribution Losses": COLOUR.grey_silver,
    "Heat Ventilation": COLOUR.grey_neutral,
    "Miscellaneous": COLOUR.grey_dark,
    "Losses": COLOUR.grey_silver,
    "Storage": COLOUR.grey_light,
    "DAC": COLOUR.red_chestnut,
    "Direct Air Capture": COLOUR.red_chestnut,
    "co2 vent": COLOUR.grey_silver,
    "CO2 Ventilation": COLOUR.grey_silver,
    "CO2 Budget": COLOUR.grey_cool,
    "CO2 Sequestration": COLOUR.grey_silver,
    "CO2 Store": COLOUR.grey_silver,
    "HVC": COLOUR.blue_moonstone,
    Group.import_foreign: COLOUR.grey_silver,
    Group.export_foreign: COLOUR.grey_silver,
    Group.import_domestic: COLOUR.blue_lavender,
    Group.export_domestic: COLOUR.orange_mellow,
    Group.power_disconnect: COLOUR.grey_dark,
    "Grid Losses": COLOUR.grey_silver,
    # Sectors
    "Industry": COLOUR.red,
    "Oil Refining": COLOUR.red_bright,
    "Households & Services": COLOUR.grey_neutral,
    "Transport": COLOUR.grey_deep,
    "Industry CC": COLOUR.red_deep,
    "Industry (CC)": COLOUR.red_deep,
    # Time Series
    "Inflexible Demand": COLOUR.black,
    "Base Load": COLOUR.yellow_golden,
    "Storage In": COLOUR.green_sage,
    "Storage Out": COLOUR.green_sage,
    "Net Import": COLOUR.grey_silver,
    "Net Export": COLOUR.grey_silver,
    Group.import_global: COLOUR.grey_silver,
    Group.global_market: COLOUR.blue_lavender,
    "State of Charge": COLOUR.blue_sky,
    "Max State of Charge": COLOUR.grey_silver,
    "Accumulated Turbining": COLOUR.blue_celestial,
    "Accumulated Pumping": COLOUR.peach,
    "Accumulated Outflow Spill": COLOUR.grey_silver,
    "Accumulated Natural Inflow": COLOUR.blue_cerulean,
    "Residualload": COLOUR.red_fire,
    "Waste": COLOUR.raspberry,
    "Solid Waste": COLOUR.raspberry,
    "Waste CHP": COLOUR.raspberry,
    "Methanolisation": COLOUR.salmon,
    "Hydrogen Compressors": COLOUR.blue_pastel,
    "Haber-Bosch": COLOUR.red,
    "Agriculture": COLOUR.green_light,
    "Distribution Grid": COLOUR.grey_silver,
    "Transmission Losses": COLOUR.grey_silver,
    "Ammonia Cracker": COLOUR.red_chestnut,
    "Ammonia": COLOUR.red_chestnut,
    "Sabatier": COLOUR.yellow_canary,
    "Synth. Fuels": COLOUR.red,
    "Methanol Steam Reforming": COLOUR.salmon,
    "Methanol": COLOUR.salmon,
    "Bio H2": COLOUR.green_mint,
}
COLOR_SCHEME_FILL: dict = {
    "Residual Load": "none",
    "Residual Load Duration Curve": "none",
}
LINE_WIDTH: dict = {
    "Residual Load": 2,
    "Residual Load Duration Curve": 2,
}
ALIAS_REGION: frozendict = frozendict(
    {
        # Austrian is clustered on NUTS1 (AT10) or NUTS3 (AT35)
        "AT11": "Burgenland (AT)",
        "AT12": "Lower Austria (AT)",
        "AT13": "Vienna (AT)",
        "AT21": "Carinthia (AT)",
        "AT22": "Styria (AT)",
        "AT31": "Upper Austria (AT)",
        "AT32": "Salzburg (AT)",
        "AT33": "Tyrol (AT)",
        "AT34": "Vorarlberg (AT)",
        # fixed custom administrative clustering regions
        "IT0": "Italy (mainland)",
        "IT1": "Sicily",
        "IT2": "Sardinia",
        "DK0": "Denmark",
        "DK1": "Sjaelland",
        "GB0": "Great Britain",
        "GB1": "North-Ireland",
        "ES0": "Spain",
        "ES1": "Balearic Islands",
    }
)
ALIAS_REGION_AT10_CLUSTERING = {
    "AT11": "Burgenland (AT)",
    "AT12": "Lower Austria (AT)",
    "AT13": "Vienna (AT)",
    "AT21": "Carinthia (AT)",
    "AT22": "Styria (AT)",
    "AT31": "Upper Austria (AT)",
    "AT32": "Salzburg (AT)",
    "AT33": "Tyrol (AT)",
    "AT34": "Vorarlberg (AT)",
    "AT333": "East Tyrol (AT)",
}
ALIAS_REGION_AT35_CLUSTERING = {
    "AT111": "Mittelburgenland",
    "AT112": "Nordburgenland",
    "AT113": "Südburgenland",
    "AT121": "Mostviertel-Eisenwurzen",
    "AT122": "Niederösterreich-Süd",
    "AT123": "Sankt Pölten",
    "AT124": "Waldviertel",
    "AT125": "Weinviertel",
    "AT126": "Wiener Umland/Nordteil",
    "AT127": "Wiener Umland/Südteil",
    "AT130": "Wien",
    "AT211": "Klagenfurt-Villach",
    "AT212": "Oberkärnten",
    "AT213": "Unterkärnten",
    "AT221": "Graz",
    "AT222": "Liezen",
    "AT223": "Östliche Obersteiermark",
    "AT224": "Oststeiermark",
    "AT225": "West- und Südsteiermark",
    "AT226": "Westliche Obersteiermark",
    "AT311": "Innviertel",
    "AT312": "Linz-Wels",
    "AT313": "Mühlviertel",
    "AT314": "Steyr-Kirchdorf",
    "AT315": "Traunviertel",
    "AT321": "Lungau",
    "AT322": "Pinzgau-Pongau",
    "AT323": "Salzburg und Umgebung",
    "AT331": "Außerfern",
    "AT332": "Innsbruck",
    "AT333": "East Tyrol (AT)",
    "AT334": "Tiroler Oberland",
    "AT335": "Tiroler Unterland",
    "AT341": "Bludenz-Bregenzer Wald",
    "AT342": "Rheintal-Bodenseegebiet",
}
ALIAS_REGION_DE16_CLUSTERING = {  # NUTS1
    "DE1": "Baden-Württemberg",
    "DE2": "Bavaria",
    "DE3": "Berlin",
    "DE4": "Brandenburg",
    "DE5": "Bremen",
    "DE6": "Hamburg",
    "DE7": "Hesse",
    "DE8": "Mecklenburg-Western Pomerania",
    "DE9": "Lower Saxony",
    "DEA": "North Rhine-Westphalia",
    "DEB": "Rhineland-Palatinate",
    "DEC": "Saarland",
    "DED": "Saxony",
    "DEE": "Saxony-Anhalt",
    "DEF": "Schleswig-Holstein",
    "DEG": "Thuringia",
}
ALIAS_REGION_DE5_CLUSTERING = {
    "DE1": "Baden-Württemberg",
    "DE2": "Bavaria",
    "DE3": "Midwest Germany",
    "DE4": "Mideast Germany",
    "DE5": "North Germany",
}

# reverse and then combine all dictionaries to prevent overwriting DE1-5 keys
ALIAS_LOCATION_REV = frozendict(
    {
        v: k
        for dict_ in (
            ALIAS_COUNTRY,
            ALIAS_REGION,
            ALIAS_REGION_DE5_CLUSTERING,
            ALIAS_REGION_DE16_CLUSTERING,
            ALIAS_REGION_AT10_CLUSTERING,
            ALIAS_REGION_AT35_CLUSTERING,
        )
        for k, v in dict_.items()
    }
)

try:
    repo = git.Repo(search_parent_directories=True)
    branch = repo.active_branch.name
    repo_name = repo.remotes.origin.url.split(".git")[0].split("/")[-1]
    git_hash = repo.head.object.hexsha
except (CalledProcessError, FileNotFoundError):
    repo_name = branch = git_hash = "Not a git repo."
except TypeError:
    repo_name = branch = git_hash = "Detached HEAD"

RUN_META_DATA = {
    "repo_name": repo_name,
    "repo_branch": branch,
    "repo_hash": git_hash,
}
