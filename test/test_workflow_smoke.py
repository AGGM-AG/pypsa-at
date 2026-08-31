# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Smoke tests for the Snakemake DAG wiring via dry-runs."""

import re
import shutil
import subprocess
import textwrap

import pytest

pytestmark = pytest.mark.smoke


def scheduled_rules(*snakemake_args: str) -> set[str]:
    """
    Collect the scheduled rule names from a Snakemake dry-run.

    Parameters
    ----------
    *snakemake_args
        Extra command line arguments appended to the dry-run invocation.

    Returns
    -------
    :
        Names of all rules scheduled in the dry-run job table.
    """
    result = subprocess.run(
        ["snakemake", "--dry-run", "--quiet", "rules", *snakemake_args],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return {
        match.group(1)
        for line in result.stdout.splitlines()
        if (match := re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s+\d+$", line.strip()))
    }


@pytest.mark.skipif(
    shutil.which("snakemake") is None, reason="snakemake is not available"
)
@pytest.mark.parametrize("use_nea_demand", [True, False])
def test_transport_demand_override_follows_config(tmp_path, use_nea_demand):
    """The AT transport override must only be active with use_nea_demand."""
    override = tmp_path / "override.yaml"
    override.write_text(
        textwrap.dedent(
            f"""
            demand:
              transport:
                use_nea_demand: {str(use_nea_demand).lower()}
            """
        )
    )

    rules = scheduled_rules("--configfile", str(override))

    assert ("build_transport_demand_at" in rules) == use_nea_demand
    assert ("patch_transport_demand_at" in rules) == use_nea_demand
    assert ("build_transport_demand" in rules) == (not use_nea_demand)
