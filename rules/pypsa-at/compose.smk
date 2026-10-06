# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT patch to the compose_network rule.

Upstream composes the network in a single rule. The AT inputs and params of
the former ``prepare_sector_network_at``, ``add_existing_baseyear_at`` and
``modify_prenetwork_at`` overrides are merged into it here. The AT hooks in
``scripts/compose_network.py`` consume them.
"""


def get_compose_inputs_at(w):
    """Upstream compose inputs plus the AT replacements and additions."""
    inputs = get_compose_inputs(w)

    # former prepare_sector_network_at: AT replacements of upstream inputs
    if config_provider("demand", "transport", "use_nea_demand")(w):
        inputs["transport_demand"] = resources("transport_demand_at.csv")
        inputs["transport_data"] = resources("transport_data_at.csv")
        inputs["avail_profile"] = resources("avail_profile_at.csv")
        inputs["dsm_profile"] = resources("dsm_profile_at.csv")
    if config_provider("demand", "heat", "apply_at_demand")(w):
        inputs["district_heat_share"] = resources(
            "district_heat_share_{horizon}-modified_at.csv"
        )

    inputs.update(
        # former prepare_sector_network_at
        powerplants=resources("powerplants.csv"),
        inflow=resources("inflow_per_region.nc"),
        hydro_capacities=ancient("data/hydro_capacities.csv"),
        industrial_demand_profiles=(
            resources("industrial_demand_profiles.csv")
            if config_provider("industry", "demand_profiles", "enable")(w)
            else []
        ),
        annual_demand_overrides=(
            resources("industrial_demand_overrides.csv")
            if config_provider("industry", "annual_demand_overrides", "enable")(w)
            else []
        ),
        # former add_existing_baseyear_at: patched power plants for the
        # existing capacities only, add_electricity keeps the upstream file
        powerplants_at=resources("powerplants-overwrite.csv"),
        # former modify_prenetwork_at
        tyndp_trajectories=(
            resources("tyndp_trajectories.csv")
            if config_provider("mods", "PEMMDB_trajectories", "enable")(w)
            else []
        ),
        tyndp_transmission_trajectories=(
            resources("tyndp_transmission_trajectories.csv")
            if config_provider("mods", "tyndp_lower_bounds", "enable")(w)
            else []
        ),
        nuts3_buildings=f"{KLIEN_POTENTIALS['folder']}/nuts3_pv_buildings.csv",
        nuts3_ground=f"{KLIEN_POTENTIALS['folder']}/nuts3_pv_ground.csv",
        nuts3_wind=f"{KLIEN_POTENTIALS['folder']}/nuts3_wind.csv",
        onwind_brownfield=resources("onwind_brownfield_at.csv"),
        biogas_plants_at=resources("biogas_plants_at.csv"),
        gas_input_nodes_simplified=resources("gas_input_locations_simplified.csv"),
        gas_storage_capacities="data/pypsa-at/gas_input_locations_s_AT35DE16_updated.csv",
        clustered_gas_network=resources("gas_network_clustered.csv"),
        h2_imports_tyndp=(
            resources("h2_import_potentials_{horizon}.csv")
            if config_provider("sector", "h2_topology_tyndp")(w)
            else []
        ),
        heat_demand_nea_at=(
            resources("heat_demand_nea_at.csv")
            if config_provider("demand", "heat", "apply_at_demand")(w)
            else []
        ),
        electricity_base_load_at=(
            resources("electricity_base_load_at.csv")
            if config_provider("mods", "electricity_base_load", "enable")(w)
            else []
        ),
        code_files=[
            "mods/network/biogas.py",
            "mods/network/common.py",
            "mods/network/electricity.py",
            "mods/network/gas.py",
            "mods/network/h2.py",
            "mods/network/hydro.py",
            "mods/network/onwind.py",
            "mods/network/potentials.py",
            "mods/network/trajectories.py",
            "mods/demand/annual.py",
            "mods/demand/electricity.py",
            "mods/demand/heat_demand.py",
            "mods/demand/industrial_demand.py",
            "mods/constants.py",
            "mods/utils.py",
        ],
    )
    return inputs


use rule compose_network as compose_network_at with:
    input:
        unpack(get_compose_inputs_at),
    params:
        **rules.compose_network.params,
        # former prepare_sector_network_at
        consider_efficiency_classes=config_provider(
            "clustering", "consider_efficiency_classes"
        ),
        aggregation_strategies=config_provider("clustering", "aggregation_strategies"),
        exclude_carriers=config_provider("clustering", "exclude_carriers"),
        carrier_to_load_mapping=config_provider("demand", "carrier_to_load_mapping"),
        annual_demand_overrides=config_provider("industry", "annual_demand_overrides"),
        # former modify_prenetwork_at
        klien_potential_limits_technologies=config_provider(
            "mods", "klien_potential_limits", "technologies"
        ),
        klien_potential_limits_use_technical_potentials=config_provider(
            "mods", "klien_potential_limits", "use_technical_potentials"
        ),
        klien_potential_limits_climate_scenario=config_provider(
            "mods", "klien_potential_limits", "climate_scenario"
        ),
        klien_potential_limits_year=config_provider(
            "mods", "klien_potential_limits", "year"
        ),
        klien_potential_limits_ambition=config_provider(
            "mods", "klien_potential_limits", "ambition"
        ),
        block_russian_gas_imports=config_provider("mods", "block_russian_gas_imports"),
        admin_levels=config_provider("clustering", "administrative"),
        custom_clustering=config_provider("mods", "modify_nuts3_shapes"),
        apply_at_heat_demand=config_provider("demand", "heat", "apply_at_demand"),
        add_biogas_to_power_plants_AT=config_provider(
            "mods", "existing_capacities", "add_biogas_to_power_plants_AT"
        ),
        electricity_base_load=config_provider("mods", "electricity_base_load"),
        use_nea_transport_demand=config_provider(
            "demand", "transport", "use_nea_demand"
        ),


ruleorder: compose_network_at > compose_network
