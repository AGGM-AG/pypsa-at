# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT

"""Test hydro inflow patching."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pypsa import Network

from test.conftest import require_config

_NON_RETIRING_HYDRO_CARRIERS = [
    "ror",
    "hydro discharger",
    "hydro store",
    "PHS charger",
    "PHS discharger",
    "PHS store",
]


def test_hydro_capacity_never_decreases(nc):
    """Test that hydro (ror/reservoir/PHS) has a 100-year lifetime and must never retire."""
    capacity = nc.statistics.installed_capacity(
        carrier=_NON_RETIRING_HYDRO_CARRIERS,
        groupby=["carrier", "location"],
        aggregate_across_components=True,
        nice_names=False,
        drop_zero=False,
    )
    if capacity.empty:
        pytest.skip("No hydro components in network, skipping")
    capacity.index.names = ["year", "carrier", "location"]

    for carrier, group in capacity.groupby(["carrier", "location"]):
        series = group.droplevel("carrier").sort_index()
        assert (series.diff().dropna() >= 0).all(), (
            f"'{carrier}' capacity decreased: {series}"
        )


def _snapshot_profiles(
    n: Network, inflow: xr.DataArray, carrier: str, suffix: str
) -> pd.DataFrame:
    """Aggregate the hourly PEMMDB inflow to the network snapshots (mean per bin)."""
    profiles = inflow.sel(carrier=carrier).transpose("time", "countries").to_pandas()
    time = profiles.index
    edges = n.snapshots.append(pd.DatetimeIndex([time[-1] + pd.Timedelta(hours=1)]))
    bins = pd.cut(time, bins=edges, labels=n.snapshots, right=False)
    profiles = profiles.groupby(bins, observed=False).mean()
    profiles.index = n.snapshots
    profiles.columns = [f"{region} {suffix}" for region in profiles.columns]
    return profiles.fillna(0.0)


def _per_unit(profiles: pd.DataFrame, p_nom: pd.Series) -> pd.DataFrame:
    """Convert absolute inflow profiles to per unit of nominal capacity."""
    p_nom = p_nom.reindex(profiles.columns)
    profiles = profiles.div(p_nom, axis=1)
    return profiles.replace([np.inf, -np.inf], 0.0).fillna(0.0)


def _energy(profiles: pd.DataFrame, weightings: pd.Series, clip: float) -> pd.Series:
    """
    Total inflow energy per component.

    ``solve_network`` zeroes all profile values below ``solving.options.clip_p_max_pu``
    (generator/link ``p_max_pu``/``p_min_pu`` and storage unit ``inflow``). The solved
    networks therefore carry slightly less inflow energy than PEMMDB reports, which is
    replicated here to compare like with like.
    """
    clipped = profiles.where(profiles.abs() > clip, other=0.0)
    return clipped.mul(weightings, axis=0).sum()


def _assert_energy_matches(actual: pd.Series, expected: pd.Series, tol: float) -> None:
    """Compare inflow energies of all regions with an inflow timeseries."""
    actual = actual.reindex(expected.index, fill_value=0.0)
    actual.name = expected.name = "inflow"
    actual.index.name = expected.index.name = None
    pd.testing.assert_series_equal(actual, expected, check_exact=False, atol=tol)


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

    clip = require_config(nc, "solving", "options", "clip_p_max_pu")

    for year, n in nc.networks.items():
        inflow = xr.DataArray.from_dict(n.meta["resources"]["inflow_data"])
        inflow = inflow.assign_coords(time=pd.to_datetime(inflow.time.values))
        weightings = n.snapshot_weightings.stores
        tol = 0.01 * n.snapshot_weightings.max().iloc[0]

        for model_carrier, resource_carrier in [
            ("hydro inflow", "hydro"),
            ("PHS inflow", "PHS"),
            ("ror", "ror"),
        ]:
            columns = n.generators.query(f'carrier == "{model_carrier}"').index
            actual = (
                n.generators_t.p_max_pu.reindex(columns=columns, fill_value=0.0)
                .mul(weightings, axis=0)
                .sum()
            )
            expected = _energy(
                _per_unit(
                    _snapshot_profiles(n, inflow, resource_carrier, model_carrier),
                    n.generators["p_nom"],
                ),
                weightings,
                clip,
            )
            _assert_energy_matches(actual, expected, tol)


class TestRedistributePeaks:
    """Unit tests for the p_max_pu peak redistribution guard."""

    def test_feasible_column_conserves_energy(self):
        from mods.network.hydro import _redistribute_peaks

        df = pd.DataFrame({"a": [2.0, 0.4, 0.2, 0.2, 0.2]})
        out = _redistribute_peaks(df)
        assert out["a"].max() <= 1.0
        assert out["a"].sum() == pytest.approx(3.0, abs=0.011)

    def test_infeasible_column_raises(self):
        from mods.network.hydro import _redistribute_peaks

        # total 6.0 > feasible maximum 5.0 -> would loop forever unguarded
        df = pd.DataFrame({"a": [3.0, 2.0, 0.5, 0.25, 0.25]})
        with pytest.raises(ValueError, match="feasible maximum"):
            _redistribute_peaks(df)

    def test_infeasible_column_error_names_the_column(self):
        from mods.network.hydro import _redistribute_peaks

        df = pd.DataFrame(
            {
                "infeasible": [3.0, 2.0, 0.5, 0.25, 0.25],
                "feasible": [2.0, 0.4, 0.2, 0.2, 0.2],
            }
        )
        with pytest.raises(ValueError, match="infeasible"):
            _redistribute_peaks(df)

    def test_feasible_frame_with_zero_column_keeps_columns_independent(self):
        from mods.network.hydro import _redistribute_peaks

        df = pd.DataFrame(
            {
                "feasible": [2.0, 0.4, 0.2, 0.2, 0.2],
                "zero": [0.0, 0.0, 0.0, 0.0, 0.0],
            }
        )
        out = _redistribute_peaks(df)
        assert out["feasible"].sum() == pytest.approx(3.0, abs=0.011)
        assert (out["zero"] == 0.0).all()
        assert out.notna().all().all()

    def test_max_iter_falls_back_to_energy_conserving_waterfill(self, caplog):
        from mods.network.hydro import _redistribute_peaks

        df = pd.DataFrame({"a": [2.0, 0.4, 0.2, 0.2, 0.2]})
        with caplog.at_level("INFO"):
            out = _redistribute_peaks(df, max_iter=1)
        assert out["a"].max() <= 1.0
        assert out["a"].sum() == pytest.approx(3.0, abs=0.011)
        assert "waterfill" in caplog.text

    def test_near_bound_column_conserves_energy(self):
        from mods.network.hydro import _redistribute_peaks

        # 99.99% of the feasible maximum: proportional redistribution stalls
        n, total = 100, 100 * 0.9999
        profile = pd.Series(range(1, n + 1), dtype=float)
        df = pd.DataFrame({"a": profile / profile.sum() * total})
        out = _redistribute_peaks(df)
        assert out["a"].max() <= 1.0
        assert out["a"].sum() == pytest.approx(total, abs=0.011)
