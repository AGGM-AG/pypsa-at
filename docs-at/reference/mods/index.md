# PyPSA-AT application layer modifications

The `mods/` package collects Python modules containing functions that update, enhance, augment, patch, or overwrite parts of the Snakemake workflow. These modifications implement Austrian-specific adaptations to the PyPSA-Eur base model, and are called from Snakemake scripts at the appropriate workflow stage.

The package is organised by workflow phase:

- [clustering](clustering.md) — **build phase**: NUTS3 administrative clustering modifications
- [network](network/index.md) — **modify phase**: pre-network state modifications
    - [common](network/common.md) — cross-cutting helpers (resource meta attach, negative-load clipping)
    - [electricity](network/electricity.md) — TYNDP cross-border transmission lower bounds
    - [gas](network/gas.md) — gas import, production, transit, pipelines, and storage capacities
    - [h2](network/h2.md) — H2 for industry bus topology and methane pyrolysis plasma
    - [trajectories](network/trajectories.md) — TYNDP PEMMDB capacity trajectory overwrites
    - [potentials](network/potentials.md) — KLIEN regional capacity potential overwrites
- [constraints](constraints/index.md) — **solve phase**: custom linopy optimization constraints
    - [co2_budget](constraints/co2_budget.md) — national CO₂ budgets balanced at the `co2 atmosphere` bus
    - [eag](constraints/eag.md) — EAG §4(2) national net-zero electricity production stack
    - [tyndp](constraints/tyndp.md) — TYNDP NTC cross-border flows and solar utility trajectory bands
