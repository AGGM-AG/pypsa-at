import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Hydro inflow recalibration: TYNDP country totals → KLIEN NUTS3 targets

    Prototype of the effect of the planned calibration steps (targets & scaling
    layer only — the **profile shape stays the ERA5/atlite one**):

    - **Before** — the AT inflow totals built by
      `build_inflow_totals_per_region` (TYNDP/PEMMDB country totals distributed
      to regions by capacity), read from
      `resources/hydro-capacities-update/AT_KN2040/`. **Caveat:** since the
      calibration is wired into the workflow, that file already carries the
      KLIEN targets for AT ror/hydro when `mods.update_hydro_capacities_AT` is
      enabled; a true TYNDP "before" needs a run predating the wiring.
    - **After** — KLIEN study existing generation (`E_current`, GWh/a
      Regelarbeitsvermögen per river-section catchment, discharge reference
      1991–2020) mapped to NUTS3, split into `ror`/`hydro` by the regional
      plant-capacity mix, and scaled to a selectable weather year with
      E-Control's annual Laufkraft/Speicherkraft series.
    - **Deliverable check** — RoR energy is re-simulated hourly with the
      unchanged ERA5 profile and clipped at installed capacity
      (`min(inflow, p_nom)`), mirroring `patch_inflows`' `p_max_pu ≤ 1`.

    Assumptions (documented, to be replaced by the real implementation;
    KLIEN facts verified against the Langfassung, §4.3.2/§4.3.4):

    1. **Carved out:** Section→NUTS3 allocation is now **plant-location
       based** (`scripts/pypsa-at/build_hydro_inflow_targets.py`, unit
       tests in `test/test_build_hydro_inflow_targets.py`): plants with
       coordinates (100% of hydro/PHS MW, 75% of ror MW) are placed
       point-in-catchment; coordless Anlagenregister plants are spread over
       the sections intersecting their NUTS3 region (area-weighted
       overlap); each section's energy then follows plant capacity. The
       former area-weighted heuristic is kept as a reference — border
       sections (`BUNDESLAND = "anteilig …"`, Danube!) are where the two
       methods differ. Coordless Anlagenregister plants are spread over the
       sections intersecting their NUTS3 `bus` region. A finer PLZ/Gemeinde
       lookup cascade exists in the module (`extra_lookups`; the `plz`
       column is in the overwrite CSV) but was measured to move only
       0.78% of the energy (max 82 GWh/a per NUTS3) and is deliberately
       not wired to external polygon datasets — reactivate it when outputs
       become finer than NUTS3 (per-plant profiles, section-level
       corridors).
    2. **Verified:** `E_current` is the RAV of Lauf- **und**
       Speicherkraftwerke (44.14 TWh/a, Datenstand Nov 2024; 5,835 Lauf +
       74 Speicher plants), **excluding** the 24 Pumpspeicherkraftwerke
       (total incl. PS would be 53.3 TWh/a; Tabelle 15). The `ror`/`hydro`
       split here uses regional capacity shares from
       `powerplants_s_adm.csv` — caveat: KLIEN's Speicher/PS
       boundary (PS EPL ≈ 15,756 − 10,660 ≈ 5.1 GW) differs from the model's
       `Technology` labels (PHS ≈ 6.1 GW) by ~1 GW of borderline storage
       plants; the real implementation should reconcile plant classification
       before splitting.
    3. **PHS natural inflow stays untouched** (TYNDP *PS Open*). Verified as
       double-count-free: PS plants are outside `E_current`, and in the
       Restpotenzial their river sections are treated "als ausgebaut", so
       PS water is in neither KLIEN quantity — the TYNDP value is additive.
       Before = after for PHS. (KLIEN's PS RAV ≈ 9.2 TWh includes
       pumping-derived generation — never use it as natural inflow.)
    4. Year factors: `f_ror = Lauf(year)/mean(Lauf 1991–2020)`,
       `f_hydro = Speicher(year)/mean(Speicher 1991–2020)` (E-Control
       Speicher incl. pumped-storage generation — caveat).

    Downloads on first run (cached in `data/klien-hydro/`): KLIEN hydro
    GeoJSON (~82 MB) from the GTIF share, E-Control `BStGes-JR1_Bilanz.xlsx`.

    Run from the repository root:
    `pixi run marimo edit .marimo/recalibrate-hydro-inflows-klien.py`
    """)
    return


@app.cell(hide_code=True)
def _(econtrol, mo):
    _years = [
        int(y)
        for y in econtrol.index
        if econtrol.loc[y, ["lauf", "speicher"]].notna().all()
    ]
    year_sel = mo.ui.dropdown(
        options={str(y): y for y in _years},
        value="2013",
        label="Scale KLIEN RAV to weather year",
    )
    year_sel
    return (year_sel,)


@app.cell(hide_code=True)
def _(
    clip_after,
    clip_before,
    comp,
    diag_pb,
    f_hydro,
    f_ror,
    klien_total_gwh,
    mo,
    year,
):
    _t = comp.groupby("carrier")[["before_mwh", "after_mwh"]].sum() / 1e6
    _ca, _cb = clip_after.sum() / 1e6, clip_before.sum() / 1e6
    mo.md(f"""
    ## Summary — weather year {year}

    | | before | after | Δ |
    |---|---:|---:|---:|
    | ror [TWh/a] | {_t.loc["ror", "before_mwh"]:.1f} | {_t.loc["ror", "after_mwh"]:.1f} | {_t.loc["ror", "after_mwh"] - _t.loc["ror", "before_mwh"]:+.1f} |
    | hydro [TWh/a] | {_t.loc["hydro", "before_mwh"]:.1f} | {_t.loc["hydro", "after_mwh"]:.1f} | {_t.loc["hydro", "after_mwh"] - _t.loc["hydro", "before_mwh"]:+.1f} |
    | PHS [TWh/a] (unchanged) | {_t.loc["PHS", "before_mwh"]:.1f} | {_t.loc["PHS", "after_mwh"]:.1f} | +0.0 |
    | **total** | **{_t["before_mwh"].sum():.1f}** | **{_t["after_mwh"].sum():.1f}** | **{_t["after_mwh"].sum() - _t["before_mwh"].sum():+.1f}** |

    - KLIEN RAV basis: **{klien_total_gwh / 1e3:.1f} TWh/a** across sections;
      year factors ror **{f_ror:.3f}**, hydro **{f_hydro:.3f}**.
    - Plant-based allocation left
      **{diag_pb["unallocated"].sum():.0f} GWh/a** unallocated (sections
      without any eligible ror/hydro plant).
    - RoR clipping at p_nom with the unchanged ERA5 shape:
      before **{_cb["clipped_mwh"]:.2f} TWh** ({_cb["clipped_mwh"] / max(_cb.sum(), 1e-9):.1%}),
      after **{_ca["clipped_mwh"]:.2f} TWh**
      ({_ca["clipped_mwh"] / max(_ca.sum(), 1e-9):.1%} of the RoR target) —
      energy the calibration pushes in but the current fleet + profile cannot
      absorb. A routed discharge shape (EFAS/GloFAS) would flatten exactly
      these peaks.
    """)
    return


@app.cell(hide_code=True)
def _(C_AFTER, C_CLIP, plt, ror_monthly):
    _fig, _ax = plt.subplots(figsize=(8, 3.4))
    _m = ror_monthly.copy()
    _m.index = _m.index.strftime("%b")
    _ax.bar(_m.index, _m["delivered"], color=C_AFTER, label="delivered")
    _ax.bar(
        _m.index,
        _m["target"] - _m["delivered"],
        bottom=_m["delivered"],
        color=C_CLIP,
        label="clipped",
    )
    _ax.set_ylabel("GWh/month")
    _ax.set_title(
        "Austria ror after calibration: monthly energy and clipping (ERA5 shape)",
        loc="left",
        fontsize=10,
    )
    _ax.legend(frameon=False, fontsize=9)
    _ax.spines[["top", "right"]].set_visible(False)
    _ax.grid(axis="y", alpha=0.25)
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(C_AFTER, C_BEFORE, C_CLIP, C_INK, clip_after, comp, plt):
    _tot = comp.groupby("carrier")[["before_mwh", "after_mwh"]].sum() / 1e6
    _tot = _tot.reindex(["ror", "hydro", "PHS"])
    _fig, _ax = plt.subplots(figsize=(7.5, 3.6))
    _x = range(len(_tot))
    _w = 0.38
    _b1 = _ax.bar(
        [i - _w / 2 for i in _x],
        _tot["before_mwh"],
        _w,
        color=C_BEFORE,
        label="before (TYNDP)",
    )
    _b2 = _ax.bar(
        [i + _w / 2 for i in _x],
        _tot["after_mwh"],
        _w,
        color=C_AFTER,
        label="after (KLIEN × year factor)",
    )
    _del = clip_after["delivered_mwh"].sum() / 1e6
    _ax.hlines(
        _del,
        0 + _w / 2 - _w / 2 * 0.9,
        0 + _w / 2 + _w / 2 * 0.9,
        color=C_CLIP,
        lw=2.5,
        zorder=5,
        label="ror deliverable after clipping",
    )
    for _bars in (_b1, _b2):
        _ax.bar_label(_bars, fmt="%.1f", padding=2, fontsize=9, color=C_INK)
    _ax.set_xticks(list(_x), _tot.index)
    _ax.set_ylabel("TWh/a")
    _ax.set_title("Austria: annual inflow energy by carrier", loc="left")
    _ax.legend(frameon=False, fontsize=9)
    _ax.spines[["top", "right"]].set_visible(False)
    _ax.grid(axis="y", alpha=0.25)
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(C_AFTER, C_BEFORE, comp, plt):
    _fig, _axes = plt.subplots(1, 2, figsize=(9.5, 7), sharey=False)
    for _ax, _car in zip(_axes, ["ror", "hydro"]):
        _d = (
            comp[comp["carrier"] == _car]
            .set_index("bus")[["before_mwh", "after_mwh"]]
            .div(1e3)  # GWh
        )
        _d = _d[(_d > 0).any(axis=1)].sort_values("after_mwh")
        _y = range(len(_d))
        _h = 0.38
        _ax.barh(
            [i + _h / 2 for i in _y],
            _d["before_mwh"],
            _h,
            color=C_BEFORE,
            label="before",
        )
        _ax.barh(
            [i - _h / 2 for i in _y],
            _d["after_mwh"],
            _h,
            color=C_AFTER,
            label="after",
        )
        _ax.set_yticks(list(_y), _d.index, fontsize=8)
        _ax.set_title(f"{_car} — inflow energy per NUTS3 [GWh/a]", loc="left")
        _ax.spines[["top", "right"]].set_visible(False)
        _ax.grid(axis="x", alpha=0.25)
    _axes[0].legend(frameon=False, fontsize=9, loc="lower right")
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(C_AFTER, C_CLIP, clip_after, plt):
    _d = (clip_after / 1e3).sort_values("delivered_mwh")
    _d = _d[_d.sum(axis=1) > 0]
    _fig, _ax = plt.subplots(figsize=(8, 5.5))
    _y = range(len(_d))
    _ax.barh(_y, _d["delivered_mwh"], color=C_AFTER, label="delivered")
    _ax.barh(
        _y,
        _d["clipped_mwh"],
        left=_d["delivered_mwh"],
        color=C_CLIP,
        label="clipped at p_nom",
    )
    for _i, (_b, _row) in enumerate(_d.iterrows()):
        if _row["clipped_mwh"] > 0.02 * _row.sum():
            _ax.text(
                _row.sum() + 8,
                _i,
                f"−{_row['clipped_mwh'] / _row.sum():.0%}",
                va="center",
                fontsize=8,
                color=C_CLIP,
            )
    _ax.set_yticks(list(_y), _d.index, fontsize=8)
    _ax.set_xlabel("GWh/a")
    _ax.set_title(
        "ror after calibration: delivered vs clipped (ERA5 shape, hourly min(inflow, p_nom))",
        loc="left",
        fontsize=10,
    )
    _ax.legend(frameon=False, fontsize=9, loc="lower right")
    _ax.spines[["top", "right"]].set_visible(False)
    _ax.grid(axis="x", alpha=0.25)
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(comp, nuts3_at, plt):
    _delta = (
        comp.groupby("bus")[["before_mwh", "after_mwh"]]
        .sum()
        .eval("(after_mwh - before_mwh) / 1e3")
    )
    _g = nuts3_at.merge(_delta.rename("delta_gwh"), on="bus", how="left")
    _lim = _g["delta_gwh"].abs().max()
    _fig, _ax = plt.subplots(figsize=(8.5, 4.6))
    _g.plot(
        column="delta_gwh",
        cmap="RdBu",
        vmin=-_lim,
        vmax=_lim,
        edgecolor="white",
        linewidth=0.4,
        legend=True,
        ax=_ax,
        legend_kwds={"label": "after − before [GWh/a]", "shrink": 0.7},
        missing_kwds={"color": "#e8e8e8"},
    )
    _ax.set_axis_off()
    _ax.set_title("Change in annual inflow energy per NUTS3 (all carriers)", loc="left")
    _fig.tight_layout()
    _fig
    return


@app.cell
def _():
    import shutil
    import sys
    import urllib.request
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import xarray as xr

    sys.path[:0] = [".", "scripts", "scripts/pypsa-at"]
    import build_hydro_inflow_targets as bhit

    from mods.network.hydro import _redistribute_peaks as redistribute_peaks

    return (
        Path,
        bhit,
        gpd,
        mdates,
        mo,
        np,
        pd,
        plt,
        redistribute_peaks,
        shutil,
        urllib,
        xr,
    )


@app.cell
def _(Path):
    RESOURCES = Path("resources/hydro-capacities-update/AT_KN2040")
    NUTS3_SHAPES = Path("resources/nuts3_shapes.geojson")
    CACHE = Path("data/klien-hydro")

    KLIEN_BASE = (
        "https://workspace-ui-public.gtif-austria.hub-otc.eox.at"
        "/api/public/share/public-4wazei3y-02/KLIEN-studie"
    )
    KLIEN_GEOJSON_URL = f"{KLIEN_BASE}/hydro/hydro_EEPOT_W23.geojson"
    ECONTROL_URL = (
        "https://www.e-control.at/documents/1785851/1811609/BStGes-JR1_Bilanz.xlsx"
    )

    TECH_TO_CARRIER = {
        "Run-Of-River": "ror",
        "Reservoir": "hydro",
        "Pumped Storage": "PHS",
    }
    # dataviz palette (validated): before / after / clipped + neutral ink
    C_BEFORE = "#9AA5B1"
    C_AFTER = "#1F6FB2"
    C_CLIP = "#C08A26"
    C_INK = "#3A4550"
    # categorical carrier colours (dataviz slots 1-3, fixed order)
    C_CARRIER = {"ror": "#2a78d6", "hydro": "#eb6834", "PHS": "#1baf7a"}
    return (
        CACHE,
        C_AFTER,
        C_BEFORE,
        C_CARRIER,
        C_CLIP,
        C_INK,
        ECONTROL_URL,
        KLIEN_GEOJSON_URL,
        NUTS3_SHAPES,
        RESOURCES,
        TECH_TO_CARRIER,
    )


@app.cell
def _(CACHE, ECONTROL_URL, KLIEN_GEOJSON_URL, shutil, urllib):
    def _download(url: str, dest):
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return dest

    klien_geojson_path = _download(KLIEN_GEOJSON_URL, CACHE / "hydro_EEPOT_W23.geojson")
    econtrol_path = _download(ECONTROL_URL, CACHE / "BStGes-JR1_Bilanz.xlsx")
    return econtrol_path, klien_geojson_path


@app.cell
def _(gpd, klien_geojson_path):
    sections = gpd.read_file(klien_geojson_path)
    sections.columns = [c.strip() for c in sections.columns]
    sections = sections[
        [
            "id",
            "ABSCHNITT",
            "BUNDESLAND",
            "FLAECHEKM2",
            "E_current",
            "C_current",
            "geometry",
        ]
    ]
    # 249 of 289 sections carry data; the rest are foreign catchments
    sections = sections[sections["E_current"].notna()].to_crs(3416)
    klien_total_gwh = sections["E_current"].sum()
    return klien_total_gwh, sections


@app.cell
def _(NUTS3_SHAPES, Path, RESOURCES, bhit, gpd, pd, xr):
    nuts3_at = (
        gpd.read_file(NUTS3_SHAPES)
        .query("country == 'AT'")[["index", "name", "geometry"]]
        .rename(columns={"index": "bus"})
        .to_crs(3416)
    )

    before = pd.read_csv(RESOURCES / "inflow_totals_per_region_adm.csv")
    before = before[before["bus"].str.startswith("AT")].rename(
        columns={"inflow": "before_mwh"}
    )

    _ppl = pd.read_csv(
        RESOURCES / "powerplants_s_adm.csv",
        dtype={"plz": str},
        low_memory=False,
    )
    # AT fleet plus the German Grenzkraftwerke halves, as in the workflow rule
    plants_at = bhit.select_hydro_plants(
        _ppl, pd.read_csv(Path("data/pypsa-at/grenzkraftwerke_AT.csv"))
    )
    cap = (
        plants_at[plants_at["bus"].str.startswith("AT")]
        .groupby(["bus", "carrier"])["p_nom"]
        .sum()
        .unstack(fill_value=0)
    )

    profile = xr.open_dataarray(RESOURCES / "profile_inflow_adm.nc")
    profile_at = profile.sel(
        countries=[c for c in profile.countries.values if str(c).startswith("AT")]
    ).to_pandas()  # time x region, sums to 1.0 per year
    if profile_at.shape[0] < profile_at.shape[1]:
        profile_at = profile_at.T
    return before, cap, nuts3_at, plants_at, profile_at


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 1 — KLIEN section catchments → NUTS3

    **Plant-based (production logic, used downstream):** each section's
    `E_current` is split over the ror/hydro plants located in its catchment,
    capacity-weighted (`build_hydro_inflow_targets.build_inflow_targets`).
    The carrier split falls out of the plant list — no capacity-share
    heuristic needed. Inter-catchment **diversion overrides**
    (`hydro_diversion_overrides_AT.csv`) pin plants that turbine water from a
    different catchment than they sit in (Prutz/Kaunertal ← Faggenbach) to
    the section they actually turbine — this is what makes AT334 feasible.

    **Area-weighted (reference only):** energy proportional to
    catchment ∩ NUTS3 overlap area, carrier split by regional capacity mix.
    """)
    return


