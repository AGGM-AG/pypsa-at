# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Tests for the Austrian gas brownfield calibration.

Covers the Anlagenregister gas deduplication in
``scripts/pypsa-at/build_anlagenregister_at.py``, the curated overrides and the
E-Control calibration in ``scripts/pypsa-at/overwrite_powerplants.py``, and the
full load hours of the solved networks.
"""

import logging
import pathlib
import textwrap
from types import SimpleNamespace

import pandas as pd
import pytest
from build_anlagenregister_at import (
    GAS_TECHCODES,
    deduplicate_gas_registrations,
    drop_curated_gas_registrations,
    drop_duplicate_gas_registrations,
    drop_shared_capacity_gas_registrations,
    normalise_techcode,
)
from overwrite_powerplants import (
    GAS_CALIBRATION_BASE_YEAR,
    GAS_DEVIATION_COLUMNS,
    GAS_FULL_LOAD_HOUR_BAND,
    GAS_TECHNOLOGIES,
    apply_gas_overrides_at,
    check_gas_calibration_at,
)

DATA = pathlib.Path.cwd() / "data" / "pypsa-at"
OVERRIDES = str(DATA / "gas_powerplant_overrides_AT.csv")
TARGETS = str(DATA / "gas_calibration_targets_AT.csv")

FEEDIN_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]


def register_row(plant_id, plz, techcode, mw, feedin_gwh=0.0, bundesland="ST"):
    """Build one Anlagenregister row; feed-in is spread evenly over the window."""
    row = {
        "reference_year": 2026,
        "typ": "Strom",
        "id": plant_id,
        "plz": plz,
        "ort": "Testort",
        "bundesland": bundesland,
        "techcode": techcode,
        "energietraeger": "",
        "inbetriebnahme": "",
        "engpassleistung_kw": mw * 1e3,
    }
    for year in FEEDIN_YEARS:
        row[f"feedin_kwh_{year}"] = feedin_gwh * 1e6 / len(FEEDIN_YEARS)
    return row


def gas_mw(df):
    """Total natural gas capacity [MW] in a register table."""
    techcode = normalise_techcode(df["techcode"])
    mask = (df["typ"] == "Strom") & techcode.isin(GAS_TECHCODES)
    return df.loc[mask, "engpassleistung_kw"].sum() / 1e3


class TestGasDeduplication:
    """The gas half of the Anlagenregister double counting (#323)."""

    def test_multi_fuel_site_keeps_only_the_fuel_that_produced(self):
        """Duernrohr registers one 398.4 MW plant under five fuels."""
        df = pd.DataFrame(
            [
                register_row(1, "3435", "Abfall", 398.4, 502.7),
                register_row(2, "3435", "Erdgas", 398.4, 2.4),
                register_row(3, "3435", "Biomasse flüssig", 398.4, 2.0),
                register_row(4, "3435", "Biomasse fest", 398.4, 246.2),
            ]
        )
        out = drop_shared_capacity_gas_registrations(df)
        assert gas_mw(out) == 0.0
        assert len(out) == 3, "only the gas row may be dropped"

    def test_gas_is_kept_when_it_outproduced_the_other_fuels(self):
        """Theiss registers gas and heavy fuel oil at one capacity."""
        df = pd.DataFrame(
            [
                register_row(1, "3494", "Erdgas", 815.0, 1079.5),
                register_row(2, "3494", "Heizöl schwer", 815.0, 0.0),
            ]
        )
        out = drop_shared_capacity_gas_registrations(df)
        assert gas_mw(out) == 815.0

    def test_capacity_collision_with_a_hydro_plant_is_left_alone(self):
        """Salzburg has a 13.7 MW gas plant and a 13.7 MW hydro plant."""
        df = pd.DataFrame(
            [
                register_row(1, "5020", "Fossil - Natural gas", 13.7, 60.8),
                register_row(2, "5020", "Wasserkraft > 10 MW", 13.7, 329.4),
            ]
        )
        out = drop_shared_capacity_gas_registrations(df)
        assert gas_mw(out) == 13.7, "a non-combustion collision is a coincidence"
        assert len(out) == 2

    def test_a_tie_leaves_the_gas_row_in_place(self):
        """Nothing fed in, so nothing says the capacity belongs to the other fuel."""
        df = pd.DataFrame(
            [
                register_row(1, "8410", "Erdgas", 175.0, 0.0),
                register_row(2, "8410", "Heizöl schwer", 175.0, 0.0),
            ]
        )
        assert gas_mw(drop_shared_capacity_gas_registrations(df)) == 175.0

    def test_same_fuel_twice_collapses_to_the_higher_feedin(self):
        df = pd.DataFrame(
            [
                register_row(1, "4560", "Erdgas", 13.2, 156.0),
                register_row(2, "4560", "Thermal - Gaseous - unspecified", 13.2, 0.0),
            ]
        )
        out = drop_duplicate_gas_registrations(df, keep=())
        assert gas_mw(out) == 13.2
        assert out["id"].tolist() == [1]

    def test_keep_list_protects_the_simmering_double_unit(self):
        """Two separate ~278 MW units, each with its own feed-in."""
        df = pd.DataFrame(
            [
                register_row(1, "1110", "Fossil - Natural gas", 278.0, 2329.3, "W"),
                register_row(2, "1110", "Fossil - Natural gas", 278.0, 2305.4, "W"),
            ]
        )
        out = drop_duplicate_gas_registrations(df, keep=(("1110", 278_000.0),))
        assert gas_mw(out) == 556.0

    def test_stale_keep_entry_raises(self):
        df = pd.DataFrame(
            [
                register_row(1, "1110", "Erdgas", 100.0, 10.0, "W"),
                register_row(2, "1110", "Erdgas", 100.0, 5.0, "W"),
            ]
        )
        with pytest.raises(ValueError, match="matches no duplicated gas registration"):
            drop_duplicate_gas_registrations(df, keep=(("1110", 278_000.0),))

    def test_small_registrations_are_not_deduplicated(self):
        """Equal small capacities at one postal code are common and genuine."""
        df = pd.DataFrame(
            [
                register_row(1, "1110", "Erdgas", 0.5, 1.0, "W"),
                register_row(2, "1110", "Erdgas", 0.5, 0.5, "W"),
            ]
        )
        assert gas_mw(drop_duplicate_gas_registrations(df, keep=())) == 1.0

    def test_curated_drop_removes_the_second_postal_code(self):
        """GDK Mellach is registered under both banks of the Mur."""
        df = pd.DataFrame(
            [
                register_row(32020, "8410", "Erdgas", 832.0, 6411.0),
                register_row(44405, "8402", "Fossil - Natural gas", 430.0, 2483.2),
            ]
        )
        out = drop_curated_gas_registrations(df, drops=(("ST", 44405),))
        assert gas_mw(out) == 832.0

    def test_stale_curated_drop_raises(self):
        df = pd.DataFrame([register_row(1, "8410", "Erdgas", 832.0, 6411.0)])
        with pytest.raises(ValueError, match="matched 0 rows"):
            drop_curated_gas_registrations(df, drops=(("ST", 44405),))

    def test_composition_applies_the_curated_drops_first(self):
        """
        A curated duplicate must not win a feed-in comparison against the row
        that supersedes it.
        """
        df = pd.DataFrame(
            [
                register_row(32020, "8410", "Erdgas", 430.0, 100.0),
                register_row(44405, "8402", "Fossil - Natural gas", 430.0, 2483.2),
            ]
        )
        out = deduplicate_gas_registrations(df, keep=(), drops=(("ST", 44405),))
        assert 44405 not in out["id"].tolist(), (
            "the 430 MW Werndorf row outproduced its Wildon counterpart and would "
            "have survived a feed-in comparison"
        )
        assert gas_mw(out) == 430.0

    def test_techcode_whitespace_is_tolerated(self):
        """Several register techcodes carry trailing spaces."""
        df = pd.DataFrame(
            [
                register_row(1, "3435", "Abfall", 10.0, 500.0),
                register_row(
                    2,
                    "3435",
                    "Thermal - Fossil - Natural gas - unspecified (CHP) ",
                    10.0,
                    1.0,
                ),
            ]
        )
        assert gas_mw(drop_shared_capacity_gas_registrations(df)) == 0.0


@pytest.fixture
def powerplants():
    """Austrian gas rows as build_powerplants hands them over."""
    return pd.DataFrame(
        [
            {
                "Name": "Mellach",
                "Country": "AT",
                "Fueltype": "Natural Gas",
                "Technology": "CCGT",
                "Set": "CHP",
                "Capacity": 1084.0,
                "DateIn": 2011.0,
                "DateOut": float("nan"),
                "bus": "AT225",
            },
            {
                "Name": "Theiss",
                "Country": "AT",
                "Fueltype": "Natural Gas",
                "Technology": "CCGT",
                "Set": "CHP",
                "Capacity": 485.0,
                "DateIn": 2000.0,
                "DateOut": float("nan"),
                "bus": "AT124",
            },
        ]
    )


@pytest.fixture
def overrides_file(tmp_path):
    """Minimal override file exercising all three actions."""
    path = tmp_path / "overrides.csv"
    path.write_text(
        textwrap.dedent(
            """\
            name,ppm_name,action,technology,capacity_mw_net,capacity_mw_gross,capacity_basis,date_in,date_out,bus,set,autoproducer,source,evidence,rejected_alternatives
            GDK Mellach,Mellach,update,CCGT,832.0,832.0,test,2012,,,CHP,false,src,ev,
            FHKW Mellach,,add,CCGT,165.0,246.0,test,1986,,AT225,CHP,false,src,ev,
            Theiss,Theiss,drop,,,,,,,,,,src,ev,
            """
        )
    )
    return str(path)


class TestGasOverrides:
    def test_all_three_actions_apply(self, powerplants, overrides_file):
        out = apply_gas_overrides_at(powerplants, overrides_file)
        gas = out[out["Fueltype"] == "Natural Gas"]
        assert sorted(gas["Name"]) == ["FHKW Mellach", "GDK Mellach"]
        assert gas["Capacity"].sum() == pytest.approx(997.0)
        assert gas.set_index("Name").loc["GDK Mellach", "DateIn"] == 2012

    def test_added_rows_stay_on_the_gas_bus_and_keep_the_chp_set(
        self, powerplants, overrides_file
    ):
        out = apply_gas_overrides_at(powerplants, overrides_file)
        added = out[out["Name"] == "FHKW Mellach"].squeeze()
        assert added["bus"] == "AT225"
        assert added["Set"] == "CHP"
        assert added["Country"] == "AT"
        assert added["Fueltype"] == "Natural Gas"

    def test_stale_reference_raises(self, powerplants, overrides_file, tmp_path):
        powerplants.loc[powerplants["Name"] == "Mellach", "Name"] = "Mellach GDK"
        with pytest.raises(ValueError, match="matches 0 Austrian natural gas rows"):
            apply_gas_overrides_at(powerplants, overrides_file)

    def test_technology_outside_ocgt_ccgt_raises(self, powerplants, overrides_file):
        """add_existing_baseyear silently drops anything else, including CCGT, Thermal."""
        powerplants.loc[powerplants["Name"] == "Theiss", "Technology"] = "CCGT, Thermal"
        path = pathlib.Path(overrides_file)
        path.write_text(
            path.read_text().replace("Theiss,Theiss,drop", "Theiss,Theiss,update")
        )
        with pytest.raises(ValueError, match="only keeps"):
            apply_gas_overrides_at(powerplants, overrides_file)

    def test_missing_gas_fleet_raises(self, overrides_file):
        empty = pd.DataFrame(
            columns=[
                "Name",
                "Country",
                "Fueltype",
                "Technology",
                "Set",
                "Capacity",
                "DateIn",
                "DateOut",
                "bus",
            ]
        )
        with pytest.raises(ValueError, match="No Austrian natural gas plants"):
            apply_gas_overrides_at(empty, overrides_file)


class TestFeatureToggle:
    """``mods: update_gas_capacities_AT: enable`` must guard the whole step."""

    @staticmethod
    def _run(monkeypatch, enabled, ppl, overrides_file):
        import overwrite_powerplants as module

        monkeypatch.setattr(
            module,
            "snakemake",
            SimpleNamespace(
                params=SimpleNamespace(
                    update_gas_capacities_AT=enabled, clustering="AT35DE5"
                ),
                input=SimpleNamespace(
                    gas_overrides=overrides_file,
                    gas_targets=TARGETS,
                    anlagenregister=str(DATA / "AT-Postal-to-NUTS.csv"),
                    postal_to_nuts=str(DATA / "AT-Postal-to-NUTS.csv"),
                ),
            ),
            raising=False,
        )
        return module.gas_powerplants_AT(ppl)

    def test_disabled_is_a_no_op(self, monkeypatch, powerplants, overrides_file):
        out, deviations = self._run(monkeypatch, False, powerplants, overrides_file)
        assert out.equals(powerplants)
        assert deviations.empty
        assert list(deviations.columns) == GAS_DEVIATION_COLUMNS

    def test_enabled_changes_the_fleet(self, powerplants, overrides_file):
        """Guards against the toggle looking like a no-op in both states."""
        assert not apply_gas_overrides_at(powerplants, overrides_file).equals(
            powerplants
        )


class TestShippedOverrides:
    """The curated file must stay consistent with what the scripts expect."""

    def test_every_row_carries_a_source_and_evidence(self):
        overrides = pd.read_csv(OVERRIDES)
        assert overrides["source"].notna().all()
        assert overrides["evidence"].notna().all()
        assert (overrides["source"].str.len() > 10).all()

    def test_added_rows_are_fully_specified(self):
        """An empty DateIn would let add_existing_baseyear invent a vintage."""
        added = pd.read_csv(OVERRIDES).query("action == 'add'")
        for column in ("technology", "capacity_mw_net", "date_in", "bus", "set"):
            assert added[column].notna().all(), column
        assert added["technology"].isin(GAS_TECHNOLOGIES).all()


class TestCalibration:
    def _fleet(self, capacity_mw):
        return pd.DataFrame(
            [
                {
                    "Name": "Test",
                    "Country": "AT",
                    "Fueltype": "Natural Gas",
                    "Technology": "CCGT",
                    "Capacity": capacity_mw,
                    "DateIn": 2000.0,
                    "DateOut": float("nan"),
                }
            ]
        )

    def test_plausible_fleet_passes(self):
        check_gas_calibration_at(self._fleet(4569.2), TARGETS)

    def test_far_too_little_capacity_raises(self):
        with pytest.raises(ValueError, match="outside the plausible band"):
            check_gas_calibration_at(self._fleet(2000.0), TARGETS)

    def test_far_too_much_capacity_raises(self):
        with pytest.raises(ValueError, match="outside the plausible band"):
            check_gas_calibration_at(self._fleet(9000.0), TARGETS)

    def test_overshoot_only_warns(self, caplog):
        """The national check is one-sided and never fatal."""
        check_gas_calibration_at(self._fleet(5200.0), TARGETS)
        assert "exceeds the national statistic" in caplog.text

    def test_retired_units_are_excluded(self, caplog):
        caplog.set_level(logging.INFO)
        fleet = self._fleet(4569.2)
        fleet.loc[1] = {
            "Name": "Leopoldau",
            "Country": "AT",
            "Fueltype": "Natural Gas",
            "Technology": "CCGT",
            "Capacity": 140.0,
            "DateIn": 1975.0,
            "DateOut": 2012.0,
        }
        check_gas_calibration_at(fleet, TARGETS)
        assert "Excluded 1 retired" in caplog.text
        assert "4,569.2 MW" in caplog.text

    def test_unknown_base_year_raises(self):
        with pytest.raises(ValueError, match="is not in"):
            check_gas_calibration_at(self._fleet(4569.2), TARGETS, base_year=1990)


@pytest.mark.AT
def test_at_gas_full_load_hours_are_plausible(nc):
    """
    The modelled Austrian gas fleet must run within the historical band.

    Fatal for the calibration base year, a warning for the later horizons:
    those are projections, and a decarbonising fleet is expected to drift out
    of a band measured on today's system.
    """
    low, high = GAS_FULL_LOAD_HOUR_BAND
    failures = []
    for year, n in nc.networks.items():
        links = n.links.query(
            "carrier in ['OCGT', 'CCGT'] and bus1.str.startswith('AT')"
        )
        if links.empty:
            continue
        # p_nom sits at bus0 (gas), so the electrical capacity is p_nom * efficiency.
        capacity_mw = (links["p_nom_opt"] * links["efficiency"]).sum()
        generation_mwh = (
            -n.links_t.p1[links.index].sum().sum()
            * n.snapshot_weightings.generators.iloc[0]
        )
        if capacity_mw <= 0:
            continue
        full_load_hours = generation_mwh / capacity_mw
        if int(year) == GAS_CALIBRATION_BASE_YEAR:
            failures.append(
                (year, full_load_hours) if not low <= full_load_hours <= high else None
            )
    failures = [f for f in failures if f]
    assert not failures, (
        f"Austrian gas full load hours outside {low:.0f}-{high:.0f} h in the "
        f"calibration base year: {failures}"
    )
