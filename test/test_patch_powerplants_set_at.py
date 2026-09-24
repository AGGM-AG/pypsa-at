import importlib

import pandas as pd
import pytest

patch = importlib.import_module("scripts.pypsa-at.patch_powerplants_set_at")


def make_ppl(**overrides) -> pd.DataFrame:
    """Minimal powerplantmatching table covering the cases the rule guards."""
    rows = [
        {
            "Name": n,
            "Country": "Germany",
            "Fueltype": "Lignite",
            "Set": "CHP",
            "Capacity": c,
        }
        for n, c in patch.DE_LIGNITE_CONDENSING.items()
    ]
    rows += [
        # already CHP on 0.6.1 -> stays CHP, supplied via MaStR
        {
            "Name": "Schkopau",
            "Country": "Germany",
            "Fueltype": "Lignite",
            "Set": "CHP",
            "Capacity": 900.0,
        },
        # must not be touched
        {
            "Name": "Boxberg",
            "Country": "Poland",
            "Fueltype": "Lignite",
            "Set": "CHP",
            "Capacity": 2470.0,
        },
        {
            "Name": "Moorburg",
            "Country": "Germany",
            "Fueltype": "Hard Coal",
            "Set": "CHP",
            "Capacity": 1600.0,
        },
    ]
    df = pd.DataFrame(rows)
    for key, value in overrides.items():
        df[key] = value
    return df


class TestRestoreCondensingSet:
    def test_patches_every_expected_unit(self):
        out = patch.restore_condensing_set(make_ppl())
        patched = out[
            out["Name"].isin(patch.DE_LIGNITE_CONDENSING)
            & (out["Country"] == "Germany")
        ]
        assert (patched["Set"] == "PP").all()
        assert len(patched) == len(patch.DE_LIGNITE_CONDENSING)

    def test_leaves_genuine_chp_alone(self):
        out = patch.restore_condensing_set(make_ppl())
        assert out.loc[out["Name"] == "Schkopau", "Set"].eq("CHP").all()

    def test_leaves_other_countries_and_fueltypes_alone(self):
        out = patch.restore_condensing_set(make_ppl())
        assert out.loc[out["Country"] == "Poland", "Set"].eq("CHP").all()
        assert out.loc[out["Fueltype"] == "Hard Coal", "Set"].eq("CHP").all()

    def test_input_is_not_mutated(self):
        ppl = make_ppl()
        before = ppl.copy()
        patch.restore_condensing_set(ppl)
        assert ppl.compare(before).empty

    def test_raises_without_german_lignite(self):
        ppl = make_ppl()
        ppl["Fueltype"] = "Hard Coal"
        with pytest.raises(ValueError, match="No German lignite units"):
            patch.restore_condensing_set(ppl)

    def test_raises_on_renamed_unit(self):
        ppl = make_ppl()
        ppl.loc[ppl["Name"] == "Neurath", "Name"] = "Neurath BoA"
        with pytest.raises(ValueError, match="not found"):
            patch.restore_condensing_set(ppl)

    def test_raises_on_split_unit(self):
        ppl = make_ppl()
        extra = ppl[ppl["Name"] == "Boxberg"].iloc[[0]]
        ppl = pd.concat([ppl, extra], ignore_index=True)
        with pytest.raises(ValueError, match="more than"):
            patch.restore_condensing_set(ppl)

    def test_raises_on_capacity_drift(self):
        ppl = make_ppl()
        ppl.loc[ppl["Name"] == "Lippendorf", "Capacity"] *= 1.5
        with pytest.raises(ValueError, match="Capacity drift"):
            patch.restore_condensing_set(ppl)

    def test_tolerates_capacity_drift_within_tolerance(self):
        ppl = make_ppl()
        ppl.loc[ppl["Name"] == "Lippendorf", "Capacity"] *= 1.01
        out = patch.restore_condensing_set(ppl)
        assert out.loc[out["Name"] == "Lippendorf", "Set"].eq("PP").all()

    def test_raises_when_upstream_fixed_the_tag(self):
        ppl = make_ppl()
        ppl.loc[ppl["Name"] == "Neurath", "Set"] = "PP"
        with pytest.raises(ValueError, match="obsolete"):
            patch.restore_condensing_set(ppl)

    def test_raises_on_unknown_set_value(self):
        ppl = make_ppl()
        ppl.loc[ppl["Name"] == "Neurath", "Set"] = "Store"
        with pytest.raises(ValueError, match="Unknown Set value"):
            patch.restore_condensing_set(ppl)

    def test_raises_on_new_large_lignite_unit(self):
        ppl = make_ppl()
        new = pd.DataFrame(
            [
                {
                    "Name": "Neu Boxberg",
                    "Country": "Germany",
                    "Fueltype": "Lignite",
                    "Set": "CHP",
                    "Capacity": 1200.0,
                }
            ]
        )
        with pytest.raises(ValueError, match="Neu Boxberg"):
            patch.restore_condensing_set(pd.concat([ppl, new], ignore_index=True))

    def test_min_capacity_keeps_schkopau_below_threshold(self):
        """Schkopau must stay below the threshold or it double counts."""
        assert 900.0 < patch.MIN_CONDENSING_CAPACITY
        assert min(patch.DE_LIGNITE_CONDENSING.values()) > patch.MIN_CONDENSING_CAPACITY
