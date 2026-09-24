import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Review slides: Austrian hydro capacity and inflow update

    Three figures for the review of `feat/scale-austrian-hydro-capacities`,
    written to `OUT` as PNG:

    1. **Capacity per NUTS3 by source** — powerplantmatching (ppm, before),
       KLIEN catchment capacity, the curated fleet (ppm + Anlagenregister +
       corrections) and the solved 2025 network (curated fleet + KLIEN residual
       plants).
    2. **Inflow calculation steps** for one region — ERA5 runoff profile, hourly
       inflow per carrier, `p_max_pu` before/after `_redistribute_peaks`, the
       store inflow profiles and the values the solved network uses.
    3. **Weather years against the EAG floor** — natural inflow energy of the
       2025 fleet per E-Control weather year, the 47 TWh line and the energy the
       KLIEN run-of-river corridor could add on top.

    Run from the repository root after a workflow run of the results prefix:
    `pixi run python .marimo/review-hydro-slides.py` (headless) or
    `pixi run marimo edit .marimo/review-hydro-slides.py`.
    """)
    return


@app.cell
def _():
    import sys
    import warnings
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import pypsa
    import xarray as xr

    warnings.filterwarnings("ignore")
    sys.path[:0] = [".", "scripts", "scripts/pypsa-at"]
    import build_hydro_inflow_targets as bhit

    from mods.network.hydro import _redistribute_peaks as redistribute_peaks
    from mods.utils import inflow_turbine_weights

    return (
        Path,
        bhit,
        gpd,
        inflow_turbine_weights,
        mdates,
        mo,
        np,
        pd,
        plt,
        pypsa,
        redistribute_peaks,
        xr,
    )


@app.cell
def _(Path):
    PREFIX, SCENARIO = "hydro-capacities-update-complete", "AT_KN2040"
    RESOURCES = Path(f"resources/{PREFIX}/{SCENARIO}")
    RESULTS = Path(f"results/{PREFIX}/{SCENARIO}")
    NETWORK = RESULTS / "networks/base_s_adm__none_2025.nc"
    OUT = RESULTS / "graphics/review-slides"
    OUT.mkdir(parents=True, exist_ok=True)

    NUTS3_SHAPES = Path("resources/nuts3_shapes.geojson")
    REGIONS_ONSHORE = Path("resources/regions_onshore_base_s_adm.geojson")
    KLIEN_GEOJSON = Path(
        "data/klien_potentials/archive/2026-v3/catchments_hydro.geojson"
    )
    ECONTROL_XLSX = Path(
        "data/econtrol-betriebsstatistik/primary/2025/BStGes-JR1_Bilanz.xlsx"
    )
    ECONTROL_CAPACITY_XLSX = Path(
        "data/econtrol-bestandsstatistik/primary/2025/BeStGes-JR_KWEPL.xlsx"
    )
    GRENZKRAFTWERKE = Path("data/pypsa-at/grenzkraftwerke_AT.csv")
    DIVERSION_OVERRIDES = Path("data/pypsa-at/hydro_diversion_overrides_AT.csv")
    CATCHMENT_CORRECTIONS = Path("data/pypsa-at/hydro_catchment_corrections_AT.csv")

    TECH_TO_CARRIER = {
        "Run-Of-River": "ror",
        "Reservoir": "hydro",
        "Pumped Storage": "PHS",
    }
    CARRIERS = ["ror", "hydro", "PHS"]
    CARRIER_LABEL = {
        "ror": "run-of-river",
        "hydro": "reservoir",
        "PHS": "pumped storage",
    }
    EAG_TARGET_TWH = 47.0
    # regions for the inflow steps: all three carriers / Danube run-of-river
    REGIONS = ["AT322", "AT121"]

    # dataviz palette (validated with validate_palette.js, light mode)
    C_SOURCE = {  # categorical slots 1-4 in fixed order
        "ppm": "#2a78d6",
        "klien": "#eb6834",
        "curated": "#1baf7a",
        "network": "#eda100",
    }
    C_CARRIER = {"ror": "#2a78d6", "hydro": "#eb6834", "PHS": "#1baf7a"}
    C_HEADROOM = {"2030": "#86b6ef", "2040": "#5598e7"}  # ordinal blue ramp
    INK, MUTED, GRID, BASELINE = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"
    C_TARGET = "#d03b3b"
    DPI = 200

    def style_axis(ax, axis="x"):
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_color(BASELINE)
        ax.spines["bottom"].set_color(BASELINE)
        ax.tick_params(colors=MUTED, labelsize=8)
        ax.grid(axis=axis, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)

    return (
        ECONTROL_CAPACITY_XLSX,
        BASELINE,
        CARRIERS,
        CARRIER_LABEL,
        CATCHMENT_CORRECTIONS,
        C_CARRIER,
        C_HEADROOM,
        C_SOURCE,
        C_TARGET,
        DIVERSION_OVERRIDES,
        DPI,
        EAG_TARGET_TWH,
        ECONTROL_XLSX,
        GRENZKRAFTWERKE,
        INK,
        KLIEN_GEOJSON,
        MUTED,
        NETWORK,
        NUTS3_SHAPES,
        OUT,
        REGIONS,
        REGIONS_ONSHORE,
        RESOURCES,
        TECH_TO_CARRIER,
        style_axis,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Capacity per NUTS3 by source

    - **ppm** — raw powerplantmatching table (`powerplants_s_adm-raw.csv`), all
      Austrian hydro rows including the ones without a `Technology` label that
      the model used to drop silently.
    - **KLIEN** — the study's current capacity per river-section catchment
      (`C_current`), allocated to regions through the plants located in each
      catchment (same membership logic as the inflow targets); the study
      counts pumped storage only in a few catchments.
    - **ppm + Anlagenregister** — the calibrated fleet
      (`powerplants_s_adm.csv`) without the KLIEN residual plants: duplicates
      dropped, technologies reclassified, Grenzkraftwerke treaty halves,
      curated missing plants and the register's Kleinwasserkraft fleet scaled to
      the E-Control Bestandsstatistik.
    - **network 2025** — turbine capacity in the solved base-year network,
      expected to equal the calibrated fleet plus the residual plants.
    """)
    return


