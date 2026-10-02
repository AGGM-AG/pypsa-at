# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for the custom cost file builder script."""

import pandas as pd
import pytest
from build_custom_cost_at import main

from scripts._helpers import mock_snakemake


def test_combine_two_files_with_overlapping_entries_keeps_first(tmp_path):
    """
    Test that combining two CSV files retains the first file's values for
    duplicate index entries and discards the second file's values.

    This verifies the core behavior: earlier files have priority.
    """
    # Create first CSV with entries for solar and wind.
    csv1_path = tmp_path / "costs_1.csv"
    csv1_data = pd.DataFrame(
        {
            "planning_horizon": [2030, 2030, 2050],
            "technology": ["solar", "wind", "solar"],
            "parameter": ["capital_cost", "capital_cost", "capital_cost"],
            "value": [100.0, 200.0, 80.0],
        }
    )
    csv1_data.to_csv(csv1_path, index=False)

    # Create second CSV with overlapping and new entries.
    # Overlapping: (2030, solar, capital_cost) and (2050, solar, capital_cost)
    # New: (2040, wind, capital_cost)
    csv2_path = tmp_path / "costs_2.csv"
    csv2_data = pd.DataFrame(
        {
            "planning_horizon": [2030, 2050, 2040],
            "technology": ["solar", "solar", "wind"],
            "parameter": ["capital_cost", "capital_cost", "capital_cost"],
            "value": [999.0, 888.0, 300.0],  # Different values for duplicates
        }
    )
    csv2_data.to_csv(csv2_path, index=False)

    # Create output path
    output_path = tmp_path / "combined.csv"

    # Create mock Snakemake object
    snakemake = mock_snakemake("build_custom_cost_at", run="AT_KN2040")
    snakemake.input.custom_cost_files = [str(csv1_path), str(csv2_path)]
    snakemake.output.custom_cost_fn = str(output_path)

    # Call the actual function
    main(snakemake)

    # Read and verify output
    result = pd.read_csv(output_path, index_col=[0, 1, 2])

    # Verify no duplicates in the result.
    assert result.index.is_unique, "Result should have no duplicate indices"

    # Verify the result has 4 entries: 3 from file 1, 1 new from file 2.
    assert len(result) == 4, f"Expected 4 entries, got {len(result)}"

    # Verify first file's values are retained for overlapping entries.
    # (2030, solar, capital_cost) should be 100.0, not 999.0
    assert result.loc[(2030, "solar", "capital_cost"), "value"] == 100.0
    # (2050, solar, capital_cost) should be 80.0, not 888.0
    assert result.loc[(2050, "solar", "capital_cost"), "value"] == 80.0

    # Verify unique entries from both files are present.
    # (2030, wind, capital_cost) from file 1
    assert result.loc[(2030, "wind", "capital_cost"), "value"] == 200.0
    # (2040, wind, capital_cost) from file 2 (no overlap)
    assert result.loc[(2040, "wind", "capital_cost"), "value"] == 300.0


def test_duplicate_within_single_file_keeps_first_occurrence(tmp_path):
    """
    Test that duplicates within a single file are handled correctly:
    only the first occurrence is retained.
    """
    # Create a CSV with duplicate entries (same index, different values).
    csv_path = tmp_path / "costs_duplicates.csv"
    csv_data = pd.DataFrame(
        {
            "planning_horizon": [2030, 2030, 2030],
            "technology": ["solar", "solar", "wind"],
            "parameter": ["capital_cost", "capital_cost", "capital_cost"],
            "value": [100.0, 200.0, 300.0],
        }
    )
    csv_data.to_csv(csv_path, index=False)

    # Create output path
    output_path = tmp_path / "deduplicated.csv"

    # Create mock Snakemake object
    snakemake = mock_snakemake("build_custom_cost_at", run="AT_KN2040")
    snakemake.input.custom_cost_files = [str(csv_path)]
    snakemake.output.custom_cost_fn = str(output_path)

    # Call the actual function
    main(snakemake)

    # Read and verify output
    result = pd.read_csv(output_path, index_col=[0, 1, 2])

    # Verify only 2 entries: first solar (100.0) and wind (300.0).
    assert len(result) == 2
    assert result.loc[(2030, "solar", "capital_cost"), "value"] == 100.0
    assert result.loc[(2030, "wind", "capital_cost"), "value"] == 300.0


def test_multiple_cost_columns_preserved(tmp_path):
    """
    Test that all columns beyond the index are preserved during combination.
    """
    # Create CSV with multiple cost-related columns.
    csv_path = tmp_path / "costs_multi.csv"
    csv_data = pd.DataFrame(
        {
            "planning_horizon": [2030, 2050],
            "technology": ["solar", "wind"],
            "parameter": ["capital_cost", "capital_cost"],
            "value": [100.0, 200.0],
            "unit": ["EUR/kW", "EUR/kW"],
            "source": ["DEA 2024", "DEA 2024"],
        }
    )
    csv_data.to_csv(csv_path, index=False)

    # Create output path
    output_path = tmp_path / "output.csv"

    # Create mock Snakemake object
    snakemake = mock_snakemake("build_custom_cost_at", run="AT_KN2040")
    snakemake.input.custom_cost_files = [str(csv_path)]
    snakemake.output.custom_cost_fn = str(output_path)

    # Call the actual function
    main(snakemake)

    # Read and verify output
    result = pd.read_csv(output_path, index_col=[0, 1, 2])

    # Verify that non-index columns are preserved.
    assert set(result.columns) == {"value", "unit", "source"}
    assert result.loc[(2030, "solar", "capital_cost"), "unit"] == "EUR/kW"
    assert result.loc[(2030, "solar", "capital_cost"), "source"] == "DEA 2024"


def test_empty_file_list_raises_error(tmp_path):
    """
    Test that an empty file list raises ValueError.

    In practice, Snakemake ensures at least one input file, so this
    behavior is documented but not expected to occur in normal operation.
    """
    # Create output path
    output_path = tmp_path / "output.csv"

    # Create mock Snakemake object with empty input list
    snakemake = mock_snakemake("build_custom_cost_at", run="AT_KN2040")
    snakemake.input.custom_cost_files = []
    snakemake.output.custom_cost_fn = str(output_path)

    # Calling main with empty file list raises ValueError from pd.concat
    with pytest.raises(ValueError, match="No objects to concatenate"):
        main(snakemake)
