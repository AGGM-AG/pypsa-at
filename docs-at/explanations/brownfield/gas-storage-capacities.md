# Gas Storage Capacities

## Motivation

PyPSA-Eur builds gas `Store` components as fully extendable: the optimizer is free to choose
any storage volume and pays the associated capital cost. For underground gas storage this is
physically wrong. Salt caverns, depleted gas fields, and porous rock aquifers are tied to
specific geological formations that cannot be created elsewhere. Lead times for new sites are
10–20 years, so within any single planning horizon the installed storage capacity is
effectively fixed by what physically exists today.

Two further constraints reinforce the brownfield treatment:

- **Regulatory**: Austrian and German gas storage is operated under regulated third-party
  access regimes (GWG 2011, EU Gas Directive). Storage is not a freely investable commodity
  in the model's cost-minimisation sense.
- **Strategic reserve**: EU Regulation 2022/1032 mandates minimum fill levels for gas storage,
  reinforcing that storage is managed as strategic infrastructure rather than optimised on
  pure economics.

PyPSA-AT therefore replaces the upstream default with fixed, observed capacities and removes
the investment degree of freedom for gas stores.

## Data Sources

Capacities are compiled in `data/pypsa-at/gas_input_locations_s_AT35DE16_updated.csv`.
The file records working gas volume in GWh per region at AT NUTS3 / DE NUTS1 resolution.
Three sources are used depending on the region:

| Scope | Source | Notes |
|---|---|---|
| Austria (AT NUTS3) | Operator technical data sheets | Site-level working volumes reported by RAG, SEFE, UNIPER, and OMV; aggregated to NUTS3 by AGGM |
| Most EU countries | [Gas Infrastructure Europe – AGSI](https://agsi.gie.eu/) | Country-level working gas volume reported by storage operators; used for BE, BG, CZ, ES, FR, HR, HU, IE, IT, LV, NL, PL, PT, RO, RS, SE, SK |
| Germany (DE NUTS1) | [SciGRID_gas](https://zenodo.org/records/4767098) scaled to AGSI total | SciGRID provides the spatial distribution across NUTS1 states; the country total is scaled to match the AGSI reported figure |
| Great Britain, Greece | [SciGRID_gas](https://zenodo.org/records/4767098) | No AGSI breakdown available; SciGRID values used as-is |

### Austrian Storage Sites

The Austrian values are aggregated from individual underground storage sites.
Working gas volumes are in TWh.

| Operator | Site | NUTS3 | Working volume (TWh) | Source |
|---|---|---|---|---|
| RAG | Puchkirchen | AT315 | 13.4 | [RAG Leistungskennzahlen](https://www.rag-austria.at/rag-energiewelt/energie-speichern/leistungskennzahlen-der-speicher) |
| RAG | Nussdorf Zagling | AT315 | 6.3 | [RAG Leistungskennzahlen](https://www.rag-austria.at/rag-energiewelt/energie-speichern/leistungskennzahlen-der-speicher) |
| UNIPER | 7 Fields EGS | AT315 | 17.8 | [RAG Leistungskennzahlen](https://www.rag-austria.at/rag-energiewelt/energie-speichern/leistungskennzahlen-der-speicher) |
| RAG | Aigelsbrunn + Haidach 5 | AT311 | 1.684 | [RAG Leistungskennzahlen](https://www.rag-austria.at/rag-energiewelt/energie-speichern/leistungskennzahlen-der-speicher) |
| RAG | Haidach (RAG share) | AT311 | 14.8 | [RAG Leistungskennzahlen](https://www.rag-austria.at/rag-energiewelt/energie-speichern/leistungskennzahlen-der-speicher) |
| SEFE | Haidach (SEFE share) | AT311 | 19.5 | [RAG Leistungskennzahlen](https://www.rag-austria.at/rag-energiewelt/energie-speichern/leistungskennzahlen-der-speicher) |
| OMV | Schönkirchen + Tallesbrunn | AT126 | 26.771 | [OMV Online Capacity Booking](https://ocb-st.omv.com/ocb/app/) |

## Seasonal balancing

Gas storage is modelled with a cyclic boundary condition: the fill level at the end of the
year must equal the fill level at the beginning. The model is therefore free to choose how
full the stores are at any point in time, but must return them to the same state by year end —
consistent with how seasonal underground storage is operated in practice.
