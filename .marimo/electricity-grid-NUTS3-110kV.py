import marimo

__generated_with = "0.23.13"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Austrian 110 kV Network — Per-Region Asset Transparency

    Every OSM asset (line, bus, transformer) that touches Austria is listed with a
    **stable integer ID**, its **active/inactive status**, and the **rule that decided it**.

    The purpose is reviewability: a human should be able to look at one NUTS3 region,
    see every asset on the map, find it in the table below the map by its ID, and read
    exactly why it is in or out of the model.

    **Data version.** Reads `osm-at 0.3-at`, which carries `operator`,
    `operator_clean` and `tag_frequency` columns and already excludes railway
    traction and cross-border sub-220 kV lines. Each asset also gets a clickable
    OSM link for manual verification.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. NUTS3 regions and asset-to-region assignment
    """)
    return


@app.cell(hide_code=True)
def _(NUTS3_PATH, gpd):
    nuts3_all = gpd.read_file(NUTS3_PATH)
    nuts3_at = (
        nuts3_all[nuts3_all["CNTR_CODE"] == "AT"][["NUTS_ID", "NAME_LATN", "geometry"]]
        .sort_values("NUTS_ID")
        .reset_index(drop=True)
    )
    region_name = dict(zip(nuts3_at["NUTS_ID"], nuts3_at["NAME_LATN"]))
    print(f"AT NUTS3 regions: {len(nuts3_at)}")
    return nuts3_at, region_name


@app.cell(hide_code=True)
def _(buses, gpd, lines, nuts3_at, transformers):
    # Buses: point-in-polygon, with a nearest-neighbour fallback for buses that fall
    # just outside the simplified NUTS3 outline (coastline/border generalisation).
    _joined = gpd.sjoin(
        buses[["geometry"]], nuts3_at[["NUTS_ID", "geometry"]], predicate="within"
    )
    bus_region = _joined["NUTS_ID"].groupby(level=0).first()

    _missing = buses.index.difference(bus_region.index)
    if len(_missing):
        _near = (
            gpd.sjoin_nearest(
                buses.loc[_missing, ["geometry"]].to_crs(3035),
                nuts3_at[["NUTS_ID", "geometry"]].to_crs(3035),
            )["NUTS_ID"]
            .groupby(level=0)
            .first()
        )
        bus_region = bus_region.reindex(buses.index)
        bus_region.loc[_missing] = _near
    bus_region = bus_region.reindex(buses.index)

    def _regions_of(df):
        return df["bus0"].map(bus_region), df["bus1"].map(bus_region)

    lines_r0, lines_r1 = _regions_of(lines)
    tr_r0, tr_r1 = _regions_of(transformers)

    print(f"Buses without a region: {int(bus_region.isna().sum())}")
    print(f"Lines crossing a NUTS3 boundary: {int((lines_r0 != lines_r1).sum())}")
    return bus_region, lines_r0, lines_r1, tr_r0, tr_r1


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3b. Line operators

    From `0.3-at` on the archive carries the operator attribution itself:
    `build_osm_network_at` recovers `operator` (verbatim OSM values),
    `operator_clean` (canonical alias, e.g. every APG spelling becomes `APG`)
    and `tag_frequency` (the raw frequency tag before upstream normalisation)
    from the raw Overpass JSON. The notebook reads those columns directly.

    Railway traction (16.7 Hz) and cross-border sub-220 kV lines are already
    removed at archive build time, so the corresponding rules below act as
    verification guards and should match zero lines.
    """)
    return


