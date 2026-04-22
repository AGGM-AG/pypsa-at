# PyPSA-AT application layer modifications

The `mods/` package collects Python modules containing functions that update, enhance, augment, patch, or overwrite parts of the Snakemake workflow. These modifications implement Austrian-specific adaptations to the PyPSA-Eur base model, and are called from Snakemake scripts (typically `scripts/pypsa-de/modify_prenetwork.py`) at the appropriate workflow stage.

- [clustering.py](clustering.md) — administrative clustering modifications
- [constraints.py](constraints.md) — custom optimization constraints
- [network_updates.py](network_updates.md) — transmission, demand, and import/export network updates
