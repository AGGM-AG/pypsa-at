# How to Run Evaluations

This guide shows you how to execute evaluations on PyPSA-AT model results using the command-line interface. Evaluations transform raw network outputs into analysis views, visualizations, and export formats for further analysis.

## Prerequisites

Before running evaluations, ensure you have:

- Completed model runs with results in your `results/` directory
- Activated your PyPSA-AT environment (via `pixi shell` or conda/mamba)
- Network files available in the expected subdirectory structure

## Basic Usage

### Run All Available Evaluations

To execute all evaluation functions on your results:
```bash
run_eval "/path/to/results/scenario_name"
```

Example with a typical PyPSA-AT results structure:
```bash
run_eval "results/v2025.02/KN2045_Mix"
```

This command will:
1. Discover all network files in the `networks/` subdirectory
2. Execute every evaluation function defined in `evals.views.__all__`
3. Generate outputs (views, plots, exports) in the results directory
4. Report execution time and any failures

### Run Specific Evaluations

To run only particular evaluation functions, use the `-n` option:

```bash
# Single evaluation
run_eval "results/v2025.02/KN2045_Mix" -n "view_balance_electricity"

# Multiple evaluations
run_eval "results/v2025.02/KN2045_Mix" -n "view_balance_electricity" -n "view_grid_capacity"
```

Available evaluation functions include:
- **Demand views**: `view_demand_heat`, `view_final_energy_demand`
- **Capacity views**: `view_capacity_electricity_production`, `view_capacity_gas_storage`
- **Balance views**: `view_balance_electricity`, `view_balance_hydrogen`, `view_balance_heat`
- **Time series views**: `view_timeseries_electricity`, `view_timeseries_carbon`
- **Grid views**: `view_grid_capacity`
- **Flow diagrams**: `view_sankey`

## Advanced Options

### Custom Subdirectory

If your network files are in a different subdirectory than the default `networks/`:

```bash
run_eval "results/v2025.02/KN2045_Mix" -s "custom_networks"
```

### Configuration Override

Override default evaluation configurations using a custom TOML file:

```bash
run_eval "results/v2025.02/KN2045_Mix" -c "custom_config.toml"
```

The configuration file should match the structure of `config.defaults.toml` and can override:
- Plot styling and colors
- Output file naming conventions
- Data aggregation parameters
- Export formats

### Fail-Fast Mode

To stop execution immediately when an evaluation fails:

```bash
run_eval "results/v2025.02/KN2045_Mix" -f true
```

By default, evaluations continue running even if individual functions fail, allowing you to see results from successful evaluations.

## Running Without Installation

For development or testing, run evaluations directly from the project root without installing the package:

```bash
PYTHONPATH="./" python evals/cli.py "results/v2025.02/KN2045_Mix" -n "view_balance_heat"
```

This approach requires:
- Your virtual environment to be activated
- Running from the PyPSA-AT project root directory
- Setting `PYTHONPATH` to include the current directory

## Common Tasks

### Generate All Capacity Views
```bash
run_eval "results/scenario" \
  -n "view_capacity_electricity_production" \
  -n "view_capacity_electricity_storage" \
  -n "view_capacity_gas_production" \
  -n "view_capacity_gas_storage" \
  -n "view_capacity_heat_demand" \
  -n "view_capacity_hydrogen_production"
```

### Create Energy Balance Analysis
```bash
run_eval "results/scenario" \
  -n "view_balance_electricity" \
  -n "view_balance_heat" \
  -n "view_balance_hydrogen" \
  -n "view_balance_carbon"
```

### Generate Time Series Analysis
```bash
run_eval "results/scenario" \
  -n "view_timeseries_electricity" \
  -n "view_timeseries_hydrogen" \
  -n "view_timeseries_carbon"
```

### Quick Single Evaluation Test
```bash
run_eval "results/test_scenario" -n "view_sankey" -f true
```

## Troubleshooting

### Missing Network Files
**Problem**: `FileNotFoundError` when accessing networks
**Solution**: Verify that:
- The results path exists and contains the expected subdirectory
- Network files (`.nc` format) are present in the subdirectory
- File permissions allow reading

### Memory Issues
**Problem**: Evaluations fail with memory errors on large models
**Solution**:
- Run evaluations on a subset using `-n` options
- Consider running on a machine with more RAM
- Check if intermediate files can be cleaned up

### Configuration Errors
**Problem**: Evaluation fails with configuration-related errors
**Solution**:
- Check that any custom configuration file follows the expected TOML structure
- Verify that the configuration file path is correct
- Try running without configuration override to test with defaults

### Failed Evaluations
**Problem**: Some evaluations fail while others succeed
**Solution**:
- Review the specific error messages in the log output
- Check if the failing evaluation requires specific network components
- Verify that the model results contain the expected data structures

## Output Files

Evaluations generate various output types:

- **CSV files**: Data views exported for spreadsheet analysis
- **HTML files**: Interactive Plotly visualizations
- **Excel files**: Formatted reports with multiple sheets
- **JSON files**: Configuration and metadata

All outputs are placed in the results directory, typically organized by evaluation type and scenario.

## Performance Tips

1. **Selective execution**: Use `-n` to run only needed evaluations
2. **Parallel processing**: The CLI automatically handles parallel processing where possible
3. **Resource cleanup**: Large evaluations may benefit from clearing temporary files between runs
4. **Development workflow**: Use the PYTHONPATH approach for rapid iteration during development