@app.cell
def _(lines):
    # The canonical aliases come straight from the archive's operator_clean
    # column, produced by OPERATOR_ALIASES in build_osm_network_at (where every
    # APG spelling maps to "APG" and Verbund Hydro Power stays separate).
    line_operator = lines["operator"]
    line_operator_clean = lines["operator_clean"]
    line_frequency = lines["tag_frequency"].astype("string")

    is_apg = line_operator_clean.fillna("").str.contains("APG")

    # Traction is already removed at archive build time; recompute the flag from
    # tag_frequency as a guard. Only 16.7 Hz counts — the ÖBB-operated 50 Hz
    # feeds to its converter stations legitimately remain in the archive.
    is_traction = line_frequency.fillna("").str.contains("16.7")

    print(
        f"Lines with a resolved operator: {int(line_operator.notna().sum())}/{len(lines)}"
    )
    print(f"Lines operated by APG         : {int(is_apg.sum())}")
    print(f"Traction left in archive      : {int(is_traction.sum())} (guard, expect 0)")
    print("\nTop operators (clean):")
    print(line_operator_clean.value_counts().head(12).to_string())
    print("\nMatched as APG (verbatim spellings):")
    print(line_operator[is_apg].value_counts().to_string())
    print("\nÖBB lines kept (explicit 50 Hz converter feeds):")
    _obb_kept = line_operator_clean.fillna("").str.contains("ÖBB") & ~is_traction
    print(
        line_frequency[_obb_kept].fillna("<none>").value_counts().to_string()
        or "  none"
    )
    return is_apg, is_traction, line_frequency, line_operator


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Activation rules

    Rules are evaluated **in order, first match wins**. Each asset therefore carries
    exactly one `rule` and one human-readable `reason`.

    The intent encoded here is: *110 kV must not form cross-regional transmission
    corridors, but a region with no transmission-level substation must still be fed.*

    | # | Rule | Effect |
    |---|------|--------|
    | R0 | `TRACTION` — 16.7 Hz railway line, or ÖBB without an explicit 50 Hz tag | inactive |
    | R1 | `CROSS_BORDER_LV` — sub-220 kV line with exactly one AT endpoint, unless TSO-operated | inactive |
    | R2 | `TRANSMISSION` — voltage ≥ 220 kV | active |
    | R2b | `APG_TSO` — operated by Austrian Power Grid at any voltage | active |
    | R3 | `INTRA_REGION` — 110 kV, both endpoints in the same NUTS3 region | active |
    | R4 | `SOLE_FEED` — 110 kV inter-regional, designated single feed of a region with no ≥220 kV substation | active |
    | R5 | `INTER_REGION` — any remaining 110 kV line crossing a NUTS3 boundary | inactive |

    R4 resolves in two stages. A region listed in the **override table** below takes
    its feeds from there, with a cited source. Any remaining feed-less region falls
    back to a heuristic: most circuits wins, ties break on shortest length, then on
    line ID. The heuristic is a stand-in only — it has no knowledge of where the
    transmission grid is actually handed over to the DNO, and it picks badly when a
    short inter-DNO tie exists (see AT315 below).

    A region may have **more than one** documented feed. That is the normal case
    where a region hangs off one transformer station via several corridors.
    """)
    return


@app.cell
def _(pd):
    # Documented 110 kV feeds, one row per line — the same file the model
    # pipeline consumes (mods.filter_inter_regional_lines), so notebook and
    # model cannot drift. Add rows there, with substation, source and evidence.
    FEED_OVERRIDES = pd.read_csv("data/pypsa-at/electricity_network_overrides.csv")
    FEED_OVERRIDES
    return (FEED_OVERRIDES,)


@app.cell(hide_code=True)
def _(
    FEED_OVERRIDES,
    TRANSMISSION_KV,
    bus_region,
    buses,
    lines,
    lines_r0,
    lines_r1,
    pd,
):
    def _regions_without_transmission():
        """NUTS3 regions that host no substation at or above TRANSMISSION_KV."""
        hv = buses[buses["voltage"] >= TRANSMISSION_KV].index
        hv_regions = set(bus_region.loc[hv].dropna())
        return set(bus_region.dropna().unique()) - hv_regions

    def _designate_sole_feeds(feedless, inter_regional):
        """
        Designate the 110 kV feeds of every feed-less region.

        Overrides win; regions they do not cover fall back to the heuristic.
        Returns ``({line_id: region}, {line_id: evidence})``.
        """
        chosen, evidence, documented = {}, {}, set()

        for row in FEED_OVERRIDES.itertuples():
            if row.line_id not in inter_regional.index:
                # Loud rather than silent: an override that matches nothing means the
                # archive changed under us and the region would quietly lose its feed.
                print(
                    f"  WARNING override {row.line_id} ({row.region}) is not an "
                    "inter-regional 110 kV candidate — ignored."
                )
                continue
            touches = row.region in (lines_r0[row.line_id], lines_r1[row.line_id])
            if not touches:
                print(
                    f"  WARNING override {row.line_id} does not touch {row.region} "
                    "— ignored."
                )
                continue
            chosen[row.line_id] = row.region
            evidence[row.line_id] = (
                f"{row.evidence} Source: {row.source}. Handover at {row.substation}."
            )
            documented.add(row.region)

        for region in sorted(feedless - documented):
            candidates = inter_regional[
                (lines_r0.loc[inter_regional.index] == region)
                | (lines_r1.loc[inter_regional.index] == region)
            ]
            if candidates.empty:
                continue
            best = candidates.sort_values(
                ["circuits", "length"], ascending=[False, True]
            ).index[0]
            chosen[best] = region
            evidence[best] = (
                "UNDOCUMENTED — picked by heuristic (most circuits, then shortest). "
                "No source confirms this is where the region meets the transmission "
                "grid; verify against the operator's Netzentwicklungsplan."
            )
        return chosen, evidence

    _at_ends = pd.DataFrame(
        {
            "in_at0": lines["bus0"].isin(buses.index),
            "in_at1": lines["bus1"].isin(buses.index),
        }
    )
    is_cross_border = _at_ends["in_at0"] != _at_ends["in_at1"]
    is_transmission = lines["voltage"] >= TRANSMISSION_KV
    is_intra_region = (lines_r0 == lines_r1) & lines_r0.notna()

    feedless_regions = _regions_without_transmission()
    _inter = lines[~is_transmission & ~is_cross_border & ~is_intra_region]
    print(
        f"Regions without a >={TRANSMISSION_KV:.0f} kV substation: {len(feedless_regions)}"
    )
    print(f"  {sorted(feedless_regions)}")
    sole_feeds, feed_evidence = _designate_sole_feeds(feedless_regions, _inter)

    _documented = {r for r in sole_feeds.values() if r in set(FEED_OVERRIDES["region"])}
    print(f"Designated 110 kV feeds: {len(sole_feeds)}")
    print(f"  documented by source : {sorted(_documented)}")
    print(f"  still heuristic      : {sorted(feedless_regions - _documented)}")
    return (
        feed_evidence,
        is_cross_border,
        is_intra_region,
        is_transmission,
        sole_feeds,
    )


@app.cell(hide_code=True)
def _(
    feed_evidence,
    is_apg,
    is_cross_border,
    is_intra_region,
    is_traction,
    is_transmission,
    line_frequency,
    line_operator,
    lines,
    lines_r0,
    lines_r1,
    pd,
    region_name,
    sole_feeds,
):
    def _classify(line_id):
        """Return (active, rule, reason) for one line. First match wins."""
        r0, r1 = lines_r0.get(line_id), lines_r1.get(line_id)
        kv = lines.at[line_id, "voltage"]

        if is_traction.get(line_id, False):
            hz = line_frequency.get(line_id)
            return (
                False,
                "R0 TRACTION",
                f"Railway traction line (operator {line_operator.get(line_id)}, "
                f"frequency {hz if pd.notna(hz) else 'untagged'} Hz). The 16.7 Hz "
                "traction network is galvanically separate from the 50 Hz public "
                "grid and must not carry power in this model.",
            )
        if (
            is_cross_border.get(line_id, False)
            and not is_transmission[line_id]
            and not is_apg.get(line_id, False)
        ):
            return (
                False,
                "R1 CROSS_BORDER_LV",
                f"Cross-border line at {kv:.0f} kV. The AT 110 kV level is not "
                "validated against foreign grids, so sub-220 kV interconnectors "
                "are excluded — unless TSO-operated (see R2b).",
            )
        if is_transmission[line_id]:
            return (
                True,
                "R2 TRANSMISSION",
                f"Transmission level ({kv:.0f} kV). Not affected by the 110 kV rules.",
            )
        if is_apg.get(line_id, False):
            return (
                True,
                "R2b APG_TSO",
                f"Operated by the TSO ({line_operator.get(line_id)}) at {kv:.0f} kV. "
                "APG-operated lines are part of the transmission system regardless "
                "of voltage level, so they are kept whatever the region rules say.",
            )
        if is_intra_region.get(line_id, False):
            return (
                True,
                "R3 INTRA_REGION",
                f"Both ends inside {r0} ({region_name.get(r0, '?')}). Cannot carry "
                "inter-regional transit, so it is safe to keep.",
            )
        if line_id in sole_feeds:
            fed = sole_feeds[line_id]
            return (
                True,
                "R4 SOLE_FEED",
                f"Designated 110 kV feed for {fed} ({region_name.get(fed, '?')}), "
                f"which hosts no >=220 kV substation. {feed_evidence[line_id]}",
            )
        return (
            False,
            "R5 INTER_REGION",
            f"Crosses the boundary between {r0} and {r1}. Keeping it would create a "
            "transmission corridor at 110 kV.",
        )

    line_status = pd.DataFrame(
        [_classify(i) for i in lines.index],
        index=lines.index,
        columns=["active", "rule", "reason"],
    )

    print(line_status.groupby(["rule", "active"]).size().to_string())
    return (line_status,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. Asset registry

    One flat table of every in-scope asset with a **globally unique integer ID**.
    These IDs are what the maps below annotate, so an ID always means the same asset
    everywhere in this notebook. Ordering is deterministic (kind, then OSM ID), so IDs
    stay stable across re-runs as long as the input archive does not change.
    """)
    return


