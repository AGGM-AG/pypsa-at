import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Hydropower ground truth: Anlagenregister vs. model (NUTS3)

    Ground-truth check for
    [pypsa-at-planning#312](https://github.com/AGGM-AG/pypsa-at-planning/issues/312)
    (scale hydropower to the EAG goal of 47 TWh/a):

    - **Ground truth** — water-powered plants in the E-Control **Anlagenregister**,
      assigned to NUTS3 regions via postal codes
      (`data/pypsa-at/AT-Postal-to-NUTS.csv`, same mapping as
      `scripts/pypsa-at/build_anlagenregister_at.py`).
    - **Model** — the Austrian hydro fleet the workflow builds from
      **powerplantmatching** (`data/powerplants/…/powerplants.csv`, the input of
      `build_powerplants`), assigned to NUTS3 regions via plant coordinates.
      With `clusters: adm` (`AT35…`) every Austrian bus *is* a NUTS3 region, so
      the polygon containment below approximates the model's bus assignment
      (the workflow itself snaps plants to the nearest substation of
      `base_s_adm.nc`, which can differ right at region borders — see
      pypsa-at-planning#92, Grenzkraftwerke).

    Required inputs (retrieve once):

    ```bash
    pixi run snakemake retrieve_anlagenregister_at retrieve_powerplants retrieve_eu_nuts_2021 -c1
    ```

    Run from the repository root:
    `pixi run marimo edit .marimo/compare-hydro-anlagenregister.py`

    **Unit caveat:** the register reports *Engpassleistung* (bottleneck
    capacity, MW_el), powerplantmatching reports installed capacity (MW).
    The register snapshot also reflects its `reference_year`, while
    powerplantmatching aggregates older source databases.
    """)
    return


@app.cell
def _():
    import sys
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt
    import pandas as pd

    sys.path[:0] = [".", "scripts", "scripts/pypsa-at"]
    import build_anlagenregister_at as bar

    return Path, bar, gpd, mcolors, mo, pd, plt


@app.cell
def _():
    # dataviz palette (validated): slot 1 blue = register, slot 2 orange = model
    C_REGISTER = "#2a78d6"
    C_MODEL = "#eb6834"
    SEQ_BLUES = [
        "#cde2fb",
        "#9ec5f4",
        "#6da7ec",
        "#3987e5",
        "#256abf",
        "#184f95",
        "#0d366b",
    ]
    DIV_RED, DIV_MID, DIV_BLUE = "#e34948", "#f0efec", "#2a78d6"
    INK, MUTED, GRID, BASELINE = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"
    return (
        BASELINE,
        C_MODEL,
        C_REGISTER,
        DIV_BLUE,
        DIV_MID,
        DIV_RED,
        GRID,
        INK,
        MUTED,
        SEQ_BLUES,
    )


@app.cell
def _(Path):
    def _latest(pattern: str, rule: str) -> Path:
        matches = sorted(Path(".").glob(pattern))
        if not matches:
            raise FileNotFoundError(
                f"no match for {pattern!r} — run `pixi run snakemake {rule} -c1`"
            )
        return matches[-1]

    ar_plants_path = _latest(
        "data/anlagenregister/*/*/anlagenregister_plants.csv",
        "retrieve_anlagenregister_at",
    )
    powerplants_path = _latest(
        "data/powerplants/*/*/powerplants.csv", "retrieve_powerplants"
    )
    nuts3_path = _latest(
        "data/eu_nuts2021/*/*/ref-nuts-2021-01m.geojson/"
        "NUTS_RG_01M_2021_4326_LEVL_3.geojson",
        "retrieve_eu_nuts_2021",
    )
    postal_to_nuts_path = Path("data/pypsa-at/AT-Postal-to-NUTS.csv")
    return ar_plants_path, nuts3_path, postal_to_nuts_path, powerplants_path


@app.cell
def _(gpd, nuts3_path):
    nuts3_at = (
        gpd.read_file(nuts3_path)
        .query("CNTR_CODE == 'AT'")[["NUTS_ID", "NAME_LATN", "geometry"]]
        .sort_values("NUTS_ID")
        .reset_index(drop=True)
    )
    nuts3_names = nuts3_at.set_index("NUTS_ID")["NAME_LATN"]
    return nuts3_at, nuts3_names


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Ground truth — Anlagenregister water-powered plants

    Water-powered technology codes in the register and the coarse category used
    for the model comparison. The register does **not** split run-of-river from
    reservoir plants for the two `Wasserkraft` classes, so the per-type
    comparison against the model is only possible at the level
    *turbine hydro* (model `ror` + `hydro`) vs. *pumped storage* (model `PHS`).
    Mixed pumped-storage plants also turbine natural inflow; both datasets file
    them under pumped storage.
    """)
    return


@app.cell
def _():
    WATER_TECHCODES = {
        "Kleinwasserkraft bis 10 MW": "turbine hydro",
        "Wasserkraft > 10 MW": "turbine hydro",
        "Hydro power Run-of-river head installation": "turbine hydro",
        "Hydro power Storage head installation": "turbine hydro",
        "Hydro power Pure pumped storage head installation": "pumped storage",
        "Hydro power Mixed pumped storage head": "pumped storage",
        "Tidal Energy Onshore": "turbine hydro",
    }
    return (WATER_TECHCODES,)


@app.cell
def _(WATER_TECHCODES, ar_plants_path, bar, pd, postal_to_nuts_path):
    ar_all = pd.read_csv(ar_plants_path, dtype={"plz": str}, low_memory=False)

    # techcode carries stray whitespace in the raw register -> strip first
    ar_water = ar_all.query("typ == 'Strom'").assign(
        techcode=lambda df: df["techcode"].str.strip()
    )
    ar_water = ar_water.query("techcode in @WATER_TECHCODES").copy()
    ar_water["category"] = ar_water["techcode"].map(WATER_TECHCODES)
    ar_water["capacity_mw"] = ar_water["engpassleistung_kw"] / 1e3
    ar_water["plz_clean"] = bar.clean_plz(ar_water["plz"])
    ar_water["nuts3"] = ar_water["plz_clean"].map(
        bar.load_postal_to_nuts(postal_to_nuts_path)
    )
    ar_water
    return ar_all, ar_water


@app.cell(hide_code=True)
def _(WATER_TECHCODES, ar_all, mo):
    _water_like = set(
        ar_all.query("typ == 'Strom'")["techcode"]
        .dropna()
        .str.strip()
        .loc[lambda s: s.str.contains(r"(?i)wasser|hydro|tidal|wave")]
    )
    _extra = _water_like - set(WATER_TECHCODES)
    if _extra:
        _out = mo.md(
            f"⚠️ Water-like technology codes not covered by "
            f"`WATER_TECHCODES`: {sorted(_extra)}"
        ).callout(kind="warn")
    else:
        _out = mo.md(
            "All water-like technology codes in the register are covered by "
            "`WATER_TECHCODES`."
        ).callout(kind="success")
    _out
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 1.1 Plants without a NUTS3 assignment
    """)
    return


@app.cell(hide_code=True)
def _(ar_water, mo):
    unmapped = ar_water[ar_water["nuts3"].isna()]
    _n = len(unmapped)
    _mw = unmapped["capacity_mw"].sum()
    _no_plz = int(unmapped["plz_clean"].isna().sum())
    mo.md(
        f"**{_n} of {len(ar_water)} water-powered plants cannot be assigned a "
        f"NUTS3 region via postal code** — {_mw:.2f} MW, "
        f"{_mw / ar_water['capacity_mw'].sum():.3%} of the register's water "
        f"capacity.\n\n"
        f"- {_no_plz} plants without an extractable 4-digit postal code\n"
        f"- {_n - _no_plz} plants whose postal code is missing from "
        f"`data/pypsa-at/AT-Postal-to-NUTS.csv`"
    )
    return (unmapped,)


@app.cell
def _(unmapped):
    unmapped[["id", "plz", "ort", "bundesland", "techcode", "capacity_mw"]].sort_values(
        "capacity_mw", ascending=False
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 1.2 Deduplicating multi-registered large plants

    The register contains several entries for the same physical plant
    (registrations per marketing contract, with the reported feed-in split
    across them). Verified cases (2026-09): Malta Hauptstufe appears four
    times (4 x 730 MW, PLZ 9815 Kolbnitz), the Zemm-Ziller group twice
    (2 x 936 MW, Mayrhofen), Kaunertal twice (2 x 392 MW, Prutz) and
    Reisseck II twice (2 x 430 MW, Muehldorf).

    **Rule:** among plants above `DEDUP_MIN_MW` that share
    (postal code, capacity), keep only the entry with the highest total
    reported feed-in. Groups verified as genuinely distinct units are kept
    via `DEDUP_KEEP`: Kaprun 2 x 480 MW (Limberg II, 2011 + Limberg III,
    opened Sep 2025) and Schwarzach im Pongau 2 x 60 MW (the 120 MW
    Speicherkraftwerk Schwarzach registered as two units).

    Note: the kept entry's `techcode` decides the category split — Malta
    Hauptstufe survives as `Wasserkraft > 10 MW`, so its 730 MW count as
    *turbine hydro* instead of *pumped storage*. The register's techcode
    labels for large plants are unreliable either way.
    """)
    return