@app.cell
def _(NUTS3_SHAPES, RESOURCES, TECH_TO_CARRIER, gpd, pd):
    nuts3 = gpd.read_file(NUTS3_SHAPES).query("country == 'AT'")
    region_names = nuts3.set_index("index")["name"].sort_index()
    AT_BUSES = region_names.index

    def _at_hydro(path):
        df = pd.read_csv(path, index_col=0, low_memory=False)
        df = df.query("Country == 'AT' and Fueltype == 'Hydro'").copy()
        df["carrier"] = df["Technology"].map(TECH_TO_CARRIER).fillna("unclassified")
        return df

    ppl_raw = _at_hydro(RESOURCES / "powerplants_s_adm-raw.csv")
    ppl_final = _at_hydro(RESOURCES / "powerplants_s_adm.csv")
    is_residual = ppl_final["Name"].str.startswith("KLIEN residual ")
    ppl_curated = ppl_final[~is_residual]
    ppl_residual = ppl_final[is_residual]

    def _by_bus(df):
        return (
            df.groupby(["bus", "carrier"])["Capacity"]
            .sum()
            .unstack(fill_value=0.0)
            .reindex(AT_BUSES, fill_value=0.0)
        )

    cap_ppm = _by_bus(ppl_raw)
    cap_curated = _by_bus(ppl_curated)
    cap_residual = _by_bus(ppl_residual)
    return (
        AT_BUSES,
        cap_curated,
        cap_ppm,
        cap_residual,
        ppl_final,
        ppl_raw,
        region_names,
    )


@app.cell
def _(
    AT_BUSES,
    CATCHMENT_CORRECTIONS,
    DIVERSION_OVERRIDES,
    GRENZKRAFTWERKE,
    KLIEN_GEOJSON,
    REGIONS_ONSHORE,
    RESOURCES,
    bhit,
    gpd,
    pd,
):
    # KLIEN C_current per catchment -> regions, through the plants located in
    # each catchment (the production membership logic of the inflow targets)
    _ppl = pd.read_csv(
        RESOURCES / "powerplants_s_adm.csv",
        index_col=0,
        dtype={"plz": str},
        low_memory=False,
    )
    _plants = bhit.select_hydro_plants(_ppl, pd.read_csv(GRENZKRAFTWERKE))
    _sections = gpd.read_file(KLIEN_GEOJSON)
    _sections.columns = _sections.columns.str.strip()
    _sections = (
        _sections[_sections["E_current"].notna()].set_index("id").to_crs(bhit.KLIEN_CRS)
    )
    _sections = bhit.apply_catchment_corrections(
        _sections, pd.read_csv(CATCHMENT_CORRECTIONS)
    )
    _regions = gpd.read_file(REGIONS_ONSHORE).set_index("name").to_crs(bhit.KLIEN_CRS)
    _membership = bhit.assign_plants_to_sections(
        _plants, _sections, _regions, overrides=pd.read_csv(DIVERSION_OVERRIDES)
    )
    _plant_cap, klien_unallocated_mw = bhit.allocate_section_energy(
        _sections,
        _membership,
        _plants,
        energy_col="C_current",
        capacity_col="C_current",
    )
    _targets = bhit.aggregate_by_region(_plant_cap, _plants)
    cap_klien = (
        _targets[_targets["bus"].isin(AT_BUSES)]
        .pivot(index="bus", columns="carrier", values="energy")
        .reindex(AT_BUSES, fill_value=0.0)
        .fillna(0.0)
    )
    klien_total_mw = _sections["C_current"].sum()
    return cap_klien, klien_total_mw, klien_unallocated_mw


@app.cell
def _(AT_BUSES, NETWORK, inflow_turbine_weights, pd, pypsa):
    n = pypsa.Network(NETWORK)
    _loc = n.buses["location"]
    _gen = n.generators[n.generators.carrier == "ror"]
    _ror = _gen.groupby(_gen["bus"].map(_loc))["p_nom_opt"].sum()
    _links = n.links[n.links.carrier.isin(["hydro discharger", "PHS discharger"])]
    # the PHS discharger is sized on the store side (p_nom / sqrt(eta)); its
    # electrical capacity is p_nom x efficiency. The reservoir discharger is
    # sized at the turbine capacity directly.
    _elec = _links["p_nom_opt"].where(
        _links["carrier"] == "hydro discharger",
        _links["p_nom_opt"] * _links["efficiency"],
    )
    _store = (
        _elec.groupby(
            [_links["bus1"].map(_loc), _links["carrier"].str.replace(" discharger", "")]
        )
        .sum()
        .unstack(fill_value=0.0)
    )
    cap_network = (
        pd.concat([_ror.rename("ror"), _store], axis=1)
        .reindex(AT_BUSES, fill_value=0.0)
        .fillna(0.0)
    )

    # natural inflow energy the EAG floor counts (inflow generators weighted
    # by the efficiency of their store's turbine link)
    _infl = n.generators[
        n.generators.carrier.isin(["ror", "hydro inflow", "PHS inflow"])
        & n.generators["bus"].map(_loc).isin(AT_BUSES)
    ].index
    _w = inflow_turbine_weights(n, _infl)
    _e = (n.generators_t.p_max_pu[_infl] * n.generators.loc[_infl, "p_nom_opt"]).mul(
        n.snapshot_weightings.generators, axis=0
    ).sum() * _w
    network_inflow_twh = (
        _e.groupby(n.generators.loc[_infl, "carrier"].str.replace(" inflow", "")).sum()
        / 1e6
    )
    return cap_network, n, network_inflow_twh


@app.cell(hide_code=True)
def _(
    cap_curated,
    cap_klien,
    cap_network,
    cap_ppm,
    cap_residual,
    klien_total_mw,
    klien_unallocated_mw,
    mo,
    network_inflow_twh,
    pd,
):
    totals = pd.DataFrame(
        {
            "ppm": cap_ppm.sum(),
            "KLIEN": cap_klien.sum(),
            "ppm + Anlagenregister": cap_curated.sum(),
            "residual": cap_residual.sum(),
            "network 2025": cap_network.sum(),
        }
    ).fillna(0.0)
    totals.loc["total"] = totals.sum()
    mo.vstack(
        [
            mo.md(
                f"**AT totals per source [MW]** — KLIEN catchments carry "
                f"{klien_total_mw:,.0f} MW, of which "
                f"{klien_unallocated_mw.sum():,.0f} MW find no plant. Natural "
                f"inflow the 2025 network delivers: "
                f"{network_inflow_twh.sum():.1f} TWh "
                f"({network_inflow_twh.round(1).to_dict()})."
            ),
            totals.round(0),
        ]
    )
    return (totals,)


