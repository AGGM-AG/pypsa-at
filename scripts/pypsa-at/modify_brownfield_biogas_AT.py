# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Modify the powerplantmatching results for Austrian brownfield of biogas plants."""

import logging

import pandas as pd

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)


def assign_nuts3_to_postal_at(ppl):
    postal_to_nuts_at = (
        pd.read_csv(
            "AT-Postal-to-NUTS.csv",
            sep=";",
            dtype=str,
            names=["nuts3", "plz"],
            header=0,
        )
        .assign(
            plz=lambda x: x["plz"].str.strip("'"),
            nuts3=lambda x: x["nuts3"].str.strip("'"),
        )
        .set_index("plz")["nuts3"]
    )

    ppl = ppl.dropna(subset=["Plz"])
    ppl["Plz"] = ppl["Plz"].astype("Int64").astype(str).str.zfill(4)

    ppl["nuts3"] = ppl["Plz"].map(postal_to_nuts_at)

    cols = ["ID", "Plz", "nuts3"] + [
        c for c in ppl.columns if c not in {"ID", "Plz", "nuts3"}
    ]
    ppl = ppl[cols]

    return ppl


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