@app.cell
def _(ar_water, bar, pd):
    DEDUP_MIN_MW = 50.0
    # (plz, capacity_mw) groups verified as genuinely distinct plants
    DEDUP_KEEP = {
        ("5710", 480.0),  # Kaprun: Limberg II (2011) + Limberg III (Sep 2025)
        ("5620", 60.0),  # Speicherkraftwerk Schwarzach: 120 MW as 2 x 60 MW
    }

    _feedin = ar_water[bar.feedin_columns(ar_water)].fillna(0).sum(axis=1)
    _keys = pd.Series(
        list(zip(ar_water["plz_clean"], ar_water["capacity_mw"])),
        index=ar_water.index,
    )
    _candidates = (
        ar_water[(ar_water["capacity_mw"] > DEDUP_MIN_MW) & ~_keys.isin(DEDUP_KEEP)]
        .assign(feedin_total_gwh=_feedin / 1e6)
        .sort_values("feedin_total_gwh", ascending=False)
    )
    ar_dupes = _candidates[
        _candidates.duplicated(subset=["plz_clean", "capacity_mw"], keep="first")
    ]
    ar_water_dedup = ar_water.drop(index=ar_dupes.index)
    return ar_dupes, ar_water_dedup


@app.cell(hide_code=True)
def _(ar_dupes, ar_water, mo):
    mo.md(f"""
    Dropped **{len(ar_dupes)} duplicate register entries** with "
        f"**{ar_dupes["capacity_mw"].sum():.0f} MW** "
        f"({ar_dupes["capacity_mw"].sum() / ar_water["capacity_mw"].sum():.1%} "
        "of the raw register water capacity). All aggregations below use the "
        "deduplicated table.
    """)
    return


