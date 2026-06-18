# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Modify the powerplantmatching results for Austrian brownfield of biogas plants."""

import logging

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)


def modify_brownfield_biogas_AT():
    print("meow")
    pass


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "modify_brownfield_biogas_AT",
            simpl="",
            clusters="adm",
            opts="",
            ll="v1.25",
            sector_opts="none",
            run="AT_KN2040",
        )

    configure_logging(snakemake)
    config = snakemake.config

    modify_brownfield_biogas_AT()