@app.cell(hide_code=True)
def _(
    bus_region,
    buses,
    line_operator,
    line_status,
    lines,
    lines_r0,
    lines_r1,
    pd,
    tr_r0,
    tr_r1,
    transformers,
):
    def _osm_url(osm_id):
        """OSM IDs carry a voltage suffix (``way/123-110``) — strip it for the link."""
        base = str(osm_id).rsplit("-", 1)[0] if "-" in str(osm_id) else str(osm_id)
        return f"https://www.openstreetmap.org/{base}"

    _bus_rows = pd.DataFrame(
        {
            "osm_id": buses.index,
            "kind": "bus",
            "voltage": buses["voltage"].values,
            "region0": bus_region.reindex(buses.index).values,
            "region1": None,
            "operator": pd.NA,
            "length_km": float("nan"),
            "circuits": float("nan"),
            "active": True,
            "rule": "R0 BUS",
            "reason": "Substations are never deactivated; only lines are.",
        }
    )

    _line_rows = pd.DataFrame(
        {
            "osm_id": lines.index,
            "kind": "line",
            "voltage": lines["voltage"].values,
            "region0": lines_r0.values,
            "region1": lines_r1.values,
            "operator": line_operator.values,
            "length_km": (lines["length"] / 1e3).round(2).values,
            "circuits": lines["circuits"].values,
            "active": line_status["active"].values,
            "rule": line_status["rule"].values,
            "reason": line_status["reason"].values,
        }
    )

    _tr_rows = pd.DataFrame(
        {
            "osm_id": transformers.index,
            "kind": "transformer",
            "voltage": transformers["voltage_bus0"].values,
            "region0": tr_r0.values,
            "region1": tr_r1.values,
            "operator": pd.NA,
            "length_km": float("nan"),
            "circuits": float("nan"),
            "active": True,
            "rule": "R0 TRANSFORMER",
            "reason": "Transformers follow their buses; they are not filtered here.",
        }
    )

    assets = pd.concat([_bus_rows, _line_rows, _tr_rows], ignore_index=True)
    assets = assets.sort_values(["kind", "osm_id"], kind="stable").reset_index(
        drop=True
    )
    assets.insert(0, "id", range(1, len(assets) + 1))
    assets["osm_url"] = assets["osm_id"].map(_osm_url)

    # id lookups used by the plots
    asset_id = assets.set_index(["kind", "osm_id"])["id"]
    bus_id_map = asset_id.loc["bus"]
    line_id_map = asset_id.loc["line"]
    tr_id_map = asset_id.loc["transformer"]

    print(assets.groupby(["kind", "active"]).size().to_string())
    return assets, bus_id_map, line_id_map, tr_id_map


