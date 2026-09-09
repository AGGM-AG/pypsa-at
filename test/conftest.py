# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT

import pathlib
import zipfile
from functools import reduce
from urllib.request import urlretrieve

import geopandas as gpd
import pandas as pd
import pypsa
import pytest
import yaml
from pypsa import NetworkCollection

from evals.fileio import read_networks
from evals.utils import get_latest_results_folder


@pytest.fixture(scope="function")
def scigrid_network():
    return pypsa.examples.scigrid_de(from_master=True)


@pytest.fixture(scope="function")
def ac_dc_network():
    return pypsa.examples.ac_dc_meshed(from_master=True)


@pytest.fixture(scope="session")
def config():
    path_config = pathlib.Path(pathlib.Path.cwd(), "config", "config.default.yaml")
    with open(path_config) as file:
        config_dict = yaml.safe_load(file)
    return config_dict


@pytest.fixture(scope="function")
def buses_dataframe():
    return pd.DataFrame(
        {
            "bus_id": [5231, 5232],
            "voltage": [380.0, 380.0],
            "dc": ["f", "f"],
            "symbol": ["Substation", "Substation"],
            "under_construction": ["f", "f"],
            "x": [6.8884, 6.8894],
            "y": [45.6783, 45.6793],
            "country": ["IT", "IT"],
            "geometry": ["POINT (6.8884 45.6783)", "POINT (6.8894 45.6793)"],
        },
        index=[5090, 5091],
    )


@pytest.fixture(scope="function")
def converters_dataframe():
    return pd.DataFrame(
        {
            "converter_id": "convert_5231_5232",
            "bus0": 5231,
            "bus1": 5232,
            "voltage": 380.0,
            "geometry": "'LINESTRING(6.8884 45.6783 ",
            "": "6.8894 45.6793)'",
        },
        index=[0],
    )


@pytest.fixture(scope="function")
def lines_dataframe():
    return pd.DataFrame(
        {
            "line_id": "line_5231_5232",
            "bus0": 5231,
            "bus1": 5232,
            "voltage": 380.0,
            "circuits": 1.0,
            "length": 1000.0,
            "underground": "t",
            "under_construction": "f",
            "geometry": "'LINESTRING(6.8884 45.6783 ",
            "": "6.8894 45.6793)'",
        },
        index=[0],
    )


@pytest.fixture(scope="function")
def links_dataframe():
    return pd.DataFrame(
        {
            "link_id": "link_5231_5232",
            "bus0": 5231,
            "bus1": 5232,
            "voltage": 380.0,
            "p_nom": 600.0,
            "length": 1000.0,
            "underground": "t",
            "under_construction": "f",
            "geometry": "'LINESTRING(6.8884 45.6783 ",
            "": "6.8894 45.6793)'",
        },
        index=[0],
    )


@pytest.fixture(scope="function")
def transformers_dataframe():
    return pd.DataFrame(
        {
            "transformer_id": "transf_5231_5232",
            "bus0": 5231,
            "bus1": 5232,
            "voltage": 380.0,
            "geometry": "'LINESTRING(6.8884 45.6783 ",
            "": "6.8894 45.6793)'",
        },
        index=[0],
    )


@pytest.fixture(scope="function")
def download_natural_earth(tmpdir):
    url = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries_deu.zip"
    directory_to_extract_to = pathlib.Path(tmpdir, "folder")
    zipped_filename = "ne_10m_admin_0_countries_deu.zip"
    path_to_zip_file, headers = urlretrieve(url, zipped_filename)
    with zipfile.ZipFile(path_to_zip_file, "r") as zip_ref:
        zip_ref.extractall(directory_to_extract_to)
    natural_earth_shape_file_path = pathlib.Path(
        directory_to_extract_to, "ne_10m_admin_0_countries_deu.shp"
    )
    yield natural_earth_shape_file_path
    pathlib.Path(zipped_filename).unlink(missing_ok=True)
    pathlib.Path(natural_earth_shape_file_path).unlink(missing_ok=True)


# Disable because of unreliable data download
# @pytest.fixture(scope="function")
# def download_eez(tmpdir):
#     url = "https://data.pypsa.org/workflows/eur/eez/v12_20231025/World_EEZ_v12_20231025_LR.zip"
#     zipped_filename = "World_EEZ_v12_20231025_LR.zip"
#     zipped_filename_path = pathlib.Path(tmpdir, zipped_filename)
#     urlretrieve(url, zipped_filename_path)
#     unpack_archive(zipped_filename_path, tmpdir)
#     output_path = pathlib.Path(
#         tmpdir, "World_EEZ_v12_20231025_LR", "eez_v12_lowres.gpkg"
#     )
#     yield output_path
#     pathlib.Path(output_path).unlink(missing_ok=True)