@app.cell
def _(Path, bhit, nuts3_at, pd, plants_at, sections):
    # inter-catchment diversion overrides: plants that turbine water dammed
    # in a different catchment than where they sit (Prutz/Kaunertal turbines
    # the Faggenbach) — point-in-polygon cannot place these
    diversion_overrides = pd.read_csv(
        Path("data/pypsa-at/hydro_diversion_overrides_AT.csv")
    )
    _targets, diag_pb = bhit.build_inflow_targets(
        plants_at,
        sections.set_index("id"),
        nuts3_at.set_index("bus"),
        overrides=diversion_overrides,
        capacity_col="C_current",  # cap at the section's own full-load hours
    )
    # the German twins' share and the PHS-attributed energy are dropped, as
    # in the workflow rule
    targets_gwh = _targets[
        _targets["bus"].str.startswith("AT") & (_targets["carrier"] != "PHS")
    ].rename(columns={"energy": "target_gwh"})
    return diag_pb, targets_gwh


@app.cell
def _(cap, gpd, nuts3_at, sections):
    _s = sections.copy()
    _s["sec_area"] = _s.geometry.area
    _ov = gpd.overlay(
        _s[["id", "E_current", "sec_area", "geometry"]],
        nuts3_at[["bus", "geometry"]],
        how="intersection",
        keep_geom_type=True,
    )
    _ov["e_gwh"] = _ov["E_current"] * _ov.geometry.area / _ov["sec_area"]
    e_nuts3_gwh = _ov.groupby("bus")["e_gwh"].sum()

    # split ror / hydro by capacity share; PHS capacity does not take KLIEN energy
    _cap_rh = cap.reindex(columns=["ror", "hydro"], fill_value=0.0)
    _share = _cap_rh.div(_cap_rh.sum(axis=1), axis=0)
    _share = _share.reindex(e_nuts3_gwh.index)
    targets_area_gwh = (
        _share.mul(e_nuts3_gwh, axis=0)
        .dropna()
        .rename_axis("bus")
        .reset_index()
        .melt(id_vars="bus", var_name="carrier", value_name="target_gwh")
    )
    return e_nuts3_gwh, targets_area_gwh


