# Run the model Workflow

This section describes how to run the model.

## Requirements

Running the model at high spatial and temporal resolution requires substantial resources.

| Clustering | Spatial Resolution (n) | Temporal Resolution (h) | Time to Solve (s) | Time to Solve (h) | RAM (GB) | 
|------------|------------------------|-------------------------|-------------------|-------------------|----------|
| AT10DE5    | 54                     |                         |                   |                   |
| AT10DE19   | 65                     | 365                     |                   |                   |          |
| AT10DE19   | 65                     | 120                     |                   |                   |          |
| AT10DE19   | 65                     | 24                      |                   |                   |          |
| AT10DE19   | 65                     | 3                       | 29520             | 8.2               | 120      |
| AT10DE19   | 65                     | 1                       | 197116            | 54.7              | 370      |
| AT35DE5    | 77                     | 24                      | 4318              | 1.2               | 25       |
| AT35DE5    | 77                     | 3                       | 32465             | 9.0               | 126      |
| AT35DE5    | 77                     | 1                       | 216975            | 60.0              | 450      |
| AT35DE19   | 91                     | 365                     |                   |                   |          |
| AT35DE19   | 91                     | 120                     |                   |                   |          |
| AT35DE19   | 91                     | 24                      |                   |                   |          |
| AT35DE19   | 91                     | 3                       |                   | 12.5              | 170      |
| AT35DE19   | 91                     | 1                       |                   |                   |          |

**Table 1:** Required time and memory per network for productive pypsa-at model runs. Values are given per network and for the largest network.

Benchmarks are for `INTEL(R) XEON(R) GOLD 6544Y` processor and using `threads: 8` with a gurobi solver and the default
gurobi solver settings from `config/config.default.yaml`.

Values in the benchmark are given for the longest runtime and highest memory usage for all networks in the myopic
workflow.

## Run the workflow from source

Log in to the server that should perform the model run. Then enter a tmux session:

```shell
tmux new -s pypsa-at-prod-run
```

Note that tmux sessions are separate per user. Chose a descriptive session name. Then, change directory to a directory
somewhere with at least 20GB of available disk space.

```shell
cd /mnt/storage/runs
```

Clone the repository in a new directory. It's recommended to name the directory after the tmux session.

```shell
git clone https://github.com/AGGM-AG/pypsa-at.git pypsa-at-prod-run 
cd pypsa-at-prod-run
```

Optionally, you may need to check out a specific branch of the repository. You are free to change the configuration at
this point

```shell
git checkout feature
```

With your virtual environment activated, build the scenario files and run the workflow:

```shell
snakemake build_scenarios -f --cores 'all'
snakemake -call all --cores 'all'
```

## Debugging

The simplest way to debug a model run is to connect your IDE via SSH to the server and use the builtin debugging
capabilities. Point your SSH connection to the folder where the repository was cloned and consult your IDEs debugging
docs for further instructions.
