# Road Mobility Demand

This diagram traces the shared road-mobility build and the Austrian vehicle-stock and
Nutzenergieanalyse (NEA) overrides to the final transport Loads, Links, and Stores.
Violet nodes are Austrian-specific; blue and amber nodes are inherited or shared workflow
steps. See [Data Flow Diagrams](index.md) for the shared diagram convention.

```mermaid
flowchart TD
    classDef source fill:#f8fafc,stroke:#cbd5e1,stroke-width:1px,color:#1e293b,rx:10,ry:10
    classDef step fill:#f0f9ff,stroke:#7dd3fc,stroke-width:1px,color:#0c4a6e,rx:10,ry:10
    classDef aggstep fill:#fffbeb,stroke:#fcd34d,stroke-width:1px,color:#78350f,rx:10,ry:10
    classDef final fill:#ecfdf5,stroke:#6ee7b7,stroke-width:1.5px,color:#064e3b,rx:10,ry:10
    classDef at fill:#fdf2f8,stroke:#f9a8d4,stroke-width:1.5px,color:#831843,rx:10,ry:10

    subgraph retrieve["Retrieve"]
        SHARED(["<div style='padding:12px 26px'><b>Shared road-energy and vehicle inputs</b><br/><span style='font-size:12px'>JRC IDEES, Eurostat, and existing transport data</span><br/><i style='font-size:11px;color:#64748b'>country · annual · energy, cars, efficiency</i><br/><span style='font-size:9.5px;color:#94a3b8;font-family:monospace'>build_energy_totals.py / transport_data.csv</span></div>"]):::source
        MOBILITY(["<div style='padding:12px 26px'><b>Traffic, population, and weather inputs</b><br/><span style='font-size:12px'>BASt weekly profiles, population layout, air temperature</span><br/><i style='font-size:11px;color:#64748b'>counter/node · weekly/hourly · traffic, population, °C</i><br/><span style='font-size:9.5px;color:#94a3b8;font-family:monospace'>build_mobility_profiles.py / temp_air_total</span></div>"]):::source
        KFZ(["<div style='padding:12px 26px'><b>Statistik Austria vehicle stock</b><br/><span style='font-size:12px'>Kfz-Bestand ODS by registration district</span><br/><i style='font-size:11px;color:#9d174d'>registration district · annual · vehicles by type</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>build_kfz_bestand_at</span></div>"]):::at
        REGIONS(["<div style='padding:12px 26px'><b>Austrian municipality register and NUTS shapes</b><br/><span style='font-size:12px'>Statistik Austria RegGemVz + final NUTS3 GeoJSON</span><br/><i style='font-size:11px;color:#9d174d'>municipality/NUTS3 · static · codes and population</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>build_statistik_at_regions</span></div>"]):::at
        NEA(["<div style='padding:12px 26px'><b>Statistik Austria NEA</b><br/><span style='font-size:12px'>useful-energy records by carrier and Bundesland</span><br/><i style='font-size:11px;color:#9d174d'>NUTS2 · annual · TWh by use and carrier</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>retrieve_nea_at / build_nea_at.py</span></div>"]):::at
    end

    subgraph build["Build Sector"]
        ANNUAL["<div style='padding:10px 18px'><b>Shared annual transport inputs</b><br/><span style='font-size:12px'>= road-energy totals, car stock, and average efficiency</span><br/><i style='font-size:11px;color:#0e6ba8'>country · annual · MWh, cars, MWh/100 km</i><br/><span style='font-size:9.5px;color:#5b9bd5;font-family:monospace'>build_energy_totals.py / transport_data.csv</span></div>"]:::step
        BASE["<div style='padding:10px 18px'><b>Baseline driven-distance demand</b><br/><span style='font-size:12px'>📍 population allocation + kfz profile + temperature efficiency</span><br/><i style='font-size:11px;color:#92702a'>model region · hourly · 100 km</i><br/><span style='font-size:9.5px;color:#a88a4e;font-family:monospace'>build_transport_demand.py</span></div>"]:::aggstep
        REGISTER["<div style='padding:10px 18px'><b>Model-compatible Austrian regional register</b><br/><span style='font-size:12px'>= clean municipalities + attach final NUTS2 assignment</span><br/><i style='font-size:11px;color:#9d174d'>municipality · static · district/NUTS codes, population</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>build_statistik_at_regions.py</span></div>"]:::at
        ATCARS["<div style='padding:10px 18px'><b>Regional Austrian passenger-car stock</b><br/><span style='font-size:12px'>= redistribute special rows + population-weight registration districts</span><br/><i style='font-size:11px;color:#9d174d'>AT NUTS3/NUTS2 · annual · Pkw</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>build_kfz_bestand_at.py</span></div>"]:::at
        NEATARGET["<div style='padding:10px 18px'><b>NEA road-mobility targets</b><br/><span style='font-size:12px'>= selected energy × mean temperature-adjusted efficiency</span><br/><i style='font-size:11px;color:#9d174d'>AT NUTS2 · annual · 100 km</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>patch_transport_demand_at.py</span></div>"]:::at
        PATCH["<div style='padding:10px 18px'><b>Patched Austrian transport inputs</b><br/><span style='font-size:12px'>= replace regional Pkw stock + rescale demand to NEA totals</span><br/><i style='font-size:11px;color:#9d174d'>AT region · hourly 100 km + annual cars</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>build_kfz_bestand_at.py / patch_transport_demand_at.py</span></div>"]:::at
    end

    subgraph prepare["Prepare Sector Network"]
        CONFIG["<div style='padding:10px 18px'><b>Austrian drivetrain and EV settings</b><br/><span style='font-size:12px'>planning-year shares, efficiencies, charging, DSM, V2G</span><br/><i style='font-size:11px;color:#9d174d'>planning horizon · static scenario parameters</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>config.at.yaml</span></div>"]:::at
        DRIVETRAINS["<div style='padding:10px 18px'><b>Carrier-specific road demand</b><br/><span style='font-size:12px'>= common distance split into EV, fuel-cell, and ICE demand</span><br/><i style='font-size:11px;color:#0e6ba8'>node/carrier · hourly · electricity, H2, oil</i><br/><span style='font-size:9.5px;color:#5b9bd5;font-family:monospace'>prepare_sector_network.py</span></div>"]:::step
        FLEX["<div style='padding:10px 18px'><b>EV charging and storage constraints</b><br/><span style='font-size:12px'>📍 cars × electric share; availability, charger, DSM, V2G</span><br/><i style='font-size:11px;color:#92702a'>node · hourly · MW and MWh</i><br/><span style='font-size:9.5px;color:#a88a4e;font-family:monospace'>prepare_sector_network.py (add_EVs)</span></div>"]:::aggstep
    end

    subgraph solve["Solve"]
        FINAL(["<div style='padding:12px 26px'><b>Final road-mobility model</b><br/><span style='font-size:12px'>solved sector-coupled network</span><br/><i style='font-size:11px;color:#047857'>node/carrier · hourly · Loads, Links, Stores</i></div>"]):::final
    end

    SHARED --> ANNUAL
    ANNUAL --> BASE
    MOBILITY --> BASE
    REGIONS --> REGISTER
    KFZ --> ATCARS
    REGISTER --> ATCARS
    NEA --> NEATARGET
    MOBILITY --> NEATARGET
    ANNUAL --> PATCH
    BASE --> PATCH
    ATCARS --> BASE
    NEATARGET --> PATCH
    PATCH --> DRIVETRAINS
    PATCH --> FLEX
    MOBILITY --> FLEX
    CONFIG --> DRIVETRAINS
    CONFIG --> FLEX
    DRIVETRAINS --> FINAL
    FLEX --> FINAL
```