@app.cell
def _(diag_pb, e_nuts3_gwh, pd, sections, targets_area_gwh, targets_gwh):
    coverage = pd.DataFrame(
        {
            "GWh/a": {
                "KLIEN total (sections)": sections["E_current"].sum(),
                "plant-based, allocated": targets_gwh["target_gwh"].sum(),
                "plant-based, unallocated sections": diag_pb["unallocated"].sum(),
                "area-weighted, inside AT NUTS3": e_nuts3_gwh.sum(),
                "area-weighted, allocated": targets_area_gwh["target_gwh"].sum(),
            }
        }
    ).round(0)
    return (coverage,)


@app.cell(hide_code=True)
def _(C_AFTER, C_BEFORE, pd, plt, targets_area_gwh, targets_gwh):
    _pb = targets_gwh.groupby("bus")["target_gwh"].sum()
    _aw = targets_area_gwh.groupby("bus")["target_gwh"].sum()
    _d = pd.DataFrame({"plant": _pb, "area": _aw}).fillna(0.0)
    _d = _d.loc[(_d["plant"] - _d["area"]).abs().sort_values().index].tail(15)
    _fig, _ax = plt.subplots(figsize=(8, 5))
    _y = range(len(_d))
    _h = 0.38
    _ax.barh(
        [i + _h / 2 for i in _y],
        _d["area"],
        _h,
        color=C_BEFORE,
        label="area-weighted (reference)",
    )
    _ax.barh(
        [i - _h / 2 for i in _y],
        _d["plant"],
        _h,
        color=C_AFTER,
        label="plant-based (production logic)",
    )
    _ax.set_yticks(list(_y), _d.index, fontsize=8)
    _ax.set_xlabel("GWh/a (ror + hydro)")
    _ax.set_title(
        "Allocation method comparison — 15 largest NUTS3 differences",
        loc="left",
        fontsize=10,
    )
    _ax.legend(frameon=False, fontsize=9, loc="lower right")
    _ax.spines[["top", "right"]].set_visible(False)
    _ax.grid(axis="x", alpha=0.25)
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(coverage, mo):
    mo.vstack(
        [
            mo.md(
                "**Coverage check** — plant-based: unallocated energy sits in "
                "sections without any eligible (ror/hydro) plant; area-weighted: "
                "energy outside AT NUTS3 polygons belongs to foreign catchment "
                "parts. Downstream steps use the **plant-based** targets."
            ),
            coverage,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 2 — weather-year scaling (E-Control annual series)

    `E_current` is a 1991–2020 mean. The dropdown scales it to a calendar
    year's observed generation. The ERA5 profile in this run is **weather year
    2013**, so 2013 is the consistent default.
    """)
    return


@app.cell
def _(econtrol_path, pd):
    _df = pd.read_excel(econtrol_path, sheet_name="Erz", header=None)
    _d = _df.iloc[10:, :8].copy()
    _d.columns = [
        "year",
        "lauf_le10",
        "lauf_gt10",
        "lauf",
        "sp_le10",
        "sp_le10_psw",
        "sp_gt10",
        "sp_gt10_psw",
    ]
    _d = _d[pd.to_numeric(_d["year"], errors="coerce").notna()]
    econtrol = _d.apply(pd.to_numeric, errors="coerce").set_index("year").sort_index()
    econtrol["speicher"] = econtrol["sp_le10"] + econtrol["sp_gt10"]
    _ref = econtrol.loc[1991:2020]
    ref_lauf, ref_speicher = _ref["lauf"].mean(), _ref["speicher"].mean()
    return econtrol, ref_lauf, ref_speicher


@app.cell
def _(before, econtrol, ref_lauf, ref_speicher, targets_gwh, year_sel):
    year = int(year_sel.value)
    f_ror = econtrol.loc[year, "lauf"] / ref_lauf
    f_hydro = econtrol.loc[year, "speicher"] / ref_speicher
    factors = {"ror": f_ror, "hydro": f_hydro}

    _after = targets_gwh.copy()
    _after["after_mwh"] = _after.apply(
        lambda r: r["target_gwh"] * 1e3 * factors[r["carrier"]], axis=1
    )
    comp = before.merge(
        _after[["bus", "carrier", "after_mwh"]], on=["bus", "carrier"], how="outer"
    ).fillna(0.0)
    # PHS: calibration leaves TYNDP values untouched
    _phs = comp["carrier"] == "PHS"
    comp.loc[_phs, "after_mwh"] = comp.loc[_phs, "before_mwh"]
    comp = comp.sort_values(["carrier", "bus"]).reset_index(drop=True)
    return comp, f_hydro, f_ror, year


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 3 — RoR deliverable energy with the unchanged ERA5 shape

    `patch_inflows` sets `p_max_pu = inflow / p_nom` for RoR, so hourly inflow
    above installed capacity is spilled. With ~2× more annual energy pushed
    through the same normalized shape, clipping is where the calibration can
    silently lose energy.
    """)
    return


@app.cell
def _(cap, comp, np, pd, profile_at):
    _ror = comp.query("carrier == 'ror'").set_index("bus")
    _p_nom = cap["ror"].reindex(_ror.index).fillna(0.0)

    def _deliverable(energy_mwh: pd.Series) -> pd.DataFrame:
        _rows = {}
        for _b, _e in energy_mwh.items():
            if _b not in profile_at.columns or _p_nom[_b] <= 0 or _e <= 0:
                _rows[_b] = (0.0, 0.0)
                continue
            _inflow_mw = _e * profile_at[_b]  # hourly MW, sums to _e MWh
            _del = np.minimum(_inflow_mw, _p_nom[_b]).sum()
            _rows[_b] = (_del, _e - _del)
        return pd.DataFrame(_rows, index=["delivered_mwh", "clipped_mwh"]).T

    clip_before = _deliverable(_ror["before_mwh"])
    clip_after = _deliverable(_ror["after_mwh"])

    # deliverable with the model's actual logic: patch_inflows applies
    # _redistribute_peaks to ror p_max_pu, shifting clipped energy into
    # unclipped hours. For a feasible region (target <= p_nom * 8760 h) that
    # converges to exactly the target (computed directly here for speed,
    # matching mods.network.hydro._redistribute_peaks' converged result). A
    # region whose target exceeds that bound is infeasible: in production
    # _redistribute_peaks raises ValueError rather than silently spilling —
    # this notebook still shows the analytic min(target, bound) below purely
    # to size how much energy calibration would need to shed there.
    ror_redistributed_mwh = pd.Series(
        {
            b: min(_ror["after_mwh"][b], _p_nom[b] * len(profile_at))
            for b in _ror.index
            if b in profile_at.columns and _p_nom[b] > 0
        }
    )

    # hydro reservoir / PHS: StorageUnits absorb hourly inflow peaks; the
    # binding annual bound is dispatch capacity (p_nom * 8760 h) — far above
    # both targets, so no spillage is expected there
    _cap_bound = {
        c: cap[c].reindex(comp.query("carrier == @c")["bus"].unique()).sum() * 8760
        for c in ["hydro", "PHS"]
    }
    ror_monthly = (
        pd.DataFrame(
            {
                "target": pd.concat(
                    [
                        _ror["after_mwh"][b] * profile_at[b]
                        for b in _ror.index
                        if b in profile_at.columns
                    ],
                    axis=1,
                ).sum(axis=1),
                "delivered": pd.concat(
                    [
                        np.minimum(
                            _ror["after_mwh"][b] * profile_at[b], _p_nom.get(b, 0.0)
                        )
                        for b in _ror.index
                        if b in profile_at.columns
                    ],
                    axis=1,
                ).sum(axis=1),
            }
        )
        .resample("MS")
        .sum()
        / 1e3
    )  # GWh
    return clip_after, clip_before, ror_monthly, ror_redistributed_mwh


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Results
    """)
    return


@app.cell(hide_code=True)
def _(
    C_AFTER,
    C_BEFORE,
    C_CLIP,
    C_INK,
    clip_after,
    comp,
    plt,
    ror_redistributed_mwh,
):
    # yearly hydro energy in the brownfield fleet: without spillage (inflow
    # target), with pure clipping (spilled at p_nom), and with the model's
    # actual p_max_pu redistribution (_redistribute_peaks in patch_inflows)
    _t = comp.groupby("carrier")["after_mwh"].sum() / 1e6
    _no_spill = {c: _t[c] for c in ["ror", "hydro", "PHS"]}
    _clipped = {
        "ror": clip_after["delivered_mwh"].sum() / 1e6,
        "hydro": _t["hydro"],  # StorageUnit absorbs hourly peaks
        "PHS": _t["PHS"],
    }
    _redist = dict(_clipped, ror=ror_redistributed_mwh.sum() / 1e6)
    for _d in (_no_spill, _clipped, _redist):
        _d["total"] = sum(_d.values())

    _fig, _ax = plt.subplots(figsize=(8, 3.8))
    _cats = ["ror", "hydro", "PHS", "total"]
    _x = range(len(_cats))
    _w = 0.27
    _b1 = _ax.bar(
        [i - _w for i in _x],
        [_no_spill[c] for c in _cats],
        _w,
        color=C_AFTER,
        label="without spillage (inflow target)",
    )
    _b2 = _ax.bar(
        [i for i in _x],
        [_redist[c] for c in _cats],
        _w,
        color=C_BEFORE,
        label="model logic (p_max_pu redistribution)",
    )
    _b3 = _ax.bar(
        [i + _w for i in _x],
        [_clipped[c] for c in _cats],
        _w,
        color=C_CLIP,
        label="pure clipping (spillage, no redistribution)",
    )
    for _bars in (_b1, _b2, _b3):
        _ax.bar_label(_bars, fmt="%.1f", padding=2, fontsize=8, color=C_INK)
    _ax.set_xticks(list(_x), _cats)
    _ax.set_ylabel("TWh/a")
    _ax.set_title(
        "Brownfield hydro energy with and without spillage (calibrated targets)",
        loc="left",
        fontsize=11,
    )
    _ax.legend(frameon=False, fontsize=8)
    _ax.spines[["top", "right"]].set_visible(False)
    _ax.grid(axis="y", alpha=0.25)
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 4 — `p_max_pu` per technology and NUTS3 region, before and after `_redistribute_peaks`

    `patch_inflows` (`mods/network/hydro.py`) turns the hourly inflow into
    `p_max_pu` time series:

    - **ror** generators: `p_max_pu = inflow / p_nom`. Hours above 1 are
      capped and their energy is redistributed over the other hours by
      `_redistribute_peaks` — the real function is called below. A region
      whose annual energy exceeds `p_nom × 8760 h` cannot be redistributed;
      the function raises and the callout below shows the message.
    - **hydro inflow** / **PHS inflow** generators: `p_nom` is set to the
      maximum hourly inflow and `p_max_pu = inflow / max(inflow)`. The
      profile never exceeds 1 and no redistribution is applied, so before
      and after are identical for these two carriers.

    The *basis* selects which annual energies are pushed through the ERA5
    shape: the KLIEN-calibrated targets of the selected weather year (PHS
    unchanged) or the TYNDP totals of the current run.
    """)
    return


