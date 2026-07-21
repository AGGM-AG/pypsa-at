# SPDX-FileCopyrightText: Contributors to PyPSA-AT <https://github.com/AGGM-AG/pypsa-at>
#
# SPDX-License-Identifier: MIT

"""
Post-process the ``build_osm_network`` CSV outputs for the Austrian AT dataset.

This script applies AT-specific filtering to the network produced by the
PyPSA-Eur ``build_osm_network`` rule and writes a cleaned copy to
``resources/osm/build-at/``.

Operator and frequency recovery
-------------------------------
``clean_osm_data`` keeps only an allow-list of OSM tags and ``operator`` is not
on it, so the attribute never reaches ``resources/osm/build/``. It also
overwrites ``frequency``: invalid values become ``"50"`` and relation-derived
lines are forced to ``"50"``, which silently relabels 16.7 Hz railway traction
as ordinary 50 Hz.

Both are recovered here from the raw Overpass JSON, which ``retrieve_osm_data``
already stores and which carries the full tag set. Lines and buses gain three
columns:

``operator``
    The verbatim OSM value(s). Cleaned components are merged from several OSM
    objects, so disagreeing values are joined with `` | ``.
``operator_clean``
    ``operator`` mapped onto a canonical alias via :data:`OPERATOR_ALIASES`
    (e.g. every APG spelling becomes ``APG``). Unmatched values are passed
    through verbatim and logged, so nothing is lost silently.
``tag_frequency``
    The raw ``frequency`` tag before upstream normalisation, so 16.7 Hz
    traction stays identifiable downstream.

Precondition check
------------------
* Raises ``ValueError`` if 110 kV is not listed in
  ``config.electricity.voltages``, because building the AT OSM dataset only
  makes sense with the 110 kV level included.
"""

import json
import logging
import re
from csv import QUOTE_NONNUMERIC
from pathlib import Path

import pandas as pd

from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(Path(__file__).stem)

# Ordered ``(pattern, canonical name)`` pairs, matched case-insensitively
# against a single OSM ``operator`` value; the first hit wins. Order matters
# only where one pattern would shadow another: "Verbund Hydro Power GmbH" is
# Verbund's generation arm and must be caught before the APG rule, which
# otherwise claims the "Verbund / APG" spelling.
OPERATOR_ALIASES: tuple[tuple[str, str], ...] = (
    (r"verbund\s*hydro|^\s*vhp\s*$", "Verbund Hydro Power"),
    (r"\bapg\b|austrian power grid|austrian grid power", "APG"),
    (r"öbb", "ÖBB-Infrastruktur"),
    (r"netz\s*n(ö|oe)|netz\s*nieder(ö|oe)sterreich", "Netz NÖ"),
    (r"netz\s*o(ö|oe)|netz\s*ober(ö|oe)sterreich", "Netz OÖ"),
    (r"wiener netze", "Wiener Netze"),
    (r"\bkng\b|k(ä|ae)rnten netz", "Kärnten Netz"),
    (r"kelag|energie klagenfurt", "KELAG"),
    (r"linz netz|linz ag", "Linz Netz"),  # codespell:ignore linz
    (r"wels strom", "Wels Strom"),
    (
        r"energienetze steiermark|stromnetz steiermark|steweag|"
        r"e-steiermark|energie steiermark",
        "Energienetze Steiermark",
    ),
    (r"salzburg netz|salzburg ag|tauernkraftwerke", "Salzburg Netz"),
    (r"tiwag|tinetz|tiroler netze", "TINETZ"),
    (r"vorarlberger energienetze|illwerke|\bvkw\b", "Vorarlberger Energienetze"),
    (r"netz burgenland|energie burgenland", "Netz Burgenland"),
    (r"ennskraftwerke", "Ennskraftwerke"),
    # Wien Energie (supply/generation) is a different entity from Wiener Netze
    # (the DNO), so the two are deliberately kept apart.
    (r"wien energie", "Wien Energie"),
    (r"^\s*ikb\b|innsbrucker kommunalbetriebe", "IKB"),
    # Neighbouring TSOs, kept distinct so cross-border assets stay attributable.
    (r"amprion", "Amprion"),
    (r"tennet", "TenneT"),
    (r"swissgrid|^\s*nok\s*$", "Swissgrid"),
    (r"terna", "Terna"),
    (r"mavir", "MAVIR"),
    (r"(č|c)eps", "ČEPS"),
)