@app.cell(hide_code=True)
def _(assets, mo):
    mo.ui.table(
        assets[
            [
                "id",
                "kind",
                "osm_id",
                "voltage",
                "region0",
                "region1",
                "operator",
                "length_km",
                "circuits",
                "active",
                "rule",
            ]
        ],
        page_size=15,
        selection=None,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 6. Overview — what the rules do to the network
    """)
    return


@app.cell(hide_code=True)
def atgrid(
    DEFAULT_COLOUR,
    INACTIVE_COLOUR,
    VOLTAGE_COLOURS,
    line_status,
    lines,
    mlines,
    mpatches,
    nuts3_at,
    plt,
):
    _fig, _ax = plt.subplots(figsize=(14, 8))

    nuts3_at.plot(ax=_ax, color="#f4f7f4", edgecolor="#6aaa6a", linewidth=0.8)

    _active = lines[line_status["active"]]
    _inactive = lines[~line_status["active"]]

    for _v, _grp in _active.groupby("voltage"):
        _grp.plot(
            ax=_ax,
            color=VOLTAGE_COLOURS.get(_v, DEFAULT_COLOUR),
            linewidth=1.0,
            alpha=0.9,
        )
    if len(_inactive):
        _inactive.plot(
            ax=_ax,
            color=INACTIVE_COLOUR,
            linewidth=1.4,
            linestyle="--",
            alpha=0.95,
        )

    # NUTS3 labels last so they sit on top of the lines. representative_point()
    # rather than centroid keeps the label inside concave regions.
    for _, _region in nuts3_at.iterrows():
        _point = _region.geometry.representative_point()
        _ax.annotate(
            _region["NUTS_ID"],
            xy=(_point.x, _point.y),
            fontsize=7,
            ha="center",
            va="center",
            color="#2f5d2f",
            zorder=5,
            bbox=dict(
                boxstyle="round,pad=0.15",
                fc="#ffffff",
                ec="#6aaa6a",
                alpha=0.75,
                linewidth=0.4,
            ),
        )

    _handles = [
        mpatches.Patch(facecolor="#f4f7f4", edgecolor="#6aaa6a", label="NUTS3 regions")
    ]
    _handles += [
        mlines.Line2D(
            [],
            [],
            color=VOLTAGE_COLOURS.get(_v, DEFAULT_COLOUR),
            label=f"{int(_v)} kV — active",
        )
        for _v in sorted(_active["voltage"].unique())
    ]
    _handles.append(
        mlines.Line2D(
            [],
            [],
            color=INACTIVE_COLOUR,
            linestyle="--",
            label=f"inactive ({len(_inactive)})",
        )
    )
    _ax.legend(handles=_handles, loc="lower left", fontsize=9)

    _ax.set_title(
        "Austrian network after the 110 kV activation rules "
        f"({int(line_status['active'].sum())} active / {len(lines)} lines)",
        fontsize=14,
    )
    _ax.set_aspect("equal")
    _ax.set_xlabel("Longitude")
    _ax.set_ylabel("Latitude")
    plt.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(assets, mo):
    _lines = assets[assets["kind"] == "line"]
    _summary = (
        _lines.groupby(["rule", "active"])
        .agg(count=("id", "size"), circuit_km=("length_km", "sum"))
        .round(1)
        .reset_index()
    )
    mo.vstack([mo.md("### Rule outcomes"), mo.ui.table(_summary, selection=None)])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 7. Per-region detail

    Pick a region below. The next cell renders its map with every asset annotated by
    its integer ID; the cell after that lists exactly those assets.
    """)
    return


