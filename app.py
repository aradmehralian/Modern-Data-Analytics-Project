from utils import (
    load_data,
    load_raw_accidents,
    load_sites,
    load_all_base64_images,
    build_accident_index,
    slim_gdf,
)

import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import plotly.express as px
from pathlib import Path

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


TOOLTIP_FIELDS = [
    "NAAM",
    "risk_tier",
    "predicted_num_accidents",
    "accidents_per_100_cyclists",
    "most_frequent_type",
    "lat",
    "lon",
]

TYPE_COLS = [
    "prev_year_slick_accidents",
    "prev_year_carconflict_accidents",
    "prev_year_int_accidents",
    "prev_year_school_accidents",
    "prev_year_dark_count",
]

TYPE_LABELS = ["Slick", "Car Conflict", "Intersection", "School Zone", "Low Light"]

TIER_COLORS = {"Red": "#ef4444", "Yellow": "#facc15", "Green": "#22c55e"}

KEY_TO_LABEL = {
    "slick": "Slick Road",
    "car_conflict": "Car Conflict",
    "intersection": "Intersection",
    "school_accidents": "School Zone",
    "dark": "Low Light",
}

MAP_COLS = [
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

with st.spinner():
    merged_gdf = load_data()
    raw_accidents = load_raw_accidents()
    accident_index = build_accident_index(raw_accidents)
    b64_images = load_all_base64_images()
    sites_df = load_sites()

if "selected_muni" not in st.session_state:
    st.session_state.selected_muni = None

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
        padding=(0, 0),
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

    muni_key = str(muni_name).strip().lower()
    heat_data = accident_index.get(muni_key, [])

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

    # overlay Sensor Pins on top of the Heatmap
    if "join_key" in sites_df.columns:
        muni_sites = sites_df[sites_df["join_key"] == muni_key]

        pin_svg = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#3b82f6" width="28" height="28" stroke="white" stroke-width="1.5">
          <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
          <circle cx="12" cy="10" r="3" fill="white"></circle>
        </svg>
        """

        for _, site in muni_sites.iterrows():
            icon_html = f"""
            <div style="transform: translate(-50%, -100%); width: 28px; height: 28px;">
                {pin_svg}
            </div>
            """

            sensor_name = str(site.get("naam", "Unknown Sensor"))

            folium.Marker(
                location=[site["lat"], site["long"]],
                icon=folium.DivIcon(html=icon_html),
                tooltip=folium.Tooltip(f"<b>Sensor Name:</b> {sensor_name}"),
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
        <h3 style="color: var(--text-color); margin: 0 0 10px 0; text-align: center; font-size: 1.3rem; font-weight: 600;">Recorded Data (2024) vs. Predicted (2025)</h3>
        <hr style="border: none; border-top: 1px solid rgba(128,128,128,0.3); margin-bottom: 15px;">
        <div style="display: flex; gap: 15px; height: 100%;">
            <div style="flex: 1; background-color: var(--secondary-background-color); padding: 20px; border-radius: 12px; border: 1px solid rgba(128,128,128,0.2); box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); text-align: center; display: flex; flex-direction: column; justify-content: center;">
                <p style="color: var(--text-color); opacity: 0.7; font-size: 13px; margin-bottom: 5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Recorded (2024)</p>
                <p style="color: #3b82f6; font-size: 40px; font-weight: bold; margin: 0; line-height: 1;">{acc_2024:.0f}</p>
            </div>
            <div style="flex: 1; background-color: var(--secondary-background-color); padding: 20px; border-radius: 12px; border: 1px solid rgba(128,128,128,0.2); box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); text-align: center; display: flex; flex-direction: column; justify-content: center;">
                <p style="color: var(--text-color); opacity: 0.7; font-size: 13px; margin-bottom: 5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Predicted (2025)</p>
                <p style="color: #ef4444; font-size: 40px; font-weight: bold; margin: 0; line-height: 1;">{acc_pred:.0f}</p>
            </div>
        </div>
    </div>
    <div style="width: 1px; background-color: rgba(128,128,128,0.3); margin: 0 10px;"></div>
    <div style="flex: 3; display: flex; flex-direction: column;">
        <h3 style="color: var(--text-color); margin: 0 0 10px 0; text-align: center; font-size: 1.3rem; font-weight: 600;">Demographics</h3>
        <hr style="border: none; border-top: 1px solid rgba(128,128,128,0.3); margin-bottom: 15px;">
        <div style="display: flex; gap: 15px; height: 100%;">
            <div style="flex: 1; background-color: var(--secondary-background-color); padding: 15px; border-radius: 12px; border: 1px solid rgba(128,128,128,0.2); box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); display: flex; align-items: center; gap: 10px;">
                <div style="background-color: rgba(16, 185, 129, 0.2); padding: 10px; border-radius: 10px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
                </div>
                <div>
                    <p style="color: var(--text-color); opacity: 0.7; font-size: 12px; margin: 0; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Population</p>
                    <p style="color: var(--text-color); font-size: 20px; font-weight: bold; margin: 0; line-height: 1.2;">{pop_str}</p>
                </div>
            </div>
            <div style="flex: 1; background-color: var(--secondary-background-color); padding: 15px; border-radius: 12px; border: 1px solid rgba(128,128,128,0.2); box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); display: flex; align-items: center; gap: 10px;">
                <div style="background-color: rgba(245, 158, 11, 0.2); padding: 10px; border-radius: 10px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 5a8 8 0 0 0-14 5.5 8 8 0 0 0 14 5.5"></path><line x1="3" y1="9" x2="14" y2="9"></line><line x1="3" y1="12" x2="14" y2="12"></line></svg>
                </div>
                <div>
                    <p style="color: var(--text-color); opacity: 0.7; font-size: 12px; margin: 0; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Avg Income</p>
                    <p style="color: var(--text-color); font-size: 20px; font-weight: bold; margin: 0; line-height: 1.2;">{income_str}</p>
                </div>
            </div>
            <div style="flex: 1; background-color: var(--secondary-background-color); padding: 15px; border-radius: 12px; border: 1px solid rgba(128,128,128,0.2); box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); display: flex; align-items: center; gap: 10px;">
                <div style="background-color: rgba(139, 92, 246, 0.2); padding: 10px; border-radius: 10px;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                </div>
                <div>
                    <p style="color: var(--text-color); opacity: 0.7; font-size: 12px; margin: 0; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Avg Age</p>
                    <p style="color: var(--text-color); font-size: 20px; font-weight: bold; margin: 0; line-height: 1.2;">{age_str}</p>
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
        pd.to_numeric(merged_gdf[TYPE_COLS].mean(numeric_only=True))
        .round(decimals=0)
        .fillna(0)
        .tolist()
    )
    muni_counts = (
        pd.to_numeric(row[TYPE_COLS], errors="coerce").round(0).fillna(0).tolist()
    )

    profile_df = pd.DataFrame(
        {
            "Accident Type": TYPE_LABELS * 2,
            "Count": muni_counts + global_means,
            "Scope": [muni_name] * len(TYPE_LABELS)
            + ["Global Average"] * len(TYPE_LABELS),
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
        ),
        margin=dict(t=50, b=0, l=0, r=30),
        height=400,
        yaxis=dict(autorange="reversed"),
    )
    fig_types.update_xaxes(showticklabels=False, showgrid=False)

    st.plotly_chart(
        fig_types,
        use_container_width=True,
        theme="streamlit",
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

        if b64_images:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("### Legend")
            st.markdown(
                "<p style='color: #a1a1aa; font-size: 14px;'>Most Important accident type per municipality.</p>",
                unsafe_allow_html=True,
            )

            legend_rows = "".join(f"""
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 10px;">
                    <div style="
                        background-color: rgba(140, 140, 140, 0.7);
                        border-radius: 8px;
                        width: 36px; height: 36px;
                        display: flex; align-items: center; justify-content: center;
                        flex-shrink: 0;
                    ">
                        <img src="{data_uri}" width="22" height="22"
                             style="object-fit: contain;">
                    </div>
                    <span style="font-size: 14px; color: var(--text-color);">
                        {KEY_TO_LABEL.get(key, key.replace('_', ' ').title())}
                    </span>
                </div>
                """ for key, data_uri in sorted(b64_images.items()))

            st.markdown(
                f"""
                <div style="
                    background-color: var(--secondary-background-color);
                    border: 1px solid rgba(128,128,128,0.2);
                    border-radius: 12px;
                    padding: 14px 16px;
                ">
                    {legend_rows}
                </div>
                """,
                unsafe_allow_html=True,
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

        map_cols_clean = [c for c in MAP_COLS if c in gdf_has_data.columns]

        folium.GeoJson(
            gdf_has_data[map_cols_clean],
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