# OSM object references look like ``way/123`` or ``relation/456``; a cleaned
# component may list several, separated by semicolons.
_REF_RE = re.compile(r"(?:way|relation)/\d+")

# Railway traction is tagged 16.7 Hz (occasionally 16.67). Anything strictly
# between these bounds counts as traction; 0 Hz is DC and 50 Hz is the public
# grid, so both stay outside the window.
TRACTION_HZ_RANGE = (10.0, 25.0)
PUBLIC_HZ = 50.0
TRACTION_OPERATOR = "ÖBB-Infrastruktur"


def drop_cross_border_lines_lv(
    lines: pd.DataFrame,
    buses: pd.DataFrame,
    max_voltage: float = 220.0,
) -> pd.DataFrame:
    """
    Remove cross-border lines with voltage < *max_voltage* kV.

    A line is considered cross-border when exactly one of its endpoints
    (``bus0`` / ``bus1``) belongs to Austria.

    Parameters
    ----------
    lines:
        Lines DataFrame (index = ``line_id``) with columns ``bus0``, ``bus1``,
        ``voltage`` (kV).
    buses:
        Buses DataFrame (index = ``bus_id``) with column ``country``.
    max_voltage:
        Exclusive upper voltage threshold in kV.  Lines with
        ``voltage < max_voltage`` that cross the Austrian border are removed.
        Default is 220 kV, which targets all 110 kV (and lower) cross-border
        lines given the voltage levels present in the AT OSM dataset.

    Returns
    -------
    pd.DataFrame
        Copy of *lines* with the matching cross-border entries removed.
    """
    at_bus_ids = set(buses[buses["country"] == "AT"].index)

    xb_mask = lines["bus0"].isin(at_bus_ids) != lines["bus1"].isin(at_bus_ids)
    drop_mask = xb_mask & (lines["voltage"] < max_voltage)

    n_dropped = int(drop_mask.sum())
    if n_dropped:
        logger.info(
            f"Dropping {n_dropped} cross-border lines with voltage < {max_voltage:.2f} kV."
        )
        logger.debug(f"Dropped line IDs: {lines.index[drop_mask].tolist()}")
    else:
        logger.info(f"No cross-border lines with voltage < {max_voltage:.2f} kV found.")

    return lines[~drop_mask].copy()


def load_osm_tags(paths: list[str]) -> dict[str, dict[str, str]]:
    """
    Index ``operator`` and ``frequency`` from raw Overpass JSON files.

    Parameters
    ----------
    paths:
        Raw Overpass JSON files as written by ``retrieve_osm_data``. Each holds
        an ``elements`` list whose entries carry ``type``, ``id`` and ``tags``.

    Returns
    -------
    dict
        Maps ``"way/123"`` / ``"relation/456"`` to the subset of tags we keep.
    """
    tags: dict[str, dict[str, str]] = {}
    for path in paths:
        with open(path) as f:
            elements = json.load(f).get("elements", [])
        for element in elements:
            osm_tags = element.get("tags") or {}
            ref = f"{element['type']}/{element['id']}"
            tags[ref] = {
                "operator": osm_tags.get("operator"),
                "frequency": osm_tags.get("frequency"),
            }
    logger.info(f"Indexed OSM tags for {len(tags)} objects from {len(paths)} files.")
    return tags


def match_operator_alias(value: str) -> str | None:
    """
    Return the alias for one raw OSM ``operator`` value, or None if unlisted.

    Kept separate from :func:`canonical_operator` so callers can tell "matched a
    rule that happens to be spelled like its alias" (``"APG"`` -> ``"APG"``)
    apart from "matched nothing and was passed through".
    """
    for pattern, alias in OPERATOR_ALIASES:
        if re.search(pattern, value, flags=re.IGNORECASE):
            return alias
    return None


def canonical_operator(value: str) -> str:
    """Map one raw OSM ``operator`` value onto its alias, or pass it through."""
    return match_operator_alias(value) or value


