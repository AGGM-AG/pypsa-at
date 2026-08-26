from frozendict import frozendict

TYNDP_TO_PYPSA_LOCATION: dict[str, str] = {
    # Albania
    "AL00": "AL",
    # Austria
    "AT00": "AT",
    # Bosnia and Herzegovina
    "BA00": "BA",
    # Belgium
    "BE00": "BE",
    # Bulgaria
    "BG00": "BG",
    # Switzerland
    "CH00": "CH",
    # Cyprus
    "CY00": "CY",
    # Czech Republic
    "CZ00": "CZ",
    # Germany
    "DE00": "DE",
    "DEKF": "DE",  # Kriegers Flak offshore wind zone
    # Denmark — west/east split mirrors DK0/DK1 in PyPSA-AT clustering
    "DKW1": "DK0",  # DK0 West — DK1 bidding zone (Jutland + Funen)
    "DKE1": "DK1",  # DK1 East — DK2 bidding zone (Sjaelland)
    "DKKF": "DK1",  # DK1 Kriegers Flak offshore → East Denmark (DK2 connection)
    # Estonia
    "EE00": "EE",
    # Spain — Balearic split mirrors ES0/ES1 in PyPSA-AT clustering
    "ES00": "ES",  # ES0 mainland
    # (no Balearic/Mallorca TYNDP node in dataset; would map to "ES1")
    # Finland
    "FI00": "FI",
    # France (Corsica has no OSM transmission buses; modeled as single node)
    "FR00": "FR",
    # Great Britain — Northern Ireland split mirrors GB0/GB1 in PyPSA-AT clustering
    "GB00": "GB0",  # GB0 Great Britain mainland
    "GBNI": "GB1",  # GB1 Northern Ireland
    # Greece (Crete not separated in PyPSA-AT)
    "GR00": "GR",
    "GR03": "GR",  # Crete — not separated in PyPSA-AT
    # Croatia
    "HR00": "HR",
    # Hungary
    "HU00": "HU",
    # Ireland
    "IE00": "IE",
    # Italy — Sicily and Sardinia split mirrors IT0/IT1/IT2 in PyPSA-AT clustering
    "ITA0": "IT0",  # Italy aggregated (treated as mainland)
    "ITN1": "IT0",  # North (NORD)
    "ITCN": "IT0",  # Centre-North (CNOR)
    "ITCS": "IT0",  # Centre-South (CSUD)
    "ITS1": "IT0",  # South (SUD)
    "ITCA": "IT0",  # Calabria (CAL) — continental peninsula
    "ITSI": "IT1",  # Sicily (SICI)
    "ITSA": "IT2",  # IT2 Sardinia (SARD)
    # Lithuania
    "LT00": "LT",
    # Luxembourg — 4 sub-nodes aggregate to single country
    "LUB1": "LU",
    "LUF1": "LU",
    "LUG1": "LU",
    "LUV1": "LU",
    # Latvia
    "LV00": "LV",
    # Montenegro
    "ME00": "ME",
    # North Macedonia
    "MK00": "MK",
    # Malta
    "MT00": "MT",
    # Netherlands
    "NL00": "NL",
    # Norway — 3 bidding zones aggregate to single country in PyPSA-AT
    "NOS0": "NO",  # South (NO1 + NO2)
    "NOM1": "NO",  # Mid (NO3)
    "NON1": "NO",  # North (NO4 + NO5)
    # Poland
    "PL00": "PL",
    # Portugal
    "PT00": "PT",
    # Romania
    "RO00": "RO",
    # Serbia
    "RS00": "RS",
    # Sweden — 4 bidding zones; not sub-nationally split in PyPSA-AT
    "SE01": "SE",  # SE1 (Luleå area)
    "SE02": "SE",  # SE2 (Sundsvall area)
    "SE03": "SE",  # SE3 (Stockholm area)
    "SE04": "SE",  # SE4 (Malmö area)
    # Slovenia
    "SI00": "SI",
    # Slovakia
    "SK00": "SK",
    # United Kingdom
    "UK00": "GB0",
    "UKNI": "GB1",
}

TYNDP_TO_PYPSA_LOCATION_TRANSMISSION: dict[str, str | None] = (
    TYNDP_TO_PYPSA_LOCATION
    | {
        "UK00": "GB0",  # Great Britain is apparently modeled as UK and GB
        "UKNI": "GB1",  # Great Britain is apparently modeled as UK and GB
        "TR00": None,  # Turkey is not modeled in pypsa-at
        "UA00": None,  # Ukraine is not modeled in pypsa-at
        "UA01": None,  # Ukraine is not modeled in pypsa-at
        "EG00": None,  # Egypt is not modeled in pypsa-at
        "DZ00": None,  # Algeria is not modeled in pypsa-at
        "IL00": None,  # Israel is not modeled in pypsa-at
        "PS00": None,  # Palestine is not modeled in pypsa-at
        "IS00": None,  # Iceland is not modeled in pypsa-at
        "LY00": None,  # Libya is not modeled in pypsa-at
        "TN00": None,  # Tunesia is not modeled in pypsa-at
        "MD00": None,  # Moldova is not modeled in pypsa-at
        "MA00": None,  # Morocco is not modeled in pypsa-at
        "FR15": None,  # Corsica is not modeled in pypsa-at
        "MT00": None,  # Malta is not modeled in pypsa-at
        "PL00E": "PL",  # Poland is modeled as one country (synced network)
        "PL00I": "PL",  # Poland is modeled as one country (synced network)
        "ITCO": None,  # Corsica is not modeled in pypsa-at
        "ITVI": "IT1",  # Virtual node for Tyrrhenian link project is mapped to Sicily
    }
)

# Custom island nodes only exist if the country is clustered at
# administrative level 1 (see mods.clustering.custom).
ISLAND_SPLIT_NODES: dict[str, tuple[str, ...]] = {
    "DK": ("DK0", "DK1"),
    "ES": ("ES0", "ES1"),
    "GB": ("GB0", "GB1"),
    "IT": ("IT0", "IT1", "IT2"),
}

# for key countries use trajectories from values country
# because some countries do not exist in Open-TYNDP data
PROXIES = {"XK": "RS"}
HYDRO_CARRIER_MAPPING = {
    "Run of River - MW": ("ror", "Generator-p_nom", "max"),
    "Pondage - MW": ("ror", "Generator-p_nom", "max"),
    "Pondage - GWh": ("ror", None, None),
    "Reservoir - MW": ("hydro discharger", "Link-p_nom", "max"),
    "Reservoir - GWh": ("hydro store", "Store-e_nom", "max"),
    "PS Open (turbine) - MW": ("PHS discharger", "Link-p_nom", "max"),
    "PS Open (pump) - MW": ("PHS charger", "Link-p_nom", "max"),
    "PS Open - GWh": ("PHS store", "Store-e_nom", "max"),
    "PS Closed (turbine) - MW": ("PHS discharger", "Link-p_nom", "max"),
    "PS Closed (pump) - MW": ("PHS charger", "Link-p_nom", "max"),
    "PS Closed - GWh": ("PHS store", "Store-e_nom", "max"),
}
NUTS2_CODES = {
    "Burgenland": "AT11",
    "Niederoesterreich": "AT12",
    "Wien": "AT13",
    "Kaernten": "AT21",
    "Steiermark": "AT22",
    "Oberoesterreich": "AT31",
    "Salzburg": "AT32",
    "Tirol": "AT33",
    "Vorarlberg": "AT34",
}
TJ_PER_TWH = 3600.0

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
