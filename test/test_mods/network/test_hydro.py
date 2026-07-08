# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT

"""Test hydro inflow patching."""

import pandas as pd
import pytest
import xarray as xr

from test.conftest import require_config


def test_inflows_match_pemmdb_totals(nc, project_root):
    """
    Check that inflow (ROR, PHS, hydro) aggregated
    by country match the total inflows from PEMMDB per country.
    """
    renewable_carriers = require_config(nc, "electricity", "renewable_carriers")
    if not renewable_carriers:
        pytest.xfail(f"electricity.renewable_carriers is set to {renewable_carriers}.")
    if "hydro" not in renewable_carriers:
        pytest.skip("No hydro components in network, skipping")

    for year, n in nc.networks.items():
        inflow = xr.DataArray.from_dict(n.meta["resources"]["inflow_data"])
        inflow = inflow.assign_coords(time=pd.to_datetime(inflow.time.values))
        tol = 0.01 * n.snapshot_weightings.max()[0]

        for model_carrier, resource_carrier in [
            ("hydro inflow", "hydro"),
            ("PHS inflow", "PHS"),
            ("ror", "ror"),
        ]:
            columns = n.generators.query(f'carrier == "{model_carrier}"').index
            actual = (
                n.generators_t.p_max_pu.reindex(columns=columns, fill_value=0.0)
                .mul(n.snapshot_weightings.stores, axis=0)
                .sum()
            )
            expected = (
                inflow.sel(carrier=resource_carrier)
                .sum(dim="time")
                .to_dataframe(name="inflow")["inflow"]
            )
            expected.index += f" {model_carrier}"
            expected /= n.generators.loc[columns, "p_nom"].fillna(0)
            expected = expected.fillna(0)
            actual = actual.reindex(expected.index, fill_value=0.0)
            actual.name = "inflow"
            pd.testing.assert_series_equal(
                actual, expected, check_exact=False, atol=tol
            )
