# Regulatory Requirements

Austrian energy law imposes binding obligations on the energy system that go beyond generic
European targets. PyPSA-AT models these obligations as optimization constraints so that
solved scenarios are not just cost-optimal but also legally compliant.

## Overview

| Requirement | Legal basis | Constraint in PyPSA-AT | Active from |
|---|---|---|---|
| Net-zero electricity balance | EAG §4(2) | `add_national_net_zero_electricity_constraints` | 2030 |

## Design principle

Each regulatory constraint is implemented as a linear inequality over the linopy model
variables and registered in `n.global_constraints` for post-solve verification. Constraints
are activated per country and planning horizon via `config.at.yaml`, so they can be enabled
or disabled without touching the model code.

All constraints use **structural bus-carrier identification** — links are selected by the
carrier of the bus they connect to, not by hardcoded technology names. This makes the
constraints robust to additions of new carrier names in upstream PyPSA-Eur updates.