@app.cell(hide_code=True)
def _(mo, nuts3_at, region_name):
    region_selector = mo.ui.dropdown(
        options={f"{r} — {region_name[r]}": r for r in sorted(nuts3_at["NUTS_ID"])},
        value=f"{nuts3_at['NUTS_ID'].iloc[0]} — {region_name[nuts3_at['NUTS_ID'].iloc[0]]}",
        label="NUTS3 region",
    )
    region_selector
    return (region_selector,)


@app.cell(hide_code=True)
def _(
    bus_region,
    buses,
    lines,
    lines_r0,
    lines_r1,
    tr_r0,
    tr_r1,
    transformers,
):
    def assets_of_region(region):
        """
        Every asset with at least one endpoint in *region*.

        Selection is endpoint-based, so a line that merely passes through the
        region without terminating in it is neither drawn nor listed. Both the
        map and the table use this same function, which is what guarantees that
        every ID visible on the map can be looked up below it.
        """
        region_buses = buses[bus_region.reindex(buses.index) == region]

        endpoint_lines = (lines_r0 == region) | (lines_r1 == region)
        region_lines = lines[endpoint_lines]

        region_trafos = transformers[(tr_r0 == region) | (tr_r1 == region)]
        return region_buses, region_lines, region_trafos

    return (assets_of_region,)


