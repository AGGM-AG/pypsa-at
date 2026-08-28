# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Retrieve the E-Control Anlagenregister (https://anlagenregister.at) as one CSV.

The website is a Knockout.js single page application. The "Export as Excel"
button exports the grid *client-side*, so there is no Excel download endpoint.
The grid itself is filled by a JSON POST to
``/Home/SearchAnlagenregisterUebersicht`` with the search form values
(``Anlagentyp``: 1 = Strom, 2 = Gas; ``Bundesland``: one of nine codes).
Strom results are large (several hundred thousand plants) and are fetched per
Bundesland; the few dozen Gas plants are fetched with one query for all of
Austria (empty ``Bundesland``). The 9 + 1 = 10 results are concatenated into
one plant-level CSV.

The feed-in columns are labelled ``Jahressumme_Minus_{1..6}`` by the API and
are relative to a reference year that is only known from the landing page
(``sum2021Strom: "..." + " " + 2026``). The reference year is parsed from the
landing page so the columns can be renamed to absolute years.

Notes
-----
``Inbetriebnahme`` (commissioning date) is part of the API response but is
``null`` for every row as of 2026-08. It is kept in the output so that it is
picked up automatically should E-Control start publishing it.
"""

import logging
import re
import time

import pandas as pd
import requests
from snakemake.script import Snakemake

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

ANLAGENTYP = {"Strom": 1, "Gas": 2}

# Keys of the Bundesland drop-down on anlagenregister.at
BUNDESLAND_CODES = {
    "B": "Burgenland",
    "K": "Kaernten",
    "NO": "Niederoesterreich",
    "OO": "Oberoesterreich",
    "S": "Salzburg",
    "ST": "Steiermark",
    "T": "Tirol",
    "V": "Vorarlberg",
    "W": "Wien",
}

# Bundesland filters per Anlagentyp; "" = all of Austria in one query.
QUERIES = {"Strom": list(BUNDESLAND_CODES), "Gas": [""]}

SEARCH_PATH = "/Home/SearchAnlagenregisterUebersicht"

# Columns as returned by the API, in output order. ``Jahressumme_Minus_*`` are
# renamed to absolute years, see ``rename_feedin_columns``.
RAW_COLUMNS = [
    "ID",
    "AnlPlz",
    "AnlOrt",
    "Bundesland",
    "TechCode",
    "Energietraeger",
    "Inbetriebnahme",
    "Engpassleistung",
    "Jahressumme_Minus_1",
    "Jahressumme_Minus_2",
    "Jahressumme_Minus_3",
    "Jahressumme_Minus_4",
    "Jahressumme_Minus_5",
    "Jahressumme_Minus_6",
]

OUTPUT_COLUMNS = {
    "ID": "id",
    "AnlPlz": "plz",
    "AnlOrt": "ort",
    "Bundesland": "bundesland",
    "TechCode": "techcode",
    "Energietraeger": "energietraeger",
    "Inbetriebnahme": "inbetriebnahme",
    "Engpassleistung": "engpassleistung_kw",
}

REFERENCE_YEAR_PATTERN = re.compile(
    r'sum2021Strom:\s*"[^"]*"\s*\+\s*" "\s*\+\s*(\d{4})'
)

# =============================================================================
# Functions
# =============================================================================


def parse_reference_year(landing_page: str) -> int:
    """
    Extract the reference year for ``Jahressumme_Minus_1`` from the landing page.

    Parameters
    ----------
    landing_page
        HTML of https://anlagenregister.at.

    Returns
    -------
    The calendar year that ``Jahressumme_Minus_1`` refers to.

    Raises
    ------
    ValueError
        If the year cannot be found; the site layout has changed then.
    """
    match = REFERENCE_YEAR_PATTERN.search(landing_page)
    if match is None:
        raise ValueError(
            "Could not find the reference year for the feed-in columns on the "
            "anlagenregister.at landing page. Has the website changed?"
        )
    return int(match.group(1))


def rename_feedin_columns(df: pd.DataFrame, reference_year: int) -> pd.DataFrame:
    """
    Rename ``Jahressumme_Minus_{n}`` to ``feedin_kwh_{reference_year - n + 1}``.

    Parameters
    ----------
    df
        Plant table with API column names.
    reference_year
        Year that ``Jahressumme_Minus_1`` refers to.

    Returns
    -------
    Table with absolute feed-in year columns; all other columns renamed to
    ``OUTPUT_COLUMNS``.
    """
    feedin = {
        f"Jahressumme_Minus_{n}": f"feedin_kwh_{reference_year - n + 1}"
        for n in range(1, 7)
    }
    return df.rename(columns={**OUTPUT_COLUMNS, **feedin})


def fetch_search_result(
    session: requests.Session,
    base_url: str,
    anlagentyp: int,
    bundesland: str,
    timeout: float,
    retries: int,
) -> list[dict]:
    """
    Replay the search form submission for one Anlagentyp/Bundesland pair.

    Parameters
    ----------
    session
        Requests session (carries the ASP.NET session cookie).
    base_url
        Website root, e.g. ``https://anlagenregister.at``.
    anlagentyp
        1 for Strom, 2 for Gas.
    bundesland
        Bundesland drop-down key, e.g. ``"NO"``; ``""`` queries all of Austria.
    timeout
        Per-request timeout in seconds. Strom queries take up to a few minutes.
    retries
        Number of additional attempts on failure.

    Returns
    -------
    Rows of the ``Data`` list of the JSON response.

    Raises
    ------
    RuntimeError
        If the API reports ``Succeeded: false`` or all attempts fail.
    """
    payload = {
        "Anlagentyp": anlagentyp,
        "Bundesland": bundesland,
        "Energietraeger": "",
        "AnlagePlz": "",
        "AnlageOrt": "",
    }
    headers = {"X-Requested-With": "XMLHttpRequest", "_AppContext": "{}"}

    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            response = session.post(
                base_url + SEARCH_PATH, data=payload, headers=headers, timeout=timeout
            )
            response.raise_for_status()
            result = response.json()
            if not result.get("Succeeded", False):
                raise RuntimeError(
                    f"anlagenregister.at reported an error: {result.get('ErrorMessage')}"
                )
            return result["Data"]
        except (requests.RequestException, ValueError, RuntimeError) as e:
            last_error = e
            logger.warning(
                f"Attempt {attempt}/{retries + 1} for Anlagentyp={anlagentyp}, "
                f"Bundesland={bundesland} failed: {e}"
            )
            time.sleep(5 * attempt)

    raise RuntimeError(
        f"Failed to fetch Anlagentyp={anlagentyp}, Bundesland={bundesland} "
        f"after {retries + 1} attempts."
    ) from last_error


def rows_to_frame(rows: list[dict], typ: str, bundesland: str) -> pd.DataFrame:
    """
    Convert one API response into a table with ``typ``/``bundesland`` labels.

    Parameters
    ----------
    rows
        ``Data`` list of the JSON response.
    typ
        ``"Strom"`` or ``"Gas"``.
    bundesland
        Bundesland drop-down key that was queried; ``""`` keeps the
        ``Bundesland`` reported by the API for each row.

    Returns
    -------
    Table with ``RAW_COLUMNS`` plus a leading ``typ`` column. The API ``ID``
    restarts at 0 per query, so it is only unique in combination with
    ``typ`` and the queried ``bundesland``.
    """
    df = pd.DataFrame(rows, columns=RAW_COLUMNS)
    if bundesland:
        df["Bundesland"] = bundesland
    df.insert(0, "typ", typ)
    return df


def retrieve_anlagenregister(
    base_url: str, timeout: float, retries: int, pause: float
) -> pd.DataFrame:
    """
    Download all ``QUERIES`` into one table.

    Parameters
    ----------
    base_url
        Website root.
    timeout
        Per-request timeout in seconds.
    retries
        Additional attempts per request.
    pause
        Seconds to wait between requests to be polite to the server.

    Returns
    -------
    Plant-level table with absolute feed-in year columns.
    """
    session = requests.Session()
    landing = session.get(base_url, timeout=60)
    landing.raise_for_status()
    reference_year = parse_reference_year(landing.text)
    logger.info(f"Feed-in reference year on anlagenregister.at: {reference_year}")

    frames = []
    for typ, codes in QUERIES.items():
        for code in codes:
            name = BUNDESLAND_CODES.get(code, "all")
            start = time.perf_counter()
            rows = fetch_search_result(
                session, base_url, ANLAGENTYP[typ], code, timeout, retries
            )
            logger.info(
                f"{typ}/{name}: {len(rows)} plants in "
                f"{time.perf_counter() - start:.0f} s"
            )
            frames.append(rows_to_frame(rows, typ, code))
            time.sleep(pause)

    df = pd.concat(frames, ignore_index=True)
    df = rename_feedin_columns(df, reference_year)
    df.insert(0, "reference_year", reference_year)
    return df


def main(snakemake: Snakemake) -> None:
    """Retrieve the Anlagenregister and write the plant-level CSV."""
    df = retrieve_anlagenregister(
        base_url=snakemake.params.base_url,
        timeout=snakemake.params.timeout,
        retries=snakemake.params.retries,
        pause=snakemake.params.pause,
    )
    df.to_csv(snakemake.output.plants, index=False)
    logger.info(
        f"Wrote {len(df)} Anlagenregister plants "
        f"({df['engpassleistung_kw'].sum() / 1e6:.2f} GW) to {snakemake.output.plants}"
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("retrieve_anlagenregister_at")

    configure_logging(snakemake)
    main(snakemake)