## AT-Specific Processing

- **Regional reference data.** The Statistik Austria municipality workbook is read from
  the `Gemeinden` sheet, forward-filled, restricted to valid municipality records, and
  renamed to machine-readable columns. The final NUTS3 shapes supply the model-compatible
  NUTS2 assignment. Missing NUTS2 mappings stop the build rather than silently dropping
  municipalities.
- **Vehicle-stock preparation.** The district-level Kfz workbook is cleaned by removing
  source notes and national or Bundesland totals and by converting `-` entries to zero.
  Vehicles reported for `Post`, `Bahn`, and
  `Polizei, Justizwache, Finanzverwaltung` are redistributed proportionally across the
  geographic registration districts, separately for each vehicle category.
- **Registration-district mapping.** Municipality records are translated to vehicle
  registration names, including special handling for Eisenstadt/Rust, Klosterneuburg,
  Schwechat, Leoben, Gröbming, and the Bad Aussee municipalities. Population then defines
  weights from each registration district to NUTS3 model regions, or to NUTS2 regions when
  the clustering name starts with `AT10`.
- **Passenger-car override.** Weighted district stocks are aggregated by model region and
  merged into the shared transport table for the configured energy-totals year. The
  downstream Austrian override uses `Pkw`; the other vehicle categories remain available
  during source processing but do not determine EV charger or battery sizing.
- **NEA calibration.** The NEA source year configured for the base year 2025 is used,
  restricted to `Sonstiger Landverkehr` and the useful-energy category `Verkehr`, and
  converted from TWh to MWh. Electricity is mapped to BEV demand; petrol, diesel, gas,
  LPG, and biogenic fuels are mapped to ICE demand. No NEA carrier is currently mapped to
  fuel-cell vehicles.
- **Conversion to driven distance.** For ICE and BEV technologies, temperature-adjusted
  efficiencies are averaged by NUTS2 across model nodes and snapshots. Multiplying the
  selected NEA energy by these conversion factors produces a NUTS2 target in units of
  100 km.
- **Demand application.** Each NUTS2 target rescales the shared hourly demand of all model
  regions in that NUTS2 area. This preserves the baseline spatial shares and hourly shape
  while replacing the Austrian total. Regions without a matching NEA target remain
  unchanged.

## Network Interpretation

- The final network still uses one common driven-distance profile split by exogenous EV,
  fuel-cell, and ICE shares. The Austrian patches improve regional totals and passenger-car
  counts but do not create separate passenger-car, truck, bus, or motorcycle fleets.
- Regional passenger-car counts affect EV charger power and, when enabled, EV storage
  capacity. The `pkw` mobility profile controls charger availability, while the broader
  `kfz` profile shapes transport demand.
- The shared transport-demand basis can include non-electric rail energy in addition to
  road energy. The Austrian NEA patch replaces matching NUTS2 totals with the selected
  `Sonstiger Landverkehr` records, so the patched Austrian portion should be interpreted
  according to that NEA category.