def add_operator_columns(
    df: pd.DataFrame,
    osm_tags: dict[str, dict[str, str]],
) -> pd.DataFrame:
    """
    Attach ``operator``, ``operator_clean`` and ``tag_frequency`` to *df*.

    Values are collected from every OSM object listed in the ``tags`` column and
    de-duplicated in first-seen order. Components merged from objects that
    disagree keep every value, joined with `` | ``, rather than picking one.

    Parameters
    ----------
    df:
        Cleaned component table (lines or buses) carrying a ``tags`` column of
        ``;``-separated OSM references.
    osm_tags:
        Lookup as returned by :func:`load_osm_tags`.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with the three columns appended.
    """
    if "tags" not in df.columns:
        raise ValueError(
            "Component table has no 'tags' column, so OSM operators cannot be "
            f"resolved. Found columns: {df.columns.tolist()}"
        )

    def _collect(cell: object) -> tuple[str, str, str]:
        operators: dict[str, None] = {}
        aliases: dict[str, None] = {}
        frequencies: dict[str, None] = {}
        for ref in _REF_RE.findall(str(cell)):
            entry = osm_tags.get(ref)
            if entry is None:
                continue
            operator = (entry.get("operator") or "").strip()
            if operator:
                operators[operator] = None
                aliases[canonical_operator(operator)] = None
            frequency = (entry.get("frequency") or "").strip()
            if frequency:
                frequencies[frequency] = None
        return (
            " | ".join(operators),
            " | ".join(aliases),
            " | ".join(sorted(frequencies)),
        )

    resolved = df["tags"].map(_collect)
    out = df.copy()
    out["operator"] = resolved.str[0].replace("", pd.NA)
    out["operator_clean"] = resolved.str[1].replace("", pd.NA)
    out["tag_frequency"] = resolved.str[2].replace("", pd.NA)

    resolved_count = int(out["operator"].notna().sum())
    logger.info(
        f"Resolved an operator for {resolved_count}/{len(out)} components "
        f"({resolved_count / len(out):.0%})."
        if len(out)
        else "No components to resolve."
    )

    unmatched = sorted(
        {
            operator
            for cell in out["operator"].dropna()
            for operator in cell.split(" | ")
            if match_operator_alias(operator) is None
        }
    )
    if unmatched:
        logger.warning(
            f"{len(unmatched)} operator value(s) have no alias in "
            f"OPERATOR_ALIASES and are passed through verbatim: {unmatched}"
        )
    return out


def parse_frequencies(cell: object) -> set[float]:
    """Parse a ``tag_frequency`` cell (``"16.7"``, ``"16.7 | 50"``) into floats."""
    values = set()
    for token in str(cell).split("|"):
        try:
            values.add(float(token.strip()))
        except ValueError:
            continue
    return values


def is_traction(operator_clean: object, tag_frequency: object) -> bool:
    """
    Decide whether a component belongs to the railway traction network.

    An explicit 50 Hz tag always wins: ÖBB also owns ordinary public-grid lines
    (the feeds to its converter stations), and those must stay in the model.
    That also settles the conflicting case of a component merged from a 16.7 Hz
    and a 50 Hz object — dropping real public-grid infrastructure is the worse
    error, and the operator columns keep such a line reviewable.

    Otherwise a 16.7 Hz tag is decisive, and an ÖBB line carrying no frequency
    tag at all is assumed to be traction.
    """
    frequencies = parse_frequencies(tag_frequency)
    if PUBLIC_HZ in frequencies:
        return False
    low, high = TRACTION_HZ_RANGE
    if any(low < f < high for f in frequencies):
        return True
    return TRACTION_OPERATOR in str(operator_clean)


