# Heat Demand

This diagram traces heat demand from the shared weather-based heat profile and the
Austrian heat-demand datasets to the heat Loads used by the model. Violet nodes are
Austrian-specific; blue and amber nodes are inherited or shared workflow steps. See
[Data Flow Diagrams](index.md) for the diagramming convention.


```mermaid
flowchart TD
    classDef source fill:#f8fafc,stroke:#cbd5e1,stroke-width:1px,color:#1e293b,rx:10,ry:10
    classDef step fill:#f0f9ff,stroke:#7dd3fc,stroke-width:1px,color:#0c4a6e,rx:10,ry:10
    classDef aggstep fill:#fffbeb,stroke:#fcd34d,stroke-width:1px,color:#78350f,rx:10,ry:10
    classDef final fill:#ecfdf5,stroke:#6ee7b7,stroke-width:1.5px,color:#064e3b,rx:10,ry:10
    classDef at fill:#fdf2f8,stroke:#f9a8d4,stroke-width:1.5px,color:#831843,rx:10,ry:10

    subgraph retrieve["Retrieve"]
        HEATMAP(["<div style='padding:12px 26px'><b>Austrian heat-demand heatmaps</b><br/><span style='font-size:12px'>WEM / Transition raster data</span><br/><i style='font-size:11px;color:#9d174d'>AT · annual heat density · MWh/ha</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>retrieve_heat_demand_at</span></div>"]):::at
        NEA(["<div style='padding:12px 26px'><b>Statistik Austria NEA</b><br/><span style='font-size:12px'>Useful Energy Analysis workbooks</span><br/><i style='font-size:11px;color:#9d174d'>Bundesland · annual · TJ</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>retrieve_nea_at</span></div>"]):::at
        WEATHER(["<div style='padding:12px 26px'><b>Weather, population &amp; profile data</b><br/><span style='font-size:12px'>cutout, population layout, BDEW shape</span><br/><i style='font-size:11px;color:#64748b'>node · daily/hourly shape inputs</i><br/><span style='font-size:9.5px;color:#94a3b8;font-family:monospace'>build_daily_heat_demand</span></div>"]):::source
    end

    subgraph build["Build Sector"]
        REGIONAL["<div style='padding:10px 18px'><b>Regional annual heat demand</b><br/><span style='font-size:12px'>= zonal raster sums + interpolation</span><br/><i style='font-size:11px;color:#9d174d'>AT NUTS3/NUTS2 · annual · MWh</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>build_heat_demand_at.py</span></div>"]:::at
        NEATABLE["<div style='padding:10px 18px'><b>Stacked NEA data</b><br/><span style='font-size:12px'>= cleaned and reshaped ODS tables</span><br/><i style='font-size:11px;color:#9d174d'>NUTS2 · annual · TWh by sector/fuel/use</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>build_nea_at.py</span></div>"]:::at
        SHAPE["<div style='padding:10px 18px'><b>Hourly heat-demand shape</b><br/><span style='font-size:12px'>= HDD-based daily demand + BDEW intraday profile</span><br/><i style='font-size:11px;color:#0e6ba8'>node · hourly · normalized</i><br/><span style='font-size:9.5px;color:#5b9bd5;font-family:monospace'>build_daily_heat_demand.py / build_hourly_heat_demand.py</span></div>"]:::step
        SHARES["<div style='padding:10px 18px'><b>District heat shares</b><br/><span style='font-size:12px'>= population/urban shares + scenario progress</span><br/><i style='font-size:11px;color:#92702a'>node · static shares · per horizon</i><br/><span style='font-size:9.5px;color:#a88a4e;font-family:monospace'>build_district_heat_share.py</span></div>"]:::aggstep
        LOADS["<div style='padding:10px 18px'><b>Initial heat-system Loads</b><br/><span style='font-size:12px'>= hourly shape × energy totals and efficiencies</span><br/><i style='font-size:11px;color:#0e6ba8'>node · hourly · MW_th</i><br/><span style='font-size:9.5px;color:#5b9bd5;font-family:monospace'>prepare_sector_network.py (add_heat)</span></div>"]:::step
    end

    subgraph modify["Modify (AT)"]
        RECAL["<div style='padding:10px 18px'><b>NEA recalibration</b><br/><span style='font-size:12px'>= scale heatmap totals to NUTS2 NEA totals</span><br/><i style='font-size:11px;color:#9d174d'>NUTS2 → region · annual · MWh</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>recalibrate_heat_demand_at.py</span></div>"]:::at
        REDIST["<div style='padding:10px 18px'><b>Central-heat redistribution</b><br/><span style='font-size:12px'>= urban-weight regional allocation, preserve totals</span><br/><i style='font-size:11px;color:#9d174d'>region/sector · annual · central/decentral</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>recalibrate_heat_demand_at.py</span></div>"]:::at
        ALLOC["<div style='padding:10px 18px'><b>Heat-carrier allocation</b><br/><span style='font-size:12px'>= central, urban decentral, and rural carriers</span><br/><i style='font-size:11px;color:#9d174d'>region/carrier · annual · MWh</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>recalibrate_heat_demand_at.py</span></div>"]:::at
        SHAREAT["<div style='padding:10px 18px'><b>AT district-share update</b><br/><span style='font-size:12px'>= replace Austrian urban fractions</span><br/><i style='font-size:11px;color:#9d174d'>AT node · static shares · per horizon</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>modify_district_heat_share_at.py</span></div>"]:::at
        APPLY["<div style='padding:10px 18px'><b>Apply annual AT demand</b><br/><span style='font-size:12px'>= rescale dynamic/static Loads to target totals</span><br/><i style='font-size:11px;color:#9d174d'>node/carrier · annual target · MW_th</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>mods/demand/heat_demand.py</span></div>"]:::at
    end

    subgraph solve["Solve"]
        FINAL(["<div style='padding:12px 26px'><b>Final heat demand</b><br/><span style='font-size:12px'>solved sector-coupled network</span><br/><i style='font-size:11px;color:#047857'>node/carrier · hourly · MW_th</i></div>"]):::final
    end

    HEATMAP --> REGIONAL
    NEA --> NEATABLE
    WEATHER --> SHAPE
    REGIONAL --> RECAL
    NEATABLE --> RECAL
    SHARES --> RECAL
    RECAL --> REDIST
    REDIST --> ALLOC
    REDIST --> SHAREAT
    SHAPE --> LOADS
    SHARES --> SHAREAT
    SHAREAT --> LOADS
    LOADS --> APPLY
    ALLOC --> APPLY
    APPLY --> FINAL
```