@app.cell(hide_code=True)
def _(
    BASELINE,
    C_SOURCE,
    DPI,
    INK,
    MUTED,
    OUT,
    cap_curated,
    cap_klien,
    cap_network,
    cap_ppm,
    plt,
    region_names,
    style_axis,
):
    _series = [
        ("ppm", "ppm (before)", cap_ppm.sum(axis=1)),
        ("klien", "KLIEN catchments", cap_klien.sum(axis=1)),
        ("curated", "ppm + Anlagenregister", cap_curated.sum(axis=1)),
        ("network", "network 2025 (+ KLIEN residual plants)", cap_network.sum(axis=1)),
    ]
    _order = cap_network.sum(axis=1).sort_values().index
    _y = range(len(_order))
    _h = 0.2
    _fig, _ax = plt.subplots(figsize=(9, 11.5))
    for _i, (_key, _label, _values) in enumerate(_series):
        _offset = (1.5 - _i) * _h
        _ax.barh(
            [j + _offset for j in _y],
            _values.reindex(_order),
            height=_h * 0.92,
            color=C_SOURCE[_key],
            label=_label,
        )
    _ax.set_yticks(list(_y))
    _ax.set_yticklabels(
        [f"{b}  {region_names[b]}" for b in _order], fontsize=8, color=INK
    )
    _ax.set_ylim(-0.6, len(_order) - 0.4)
    style_axis(_ax, "x")
    _ax.spines["left"].set_visible(False)
    _ax.spines["bottom"].set_color(BASELINE)
    _ax.set_xlabel("installed hydro capacity [MW]", color=MUTED)
    _ax.set_title(
        "Austrian hydro capacity per NUTS3 region by data source",
        loc="left",
        color=INK,
        fontsize=12,
    )
    _tot = {k: v.sum() / 1e3 for k, _, v in _series}
    _ax.text(
        0.99,
        0.02,
        "AT totals: "
        + "  ·  ".join(f"{l.split(' (')[0]} {_tot[k]:.1f} GW" for k, l, _ in _series),
        transform=_ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        color=MUTED,
    )
    _ax.legend(frameon=False, loc="lower right", bbox_to_anchor=(1, 0.06), fontsize=9)
    _fig.tight_layout()
    _fig.savefig(OUT / "01_capacity_per_nuts3_by_source.png", dpi=DPI)
    _fig
    return


@app.cell(hide_code=True)
def _(
    BASELINE,
    CARRIERS,
    CARRIER_LABEL,
    C_SOURCE,
    DPI,
    INK,
    MUTED,
    OUT,
    cap_curated,
    cap_klien,
    cap_network,
    cap_ppm,
    plt,
    region_names,
    style_axis,
):
    # variant: one panel per technology (ppm rows without a technology label
    # are not shown here; KLIEN's carrier split follows the plants it lands on)
    _sources = [
        ("ppm", "ppm (before)", cap_ppm),
        ("klien", "KLIEN catchments", cap_klien),
        ("curated", "ppm + Anlagenregister", cap_curated),
        ("network", "network 2025", cap_network),
    ]
    _order = cap_network.sum(axis=1).sort_values().index
    _y = range(len(_order))
    _h = 0.2
    _fig, _axes = plt.subplots(1, 3, figsize=(14, 11.5), sharey=True)
    for _ax, _car in zip(_axes, CARRIERS):
        for _i, (_key, _label, _df) in enumerate(_sources):
            _vals = _df.get(_car, 0.0)
            _vals = (
                _vals.reindex(_order)
                if hasattr(_vals, "reindex")
                else [0] * len(_order)
            )
            _ax.barh(
                [j + (1.5 - _i) * _h for j in _y],
                _vals,
                height=_h * 0.92,
                color=C_SOURCE[_key],
                label=_label,
            )
        style_axis(_ax, "x")
        _ax.spines["left"].set_visible(False)
        _ax.spines["bottom"].set_color(BASELINE)
        _ax.set_title(CARRIER_LABEL[_car], loc="left", color=INK, fontsize=11)
        _ax.set_xlabel("MW", color=MUTED)
    _axes[0].set_yticks(list(_y))
    _axes[0].set_yticklabels(
        [f"{b}  {region_names[b]}" for b in _order], fontsize=8, color=INK
    )
    _axes[0].set_ylim(-0.6, len(_order) - 0.4)
    _axes[0].legend(frameon=False, loc="lower right", fontsize=9)
    _fig.suptitle(
        "Austrian hydro capacity per NUTS3 region and technology by data source",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=12,
    )
    _fig.tight_layout()
    _fig.savefig(OUT / "01b_capacity_per_nuts3_by_source_and_technology.png", dpi=DPI)
    _fig
    return


@app.cell(hide_code=True)
def _(REGIONS, mo, region_names):
    mo.md(f"""
    ## 2. Inflow calculation steps — {", ".join(f"{r} {region_names[r]}" for r in REGIONS)}

    1. `build_inflow_profile`: ERA5 runoff of the cutout (atlite, smoothed,
       lower-quantile threshold) normalised to sum to one over the weather year.
    2. `build_hydro_inflow_targets_at` + `build_inflows_per_region`: the profile
       is multiplied with the region's annual energy per carrier (KLIEN
       Regelarbeitsvermögen × E-Control year factor; pumped storage from
       E-Control's natural inflow).
    3. `patch_inflows` (run-of-river): `p_max_pu = inflow / p_nom`; hours above
       one are capped and their energy redistributed by `_redistribute_peaks`.
    4. `patch_inflows` (stores): the inflow is grossed up by the turbine
       efficiency, the inflow generator's `p_nom` is the peak and
       `p_max_pu = inflow / peak`.
    5. The solved network aggregates the hourly series to its snapshots
       (365 h in this run).

    The first region carries all three carriers; the second is a Danube region
    where the peak redistribution visibly reshapes the run-of-river profile.
    """)
    return