@app.cell
def _(ar_dupes):
    ar_dupes[
        [
            "id",
            "plz",
            "ort",
            "bundesland",
            "techcode",
            "capacity_mw",
            "feedin_total_gwh",
        ]
    ]
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 1.3 Register capacity per NUTS3 region and technology [MW]
    """)
    return


@app.cell
def _(ar_water_dedup, nuts3_names):
    _mapped = ar_water_dedup.dropna(subset=["nuts3"])
    gt_by_tech = (
        _mapped.pivot_table(
            index="nuts3",
            columns="techcode",
            values="capacity_mw",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reindex(nuts3_names.index, fill_value=0.0)
        .rename_axis(columns=None)
    )
    gt_by_tech.insert(0, "name", nuts3_names)
    gt_by_tech["total"] = gt_by_tech.drop(columns="name").sum(axis=1)
    gt_by_tech["n_plants"] = (
        _mapped.groupby("nuts3").size().reindex(nuts3_names.index, fill_value=0)
    )

    gt_cat = (
        _mapped.pivot_table(
            index="nuts3",
            columns="category",
            values="capacity_mw",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reindex(nuts3_names.index, fill_value=0.0)
        .rename_axis(columns=None)
    )
    gt_by_tech.round(2)
    return gt_by_tech, gt_cat


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. Model — powerplantmatching hydro fleet

    Mirrors what `build_powerplants` + `attach_hydro` do with the raw
    powerplantmatching table: the `electricity.powerplants_filter` date filter
    (`config/config.de.yaml`, the DE-CHP clause is irrelevant for AT) and the
    `Technology → carrier` mapping of
    `scripts/add_electricity.py::load_and_aggregate_powerplants`.
    """)
    return


