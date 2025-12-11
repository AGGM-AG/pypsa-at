# Carbon Dioxide Emission Tracking and Constraints in PyPSA-AT

PyPSA-AT implements multiple layers of CO2 tracking and constraints to model emission reduction pathways and climate policy targets. This document explains how emissions are tracked and how different constraints control the energy system's carbon footprint.

## CO2 Emission Accounting Architecture

PyPSA-AT uses two main types of CO2 constraints, each serving different modeling purposes:

### 1. National CO2 Budgets

National CO2 budgets allow **country-specific emission limits**, enabling differentiated emission reduction pathways for each country to account for country-specific climate targets (e.g., Austria's path to climate neutrality by 2040).
This feature was added in PyPSA-AT and consists of a reduced version of the PyPSA-DE function. 

```yaml
solving:
  constraints:
      co2_budget_national:
        AT:
          2020: 1.00  # 100% of 1990 levels
          2030: 0.64  # 64% of 1990 levels
          2040: 0.12  # 12% of 1990 levels
          2050: 0.00  # Net-zero
```

#### Regional Emission Tracking

- Emissions from fuels are balanced in the region where a technology causes the emission
- E-Fuels vs. Fossil Fuels: Whether E-Fuels (biomethane, synthetic oil, green methanol, etc.) or fossil fuels are burned does not make a difference in emission accounting. All emissions are booked where combustion occurs.
- Negative emissions from Carbon Capture technologies, Direct Air Capture (DAC), or CCU (e.g., bio-methanol production) are accounted for in the respective technology region
- ETS trade (Emission Trading System) is NOT explicitly modeled
- A constraint ensures that total emissions from all regions in a country are below a respective threshold (the national CO2 budget) 

#### Implications

- One country may not produce E-Fuels to compensate for emissions in another country
- In contrast, it is possible for a region to compensate for emissions in another region of the same country, because the constraint works on a per-country level. 
- It is assumed that all certificates resulting from E-Fuel generation are traded within the same country (not region!)
- CO2 deductions from CO2 buses by CCU technologies always count as negative emissions in the country where they occur
- It is possible for a country to transform imported CO2 into E-Fuels (e.g. synthetic oil) and export them to create a negative balance


**How it works**

1. Identifies all links connecting to `co2 atmosphere` bus for a given country
2. Accounts for emissions across all bus ports (bus0, bus1, bus2, etc.) for those links
3. Scales aviation emissions by domestic-to-total ratio calculated from respective model values to exclude international aviation
4. Creates a country-specific constraint: `Σ(emissions) ≤ country_budget`

✅ **Included**

- All technology emissions in the country (combustion, industrial processes)
- Negative emissions from CCU, CCS, and DAC in the country
- Emissions from domestic aviation
- All energy sectors: electricity, heating, transport, industry
- All emissions from navigation (domestic and international)

❌ **Excluded**

- International aviation

**Key differences from PyPSA-DE**

- Simpler emission tracking: does not distinguish E-Fuels and fossil fuels

### 2. Global CO2 Limit (PyPSA-EUR default)

The `CO2Limit` constraint caps total system-wide emissions based on historical baseline years (typically 1990) to account for European emission reduction targets (e.g., "reduce emissions to 55% of 1990 levels by 2030").
This is the standard PyPSA-EUR emission tracking controlled in the `config.yaml`:

```yaml
electricity:
  co2limit_enable: true  # Enable/disable the constraint
  co2limit: 7.75e+7      # Absolute limit in tonnes CO2 (if used)
```