@app.cell
def _(RESOURCES, n, pd, redistribute_peaks, xr):
    _profile_all = xr.open_dataarray(RESOURCES / "profile_inflow_adm.nc")
    _inflow_all = xr.open_dataarray(RESOURCES / "inflow_per_region_adm.nc")
    _targets_all = pd.read_csv(RESOURCES / "hydro_inflow_targets_adm.csv")

    def inflow_steps(region: str) -> dict:
        """Recompute the inflow pipeline of one region step by step."""
        profile = _profile_all.sel(countries=region).to_pandas()
        inflow = _inflow_all.sel(countries=region).to_pandas()  # time x carrier [MW]
        if "ror" not in inflow.columns:
            inflow = inflow.T
        inflow = inflow.reindex(columns=["ror", "hydro", "PHS"], fill_value=0.0)
        targets = _targets_all.query("bus == @region").set_index("carrier")

        loc = n.buses["location"]
        gen_ror = n.generators[
            (n.generators.carrier == "ror") & (n.generators["bus"].map(loc) == region)
        ].index
        p_nom_ror = n.generators.loc[gen_ror, "p_nom"].sum()
        gen_store = {
            c: n.generators[
                (n.generators.carrier == f"{c} inflow")
                & (n.generators["bus"].map(loc) == region)
            ].index
            for c in ["hydro", "PHS"]
        }
        links = n.links[n.links["bus1"] == region]
        efficiency = {
            c: links[links.carrier == f"{c} discharger"]["efficiency"].mean()
            for c in ["hydro", "PHS"]
        }

        # step 3: run-of-river p_max_pu before / after the peak redistribution
        pu_ror_raw = inflow["ror"] / p_nom_ror
        pu_ror = redistribute_peaks(pu_ror_raw.to_frame("ror"))["ror"]

        # step 4: store inflow generators (grossed up, normalised to the peak)
        grossed = {c: inflow[c] / efficiency[c] for c in ["hydro", "PHS"]}
        pu_store = {
            c: grossed[c] / grossed[c].max() if grossed[c].max() > 0 else grossed[c]
            for c in ["hydro", "PHS"]
        }

        # step 5: what the solved network holds (snapshot resolution, MW)
        w = n.snapshot_weightings.generators
        model_mw = pd.DataFrame(
            {
                "ror": (
                    n.generators_t.p_max_pu[gen_ror]
                    * n.generators.loc[gen_ror, "p_nom_opt"]
                ).sum(axis=1),
                **{
                    c: (
                        n.generators_t.p_max_pu[gen_store[c]]
                        * n.generators.loc[gen_store[c], "p_nom_opt"]
                    ).sum(axis=1)
                    for c in ["hydro", "PHS"]
                },
            }
        )
        model_twh = model_mw.mul(w, axis=0).sum() / 1e6  # gross, before turbine
        delivered_twh = model_twh * pd.Series({"ror": 1.0, **efficiency})
        return {
            "region": region,
            "profile": profile,
            "inflow": inflow,
            "targets": targets,
            "p_nom_ror": p_nom_ror,
            "efficiency": efficiency,
            "pu_ror_raw": pu_ror_raw,
            "pu_ror": pu_ror,
            "grossed": grossed,
            "pu_store": pu_store,
            "model_mw": model_mw,
            "model_twh": model_twh,
            "delivered_twh": delivered_twh,
        }

    return (inflow_steps,)


@app.cell
def _(
    CARRIER_LABEL,
    C_CARRIER,
    C_TARGET,
    DPI,
    INK,
    MUTED,
    OUT,
    mdates,
    np,
    plt,
    region_names,
    style_axis,
):
    def plot_inflow_steps(s: dict):
        """Five-panel figure of the inflow pipeline for one region."""
        region = s["region"]
        profile, inflow, targets = s["profile"], s["inflow"], s["targets"]
        pu_ror_raw, pu_ror = s["pu_ror_raw"], s["pu_ror"]
        model_mw = s["model_mw"]
        fig, axes = plt.subplots(5, 1, figsize=(11, 13), sharex=True)
        lw = 0.7

        # 1 — ERA5 profile relative to its annual mean
        ax = axes[0]
        share = profile * 1e3  # per mille of the annual energy per hour
        ax.fill_between(share.index, 0, share, color=C_CARRIER["ror"], alpha=0.25, lw=0)
        ax.plot(share.index, share, color=C_CARRIER["ror"], lw=lw)
        ax.set_ylabel("‰ of annual energy per hour")
        ax.set_title(
            "1 · ERA5 runoff profile of the region (atlite, weather year 2013): "
            f"shares that sum to 1 over the year (Σ = {profile.sum():.3f})",
            loc="left",
            fontsize=10,
            color=INK,
        )

        # 2 — hourly inflow per carrier
        ax = axes[1]
        for c in ["ror", "hydro", "PHS"]:
            e = targets.loc[c, "inflow"] / 1e6 if c in targets.index else 0.0
            if e == 0:
                continue
            ax.plot(
                inflow.index,
                inflow[c],
                color=C_CARRIER[c],
                lw=lw,
                label=f"{CARRIER_LABEL[c]} · {e:.2f} TWh/a",
            )
        yf = targets["year_factor"].get("ror", float("nan"))
        ax.set_ylabel("MW")
        ax.set_title(
            "2 · hourly inflow = profile × annual energy "
            f"(KLIEN RAV × E-Control year factor, ror {yf:.2f}; PHS from E-Control natural inflow)",
            loc="left",
            fontsize=10,
            color=INK,
        )
        ax.legend(frameon=False, fontsize=8, loc="upper right")

        # 3 — run-of-river p_max_pu before/after redistribution
        ax = axes[2]
        ax.fill_between(
            pu_ror_raw.index,
            1,
            pu_ror_raw.clip(lower=1),
            color=C_TARGET,
            alpha=0.25,
            lw=0,
            label="capped above p_nom",
        )
        ax.fill_between(
            pu_ror.index,
            pu_ror_raw.clip(upper=1),
            pu_ror,
            where=pu_ror > pu_ror_raw,
            color=C_CARRIER["ror"],
            alpha=0.25,
            lw=0,
            label="redistributed into free hours",
        )
        ax.plot(
            pu_ror_raw.index, pu_ror_raw, color=MUTED, lw=lw, label="inflow / p_nom"
        )
        ax.plot(
            pu_ror.index,
            pu_ror,
            color=C_CARRIER["ror"],
            lw=lw,
            label="after _redistribute_peaks (energy conserved)",
        )
        ax.axhline(1, color=C_TARGET, lw=0.9, ls="--")
        ax.set_ylabel("p_max_pu")
        ax.set_title(
            f"3 · run-of-river availability, p_nom {s['p_nom_ror']:,.0f} MW · "
            f"{pu_ror_raw.sum():,.0f} h target = {pu_ror.sum():,.0f} h after redistribution "
            f"({pu_ror_raw.clip(upper=1).sum():,.0f} h if simply clipped)",
            loc="left",
            fontsize=10,
            color=INK,
        )
        ax.legend(frameon=False, fontsize=8, loc="upper right")

        # 4 — store inflow generators
        ax = axes[3]
        stores = [c for c in ["hydro", "PHS"] if inflow[c].sum() > 0]
        if not stores:
            ax.text(
                0.5,
                0.5,
                "no reservoir or pumped-storage plant in this region",
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=10,
                color=MUTED,
            )
        for c in stores:
            ax.plot(
                s["pu_store"][c].index,
                s["pu_store"][c],
                color=C_CARRIER[c],
                lw=lw,
                label=(
                    f"{CARRIER_LABEL[c]} inflow · grossed up by turbine efficiency "
                    f"{s['efficiency'][c]:.2f} · generator p_nom = peak "
                    f"{s['grossed'][c].max():,.0f} MW"
                ),
            )
        ax.axhline(1, color=MUTED, lw=0.8, ls=":")
        ax.set_ylabel("p_max_pu")
        ax.set_ylim(0, 1.25)
        if not stores:
            ax.axhline(1, color="white", lw=1.2)
        ax.set_title(
            "4 · store inflow generators: inflow / peak (no redistribution, the store "
            "absorbs the peaks; both carriers share the ERA5 shape)",
            loc="left",
            fontsize=10,
            color=INK,
        )
        if stores:
            ax.legend(frameon=False, fontsize=8, loc="upper left")

        # 5 — the solved network
        ax = axes[4]
        step_h = (model_mw.index[1] - model_mw.index[0]).total_seconds() / 3600
        idx = model_mw.index.append(
            model_mw.index[-1:] + (model_mw.index[1] - model_mw.index[0])
        )
        for c in ["ror", "hydro", "PHS"]:
            if model_mw[c].sum() <= 0:
                continue
            vals = np.append(model_mw[c].to_numpy(), model_mw[c].iloc[-1])
            gross, delivered = s["model_twh"][c], s["delivered_twh"][c]
            label = f"{CARRIER_LABEL[c]} · {delivered:.2f} TWh/a"
            if c != "ror":
                label += f" delivered ({gross:.2f} gross)"
            ax.step(idx, vals, where="post", color=C_CARRIER[c], lw=1.6, label=label)
        ax.set_ylabel("MW")
        ax.set_title(
            f"5 · available inflow power in the solved network ({len(model_mw)} snapshots "
            f"of {step_h:.0f} h; p_max_pu × p_nom)",
            loc="left",
            fontsize=10,
            color=INK,
        )
        ax.legend(frameon=False, fontsize=8, loc="upper right")

        for ax in axes:
            style_axis(ax, "y")
            ax.set_xlim(profile.index[0], profile.index[-1])
        axes[-1].xaxis.set_major_locator(mdates.MonthLocator())
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        fig.suptitle(
            f"From ERA5 runoff to the model inflow — {region} {region_names[region]}, "
            "weather year 2013",
            x=0.01,
            ha="left",
            fontsize=12,
            color=INK,
        )
        fig.tight_layout()
        fig.savefig(OUT / f"02_inflow_steps_{region}.png", dpi=DPI)
        return fig

    return (plot_inflow_steps,)


