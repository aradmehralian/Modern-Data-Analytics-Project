import streamlit as st
import geopandas as gpd
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Interactive Flanders Map", layout="wide")
st.title("Flanders Cyclist Risk Assessment")


@st.cache_data
def load_data():
    gdf = gpd.read_file("data/Shapefile/Refgem.shp")
    gdf = gdf.to_crs(epsg=4326)
    df = pd.read_csv("data/tiers.csv")

    # 1. Clean the strings before merging
    gdf["join_key"] = gdf["NAAM"].astype(str).str.strip().str.lower()
    df["join_key"] = df["gemeente"].astype(str).str.strip().str.lower()

    merged_gdf = gdf.merge(df, on="join_key", how="left")

    # 2. Copy the index into a real column so Plotly can natively hide it
    merged_gdf["loc_id"] = merged_gdf.index

    return merged_gdf


with st.spinner("Loading interactive map..."):
    merged_gdf = load_data()

# Split the data into two groups
gdf_no_data = merged_gdf[merged_gdf["risk_tier"].isna()]
gdf_has_data = merged_gdf[merged_gdf["risk_tier"].notna()]

tier_colors = {"Red": "#ef4444", "Yellow": "#facc15", "Green": "#22c55e"}

# 3. Build Trace 1: Unmapped municipalities
fig = px.choropleth(
    gdf_no_data,
    geojson=gdf_no_data.geometry,
    locations="loc_id",
    color_discrete_sequence=["rgba(255, 255, 255, 0.05)"],
    hover_name="NAAM",
    hover_data={"loc_id": False, "join_key": False},
)

# 4. Build Trace 2: Mapped municipalities
if not gdf_has_data.empty:
    fig_mapped = px.choropleth(
        gdf_has_data,
        geojson=gdf_has_data.geometry,
        locations="loc_id",
        color="risk_tier",
        color_discrete_map=tier_colors,
        hover_name="NAAM",
        hover_data={
            "loc_id": False,
            "risk_tier": True,
            "predicted_num_accidents": ":.0f",
            "accidents_per_100_cyclists": ":.3f",
            "people_that_cycle": ":.0f",
            "gemeente": False,
            "join_key": False,
        },
    )

    for trace in fig_mapped.data:
        fig.add_trace(trace)

# 5. Apply styling
fig.update_traces(marker_line_color="white", marker_line_width=0.5)

fig.update_geos(
    visible=False,
    bgcolor="rgba(0,0,0,0)",
    projection_type="mercator",
    lonaxis_range=[2.53, 5.92],
    lataxis_range=[50.67, 51.51],
)

fig.update_layout(
    height=750,
    margin={"r": 0, "t": 0, "l": 0, "b": 0},
    dragmode=False,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    showlegend=False,
)

# --- NEW CONFIGURATION SECTION ---
# 6. Define the exact UI rules for the Plotly toolbar and interactions
# Define the exact UI rules for the Plotly toolbar
ui_config = {
    "scrollZoom": False,  # Disables mouse scroll zooming
    "displayModeBar": False,  # COMPLETELY hides the Plotly top menu
}

# Render with the UI config parameter
event = st.plotly_chart(
    fig,
    use_container_width=True,
    on_select="rerun",
    selection_mode="points",
    config=ui_config,
)

# 8. Capture Clicks
if event and len(event.selection["points"]) > 0:
    clicked_idx = event.selection["points"][0]["location"]

    row = merged_gdf.loc[clicked_idx]
    clicked_name = row["NAAM"]

    if pd.notna(row["risk_tier"]):
        predicted_acc = row["predicted_num_accidents"]
        st.info(
            f"**Selected Municipality:** {clicked_name} | **Predicted Accidents:** {predicted_acc:.0f}"
        )
    else:
        st.info(
            f"**Selected Municipality:** {clicked_name} | **Data:** Not available in dataset"
        )
