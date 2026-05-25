from pathlib import Path
import base64
from typing import Optional


import streamlit as st
import geopandas as gpd
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from numpy.typing import ArrayLike
import numpy as np
import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = BASE_DIR / "images"


@st.cache_data
def load_data() -> gpd.GeoDataFrame:
    """Load and merge all primary datasets into a single GeoDataFrame.

    Reads the Statbel statistical-sectors shapefile, filters it to the Flemish
    Region, dissolves to municipality level, and reprojects to WGS-84 (EPSG 4326).
    Centroids are computed and stored as ``lon``/``lat`` columns. Geometries are
    simplified to reduce file size. The spatial data is then merged with three
    CSV datasets: risk tiers, model results, and age demographics.

    Returns:
        gpd.GeoDataFrame: Municipality-level GeoDataFrame containing geometry,
            centroid coordinates, and all columns from the tier, results, and
            age CSV files.
    """

    gdf = gpd.read_file(
        DATA_DIR / "Shapefile" / "sh_statbel_statistical_sectors_3812_20240101.shp"
    )
    gdf = gdf[gdf["T_REGIO_NL"] == "Vlaams Gewest"].copy()
    gdf = gdf.dissolve(by="T_MUN_NL", as_index=False)
    gdf = gdf.rename(columns={"T_MUN_NL": "NAAM"})

    for col in gdf.select_dtypes(
        include=["datetime64", "datetime", "datetimetz"]
    ).columns:
        gdf[col] = gdf[col].astype(str)

    centroids = gdf.centroid
    centroids_wgs = centroids.to_crs(epsg=4326)

    gdf = gdf.to_crs(epsg=4326)
    gdf["lon"] = centroids_wgs.x
    gdf["lat"] = centroids_wgs.y

    # simplifies by removing the nodes that aren't really needed
    gdf["geometry"] = gdf["geometry"].simplify(tolerance=0.001, preserve_topology=True)

    df_tiers = pd.read_csv(DATA_DIR / "tiers.csv")
    df_results = pd.read_csv(DATA_DIR / "final_results.csv")
    df_age = pd.read_csv(DATA_DIR / "flanders_age_by_municipality_2024.csv")

    df_tiers.columns = df_tiers.columns.str.strip()
    df_results.columns = df_results.columns.str.strip()
    df_age.columns = df_age.columns.str.strip()

    gdf["join_key"] = gdf["NAAM"].astype(str).str.strip().str.lower()
    df_tiers["join_key"] = df_tiers["gemeente"].astype(str).str.strip().str.lower()
    df_results["join_key"] = df_results["gemeente"].astype(str).str.strip().str.lower()
    df_age["join_key"] = df_age["Municipality"].astype(str).str.strip().str.lower()

    df_merged_csvs = df_tiers.merge(
        df_results, on="join_key", how="left", suffixes=("_old", "")
    )
    df_merged_csvs = df_merged_csvs.merge(
        df_age, on="join_key", how="left", suffixes=("", "_age")
    )
    df_merged_csvs = df_merged_csvs.loc[:, ~df_merged_csvs.columns.str.endswith("_old")]

    merged_gdf = gdf.merge(df_merged_csvs, on="join_key", how="left")
    return merged_gdf


@st.cache_data
def load_raw_accidents() -> pd.DataFrame:
    """Load the raw 2024 Flanders accident records from CSV.

    Reads ``flanders_2024_accidents_wgs84.csv`` from the data directory.
    The file is read with ``low_memory=False`` to avoid mixed-type inference
    warnings on large datasets.

    Returns:
        pd.DataFrame: Raw accident records with all original columns intact.
    """

    return pd.read_csv(DATA_DIR / "flanders_2024_accidents_wgs84.csv", low_memory=False)


@st.cache_data
def load_sites() -> pd.DataFrame:
    """Load cyclist infrastructure sites and attach a normalised join key.

    Reads ``sites.csv`` from the data directory, drops any rows that are
    missing latitude or longitude values, and — when a ``gemeente`` column is
    present — adds a lower-cased, stripped ``join_key`` column so that rows
    can be matched against municipality data.

    Returns:
        pd.DataFrame: Site records with valid coordinates and, when applicable,
            a ``join_key`` column for municipality lookups.
    """

    df = pd.read_csv(DATA_DIR / "sites.csv")
    df = df.dropna(subset=["lat", "long"])
    # pre-calculate the join key so we can easily filter per municipality later
    if "gemeente" in df.columns:
        df["join_key"] = df["gemeente"].astype(str).str.strip().str.lower()
    return df