@app.cell(hide_code=True)
def _(REGIONS, inflow_steps, plot_inflow_steps, plt):
    _figs = [plot_inflow_steps(inflow_steps(_r)) for _r in REGIONS]
    for _f in _figs[1:]:
        plt.close(_f)
    _figs[0]
    return


@app.cell(hide_code=True)
def _(REGIONS, inflow_steps, plot_inflow_steps):
    plot_inflow_steps(inflow_steps(REGIONS[1])) if len(REGIONS) > 1 else None
    return


@app.cell(hide_code=True)
def _(EAG_TARGET_TWH, mo):
    mo.md(f"""
    ## 3. Weather years against the EAG floor of {EAG_TARGET_TWH:.0f} TWh

    The inflow targets scale with the weather year (E-Control Laufkraft,
    Speicherkraft and natural pumped-storage generation relative to the
    1991–2020 mean), the fleet does not. Per E-Control year the bars show the
    natural inflow energy of the calibrated 2025 fleet as the floor counts it:
    run-of-river bounded by `p_nom × 8760 h` per region (the redistribution's
    feasibility limit), reservoir and pumped-storage inflow unbounded (the
    store absorbs peaks). Stacked on top: the energy the KLIEN corridor's
    run-of-river additions could produce at the fleet's full-load hours of that
    year.
    """)
    return


@app.cell
def _(
    AT_BUSES, ECONTROL_CAPACITY_XLSX, ECONTROL_XLSX, RESOURCES, bhit, cap_network, pd
):
    econtrol = bhit.read_econtrol_annual_generation(ECONTROL_XLSX)
    econtrol_capacity = bhit.read_econtrol_capacity(ECONTROL_CAPACITY_XLSX)
    weather_years = [int(y) for y in econtrol.dropna().index if y >= 2000]

    _t = pd.read_csv(RESOURCES / "hydro_inflow_targets_adm.csv")
    rav_gwh = (
        _t[_t["bus"].isin(AT_BUSES)]
        .pivot(index="bus", columns="carrier", values="rav_gwh")
        .reindex(AT_BUSES, fill_value=0.0)
        .fillna(0.0)
    )
    _bound_ror_gwh = cap_network["ror"] * 8760 / 1e3

    _rows = {}
    for _y in weather_years:
        _f = bhit.weather_year_factors(econtrol, _y, econtrol_capacity)
        _ror = (rav_gwh["ror"] * _f["ror"]).clip(upper=_bound_ror_gwh).sum()
        _rows[_y] = {
            "ror": _ror / 1e3,
            "hydro": rav_gwh["hydro"].sum() * _f["hydro"] / 1e3,
            "PHS": rav_gwh["PHS"].sum() * _f["PHS"] / 1e3,
            "f_ror": _f["ror"],
        }
    energy_by_year = pd.DataFrame(_rows).T  # TWh
    energy_by_year["flh_ror"] = energy_by_year["ror"] * 1e6 / cap_network["ror"].sum()

    # regional corridor: one row per year and region; headroom = value - existing fleet
    corridor = pd.read_csv(RESOURCES / "klien_ror_trajectory_adm.csv")
    headroom_mw = (
        (corridor["value"] - corridor["existing_ror_mw"])
        .groupby(corridor["year"])
        .sum()
    ).round(0)
    energy_by_year["headroom_2030"] = (
        headroom_mw[2030] * energy_by_year["flh_ror"] / 1e6
    )
    energy_by_year["headroom_2040"] = (
        (headroom_mw[2040] - headroom_mw[2030]) * energy_by_year["flh_ror"] / 1e6
    )
    energy_by_year["fleet"] = energy_by_year[["ror", "hydro", "PHS"]].sum(axis=1)
    return econtrol, econtrol_capacity, energy_by_year, headroom_mw


@app.cell(hide_code=True)
def _(EAG_TARGET_TWH, energy_by_year, headroom_mw, mo, network_inflow_twh):
    _e = energy_by_year
    _reach = _e.index[_e["fleet"] >= EAG_TARGET_TWH].tolist()
    _with_2030 = _e.index[
        (_e["fleet"] < EAG_TARGET_TWH)
        & (_e["fleet"] + _e["headroom_2030"] >= EAG_TARGET_TWH)
    ].tolist()
    _with_2040 = _e.index[
        (_e["fleet"] + _e["headroom_2030"] < EAG_TARGET_TWH)
        & (_e["fleet"] + _e["headroom_2030"] + _e["headroom_2040"] >= EAG_TARGET_TWH)
    ].tolist()
    mo.vstack(
        [
            mo.md(
                f"- 2013 check: analytic {_e.loc[2013, 'fleet']:.2f} TWh vs. "
                f"network {network_inflow_twh.sum():.2f} TWh\n"
                f"- KLIEN corridor headroom: +{headroom_mw[2030]:.0f} MW by 2030, "
                f"+{headroom_mw[2040]:.0f} MW by 2040\n"
                f"- fleet alone reaches {EAG_TARGET_TWH:.0f} TWh in {_reach}\n"
                f"- with the 2030 corridor also in {_with_2030}\n"
                f"- with the 2040 corridor also in {_with_2040}"
            ),
            _e.round(2),
        ]
    )
    return