@app.cell(hide_code=True)
def _(mo, region_name, region_selector):
    _r = region_selector.value
    mo.md(f"""## {_r} — {region_name[_r]}""")
    return


@app.cell(hide_code=True)
def _(
    DEFAULT_COLOUR,
    INACTIVE_COLOUR,
    VOLTAGE_COLOURS,
    assets_of_region,
    bus_id_map,
    line_id_map,
    line_status,
    mlines,
    mpatches,
    nuts3_at,
    plt,
    region_selector,
    tr_id_map,
):
    def plot_region(region, figsize=(13, 10)):
        """Map of one NUTS3 region with every asset annotated by its integer ID."""
        rb, rl, rt = assets_of_region(region)
        shape = nuts3_at[nuts3_at["NUTS_ID"] == region]

        fig, ax = plt.subplots(figsize=figsize)

        # Neighbouring regions for context, then the region itself on top.
        nuts3_at.plot(ax=ax, color="#fafafa", edgecolor="#dddddd", linewidth=0.6)
        shape.plot(ax=ax, color="#eef5ee", edgecolor="#4a8a4a", linewidth=1.6)

        seen_voltages = set()
        for line_id, row in rl.iterrows():
            active = bool(line_status.at[line_id, "active"])
            voltage = row["voltage"]
            colour = (
                VOLTAGE_COLOURS.get(voltage, DEFAULT_COLOUR)
                if active
                else INACTIVE_COLOUR
            )
            ax.plot(
                *row.geometry.xy,
                color=colour,
                linewidth=2.0 if active else 2.4,
                linestyle="-" if active else "--",
                alpha=0.9,
                zorder=3,
            )
            seen_voltages.add(voltage)

            midpoint = row.geometry.interpolate(0.5, normalized=True)
            ax.annotate(
                str(line_id_map[line_id]),
                xy=(midpoint.x, midpoint.y),
                fontsize=7,
                ha="center",
                va="center",
                color="#ffffff",
                zorder=6,
                bbox=dict(boxstyle="round,pad=0.15", fc=colour, ec="none", alpha=0.9),
            )

        for bus_id, row in rb.iterrows():
            ax.plot(
                row.geometry.x,
                row.geometry.y,
                marker="o",
                markersize=5,
                color=VOLTAGE_COLOURS.get(row["voltage"], DEFAULT_COLOUR),
                markeredgecolor="#222222",
                markeredgewidth=0.5,
                zorder=4,
            )
            ax.annotate(
                str(bus_id_map[bus_id]),
                xy=(row.geometry.x, row.geometry.y),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=7,
                color="#111111",
                zorder=6,
                bbox=dict(
                    boxstyle="round,pad=0.12",
                    fc="#ffffff",
                    ec="#999999",
                    alpha=0.85,
                    linewidth=0.4,
                ),
            )

        for tr_id, row in rt.iterrows():
            centre = row.geometry.interpolate(0.5, normalized=True)
            ax.plot(
                centre.x,
                centre.y,
                marker="s",
                markersize=6,
                color="#ffffff",
                markeredgecolor="#000000",
                markeredgewidth=0.9,
                zorder=5,
            )
            ax.annotate(
                str(tr_id_map[tr_id]),
                xy=(centre.x, centre.y),
                xytext=(4, -9),
                textcoords="offset points",
                fontsize=7,
                color="#000000",
                zorder=6,
                bbox=dict(
                    boxstyle="round,pad=0.12",
                    fc="#f0f0f0",
                    ec="#000000",
                    alpha=0.85,
                    linewidth=0.4,
                ),
            )

        handles = [
            mpatches.Patch(facecolor="#eef5ee", edgecolor="#4a8a4a", label=region),
        ]
        handles += [
            mlines.Line2D(
                [],
                [],
                color=VOLTAGE_COLOURS.get(v, DEFAULT_COLOUR),
                label=f"{int(v)} kV — active",
            )
            for v in sorted(seen_voltages)
        ]
        handles += [
            mlines.Line2D(
                [], [], color=INACTIVE_COLOUR, linestyle="--", label="inactive line"
            ),
            mlines.Line2D(
                [],
                [],
                color="none",
                marker="o",
                markersize=6,
                markerfacecolor="#888888",
                markeredgecolor="#222222",
                label="bus / substation",
            ),
            mlines.Line2D(
                [],
                [],
                color="none",
                marker="s",
                markersize=6,
                markerfacecolor="#ffffff",
                markeredgecolor="#000000",
                label="transformer",
            ),
        ]
        ax.legend(handles=handles, loc="best", fontsize=8, framealpha=0.9)

        minx, miny, maxx, maxy = shape.total_bounds
        pad = 0.12 * max(maxx - minx, maxy - miny)
        ax.set_xlim(minx - pad, maxx + pad)
        ax.set_ylim(miny - pad, maxy + pad)
        ax.set_aspect("equal")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title(
            f"{region} — {len(rb)} buses, {len(rl)} lines, {len(rt)} transformers",
            fontsize=12,
        )
        plt.tight_layout()
        # Drop the figure from pyplot's registry so rendering all 35 regions does
        # not accumulate open figures. The Figure object itself still renders.
        plt.close(fig)
        return fig

    plot_region(region_selector.value)
    return (plot_region,)


