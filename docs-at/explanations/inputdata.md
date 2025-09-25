# Input Data Management

## Concept #1

Input data is organized in a common format. The data model of choice is the Integrated Assessment Model Consortiums (*
*IAMC**) Python implementation [pyam](https://pyam-iamc.readthedocs.io/en/stable/index.html).

| Model                              | Scenario    | Region | Variable                         | Unit    | 2025 | 2030 | 2040 | 2045 | 2050 |
|------------------------------------|-------------|--------|----------------------------------|---------|------|------|------|------|------|
| Publication Name, Paper, or Source | AT10_KN2040 | AT111  | Potential\|UV-Rooftop\|technical | GW_peak | 1    | 2    | 3    | 4    | 5    |

the model field is repurposed to contain the name of the data source. The Scenario contains the PyPSA-AT target scenario.

Pros
* database-like file collects all model inputs in a common format 
* metadata can be used for a mapping of model to full publication detail
* compatible with relational DB 

Cons
* might bloat for multiple scenarios 
* versioning unsolved 
* transformation step required from raw data file to pyam

## Concept #2 

input data is organized in data folder and per input category, e.g. PV potentials, etc.