@app.cell(hide_code=True)
def _(
    CARRIER_LABEL,
    C_CARRIER,
    C_HEADROOM,
    C_TARGET,
    DPI,
    EAG_TARGET_TWH,
    INK,
    MUTED,
    OUT,
    energy_by_year,
    headroom_mw,
    plt,
    style_axis,
):
    _e = energy_by_year
    _x = list(range(len(_e)))
    _fig, _ax = plt.subplots(figsize=(13, 6.2))
    _bottom = 0 * _e["ror"]
    for _c in ["ror", "hydro", "PHS"]:
        _ax.bar(
            _x,
            _e[_c],
            bottom=_bottom,
            width=0.78,
            color=C_CARRIER[_c],
            edgecolor="white",
            linewidth=0.6,
            label=f"{CARRIER_LABEL[_c]} · 2025 fleet",
        )
        _bottom = _bottom + _e[_c]
    for _yr, _key in [("2030", "headroom_2030"), ("2040", "headroom_2040")]:
        _mw = headroom_mw[int(_yr)] - (headroom_mw[2030] if _yr == "2040" else 0)
        _ax.bar(
            _x,
            _e[_key],
            bottom=_bottom,
            width=0.78,
            facecolor=C_HEADROOM[_yr],
            edgecolor="white",
            linewidth=0.6,
            hatch="///" if _yr == "2030" else "...",
            label=f"KLIEN ror corridor {'by' if _yr == '2030' else 'to'} {_yr}: +{_mw:,.0f} MW"
            + (" more" if _yr == "2040" else ""),
        )
        _bottom = _bottom + _e[_key]
    _ax.axhline(
        EAG_TARGET_TWH,
        color=C_TARGET,
        lw=1.4,
        ls="--",
        zorder=5,
        label=f"EAG hydro floor 2030: {EAG_TARGET_TWH:.0f} TWh/a",
    )
    for _i, (_y, _row) in enumerate(_e.iterrows()):
        _ax.text(
            _i,
            _row["fleet"] + 0.25,
            f"{_row['fleet']:.1f}",
            ha="center",
            va="bottom",
            fontsize=7,
            color=INK if _row["fleet"] >= EAG_TARGET_TWH else MUTED,
            bbox={
                "boxstyle": "round,pad=0.15",
                "fc": "white",
                "ec": "none",
                "alpha": 0.85,
            },
            zorder=6,
        )
    _i13 = list(_e.index).index(2013)
    _top13 = _e.loc[2013, ["fleet", "headroom_2030", "headroom_2040"]].sum()
    _ax.annotate(
        "model weather year",
        xy=(_i13, _top13 + 0.3),
        xytext=(_i13, _top13 + 4.0),
        ha="center",
        va="bottom",
        fontsize=8,
        color=INK,
        arrowprops={"arrowstyle": "-|>", "color": INK, "lw": 0.8},
    )
    _ax.set_xticks(_x)
    _ax.set_xticklabels([str(y) for y in _e.index], rotation=0, fontsize=8)
    _ax.set_xlim(-0.6, len(_x) - 0.4)
    _ax.set_ylim(0, 64)
    _ax.set_ylabel("natural inflow energy, delivered [TWh/a]", color=MUTED)
    _ax.set_xlabel(
        "weather year (E-Control full-load hours relative to the 1991–2020 mean "
        "scale the KLIEN inflow targets)",
        color=MUTED,
    )
    style_axis(_ax, "y")
    _ax.spines["left"].set_visible(False)
    _ax.set_title(
        "Which weather years let the calibrated Austrian hydro fleet reach the EAG floor?",
        loc="left",
        color=INK,
        fontsize=12,
    )
    _ax.legend(
        frameon=False,
        fontsize=8,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=3,
    )
    _fig.tight_layout()
    _fig.savefig(
        OUT / "03_weather_years_vs_eag_target.png", dpi=DPI, bbox_inches="tight"
    )
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. The profile says *when* the water comes, not *how much*

    A common misreading of the inflow profiles: a high peak in June looks like
    "a lot of water", a flat winter like "little water". The profile carries no
    amount at all. `build_inflow_profile` normalises the ERA5 runoff of the
    cutout so that every region's profile **sums to one over the weather
    year** (`normalize_using_yearly`); it is a distribution of shares over the
    8,760 hours. Two consequences:

    - **The cutout weather year sets only the shape.** The run uses the 2013
      cutout, so the model knows when the 2013 snowmelt and floods happened.
      Another cutout year would move the peaks, but the annual energy would not
      change by a single MWh.
    - **The amount comes from a separate source.** The annual energy per region
      and carrier is the KLIEN Regelarbeitsvermögen times the E-Control year
      factor (`hydro_inflow_targets_adm.csv`). Selecting a dry or wet year
      factor scales the whole curve; the shape stays that of the cutout year.

    The only place where the shape touches the amount is run-of-river capping:
    a peak above `p_nom` cannot be turbined in that hour, so
    `_redistribute_peaks` moves that energy into other hours (energy
    conserved), and a region whose energy exceeds `p_nom × 8760 h` is rejected
    rather than spilled.
    """)
    return


@app.cell(hide_code=True)
def _(
    CARRIER_LABEL,
    C_HEADROOM,
    C_CARRIER,
    DPI,
    INK,
    MUTED,
    OUT,
    REGIONS,
    bhit,
    econtrol,
    econtrol_capacity,
    inflow_steps,
    mdates,
    plt,
    region_names,
    style_axis,
):
    _region = REGIONS[0]
    _s = inflow_steps(_region)
    _profile = _s["profile"]
    _rav_ror_mwh = _s["targets"].loc["ror", "rav_gwh"] * 1e3
    _years = {"dry 2003": 2003, "model year 2013": 2013, "wet 2024": 2024}
    _colors = {
        "dry 2003": C_HEADROOM["2030"],
        "model year 2013": C_CARRIER["ror"],
        "wet 2024": INK,
    }

    _fig, _axes = plt.subplots(1, 3, figsize=(15, 4.2))

    # a — the shape: shares of the annual energy per hour
    _ax = _axes[0]
    _share = _profile * 1e3  # per mille of the annual energy per hour
    _ax.fill_between(_share.index, 0, _share, color=C_CARRIER["ror"], alpha=0.25, lw=0)
    _ax.plot(_share.index, _share, color=C_CARRIER["ror"], lw=0.8)
    _ax.set_ylabel("‰ of the annual energy per hour")
    _ax.set_title(
        "a · the profile: shares that sum to 1 over the year\n(ERA5 cutout 2013, no amount attached)",
        loc="left",
        fontsize=10,
        color=INK,
    )
    _ax.text(
        0.02,
        0.95,
        f"Σ over 8,760 h = {_profile.sum():.3f}",
        transform=_ax.transAxes,
        va="top",
        fontsize=9,
        color=MUTED,
    )

    # b — the amount: same shape, scaled by the year's energy
    _ax = _axes[1]
    for _label, _year in _years.items():
        _f = bhit.weather_year_factors(econtrol, _year, econtrol_capacity)["ror"]
        _mw = _profile * _rav_ror_mwh * _f
        _ax.plot(
            _mw.index,
            _mw,
            color=_colors[_label],
            lw=0.9,
            label=f"{_label}: factor {_f:.2f} → {_mw.sum() / 1e6:.2f} TWh",
        )
    _ax.set_ylim(0, _ax.get_ylim()[1] * 1.3)
    _ax.set_ylabel("run-of-river inflow [MW]")
    _ax.set_title(
        f"b · the amount: KLIEN RAV {_rav_ror_mwh / 1e6:.2f} TWh × E-Control year factor\n"
        "same shape, only the scale changes",
        loc="left",
        fontsize=10,
        color=INK,
    )
    _ax.legend(frameon=False, fontsize=8, loc="upper left")

    # c — cumulative share: identical for every scaling
    _ax = _axes[2]
    _cum = _profile.cumsum()
    _ax.plot(_cum.index, _cum, color=C_CARRIER["ror"], lw=1.4)
    _half = _cum.index[(_cum >= 0.5).argmax()]
    _ax.axhline(0.5, color=MUTED, lw=0.8, ls=":")
    _ax.axvline(_half, color=MUTED, lw=0.8, ls=":")
    _ax.text(
        _half,
        0.52,
        f" half of the year's water has arrived by {_half:%d %b}",
        fontsize=8,
        color=MUTED,
        va="bottom",
    )
    _ax.set_ylim(0, 1.02)
    _ax.set_ylabel("cumulative share of the annual energy")
    _ax.set_title(
        "c · when the water arrives: identical for dry, model and wet year\n"
        "(the cutout year decides this, the targets decide the amount)",
        loc="left",
        fontsize=10,
        color=INK,
    )

    for _ax in _axes:
        style_axis(_ax, "y")
        _ax.set_xlim(_profile.index[0], _profile.index[-1])
        _ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
        _ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    _fig.suptitle(
        f"Profile vs. amount — {CARRIER_LABEL['ror']} in {_region} {region_names[_region]}",
        x=0.01,
        ha="left",
        fontsize=12,
        color=INK,
    )
    _fig.tight_layout()
    _fig.savefig(OUT / f"04_profile_is_timing_not_amount_{_region}.png", dpi=DPI)
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. Data pipeline for one region

    Every rule the hydro update touches, from the upstream inputs to the solved
    network, with the values of the example region. Bold boxes are the steps
    this branch adds (`rules/pypsa-at/modify.smk`, `build.smk`,
    `scripts/pypsa-at/`, `mods/network/hydro.py`, `mods/constraints/`);
    plain boxes are the existing PyPSA-AT rules the update feeds. The
    diagram is rendered with Graphviz to `OUT` and shown as Mermaid below.
    """)
    return


