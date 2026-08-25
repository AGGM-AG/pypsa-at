# Industrial Demand

This diagram traces the generic industrial-demand build and the Austrian regional NEA (Nutzenergieanalyse)
override to the final network Loads. Violet nodes are Austrian-specific. See [Data Flow
Diagrams](index.md) for the shared diagram convention.

```mermaid
flowchart TD
    classDef source fill:#f8fafc,stroke:#cbd5e1,stroke-width:1px,color:#1e293b,rx:10,ry:10
    classDef step fill:#f0f9ff,stroke:#7dd3fc,stroke-width:1px,color:#0c4a6e,rx:10,ry:10
    classDef aggstep fill:#fffbeb,stroke:#fcd34d,stroke-width:1px,color:#78350f,rx:10,ry:10
    classDef final fill:#ecfdf5,stroke:#6ee7b7,stroke-width:1.5px,color:#064e3b,rx:10,ry:10
    classDef at fill:#fdf2f8,stroke:#f9a8d4,stroke-width:1.5px,color:#831843,rx:10,ry:10

    subgraph retrieve["Retrieve"]
        INDUSTRYDATA(["<div style='padding:12px 26px'><b>JRC-IDEES / Eurostat / ammonia</b><br/><span style='font-size:12px'>production and energy-balance inputs</span><br/><i style='font-size:11px;color:#64748b'>country · annual · reference year</i><br/><span style='font-size:9.5px;color:#94a3b8;font-family:monospace'>retrieve_jrc_idees</span></div>"]):::source
        SITES(["<div style='padding:12px 26px'><b>Industrial sites and population</b><br/><span style='font-size:12px'>Hotmaps, GEM, refineries, ammonia plants</span><br/><i style='font-size:11px;color:#64748b'>site/node · static</i><br/><span style='font-size:9.5px;color:#94a3b8;font-family:monospace'>retrieve_hotmaps_industrial_sites</span></div>"]):::source
        NEA(["<div style='padding:12px 26px'><b>Statistik Austria NEA</b><br/><span style='font-size:12px'>one ODS workbook per Bundesland</span><br/><i style='font-size:11px;color:#9d174d'>Bundesland · annual · TJ</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>retrieve_nea_at</span></div>"]):::at
        FFE(["<div style='padding:12px 26px'><b>FfE industry profiles</b><br/><span style='font-size:12px'>normalized electricity load shapes</span><br/><i style='font-size:11px;color:#9d174d'>sector · hourly · reference year 2017</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>retrieve_ffe_industry_load_profiles</span></div>"]):::at
    end

    subgraph build["Build Sector"]
        PROD["<div style='padding:10px 18px'><b>Production per country and target year</b><br/><span style='font-size:12px'>= historical production + scenario projections</span><br/><i style='font-size:11px;color:#92702a'>country · annual · kt/a</i><br/><span style='font-size:9.5px;color:#a88a4e;font-family:monospace'>build_industrial_production_per_country(_tomorrow).py</span></div>"]:::aggstep
        KEY["<div style='padding:10px 18px'><b>Industrial distribution keys</b><br/><span style='font-size:12px'>= site/plant activity, population fallback</span><br/><i style='font-size:11px;color:#92702a'>node · static shares</i><br/><span style='font-size:9.5px;color:#a88a4e;font-family:monospace'>build_industrial_distribution_key.py</span></div>"]:::aggstep
        NODEPROD["<div style='padding:10px 18px'><b>Production per model region</b><br/><span style='font-size:12px'>= country production × sector key</span><br/><i style='font-size:11px;color:#0e6ba8'>node · annual · kt/a</i><br/><span style='font-size:9.5px;color:#5b9bd5;font-family:monospace'>build_industrial_production_per_node.py</span></div>"]:::step
        RATIOS["<div style='padding:10px 18px'><b>Sector/carrier ratios</b><br/><span style='font-size:12px'>= energy use per unit of production</span><br/><i style='font-size:11px;color:#92702a'>country · static ratios · TWh/t</i><br/><span style='font-size:9.5px;color:#a88a4e;font-family:monospace'>build_industry_sector_ratios(_intermediate).py</span></div>"]:::aggstep
        NODEDEM["<div style='padding:10px 18px'><b>Energy demand per model region</b><br/><span style='font-size:12px'>= production × sector/carrier ratios</span><br/><i style='font-size:11px;color:#0e6ba8'>node · annual · TWh/a by carrier</i><br/><span style='font-size:9.5px;color:#5b9bd5;font-family:monospace'>build_industrial_energy_demand_per_node.py</span></div>"]:::step
        NEATABLE["<div style='padding:10px 18px'><b>Prepared NEA data</b><br/><span style='font-size:12px'>= clean ODS, reshape, convert TJ → TWh</span><br/><i style='font-size:11px;color:#9d174d'>NUTS2 · annual · sector/carrier</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>build_nea_at.py</span></div>"]:::at
        NEAREG["<div style='padding:10px 18px'><b>Regional NEA demand overrides</b><br/><span style='font-size:12px'>= Bundesland totals × regional keys</span><br/><i style='font-size:11px;color:#9d174d'>AT model region · annual · TWh/a</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>build_nea_industry_demand.py</span></div>"]:::at
        FFEBUILD["<div style='padding:10px 18px'><b>Nodal FfE electricity profiles</b><br/><span style='font-size:12px'>= subsector mix × normalized FfE shapes</span><br/><i style='font-size:11px;color:#9d174d'>AT node · hourly · normalized</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>build_industrial_demand_profiles.py</span></div>"]:::at
        LOADS["<div style='padding:10px 18px'><b>Initial industry Loads</b><br/><span style='font-size:12px'>= annual demand divided into flat power</span><br/><i style='font-size:11px;color:#0e6ba8'>node/carrier · static · MW</i><br/><span style='font-size:9.5px;color:#5b9bd5;font-family:monospace'>prepare_sector_network.py (add_industry)</span></div>"]:::step
    end

    subgraph prepare["Prepare Sector Network (AT)"]
        OVERRIDE["<div style='padding:10px 18px'><b>Apply annual regional overrides</b><br/><span style='font-size:12px'>= map carriers and replace target-year totals</span><br/><i style='font-size:11px;color:#9d174d'>AT region/carrier · annual · TWh/a</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>mods/demand/annual.py</span></div>"]:::at
        PROFILE["<div style='padding:10px 18px'><b>Apply FfE electricity profiles</b><br/><span style='font-size:12px'>= scale Loads while preserving annual energy</span><br/><i style='font-size:11px;color:#9d174d'>AT node · hourly · industry electricity</i><br/><span style='font-size:9.5px;color:#be185d;font-family:monospace'>mods/demand/industrial_demand.py</span></div>"]:::at
    end

    subgraph solve["Solve"]
        FINAL(["<div style='padding:12px 26px'><b>Final industrial demand</b><br/><span style='font-size:12px'>solved sector-coupled network</span><br/><i style='font-size:11px;color:#047857'>node/carrier · hourly or flat · MW</i></div>"]):::final
    end

    INDUSTRYDATA --> PROD
    INDUSTRYDATA --> RATIOS
    SITES --> KEY
    PROD --> NODEPROD
    KEY --> NODEPROD
    RATIOS --> NODEDEM
    NODEPROD --> NODEDEM
    NEA --> NEATABLE
    NEATABLE --> NEAREG
    KEY --> NEAREG
    NODEDEM --> LOADS
    LOADS --> OVERRIDE
    NEAREG --> OVERRIDE
    NODEPROD --> FFEBUILD
    RATIOS --> FFEBUILD
    FFE --> FFEBUILD
    FFEBUILD --> PROFILE
    OVERRIDE --> PROFILE
    PROFILE --> FINAL
```

## AT-Specific Processing

- **NEA preparation:** The Bundesland ODS files are cleaned, reshaped to long form, tagged
  with NUTS2 codes, and converted from TJ to TWh. The override currently selects the
  `Produzierender Bereich` category and maps NEA carriers to model Load carriers.
- **Regional allocation:** NEA totals are aggregated by Bundesland, sector, carrier, and
  selected distribution key. They are allocated to Austrian model regions using the matching
  industrial key, with population as fallback. `AT333` is assigned to parent NUTS2 region
  `AT33` for this allocation.
- **Load application:** For configured target years (currently 2025), regional annual totals
  replace matching industry Loads. Static Loads receive flat power; dynamic Loads are scaled
  to preserve their time shape and annual target.
- **Electricity profiles:** When enabled, FfE profiles are weighted by each region's
  subsector electricity mix and applied to `industry electricity`, preserving its annual
  energy while making it time-varying. Other industry carriers remain flat unless another
  profile is configured.