@app.cell(hide_code=True)
def _(assets, assets_of_region, mo, region_selector):
    def region_asset_table(region):
        """Table of exactly the assets drawn on that region's map, keyed by ID."""
        rb, rl, rt = assets_of_region(region)
        ids = set(rb.index) | set(rl.index) | set(rt.index)
        table = assets[assets["osm_id"].isin(ids)].copy()
        return table.sort_values(["kind", "id"])[
            [
                "id",
                "kind",
                "osm_id",
                "voltage",
                "region0",
                "region1",
                "operator",
                "length_km",
                "circuits",
                "active",
                "rule",
                "reason",
                "osm_url",
            ]
        ]

    _table = region_asset_table(region_selector.value)
    mo.vstack(
        [
            mo.md(
                f"**{len(_table)} assets in {region_selector.value}** — "
                f"{int((~_table['active']).sum())} inactive"
            ),
            mo.ui.table(_table, page_size=25, selection=None),
        ]
    )
    return (region_asset_table,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 8. All regions

    The selector above is for focused review. Enable this to render every NUTS3
    region in sequence — header, map, then table — for export or a full read-through.
    It draws 35 maps, so it is off by default.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    render_all = mo.ui.switch(label="Render all NUTS3 regions")
    render_all
    return (render_all,)


@app.cell
def _(mo, nuts3_at, plot_region, region_asset_table, region_name, render_all):
    def _all_regions():
        sections = []
        for region in sorted(nuts3_at["NUTS_ID"]):
            table = region_asset_table(region)
            sections.append(
                mo.vstack(
                    [
                        mo.md(f"### {region} — {region_name[region]}"),
                        plot_region(region, figsize=(11, 8)),
                        mo.ui.table(table, page_size=10, selection=None),
                    ]
                )
            )
        return mo.vstack(sections, gap=2)

    _all_regions() if render_all.value else mo.md("*Switch enabled above to render.*")
    return


@app.cell
def _():
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib.lines as mlines
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import pandas as pd
    from shapely import wkt

    return Path, gpd, mlines, mo, mpatches, pd, plt, wkt


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Configuration
    """)
    return


@app.cell
def _(Path):
    # From 0.3-at on, the archive itself carries `operator`, `operator_clean`
    # and `tag_frequency` (recovered in build_osm_network_at), so no external
    # operator cache is needed any more.
    OSM_DIR = Path("data/osm/archive/0.3-at")

    NUTS3_PATH = Path(
        "data/eu_nuts2021/archive/2021-01-01/ref-nuts-2021-01m.geojson"
        "/NUTS_RG_01M_2021_4326_LEVL_3.geojson"
    )

    # Voltage at or above which a line is considered transmission level and is
    # never touched by the 110 kV rules.
    TRANSMISSION_KV = 220.0

    VOLTAGE_COLOURS = {
        110.0: "#e05c1a",
        220.0: "#1a5fe0",
        380.0: "#8b008b",
        400.0: "#5b0f5b",
    }
    DEFAULT_COLOUR = "#999999"

    INACTIVE_COLOUR = "#c0392b"
    return (
        DEFAULT_COLOUR,
        INACTIVE_COLOUR,
        NUTS3_PATH,
        OSM_DIR,
        TRANSMISSION_KV,
        VOLTAGE_COLOURS,
    )


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Load OSM components
    """)
    return