@app.cell
def _(
    REGIONS,
    cap_curated,
    cap_network,
    cap_ppm,
    cap_residual,
    inflow_steps,
    pd,
    RESOURCES,
):
    _r = REGIONS[0]
    _s = inflow_steps(_r)
    _t = _s["targets"]
    _corr = pd.read_csv(RESOURCES / "klien_ror_trajectory_adm.csv")
    _corr = _corr[_corr["region"] == _r].set_index("year")

    def _mw(df, col):
        return float(df.loc[_r].get(col, 0.0)) if col in df.columns else 0.0

    def _twh(car):
        return _t.loc[car, "inflow"] / 1e6 if car in _t.index else 0.0

    C_INPUT, C_STEP, C_NEW, C_OUT = "#f0efec", "#ffffff", "#fde7dc", "#dff3ea"
    # (id, label, style)  — style: input | step | new | out
    NODES = [
        (
            "ppm",
            f"powerplantmatching\n{_r}: ror {_mw(cap_ppm, 'ror'):.0f} · res {_mw(cap_ppm, 'hydro'):.0f}\n"
            f"· PHS {_mw(cap_ppm, 'PHS'):.0f} MW",
            "input",
        ),
        ("reg", "E-Control Anlagenregister\nKleinwasserkraft ≤ 10 MW", "input"),
        ("geo", "GeoNames postal codes\ncentroid per PLZ", "input"),
        ("ecb", "E-Control Bestandsstatistik\ncapacity < 10 MW anchor", "input"),
        (
            "cur",
            "Curated lists (data/pypsa-at)\nduplicates · reclassification\n"
            "Grenzkraftwerke · missing plants\ncatchment corrections · pins",
            "input",
        ),
        ("klc", "KLIEN catchments (GTIF)\nC_current, E_current, pathways", "input"),
        ("ecj", "E-Control Betriebsstatistik\nannual Lauf / Speicher / PS", "input"),
        ("era", "ERA5 cutout 2013\natlite runoff", "input"),
        ("pem", "PEMMDB / TYNDP\ninflows, corridors (other countries)", "input"),
        ("nuts", "NUTS3 regions\nregions_onshore_base_s_adm", "input"),
        (
            "ow",
            "overwrite_powerplants_at\ndrop duplicates → reclassify\n→ treaty shares → register small hydro\n"
            "→ scale to Bestandsstatistik\n→ missing plants → KLIEN residual plants",
            "new",
        ),
        (
            "fleet",
            f"powerplants_s_adm.csv\n{_r}: ror {_mw(cap_curated, 'ror'):.0f} + "
            f"{_mw(cap_residual, 'ror'):.0f} residual\n· res {_mw(cap_curated, 'hydro'):.0f} · "
            f"PHS {_mw(cap_curated, 'PHS'):.0f} MW",
            "out",
        ),
        (
            "traj",
            f"build_klien_hydro_trajectory_at\nKLIEN buildout factor × AT ror fleet\n"
            f"2030 +{_corr.loc[2030, 'delta_c_mw']:.0f} MW · 2040 +{_corr.loc[2040, 'delta_c_mw']:.0f} MW",
            "new",
        ),
        (
            "ct",
            "build_capacity_trajectories\ntrajectories_adm.csv\nAT ror p_nom_max",
            "step",
        ),
        (
            "tgt",
            f"build_hydro_inflow_targets_at\nplants → catchments (point-in-polygon, pins)\n"
            f"E_current split by capacity × year factor\nPHS: E-Control natural inflow\n"
            f"{_r}: ror {_twh('ror'):.2f} · res {_twh('hydro'):.2f} · PHS {_twh('PHS'):.2f} TWh",
            "new",
        ),
        (
            "tot",
            "build_inflow_totals_per_region\ninflow_totals_per_region_adm.csv\nAT from targets, others PEMMDB",
            "step",
        ),
        (
            "prof",
            "build_inflow_profile\nprofile_inflow_adm.nc\nsums to 1 per region",
            "step",
        ),
        (
            "inf",
            "build_inflows_per_region\ninflow_per_region_adm.nc\n= profile × totals [MW]",
            "step",
        ),
        (
            "hy",
            "process_hydro (mods/network/hydro.py)\nadd_phs_hydro: stores, dischargers, inflow gens\n"
            "fix_store_volumes: AT e_nom_max = e_nom_min\npatch_inflows: ror p_max_pu + _redistribute_peaks\n"
            "store inflow ÷ turbine efficiency, p_nom = peak",
            "new",
        ),
        (
            "net",
            f"base_s_adm__none_2025.nc\n{_r}: ror {_mw(cap_network, 'ror'):.0f} · res "
            f"{_mw(cap_network, 'hydro'):.0f} · PHS {_mw(cap_network, 'PHS'):.0f} MW",
            "out",
        ),
        (
            "solve",
            "solve: constraints\ntrajectories: ror ≤ KLIEN corridor\nEAG floor: AT natural inflow ≥ 47 TWh (2030)\n"
            "inflow generators × turbine efficiency",
            "new",
        ),
    ]
    EDGES = [
        ("ppm", "ow"),
        ("reg", "ow"),
        ("geo", "ow"),
        ("ecb", "ow"),
        ("cur", "ow"),
        ("klc", "ow"),
        ("nuts", "ow"),
        ("ow", "fleet"),
        ("fleet", "traj"),
        ("klc", "traj"),
        ("traj", "ct"),
        ("pem", "ct"),
        ("fleet", "tgt"),
        ("klc", "tgt"),
        ("cur", "tgt"),
        ("ecj", "tgt"),
        ("nuts", "tgt"),
        ("tgt", "tot"),
        ("pem", "tot"),
        ("fleet", "tot"),
        ("era", "prof"),
        ("nuts", "prof"),
        ("prof", "inf"),
        ("tot", "inf"),
        ("inf", "hy"),
        ("fleet", "hy"),
        ("hy", "net"),
        ("ct", "solve"),
        ("net", "solve"),
    ]
    CLUSTERS = {
        "upstream inputs": [
            "ppm",
            "reg",
            "geo",
            "ecb",
            "cur",
            "klc",
            "ecj",
            "era",
            "pem",
            "nuts",
        ],
        "1 · fleet": ["ow", "fleet"],
        "2 · corridor": ["traj", "ct"],
        "3 · inflow": ["tgt", "tot", "prof", "inf"],
        "network": ["hy", "net", "solve"],
    }
    STYLE = {"input": C_INPUT, "step": C_STEP, "new": C_NEW, "out": C_OUT}
    return CLUSTERS, EDGES, NODES, STYLE


