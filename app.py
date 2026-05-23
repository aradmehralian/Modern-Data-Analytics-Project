import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import base64
import os
import plotly.express as px
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = BASE_DIR / "images"

st.set_page_config(page_title="MDA Dashboard", layout="wide")

st.markdown(
    """
    <style>
    button[title="View fullscreen"] { display: none; }
    .block-container { padding-top: 2rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "app_mode" not in st.session_state:
    st.session_state.app_mode = "Risk Assessment"

app_mode = st.session_state.app_mode

# Data loading


@st.cache_data
def load_data():
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
def load_raw_accidents():
    return pd.read_csv(DATA_DIR / "flanders_2024_accidents_wgs84.csv", low_memory=False)


@st.cache_data
def load_sites():
    df = pd.read_csv(DATA_DIR / "sites.csv")
    return df.dropna(subset=["lat", "long"])


@st.cache_data
def load_all_base64_images(images_dir: Path = IMAGES_DIR) -> dict:
    result = {}
    if not images_dir.is_dir():
        return result
    for fname in images_dir.iterdir():
        if fname.suffix.lower() == ".png":
            b64 = base64.b64encode(fname.read_bytes()).decode("utf-8")
            result[fname.stem] = f"data:image/png;base64,{b64}"
    return result


@st.cache_data
def build_accident_index(raw_accidents: pd.DataFrame) -> dict:
    df = raw_accidents.copy()
    df["join_key"] = df["TX_MUNTY_COLLISION_NL"].astype(str).str.strip().str.lower()
    df["LAT"] = pd.to_numeric(df["LAT"], errors="coerce")
    df["LON"] = pd.to_numeric(df["LON"], errors="coerce")
    df = df.dropna(subset=["LAT", "LON"])

    index: dict = {}
    for key, group in df.groupby("join_key"):
        index[key] = group[["LAT", "LON"]].values.tolist()
    return index


_TOOLTIP_FIELDS = [
    "NAAM",
    "risk_tier",
    "predicted_num_accidents",
    "accidents_per_100_cyclists",
    "most_frequent_type",
    "lat",
    "lon",
]

type_cols = [
    "prev_year_slick_accidents",
    "prev_year_carconflict_accidents",
    "prev_year_int_accidents",
]

type_labels = ["Slick", "Car Conflict", "Intersection"]

TIER_COLORS = {"Red": "#ef4444", "Yellow": "#facc15", "Green": "#22c55e"}

map_cols = [
    "geometry",
    "NAAM",
    "risk_tier",
    "predicted_num_accidents",
    "accidents_per_100_cyclists",
    "most_frequent_type",
    "lat",
    "lon",
]

FLANDERS_BOUNDS = [[50.67, 2.53], [51.60, 5.92]]


@st.cache_data
def slim_gdf(merged_gdf):
    """Return a geometry-only GDF with the minimum columns needed for maps."""
    keep = list(set(_TOOLTIP_FIELDS + ["geometry"]))
    keep = [c for c in keep if c in merged_gdf.columns]
    return merged_gdf[keep].copy()


with st.spinner("Loading data..."):
    if app_mode == "Risk Assessment":
        merged_gdf = load_data()
        raw_accidents = load_raw_accidents()
        accident_index = build_accident_index(raw_accidents)
        b64_images = load_all_base64_images()
    elif app_mode == "Locations":
        sites_df = load_sites()

if "selected_muni" not in st.session_state:
    st.session_state.selected_muni = None


# Risk Assessment view

if app_mode == "Risk Assessment":
    st.title("Flanders Bike Paths' Risk Assessment")

    # detail view for a selected municipality
    if st.session_state.selected_muni is not None:
        muni_name = st.session_state.selected_muni

        if st.button("⬅️ Back to Flanders Map"):
            st.session_state.selected_muni = None
            st.rerun()

        st.subheader(f"Accident Density Zone: {muni_name}")

        muni_data = merged_gdf[merged_gdf["NAAM"] == muni_name]

        m_detail = folium.Map(
            tiles=None, zoom_control=False, scrollWheelZoom=False, dragging=False
        )
        m_detail.get_root().html.add_child(
            folium.Element(
                "<style>.leaflet-container { background: #0E1117 !important; }</style>"
            )
        )

        bounds = muni_data.total_bounds
        m_detail.fit_bounds(
            [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
            padding=(20, 20),
        )

        folium.GeoJson(
            muni_data[["geometry", "NAAM"]],
            style_function=lambda _: {
                "fillColor": "#0E1117",
                "color": "white",
                "weight": 2,
                "fillOpacity": 0.1,
            },
            tooltip=None,
        ).add_to(m_detail)

        heat_data = accident_index.get(str(muni_name).strip().lower(), [])

        if heat_data:
            HeatMap(
                heat_data,
                radius=15,
                blur=10,
                gradient={
                    0.2: "blue",
                    0.4: "cyan",
                    0.6: "lime",
                    0.8: "yellow",
                    1.0: "red",
                },
            ).add_to(m_detail)

        st_folium(m_detail, use_container_width=True, height=500, key="detail_map")
        st.divider()

        row = muni_data.iloc[0]

        raw_2024 = row.get("prev_year_total_cyc_accidents", 0)
        raw_pred = row.get("predicted_num_accidents", 0)
        raw_pop = row.get("total_pop", 0)
        raw_income = row.get("avg_income_per_capita", 0)
        raw_age = row.get("Average Age", 0)

        try:
            acc_2024 = float(raw_2024)
        except (ValueError, TypeError):
            acc_2024 = 0
        try:
            acc_pred = float(raw_pred)
        except (ValueError, TypeError):
            acc_pred = 0

        pop_str = f"{int(raw_pop):,}" if pd.notna(raw_pop) else "N/A"
        income_str = f"€{int(raw_income):,}" if pd.notna(raw_income) else "N/A"
        age_str = f"{float(raw_age):.1f}" if pd.notna(raw_age) else "N/A"

        st.markdown(
            f"""
<div style="display: flex; gap: 20px; align-items: stretch; margin-bottom: 20px;">
    <div style="flex: 2; display: flex; flex-direction: column;">
        <h3 style="color: white; margin: 0 0 10px 0; text-align: center; font-size: 1.3rem; font-weight: 600;">Recorded Data (2024) vs. Predicted (2025)</h3>
        <hr style="border: none; border-top: 1px solid #334155; margin-bottom: 15px;">
        <div style="display: flex; gap: 15px; height: 100%;">
            <div style="flex: 1; background-color: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); text-align: center; display: flex; flex-direction: column; justify-content: center;">
                <p style="color: #94a3b8; font-size: 13px; margin-bottom: 5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Recorded (2024)</p>
                <p style="color: #3b82f6; font-size: 40px; font-weight: bold; margin: 0; line-height: 1;">{acc_2024:.0f}</p>
            </div>
            <div style="flex: 1; background-color: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); text-align: center; display: flex; flex-direction: column; justify-content: center;">
                <p style="color: #94a3b8; font-size: 13px; margin-bottom: 5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Predicted (2025)</p>
                <p style="color: #ef4444; font-size: 40px; font-weight: bold; margin: 0; line-height: 1;">{acc_pred:.0f}</p>
            </div>
        </div>
    </div>
    <div style="width: 1px; background-color: #334155; margin: 0 10px;"></div>
    <div style="flex: 3; display: flex; flex-direction: column;">
        <h3 style="color: white; margin: 0 0 10px 0; text-align: center; font-size: 1.3rem; font-weight: 600;">Demographics</h3>
        <hr style="border: none; border-top: 1px solid #334155; margin-bottom: 15px;">
        <div style="display: flex; gap: 15px; height: 100%;">
            <div style="flex: 1; background-color: #1e293b; padding: 15px; border-radius: 12px; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); display: flex; align-items: center; gap: 10px;">
                <div style="background-color: rgba(16, 185, 129, 0.2); padding: 10px; border-radius: 10px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
                </div>
                <div>
                    <p style="color: #94a3b8; font-size: 12px; margin: 0; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Population</p>
                    <p style="color: white; font-size: 20px; font-weight: bold; margin: 0; line-height: 1.2;">{pop_str}</p>
                </div>
            </div>
            <div style="flex: 1; background-color: #1e293b; padding: 15px; border-radius: 12px; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); display: flex; align-items: center; gap: 10px;">
                <div style="background-color: rgba(245, 158, 11, 0.2); padding: 10px; border-radius: 10px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 5a8 8 0 0 0-14 5.5 8 8 0 0 0 14 5.5"></path><line x1="3" y1="9" x2="14" y2="9"></line><line x1="3" y1="12" x2="14" y2="12"></line></svg>
                </div>
                <div>
                    <p style="color: #94a3b8; font-size: 12px; margin: 0; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Avg Income</p>
                    <p style="color: white; font-size: 20px; font-weight: bold; margin: 0; line-height: 1.2;">{income_str}</p>
                </div>
            </div>
            <div style="flex: 1; background-color: #1e293b; padding: 15px; border-radius: 12px; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); display: flex; align-items: center; gap: 10px;">
                <div style="background-color: rgba(139, 92, 246, 0.2); padding: 10px; border-radius: 10px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                </div>
                <div>
                    <p style="color: #94a3b8; font-size: 12px; margin: 0; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Avg Age</p>
                    <p style="color: white; font-size: 20px; font-weight: bold; margin: 0; line-height: 1.2;">{age_str}</p>
                </div>
            </div>
        </div>
    </div>
</div>
""",
            unsafe_allow_html=True,
        )
        st.html("<br>")

        st.markdown("## Accident Profile vs. Flanders Average", text_alignment="center")

        global_means = (
            pd.to_numeric(merged_gdf[type_cols].mean(numeric_only=True))
            .fillna(0)
            .tolist()
        )
        muni_counts = pd.to_numeric(row[type_cols], errors="coerce").fillna(0).tolist()

        profile_df = pd.DataFrame(
            {
                "Accident Type": type_labels * 2,
                "Count": muni_counts + global_means,
                "Scope": [muni_name] * len(type_labels)
                + ["Global Average"] * len(type_labels),
            }
        )

        fig_types = px.bar(
            profile_df,
            x="Count",
            y="Accident Type",
            color="Scope",
            barmode="group",
            orientation="h",
            text="Count",
            color_discrete_sequence=["#3b82f6", "#B2B2B2"],
        )
        fig_types.update_traces(
            texttemplate="%{text:.0f}", textposition="outside", textfont_size=12
        )
        fig_types.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title=None,
            yaxis_title=None,
            hovermode=False,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="center",
                x=0.5,
                title=None,
                font=dict(color="white"),
            ),
            margin=dict(t=50, b=0, l=0, r=30),
            height=250,
            yaxis=dict(autorange="reversed"),
        )
        fig_types.update_yaxes(tickfont=dict(color="white"))
        fig_types.update_xaxes(showticklabels=False, showgrid=False)
        st.plotly_chart(
            fig_types,
            use_container_width=True,
            config={"displayModeBar": False, "staticPlot": True},
        )

    # main Flanders overview map
    else:
        gdf_no_data = merged_gdf[merged_gdf["risk_tier"].isna()]
        gdf_has_data = merged_gdf[merged_gdf["risk_tier"].notna()]

        map_col, search_col = st.columns([6, 1], gap="large")

        with search_col:
            st.markdown("### Search")
            st.markdown(
                "<p style='color: #a1a1aa; font-size: 14px;'>Find a municipality to view detailed information.</p>",
                unsafe_allow_html=True,
            )

            valid_munis = sorted(gdf_has_data["NAAM"].dropna().unique().tolist())
            searched_muni = st.selectbox(
                "Municipality",
                options=valid_munis,
                index=None,
                placeholder="Type or select...",
                label_visibility="collapsed",
            )

            if searched_muni:
                st.session_state.selected_muni = searched_muni
                st.rerun()

            st.divider()
            st.radio(
                "View",
                ["Risk Assessment", "Locations"],
                key="app_mode",
                label_visibility="collapsed",
            )

        with map_col:
            m = folium.Map(
                tiles=None,
                zoom_control=False,
                scrollWheelZoom=False,
                dragging=False,
                zoom_snap=0.1,
                zoomSnap=0.1,
            )
            m.fit_bounds([[50.67, 2.53], [51.60, 5.92]], padding=(0, 0))
            m.get_root().html.add_child(
                folium.Element(
                    "<style>.leaflet-container { background: #0E1117 !important; }</style>"
                )
            )

            folium.GeoJson(
                gdf_no_data[["geometry", "NAAM"]],
                style_function=lambda _: {
                    "fillColor": "#ffffff",
                    "color": "white",
                    "weight": 0.5,
                    "fillOpacity": 0.05,
                },
                tooltip=folium.GeoJsonTooltip(fields=["NAAM"], labels=False),
            ).add_to(m)

            def mapped_style(feature):
                tier = feature["properties"].get("risk_tier")
                return {
                    "fillColor": TIER_COLORS.get(tier, "#ffffff"),
                    "color": "white",
                    "weight": 0.5,
                    "fillOpacity": 0.8,
                }

            map_cols = [c for c in map_cols if c in gdf_has_data.columns]

            folium.GeoJson(
                gdf_has_data[map_cols],
                style_function=mapped_style,
                tooltip=folium.GeoJsonTooltip(
                    fields=[
                        "NAAM",
                        "risk_tier",
                        "predicted_num_accidents",
                        "accidents_per_100_cyclists",
                    ],
                    aliases=[
                        "Municipality:",
                        "Risk Tier:",
                        "Predicted Accidents:",
                        "Accidents/100 Cyclists:",
                    ],
                    localize=True,
                ),
            ).add_to(m)

            _marker_rows = gdf_has_data[["most_frequent_type", "lat", "lon"]].dropna(
                subset=["most_frequent_type", "lat", "lon"]
            )

            for rec in _marker_rows.itertuples(index=False):
                freq_type = str(rec.most_frequent_type).strip()
                data_uri = b64_images.get(freq_type)
                if data_uri:
                    folium.Marker(
                        [rec.lat, rec.lon],
                        icon=folium.CustomIcon(data_uri, icon_size=(25, 25)),
                        interactive=False,
                    ).add_to(m)

            map_data = st_folium(
                m,
                use_container_width=True,
                height=550,
                returned_objects=["last_active_drawing"],
                key="main_map",
            )

            if map_data and map_data.get("last_active_drawing"):
                name = map_data["last_active_drawing"]["properties"].get("NAAM")
                if name:
                    if name in gdf_has_data["NAAM"].values:
                        st.session_state.selected_muni = name
                        st.rerun()
                    else:
                        st.toast(f"No data available for {name}", icon="⚠️")

# locations view

elif app_mode == "Locations":
    st.title("Locations of Installed Sensors")

    map_col, nav_col = st.columns([5, 1])

    with nav_col:
        st.markdown("###")
        st.radio(
            "View",
            ["Risk Assessment", "Locations"],
            key="app_mode",
            label_visibility="collapsed",
        )

    with map_col:
        m_sites = folium.Map(
            tiles=None,
            zoom_control=True,
            scrollWheelZoom=True,
            dragging=True,
            min_zoom=8,
            max_bounds=True,
            max_zoom=20,
        )
        m_sites.get_root().html.add_child(
            folium.Element(
                "<style>.leaflet-container { background: #0E1117 !important; }</style>"
            )
        )

        m_sites.fit_bounds(FLANDERS_BOUNDS)
        m_sites.options["maxBounds"] = [[50.20, 2.00], [52.10, 6.50]]

        folium.TileLayer("cartodbdark_matter", name="Dark Map").add_to(m_sites)

        features = []
        for rec in sites_df.itertuples(index=False):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [rec.long, rec.lat]},
                    "properties": {"gemeente": getattr(rec, "gemeente", "N/A")},
                }
            )

        folium.GeoJson(
            {"type": "FeatureCollection", "features": features},
            marker=folium.CircleMarker(
                radius=4,
                color="#3b82f6",
                fill=True,
                fill_color="#3b82f6",
                fill_opacity=0.8,
            ),
            tooltip=folium.GeoJsonTooltip(
                fields=["gemeente"],
                aliases=["Municipality:"],
            ),
        ).add_to(m_sites)

        st_folium(m_sites, use_container_width=True, height=650, key="sites_map")