## AT-Specific Processing

- **Heatmaps to regional demand.** The retrieved rasters contain heat density in MWh/ha.
  The workflow selects Austrian NUTS3 regions, or NUTS2 regions for AT10 clustering,
  sums raster cells with zonal statistics, and linearly interpolates between the available
  source years to the configured planning horizons.
- **NEA preparation.** One Statistik Austria ODS workbook per Bundesland is cleaned,
  reshaped from wide tables into long records, converted from TJ to TWh, and labelled with
  NUTS2 code, sector, useful-energy category, and energy carrier.
- **Recalibration.** Household and service records for space/water heat and low/high
  temperature process heat are grouped by NUTS2, sector, and central/decentral heating.
  Each group supplies a scaling factor that changes the heatmap-based regional totals while
  retaining their spatial pattern.
- **Redistribution and allocation.** Central heat is redistributed within each NUTS2
  sector group using regional heat demand and urban fractions. Decentral heat is adjusted so
  regional sector totals remain unchanged, then split into central, urban decentral, and
  rural carriers. The resulting urban fractions are also exported for the district-share
  update.
- **Network application.** The AT district-share file is used while building heat-system
  Loads. During the modify phase, the AT carrier totals replace the initial annual totals;
  dynamic Loads keep their hourly shape while static Loads are set directly from the annual
  target.
- **Limitations** Since Austrian Heatmaps provides overall data for austria including industry,
  transport, households and services, this code assumes a correlated future development of
  those demands.