@st.cache_data
def load_all_base64_images(images_dir: Path = IMAGES_DIR) -> dict[str, str]:
    """Load every PNG in a directory and return them as base64 data-URIs.

    Iterates over all ``*.png`` files in *images_dir*, encodes each one as a
    base64 string, and wraps it in a ``data:image/png;base64,`` URI suitable
    for embedding directly in HTML or Streamlit components.

    Args:
        images_dir (Path): Directory to scan for PNG files.
            Defaults to ``IMAGES_DIR``.

    Returns:
        dict[str, str]: Mapping of filename stem (without extension) to the
            corresponding base64 data-URI string. Returns an empty dict if
            *images_dir* does not exist or contains no PNG files.
    """

    result = {}
    if not images_dir.is_dir():
        return result
    for fname in images_dir.iterdir():
        if fname.suffix.lower() == ".png":
            b64 = base64.b64encode(fname.read_bytes()).decode("utf-8")
            result[fname.stem] = f"data:image/png;base64,{b64}"
    return result


@st.cache_data
def build_accident_index(raw_accidents: pd.DataFrame) -> dict[str, list[list[float]]]:
    """Build a per-municipality lookup table of accident coordinates.

    Groups the raw accident DataFrame by a normalised municipality join key and
    stores the ``LAT``/``LON`` pairs for each group in a dictionary. Rows with
    non-numeric or missing coordinates are dropped before indexing.

    Args:
        raw_accidents (pd.DataFrame): Raw accident records as returned by
            :func:`load_raw_accidents`. Must contain the columns
            ``TX_MUNTY_COLLISION_NL``, ``LAT``, and ``LON``.

    Returns:
        dict[str, list[list[float]]]: Dictionary mapping lower-cased municipality
            join keys to a list of ``[lat, lon]`` coordinate pairs.
    """

    df = raw_accidents.copy()
    df["join_key"] = df["TX_MUNTY_COLLISION_NL"].astype(str).str.strip().str.lower()
    df["LAT"] = pd.to_numeric(df["LAT"], errors="coerce")
    df["LON"] = pd.to_numeric(df["LON"], errors="coerce")
    df = df.dropna(subset=["LAT", "LON"])

    index: dict = {}
    for key, group in df.groupby("join_key"):
        index[key] = group[["LAT", "LON"]].values.tolist()
    return index


@st.cache_data
def slim_gdf(merged_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return a lightweight copy of the merged GeoDataFrame for map rendering.

    Retains only the geometry column and the subset of fields required for
    map tooltips, reducing memory usage and serialisation overhead when the
    full attribute table is not needed.

    Args:
        merged_gdf (gpd.GeoDataFrame): Full municipality GeoDataFrame as
            returned by :func:`load_data`.

    Returns:
        gpd.GeoDataFrame: GeoDataFrame containing only ``geometry`` and the
            tooltip fields that are present in *merged_gdf*:
            ``NAAM``, ``risk_tier``, ``predicted_num_accidents``,
            ``accidents_per_100_cyclists``, ``most_frequent_type``,
            ``lat``, ``lon``.
    """

    TOOLTIP_FIELDS = [
        "NAAM",
        "risk_tier",
        "predicted_num_accidents",
        "accidents_per_100_cyclists",
        "most_frequent_type",
        "lat",
        "lon",
    ]
    keep = list(set(TOOLTIP_FIELDS + ["geometry"]))
    keep = [c for c in keep if c in merged_gdf.columns]
    return merged_gdf[keep].copy()


def plot_lorenz_curve(
    y_true: ArrayLike,
    y_pred: ArrayLike,
    label: str,
    fig: Optional[Figure] = None,
    ax: Optional[Axes] = None,
) -> float:
    """
    Plots a Lorenz curve based on predicted values and calculates the Gini coefficient.

    The function sorts the true values based on the model's predictions and plots
    the cumulative proportion of true values against the cumulative population.
    It then calculates and returns the Gini coefficient, while plotting the curve.

    Args:
        y_true (ArrayLike): Actual ground truth target values.
        y_pred (ArrayLike): Predicted values used to rank/sort the actual values.
        label (str): The label for the plot's legend (e.g., model name).
        fig (Optional[Figure]): Matplotlib Figure object. Uses the current figure if None.
        ax (Optional[Axes]): Matplotlib Axes object. Uses the current axes if None.

    Returns:
        float: The calculated Gini coefficient.
    """

    if fig is None:
        fig = plt.gcf()
    if ax is None:
        ax = plt.gca()

    y_true_flat = np.array(y_true).flatten()
    y_pred_flat = np.array(y_pred).flatten()

    df_eval = pd.DataFrame({"true": y_true_flat, "pred": y_pred_flat}).sort_values(
        "pred"
    )

    cum_true = np.cumsum(df_eval["true"]) / np.sum(df_eval["true"])
    cum_pop = np.arange(1, len(cum_true) + 1) / len(cum_true)

    area_under_curve = np.trapezoid(cum_true, cum_pop)
    gini = 1 - 2 * area_under_curve

    ax.plot(cum_pop, cum_true, label=f"{label} (Gini: {gini:.3f})")
    return float(gini)
