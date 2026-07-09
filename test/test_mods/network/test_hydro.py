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

        reservoirs_columns = n.storage_units.query('carrier == "hydro"').index
        reservoirs_actual = (
            n.storage_units_t.inflow.reindex(columns=reservoirs_columns, fill_value=0.0)
            .mul(n.snapshot_weightings.stores, axis=0)
            .sum()
        )
        reservoirs_expected = (
            inflow.sel(carrier="hydro")
            .sum(dim="time")
            .to_dataframe(name="inflow")["inflow"]
        )
        reservoirs_expected.index += " hydro"
        reservoirs_actual = reservoirs_actual.reindex(
            reservoirs_expected.index, fill_value=0.0
        )
        reservoirs_actual.name = "inflow"
        pd.testing.assert_series_equal(
            reservoirs_actual, reservoirs_expected, check_exact=False, atol=tol
        )

        phs_columns = n.generators.query('carrier == "PHS inflow"').index
        phs_actual = (
            n.generators_t.p_max_pu.reindex(columns=phs_columns, fill_value=0.0)
            .mul(n.snapshot_weightings.stores, axis=0)
            .sum()
        )
        phs_expected = (
            inflow.sel(carrier="PHS")
            .sum(dim="time")
            .to_dataframe(name="inflow")["inflow"]
        )
        phs_expected.index += " PHS inflow"
        phs_expected /= n.generators.loc[phs_columns, "p_nom"].fillna(0)
        phs_expected = phs_expected.fillna(0)
        phs_actual = phs_actual.reindex(phs_expected.index, fill_value=0.0)
        phs_actual.name = "inflow"
        pd.testing.assert_series_equal(
            phs_actual, phs_expected, check_exact=False, atol=tol
        )

        ror_columns = n.generators.query('carrier == "ror"').index
        ror_actual = (
            n.generators_t.p_max_pu.reindex(columns=ror_columns, fill_value=0.0)
            .mul(n.snapshot_weightings.stores, axis=0)
            .sum()
        )
        ror_expected = (
            inflow.sel(carrier="ror")
            .sum(dim="time")
            .to_dataframe(name="inflow")["inflow"]
        )
        ror_expected.index += " ror"
        ror_expected /= n.generators.loc[ror_columns, "p_nom"]
        ror_expected = ror_expected.fillna(0)
        ror_actual = ror_actual.reindex(ror_expected.index, fill_value=0.0)
        ror_actual.name = "inflow"
        pd.testing.assert_series_equal(
            ror_actual, ror_expected, check_exact=False, atol=tol
        )