@pytest.fixture(scope="function")
def italy_shape(download_natural_earth, tmpdir):
    shape_file = gpd.read_file(download_natural_earth)
    fieldnames = (
        shape_file[x].where(lambda s: s != "-99")
        for x in ("ISO_A2", "WB_A2", "ADM0_A3")
    )
    shape_file["name"] = reduce(
        lambda x, y: x.fillna(y), fieldnames, next(fieldnames)
    ).str[:2]
    italy_shape_file = shape_file.loc[shape_file.name.isin(["IT"])]
    italy_shape_file_path = pathlib.Path(tmpdir, "italy_shape.geojson")
    italy_shape_file.to_file(italy_shape_file_path, driver="GeoJSON")
    yield italy_shape_file_path


_ABSENT = object()


def _get_config(config, keys, default=_ABSENT):
    """
    Retrieve a nested value from a config dict using a sequence of keys.

    Mirrors get_config() from rules/common.smk.
    """
    value = config
    for key in keys:
        if isinstance(value, list):
            value = value[key]
        else:
            value = value.get(key, default)
        if value == default:
            return default
    return value


def require_config(nc, *keys, **condition):
    """
    Extract a config entry from all networks and xfail if it matches a condition.

    Navigates n.meta using *keys for every network in nc, then checks the condition
    sub-key against the provided value. Fails hard if the config entry is absent or
    inconsistent across networks. Xfails if the condition key equals the condition value.

    Parameters
    ----------
    nc
        Collection of solved networks.
    *keys
        Key path into n.meta, e.g. "mods", "net_zero_electricity".
    **condition
        Single keyword argument specifying the xfail condition, e.g. enable=False.

    Returns
    -------
    :
        The config entry found at the key path, shared across all networks.
    """
    if condition == {}:
        cond_key, cond_val = None, None
    elif len(condition) == 1:
        cond_key, cond_val = next(iter(condition.items()))
    elif len(condition) != 1:
        raise ValueError(
            "require_config requires exactly one keyword condition, e.g. enable=False"
        )

    entries = {year: _get_config(n.meta, keys) for year, n in nc.networks.items()}

    key_repr = ".".join(keys)

    # fail if key was not found in any config
    if all(v is _ABSENT for v in entries.values()):
        pytest.fail(f"config '{key_repr}' absent in all networks")

    # fail if key was found in one, but not all configs
    absent = [k for k, v in entries.items() if v is _ABSENT]
    if absent:
        pytest.fail(
            f"config '{key_repr}' absent in {absent} but present in other networks"
        )

    # fail if key is set differently across networks
    present = list(entries.values())
    if not all(v == present[0] for v in present[1:]):
        pytest.fail(f"config '{key_repr}' differs across networks: {entries}")

    # this is the desired config entry
    cfg = present[0]

    # make sure the condition key is in the config
    if cond_key is not None and cond_key not in cfg:
        raise ValueError(f"config '{key_repr}' does not contain key '{cond_key}'")

    # expect fail (=xfail) if config is set to the condition value
    if cond_key is not None and cfg[cond_key] == cond_val:
        pytest.xfail(f"config '{'.'.join(keys)}.{cond_key}' == {cond_val!r}")

    return cfg


@pytest.fixture(scope="session")
def result_path(pytestconfig) -> pathlib.Path:
    """
    Retrieve the results path from CLI.
    """
    default_path = get_latest_results_folder()
    result_path = pytestconfig.getoption("result_path")
    return pathlib.Path(result_path) if result_path else default_path


@pytest.fixture(scope="session")
def project_root(pytestconfig) -> pathlib.Path:
    return pytestconfig.rootpath


@pytest.fixture(scope="session")
def eval_path(result_path: pathlib.Path) -> pathlib.Path:
    """Retrieve the evaluation path from CLI argument."""
    return pathlib.Path(result_path) / "evaluation"


@pytest.fixture(scope="session")
def json_path(eval_path: pathlib.Path) -> pathlib.Path:
    """Build the JSON result path."""
    return eval_path / "JSON"


@pytest.fixture(scope="session")
def nc(result_path: pathlib.Path) -> NetworkCollection:
    """Load the networks."""
    return read_networks(result_path)


def pytest_addoption(parser) -> None:
    """Register command line arguments."""
    parser.addoption(
        "--result-path", action="store", help="Path to the ESM results folder."
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "AT: integration test that loads solved networks via --result-path "
        "(auto-applied to any test using the `nc` fixture)",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-apply the AT mark to any test that (transitively) requests the `nc` fixture."""
    for item in items:
        if "nc" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.AT)


@pytest.fixture(scope="session")
def is_testrun(nc) -> bool:
    return any(n.meta["run"]["prefix"] == "test-sector-myopic-at10" for n in nc)