@app.cell
def _(pd, powerplants_path):
    TECH_TO_CARRIER = {
        "Run-Of-River": "ror",
        "Reservoir": "hydro",
        "Pumped Storage": "PHS",
    }
    CARRIER_TO_CATEGORY = {
        "ror": "turbine hydro",
        "hydro": "turbine hydro",
        "PHS": "pumped storage",
    }

    ppm_hydro = (
        pd.read_csv(powerplants_path, index_col=0)
        # electricity.powerplants_filter (config/config.de.yaml)
        .query(
            "(DateOut > 2025 or DateOut != DateOut) "
            "and (DateIn < 2026 or DateIn != DateIn)"
        )
        .query("Country == 'Austria' and Fueltype == 'Hydro'")
        .copy()
    )
    ppm_hydro["carrier"] = ppm_hydro["Technology"].map(TECH_TO_CARRIER)
    ppm_hydro["category"] = ppm_hydro["carrier"].map(CARRIER_TO_CATEGORY)
    ppm_hydro
    return (ppm_hydro,)


@app.cell(hide_code=True)
def _(mo, ppm_hydro):
    ppm_dropped = ppm_hydro[ppm_hydro["carrier"].isna()]
    if len(ppm_dropped):
        _out = mo.md(
            f"⚠️ **{len(ppm_dropped)} hydro plants "
            f"({ppm_dropped['Capacity'].sum():.0f} MW) have no `Technology`** in "
            "powerplantmatching. `load_and_aggregate_powerplants` maps their "
            "carrier to `NaN`, so `attach_hydro` attaches them as **no** hydro "
            "component — they are silently missing from the model. They are "
            "excluded from the model totals below (matching model behaviour) "
            "but listed here."
        ).callout(kind="warn")
    else:
        _out = mo.md("All model hydro plants map to a carrier.").callout(kind="success")
    _out
    return (ppm_dropped,)


@app.cell
def _(ppm_dropped):
    ppm_dropped[["Name", "Fueltype", "Technology", "Set", "Capacity", "lat", "lon"]]
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 2.1 Locating model plants in NUTS3 regions
    """)
    return


@app.cell
def _(gpd, nuts3_at, ppm_hydro):
    _pts = gpd.GeoDataFrame(
        ppm_hydro,
        geometry=gpd.points_from_xy(ppm_hydro["lon"], ppm_hydro["lat"]),
        crs=4326,
    ).to_crs(3035)
    _shapes = nuts3_at[["NUTS_ID", "geometry"]].to_crs(3035)

    ppm_located = (
        gpd.sjoin(_pts, _shapes, how="left", predicate="within")
        .rename(columns={"NUTS_ID": "nuts3"})
        .drop(columns="index_right")
    )
    ppm_located = ppm_located[~ppm_located.index.duplicated()]

    # plants outside every AT NUTS3 polygon (border/Grenzkraftwerke or
    # imprecise coordinates) -> snap to the nearest region and flag them
    _outside = ppm_located.index[ppm_located["nuts3"].isna()]
    _nearest = gpd.sjoin_nearest(
        _pts.loc[_outside], _shapes, distance_col="snap_distance_m"
    ).rename(columns={"NUTS_ID": "nuts3"})
    _nearest = _nearest[~_nearest.index.duplicated()]

    ppm_located["snapped_to_nearest"] = False
    ppm_located["snap_distance_m"] = 0.0
    ppm_located.loc[_outside, "nuts3"] = _nearest["nuts3"]
    ppm_located.loc[_outside, "snapped_to_nearest"] = True
    ppm_located.loc[_outside, "snap_distance_m"] = _nearest["snap_distance_m"]
    return (ppm_located,)


@app.cell(hide_code=True)
def _(mo, ppm_located):
    _snapped = ppm_located[ppm_located["snapped_to_nearest"]]
    mo.md(
        f"{len(_snapped)} model plants ({_snapped['Capacity'].sum():.0f} MW) lie "
        "outside every Austrian NUTS3 polygon (border plants / coordinate "
        "precision, cf. pypsa-at-planning#92) and were snapped to the nearest "
        "region:"
    )
    return


@app.cell
def _(ppm_located):
    ppm_located.loc[
        ppm_located["snapped_to_nearest"],
        ["Name", "Technology", "carrier", "Capacity", "nuts3", "snap_distance_m"],
    ].sort_values("snap_distance_m", ascending=False).round(0)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 2.2 Model capacity per NUTS3 region and carrier [MW]
    """)
    return