@app.cell
def _(OSM_DIR, gpd, pd, wkt):
    def _read(name):
        return pd.read_csv(OSM_DIR / f"{name}.csv", quotechar="'", low_memory=False)

    def _to_gdf(df):
        df = df.copy()
        df["geometry"] = df["geometry"].apply(wkt.loads)
        return gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")

    buses_raw = _read("buses").set_index("bus_id")
    lines_raw = _read("lines").set_index("line_id")
    transformers_raw = _read("transformers").set_index("transformer_id")

    bus_country = buses_raw["country"]
    at_bus_ids = set(bus_country[bus_country == "AT"].index)

    # Anything with at least one Austrian endpoint is in scope.
    at_lines = lines_raw[
        lines_raw["bus0"].isin(at_bus_ids) | lines_raw["bus1"].isin(at_bus_ids)
    ]
    at_transformers = transformers_raw[
        transformers_raw["bus0"].isin(at_bus_ids)
        | transformers_raw["bus1"].isin(at_bus_ids)
    ]

    # The 0.2-at archive ships transformers referencing buses absent from buses.csv.
    # base_network drops these silently via _remove_dangling_branches, so drop them
    # here too and report the count rather than letting them show up as phantom assets.
    _known = set(buses_raw.index)
    _dangling = ~(
        at_transformers["bus0"].isin(_known) & at_transformers["bus1"].isin(_known)
    )
    n_dangling = int(_dangling.sum())
    at_transformers = at_transformers[~_dangling]

    buses = _to_gdf(buses_raw.loc[sorted(at_bus_ids)])
    lines = _to_gdf(at_lines)
    transformers = _to_gdf(at_transformers)

    print(f"AT buses       : {len(buses)}")
    print(f"AT lines       : {len(lines)}")
    print(f"AT transformers: {len(transformers)}  (dropped {n_dangling} dangling)")
    return buses, lines, transformers


if __name__ == "__main__":
    app.run()