def drop_traction_lines(lines: pd.DataFrame) -> pd.DataFrame:
    """
    Remove railway traction lines from *lines*.

    The 16.7 Hz traction network is galvanically separate from the 50 Hz public
    grid, so its lines cannot carry system power and do not belong in the
    dataset. ``clean_osm_data`` does not drop them: it overwrites ``frequency``
    with ``"50"``, which relabels traction as ordinary AC. This filter therefore
    relies on ``tag_frequency``, recovered by :func:`add_operator_columns`.

    Parameters
    ----------
    lines:
        Lines DataFrame carrying ``operator_clean`` and ``tag_frequency``.

    Returns
    -------
    pd.DataFrame
        Copy of *lines* without traction lines.
    """
    missing = {"operator_clean", "tag_frequency"} - set(lines.columns)
    if missing:
        raise ValueError(
            f"Cannot identify traction lines, columns missing: {sorted(missing)}. "
            "Run add_operator_columns() first."
        )

    drop_mask = lines.apply(
        lambda row: is_traction(row["operator_clean"], row["tag_frequency"]), axis=1
    )

    n_dropped = int(drop_mask.sum())
    if n_dropped:
        logger.info(
            f"Dropping {n_dropped} railway traction lines "
            f"({n_dropped / len(lines):.1%} of all lines)."
        )
        logger.debug(f"Dropped line IDs: {lines.index[drop_mask].tolist()}")
    else:
        logger.info("No railway traction lines found.")

    return lines[~drop_mask].copy()


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("build_osm_network_at")

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    voltages_config = snakemake.config["electricity"]["voltages"]
    if 110.0 not in voltages_config:
        raise ValueError(
            "110.0 kV is not listed in config.electricity.voltages "
            f"(found: {voltages_config}). "
            "Building the AT OSM dataset requires the 110 kV voltage level."
        )

    buses = pd.read_csv(snakemake.input.buses, index_col=0, quotechar="'")
    lines = pd.read_csv(snakemake.input.lines, index_col=0, quotechar="'")
    links = pd.read_csv(snakemake.input.links, index_col=0, quotechar="'")
    converters = pd.read_csv(snakemake.input.converters, index_col=0, quotechar="'")
    transformers = pd.read_csv(snakemake.input.transformers, index_col=0, quotechar="'")

    logger.info(
        f"Loaded network: {len(buses)} buses, {len(lines)} lines, {len(links)} links."
    )

    # Drop all international buses and lines below 220 kV, because they
    # are not validated against ground truth.
    buses = buses.query("country == 'AT' or voltage >= 220")
    at_buses = buses.query("country == 'AT'").index
    lines = lines.query(
        "bus0.isin(@at_buses) or bus1.isin(@at_buses) or voltage >= 220"
    )

    # drop all cross border 110 kV Lines in Austria
    lines = drop_cross_border_lines_lv(lines, buses, max_voltage=220.0)

    # Recover operator and the pre-normalisation frequency tag from the raw
    # Overpass JSON. Lines and substations live in separate files, so each
    # component type is resolved against its own object index; a way id is only
    # unique within its feature type.
    logger.info("Recovering OSM operators for lines.")
    lines = add_operator_columns(
        lines,
        load_osm_tags(
            [
                *snakemake.input.cables_way,
                *snakemake.input.lines_way,
                *snakemake.input.routes_relation,
            ]
        ),
    )

    logger.info("Recovering OSM operators for buses.")
    buses = add_operator_columns(
        buses,
        load_osm_tags(
            [
                *snakemake.input.substations_way,
                *snakemake.input.substations_relation,
            ]
        ),
    )

    # Traction can only be identified once tag_frequency has been recovered.
    lines = drop_traction_lines(lines)

    # Traction substations are left in place: dropping buses risks orphaning
    # components elsewhere in the dataset. Report them so the count is visible.
    connected = set(lines["bus0"]) | set(lines["bus1"])
    for frame, name in ((links, "links"), (transformers, "transformers")):
        if {"bus0", "bus1"}.issubset(frame.columns):
            connected |= set(frame["bus0"]) | set(frame["bus1"])
    isolated = buses.index.difference(pd.Index(sorted(connected)))
    if len(isolated):
        logger.info(
            f"{len(isolated)} buses have no remaining line, link or transformer "
            "(mostly traction substations); they are kept in the dataset."
        )

    to_csv_kwargs = dict(quotechar="'", quoting=QUOTE_NONNUMERIC)
    buses.to_csv(snakemake.output.buses, **to_csv_kwargs)
    lines.to_csv(snakemake.output.lines, **to_csv_kwargs)
    links.to_csv(snakemake.output.links, **to_csv_kwargs)
    converters.to_csv(snakemake.output.converters, **to_csv_kwargs)
    transformers.to_csv(snakemake.output.transformers, **to_csv_kwargs)

    logger.info(
        f"Wrote filtered AT OSM network to {Path(snakemake.output.buses).parent}."
    )