@app.cell(hide_code=True)
def _(mo, nuts3_at):
    region_names = nuts3_at.set_index("bus")["name"].sort_index()
    pmax_basis_sel = mo.ui.dropdown(
        options={
            "KLIEN-calibrated (after)": "after_mwh",
            "TYNDP (before)": "before_mwh",
        },
        value="KLIEN-calibrated (after)",
        label="Inflow basis",
    )
    pmax_region_sel = mo.ui.dropdown(
        options={f"{_b} {_n}": _b for _b, _n in region_names.items()},
        value=f"AT322 {region_names['AT322']}",
        label="NUTS3 region (detail)",
    )
    pmax_tech_sel = mo.ui.dropdown(
        options=["ror", "hydro", "PHS"],
        value="ror",
        label="Technology (overview grid)",
    )
    mo.hstack([pmax_basis_sel, pmax_region_sel, pmax_tech_sel], justify="start", gap=2)
    return pmax_basis_sel, pmax_region_sel, pmax_tech_sel, region_names


@app.cell
def _(cap, comp, pmax_basis_sel, profile_at, redistribute_peaks):
    _energy = (
        comp.set_index(["bus", "carrier"])[pmax_basis_sel.value]
        .unstack(fill_value=0.0)
        .reindex(index=profile_at.columns, columns=["ror", "hydro", "PHS"])
        .fillna(0.0)
    )
    # hourly inflow in MW per carrier (time x region): annual MWh x ERA5 shape
    inflow_mw = {c: profile_at.mul(_energy[c], axis="columns") for c in _energy}

    # p_max_pu as patch_inflows defines it per carrier
    _p_nom_ror = cap["ror"].reindex(profile_at.columns).fillna(0.0)
    pmax_raw = {
        "ror": inflow_mw["ror"]
        .div(_p_nom_ror.where(_p_nom_ror > 0), axis="columns")
        .fillna(0.0)
    }
    for _c in ["hydro", "PHS"]:
        _peak = inflow_mw[_c].max()
        pmax_raw[_c] = inflow_mw[_c].div(_peak.where(_peak > 0)).fillna(0.0)

    redist_error = None
    try:
        _ror_redist = redistribute_peaks(pmax_raw["ror"])
    except ValueError as _err:
        # production raises; here keep the feasible regions redistributed and
        # only clip the infeasible ones so the plots stay informative
        redist_error = str(_err)
        _feasible = pmax_raw["ror"].columns[pmax_raw["ror"].sum() < len(profile_at)]
        _ror_redist = pmax_raw["ror"].clip(0, 1)
        _ror_redist[_feasible] = redistribute_peaks(pmax_raw["ror"][_feasible])
    pmax_redist = dict(pmax_raw, ror=_ror_redist)
    return inflow_mw, pmax_raw, pmax_redist, redist_error