@app.cell
def _(nuts3_names, ppm_located):
    _attached = ppm_located.dropna(subset=["carrier"])
    model_by_carrier = (
        _attached.pivot_table(
            index="nuts3",
            columns="carrier",
            values="Capacity",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reindex(nuts3_names.index, fill_value=0.0)
        .rename_axis(columns=None)
    )
    model_by_carrier.insert(0, "name", nuts3_names)
    model_by_carrier["total"] = model_by_carrier.drop(columns="name").sum(axis=1)
    model_by_carrier["n_plants"] = (
        _attached.groupby("nuts3").size().reindex(nuts3_names.index, fill_value=0)
    )

    model_cat = (
        _attached.pivot_table(
            index="nuts3",
            columns="category",
            values="Capacity",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reindex(nuts3_names.index, fill_value=0.0)
        .rename_axis(columns=None)
    )
    model_by_carrier.round(2)
    return model_by_carrier, model_cat


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Comparison per NUTS3 region

    `delta_mw = model − register`: negative values mean the model places less
    water-powered capacity in a region than the Anlagenregister reports.
    """)
    return


@app.cell
def _(gt_by_tech, gt_cat, model_by_carrier, model_cat, nuts3_names, pd):
    comp = pd.DataFrame(index=nuts3_names.index)
    comp["name"] = nuts3_names
    comp["register_mw"] = gt_by_tech["total"]
    comp["model_mw"] = model_by_carrier["total"]
    comp["delta_mw"] = comp["model_mw"] - comp["register_mw"]
    for _cat, _short in [("turbine hydro", "turbine"), ("pumped storage", "phs")]:
        comp[f"register_{_short}_mw"] = gt_cat.get(_cat, 0.0)
        comp[f"model_{_short}_mw"] = model_cat.get(_cat, 0.0)
    comp.round(1)
    return (comp,)


@app.cell(hide_code=True)
def _(BASELINE, C_MODEL, C_REGISTER, GRID, INK, MUTED, comp, plt):
    _d = comp.sort_values("register_mw")
    _y = range(len(_d))
    _fig, _ax = plt.subplots(figsize=(9, 11))
    _ax.barh(
        [i + 0.19 for i in _y],
        _d["register_mw"],
        height=0.36,
        color=C_REGISTER,
        label="Anlagenregister",
    )
    _ax.barh(
        [i - 0.19 for i in _y],
        _d["model_mw"],
        height=0.36,
        color=C_MODEL,
        label="Model (powerplantmatching)",
    )
    _ax.set_yticks(list(_y))
    _ax.set_yticklabels(
        [f"{i}  {n}" for i, n in zip(_d.index, _d["name"])], fontsize=8, color=INK
    )
    _ax.set_ylim(-0.6, len(_d) - 0.4)
    _ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    _ax.set_axisbelow(True)
    for _side in ("top", "right", "left"):
        _ax.spines[_side].set_visible(False)
    _ax.spines["bottom"].set_color(BASELINE)
    _ax.tick_params(colors=MUTED)
    _ax.set_xlabel("installed water-powered capacity [MW]", color=MUTED)
    _ax.set_title(
        "Water-powered capacity per NUTS3 — register vs. model",
        color=INK,
        loc="left",
    )
    _ax.legend(frameon=False, loc="lower right")
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(BASELINE, C_MODEL, C_REGISTER, GRID, INK, MUTED, comp, plt):
    _d = comp.sort_values("register_mw")
    _y = range(len(_d))
    _fig, _axes = plt.subplots(1, 2, figsize=(12, 11), sharey=True)
    for _ax, _short, _title in zip(
        _axes,
        ("turbine", "phs"),
        ("Turbine hydro (ror + reservoir)", "Pumped storage (PHS)"),
    ):
        _ax.barh(
            [i + 0.19 for i in _y],
            _d[f"register_{_short}_mw"],
            height=0.36,
            color=C_REGISTER,
            label="Anlagenregister",
        )
        _ax.barh(
            [i - 0.19 for i in _y],
            _d[f"model_{_short}_mw"],
            height=0.36,
            color=C_MODEL,
            label="Model",
        )
        _ax.set_ylim(-0.6, len(_d) - 0.4)
        _ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        _ax.set_axisbelow(True)
        for _side in ("top", "right", "left"):
            _ax.spines[_side].set_visible(False)
        _ax.spines["bottom"].set_color(BASELINE)
        _ax.tick_params(colors=MUTED)
        _ax.set_xlabel("capacity [MW]", color=MUTED)
        _ax.set_title(_title, color=INK, loc="left", fontsize=11)
    _axes[0].set_yticks(list(_y))
    _axes[0].set_yticklabels(
        [f"{i}  {n}" for i, n in zip(_d.index, _d["name"])], fontsize=8, color=INK
    )
    _axes[0].legend(frameon=False, loc="lower right")
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(
    DIV_BLUE,
    DIV_MID,
    DIV_RED,
    INK,
    SEQ_BLUES,
    comp,
    mcolors,
    nuts3_at,
    plt,
):
    _g = nuts3_at.merge(comp, left_on="NUTS_ID", right_index=True)
    _seq = mcolors.LinearSegmentedColormap.from_list("seq_blue", SEQ_BLUES)
    _div = mcolors.LinearSegmentedColormap.from_list(
        "div_rb", [DIV_RED, DIV_MID, DIV_BLUE]
    )
    _vmax = float(max(_g["register_mw"].max(), _g["model_mw"].max()))
    _dmax = float(max(_g["delta_mw"].abs().max(), 1.0))

    _fig, _axes = plt.subplots(3, 1, figsize=(9, 12))
    for _ax, _col, _cmap, _norm, _title in [
        (
            _axes[0],
            "register_mw",
            _seq,
            mcolors.Normalize(vmin=0, vmax=_vmax),
            "Anlagenregister [MW]",
        ),
        (
            _axes[1],
            "model_mw",
            _seq,
            mcolors.Normalize(vmin=0, vmax=_vmax),
            "Model (powerplantmatching) [MW]",
        ),
        (
            _axes[2],
            "delta_mw",
            _div,
            mcolors.TwoSlopeNorm(vmin=-_dmax, vcenter=0.0, vmax=_dmax),
            "Delta (model − register) [MW]",
        ),
    ]:
        _g.plot(
            column=_col,
            ax=_ax,
            cmap=_cmap,
            norm=_norm,
            edgecolor="white",
            linewidth=0.5,
            legend=True,
            legend_kwds={"shrink": 0.7},
        )
        _ax.set_title(_title, color=INK, loc="left", fontsize=11)
        _ax.set_axis_off()
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    _gaps = comp.assign(absdelta=comp["delta_mw"].abs()).nlargest(5, "absdelta")
    _lines = "\n".join(
        f"    - `{_i}` {_r['name']}: register {_r.register_mw:.0f} MW vs. "
        f"model {_r.model_mw:.0f} MW ({_r.delta_mw:+.0f} MW)"
        for _i, _r in _gaps.iterrows()
    )
    mo.md(f"\"\"
    ## Summary

    - Anlagenregister water-powered capacity (NUTS3-mapped):
      **{comp["register_mw"].sum() / 1e3:.2f} GW** in
      {len(ar_water_dedup) - len(unmapped)} plants
      (turbine hydro {comp["register_turbine_mw"].sum() / 1e3:.2f} GW,
      pumped storage {comp["register_phs_mw"].sum() / 1e3:.2f} GW)
    - Model hydro capacity (powerplantmatching, attached carriers):
      **{comp["model_mw"].sum() / 1e3:.2f} GW** in
      {int(ppm_located["carrier"].notna().sum())} plants
      (turbine hydro {comp["model_turbine_mw"].sum() / 1e3:.2f} GW,
      pumped storage {comp["model_phs_mw"].sum() / 1e3:.2f} GW)
    - Duplicate register entries removed before aggregation:
      **{len(ar_dupes)}** ({ar_dupes["capacity_mw"].sum():.0f} MW)
    - Register plants without NUTS3 assignment (postal code):
      **{len(unmapped)}** ({unmapped["capacity_mw"].sum():.2f} MW)
    - Model plants silently dropped (no `Technology` → no carrier):
      **{len(ppm_dropped)}** ({ppm_dropped["Capacity"].sum():.0f} MW)
    - Largest regional gaps (model − register):
    {_lines}
    "\"\")
    """)
    return


if __name__ == "__main__":
    app.run()
