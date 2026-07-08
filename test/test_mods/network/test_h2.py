import pandas as pd
import pytest

from test.conftest import require_config


def test_h2_import_configuration_matches_csv(nc, project_root):
    """
    Cross-reference H2 import buses, generators, and links in the solved network
    against the TYNDP CSV used to build them, verifying exact attribute values.
    """
    carriers = require_config(nc, "sector", "imports", "carriers_tyndp")
    h2_tyndp = require_config(nc, "sector", "h2_topology_tyndp")
    if not h2_tyndp or "H2" not in carriers:
        pytest.xfail(
            f"H2 not in sector.imports.carriers_tyndp (instead {carriers}) or sector.h2_topology_tyndp not enabled "
            f"(instead {h2_tyndp})."
        )

    for year, n in nc.networks.items():
        prefix = n.meta["run"]["prefix"]
        run_name = n.meta["run"]["name"][0]
        clusters = n.meta["wildcards"]["clusters"]
        # load the same CSV that prepare_sector_network.py consumed for this horizon
        csv_path = (
            project_root
            / "resources"
            / prefix
            / run_name
            / f"h2_import_potentials_{clusters}_{year}.csv"
        )
        # index_col=0 mirrors the identical call in prepare_sector_network.py;
        # the first column is the link name set by clean_tyndp_h2_imports.py
        csv = pd.read_csv(csv_path, index_col=0)
        # This happens for years that are not in the data e.g. 2025
        if csv.empty:
            continue

        gen_names = csv["Corridor"] + " H2 import"  # generator / bus index in network

        # --- generators: p_nom, marginal_cost, e_sum_max ---
        gens = n.generators.loc[gen_names.values].rename(
            index=lambda x: x.removesuffix(" H2 import")
        )
        csv_by_corridor = csv.set_index("Corridor")
        for attr in ("p_nom", "marginal_cost", "e_sum_max"):
            pd.testing.assert_series_equal(
                gens[attr],
                csv_by_corridor[attr],
                atol=1e-1,
                check_names=False,
                obj=f"generator {attr} in {year}",
            )

        # Note: h2_zones_tyndp is an experimental feature and not tested yet
        suffix = "H2 Z2" if n.meta["sector"].get("h2_zones_tyndp", False) else "H2"
        expected_bus = csv["bus1"] + f" {suffix}"
        assert (gens["bus"].values == expected_bus.values).all(), (
            f"Unexpected link bus1 values in {year}"
        )