@app.cell(hide_code=True)
def _(mo, redist_error):
    mo.callout(
        mo.md(
            "**`_redistribute_peaks` raised** — the ror panels show the "
            f"profile clipped at 1 instead:\n\n```\n{redist_error}\n```"
        ),
        kind="danger",
    ) if redist_error else None
    return


@app.cell(hide_code=True)
def _(
    C_AFTER,
    C_BEFORE,
    C_CLIP,
    cap,
    inflow_mw,
    mdates,
    plt,
    pmax_basis_sel,
    pmax_raw,
    pmax_redist,
    pmax_region_sel,
    region_names,
):
    _bus = pmax_region_sel.value
    _fig, _axes = plt.subplots(3, 1, figsize=(9.5, 8), sharex=True)
    for _ax, _car in zip(_axes, ["ror", "hydro", "PHS"]):
        _raw, _red = pmax_raw[_car][_bus], pmax_redist[_car][_bus]
        if _car == "ror":
            _p_nom = cap["ror"].get(_bus, 0.0)
            _ax.plot(
                _raw.index,
                _raw,
                color=C_BEFORE,
                lw=0.8,
                label="before: inflow / p_nom",
            )
            _ax.plot(
                _red.index,
                _red,
                color=C_AFTER,
                lw=0.8,
                label="after _redistribute_peaks",
            )
            _ax.axhline(1, color=C_CLIP, lw=1, ls="--", label="p_max_pu = 1")
            _ax.set_title(
                f"ror — p_nom {_p_nom:,.0f} MW · "
                f"{_raw.sum():,.0f} h target, {_red.sum():,.0f} h after "
                f"redistribution, {(_raw.clip(0, 1)).sum():,.0f} h if clipped",
                loc="left",
                fontsize=10,
            )
        else:
            _ax.plot(
                _red.index,
                _red,
                color=C_AFTER,
                lw=0.8,
                label=f"{_car} inflow: inflow / max(inflow) — no redistribution",
            )
            _ax.set_title(
                f"{_car} inflow — generator p_nom = max inflow "
                f"{inflow_mw[_car][_bus].max():,.0f} MW · "
                f"turbine p_nom {cap.get(_car, {}).get(_bus, 0.0):,.0f} MW",
                loc="left",
                fontsize=10,
            )
        _ax.set_ylabel("p_max_pu")
        _ax.legend(frameon=False, fontsize=8, loc="upper right")
        _ax.spines[["top", "right"]].set_visible(False)
        _ax.grid(axis="y", alpha=0.25)
    _axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    _fig.suptitle(
        f"{_bus} {region_names[_bus]} — hourly p_max_pu "
        f"({pmax_basis_sel.selected_key})",
        x=0.01,
        ha="left",
        fontsize=11,
    )
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(
    C_AFTER,
    C_BEFORE,
    C_CLIP,
    mdates,
    np,
    plt,
    pmax_raw,
    pmax_redist,
    pmax_tech_sel,
    region_names,
):
    _car = pmax_tech_sel.value
    _raw, _red = pmax_raw[_car], pmax_redist[_car]
    _buses = [b for b in _red.columns if _red[b].sum() > 0]
    _ncol = 5
    _nrow = int(np.ceil(len(_buses) / _ncol))
    _fig, _axes = plt.subplots(
        _nrow, _ncol, figsize=(12, 1.9 * _nrow + 0.6), sharex=True, sharey=True
    )
    for _ax, _b in zip(_axes.flat, _buses):
        if _car == "ror":
            _ax.plot(_raw.index, _raw[_b], color=C_BEFORE, lw=0.5)
        _ax.plot(_red.index, _red[_b], color=C_AFTER, lw=0.5)
        _ax.axhline(1, color=C_CLIP, lw=0.7, ls="--")
        _ax.set_title(
            f"{_b} {region_names.get(_b, '')[:14]} · {_red[_b].sum():,.0f} h",
            fontsize=7.5,
            loc="left",
        )
        _ax.tick_params(labelsize=7)
        _ax.spines[["top", "right"]].set_visible(False)
    for _ax in _axes.flat[len(_buses) :]:
        _ax.set_axis_off()
    _ymax = float(np.nanmax(_raw[_buses].to_numpy())) if _car == "ror" else 1.0
    _axes.flat[0].set_ylim(0, min(max(1.2, _ymax), 3.0))
    _axes.flat[0].xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
    _axes.flat[0].xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    _legend = (
        "grey: before redistribution · blue: after _redistribute_peaks · "
        "dashed: p_max_pu = 1 (y clipped at 3)"
        if _car == "ror"
        else "blue: inflow / max(inflow) (no redistribution) · dashed: p_max_pu = 1"
    )
    _fig.suptitle(
        f"{_car}: hourly p_max_pu per NUTS3 region — {_legend}",
        x=0.01,
        ha="left",
        fontsize=10,
    )
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 5 — hourly energy per technology

    What the fleet turbines or receives with the chosen basis, summed to
    weeks: **ror** is the delivered generation `p_max_pu × p_nom` after
    redistribution (the only carrier whose profile can lose energy), **hydro
    inflow** and **PHS inflow** are the natural inflows into the reservoirs —
    their dispatch is an optimisation result. Austria and the selected region.
    """)
    return


@app.cell(hide_code=True)
def _(
    C_CARRIER,
    C_INK,
    cap,
    inflow_mw,
    mdates,
    pd,
    plt,
    pmax_basis_sel,
    pmax_redist,
    pmax_region_sel,
    region_names,
):
    _p_nom_ror = cap["ror"].reindex(pmax_redist["ror"].columns).fillna(0.0)
    _energy_mw = {
        "ror": pmax_redist["ror"].mul(_p_nom_ror, axis="columns"),
        "hydro inflow": inflow_mw["hydro"],
        "PHS inflow": inflow_mw["PHS"],
    }
    _colors = [C_CARRIER["ror"], C_CARRIER["hydro"], C_CARRIER["PHS"]]
    _bus = pmax_region_sel.value
    _fig, _axes = plt.subplots(2, 1, figsize=(9.5, 6.5), sharex=True)
    for _ax, (_label, _sel) in zip(
        _axes, [("Austria", None), (f"{_bus} {region_names[_bus]}", _bus)]
    ):
        _weekly = (
            pd.DataFrame(
                {
                    k: (v.sum(axis=1) if _sel is None else v[_sel])
                    for k, v in _energy_mw.items()
                }
            )
            .resample("W")
            .sum()
            / 1e3
        )  # GWh per week
        _ax.stackplot(
            _weekly.index,
            _weekly.T.to_numpy(),
            labels=_weekly.columns,
            colors=_colors,
            alpha=0.9,
            lw=0,
        )
        _tot = _weekly.sum() / 1e3  # TWh/a
        _ax.set_title(
            f"{_label} — " + " · ".join(f"{k} {v:.1f} TWh" for k, v in _tot.items()),
            loc="left",
            fontsize=10,
            color=C_INK,
        )
        _ax.set_ylabel("GWh / week")
        _ax.spines[["top", "right"]].set_visible(False)
        _ax.grid(axis="y", alpha=0.25)
    _axes[0].legend(frameon=False, fontsize=8, loc="upper right")
    _axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    _fig.suptitle(
        f"Weekly hydro energy per technology ({pmax_basis_sel.selected_key})",
        x=0.01,
        ha="left",
        fontsize=11,
    )
    _fig.tight_layout()
    _fig
    return


if __name__ == "__main__":
    app.run()