@app.cell(hide_code=True)
def _(CLUSTERS, DPI, EDGES, NODES, OUT, REGIONS, STYLE, mo):
    import subprocess

    def _dot_label(text):
        return text.replace('"', "'").replace("\n", "\\n")

    _lines = [
        "digraph hydro {",
        "  rankdir=LR; splines=true; nodesep=0.2; ranksep=0.5;",
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9, color="#c3c2b7"];',
        '  edge [color="#52514e", arrowsize=0.7];',
    ]
    _kind = {i: k for i, _, k in NODES}
    _label = {i: lbl for i, lbl, _ in NODES}
    for _n, (_name, _ids) in enumerate(CLUSTERS.items()):
        _lines.append(
            f'  subgraph cluster_{_n} {{ label="{_name}"; fontname="Helvetica-Bold"; fontsize=11; color="#e1e0d9"; style="rounded";'
        )
        for _i in _ids:
            _bold = 'penwidth=2, color="#eb6834", ' if _kind[_i] == "new" else ""
            _lines.append(
                f'    {_i} [label="{_dot_label(_label[_i])}", {_bold}fillcolor="{STYLE[_kind[_i]]}"];'
            )
        _lines.append("  }")
    for _a, _b in EDGES:
        _lines.append(f"  {_a} -> {_b};")
    _lines.append("}")
    _dot = "\n".join(_lines)
    _dot_path = OUT / f"05_pipeline_{REGIONS[0]}.dot"
    _dot_path.write_text(_dot)
    _png = OUT / f"05_pipeline_{REGIONS[0]}.png"
    subprocess.run(
        ["dot", "-Tpng", f"-Gdpi={DPI}", "-o", str(_png), str(_dot_path)], check=True
    )
    subprocess.run(
        ["dot", "-Tsvg", "-o", str(_png.with_suffix(".svg")), str(_dot_path)],
        check=True,
    )
    mo.image(str(_png), width=1100)
    return


@app.cell(hide_code=True)
def _(CLUSTERS, EDGES, NODES, mo):
    # same graph as Mermaid for the interactive notebook
    def _mm_label(text):
        return text.replace('"', "'").replace("\n", "<br/>")

    _kind = {i: k for i, _, k in NODES}
    _label = {i: lbl for i, lbl, _ in NODES}
    _lines = ["flowchart LR"]
    for _n, (_name, _ids) in enumerate(CLUSTERS.items()):
        _lines.append(f'  subgraph c{_n}["{_name}"]')
        for _i in _ids:
            _lines.append(f'    {_i}["{_mm_label(_label[_i])}"]')
        _lines.append("  end")
    for _a, _b in EDGES:
        _lines.append(f"  {_a} --> {_b}")
    _lines.append("  classDef new fill:#fde7dc,stroke:#eb6834,stroke-width:2px;")
    _lines.append("  classDef out fill:#dff3ea,stroke:#1baf7a;")
    _lines.append("  classDef input fill:#f0efec,stroke:#c3c2b7;")
    for _k in ("new", "out", "input"):
        _ids = [i for i in _kind if _kind[i] == _k]
        _lines.append(f"  class {','.join(_ids)} {_k};")
    mo.mermaid("\n".join(_lines))
    return


if __name__ == "__main__":
    app.run()
