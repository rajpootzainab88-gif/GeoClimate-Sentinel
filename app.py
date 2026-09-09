"""
GeoClimate Sentinel
A GIS, Remote Sensing and AI-based web app for climate hazard risk assessment.

Run locally:
    pip install -r requirements.txt
    earthengine authenticate      # one-time
    streamlit run app.py
"""

import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import plotly.graph_objects as go
from geopy.geocoders import Nominatim
import pandas as pd
import requests

from gee_utils import init_ee, aoi_from_geojson
from heat_risk import compute_heat_risk
from flood_risk import compute_flood_risk
from ai_forecast import forecast_next_value, heat_condition_label
from integrated_risk import compute_integrated_risk

st.set_page_config(page_title="GeoClimate Sentinel", page_icon="\U0001F30D", layout="wide")

# Set default map center to Islamabad, Pakistan
DEFAULT_CENTER = [33.6844, 73.0479]

# In session state initialization:
if "map_center" not in st.session_state:
    st.session_state.map_center = [33.6844, 73.0479]
if "map_zoom" not in st.session_state:
    st.session_state.map_zoom = 10
if "forecast_location" not in st.session_state:
    st.session_state.forecast_location = "Islamabad"

def find_best_boundary_match(geolocator, query):
    """
    Nominatim's top search result is often a point (a node), not the actual
    administrative boundary. This searches multiple candidates and returns
    the first one that has a real Polygon/MultiPolygon boundary, preferring
    city/district/county-level results. Falls back to the first result
    (as a point) if no boundary is found at all.
    """
    results = geolocator.geocode(query, timeout=10, geometry="geojson",
                                  exactly_one=False, limit=8)
    if not results:
        return None

    preferred_types = {"administrative", "city", "county", "state_district", "district"}
    boundary_candidates = []
    for r in results:
        geom = r.raw.get("geojson", {})
        if geom.get("type") in ("Polygon", "MultiPolygon"):
            boundary_candidates.append(r)

    for r in boundary_candidates:
        if r.raw.get("type") in preferred_types or r.raw.get("class") == "boundary":
            return r

    if boundary_candidates:
        return boundary_candidates[0]

    return results[0]


def render_legend(title, color_labels):
    """color_labels: list of (css_color, label) tuples, shown as small swatches."""
    swatches = "".join(
        f'<div style="display:flex;align-items:center;margin-right:14px;">'
        f'<div style="width:16px;height:16px;background:{c};margin-right:5px;'
        f'border:1px solid #999;border-radius:2px;"></div>'
        f'<span style="font-size:0.85em;">{l}</span></div>'
        for c, l in color_labels
    )
    st.markdown(
        f'<div style="font-weight:600;margin:6px 0 4px 0;">{title}</div>'
        f'<div style="display:flex;flex-wrap:wrap;">{swatches}</div>',
        unsafe_allow_html=True,
    )


def geotiff_download_button(image, aoi_geojson, scale, filename, button_label, key):
    """Shows a 'Prepare' button that fetches a GeoTIFF from GEE, then a real download button."""
    prepare_key = f"{key}_bytes"
    if st.button(f"Prepare {button_label}", key=f"{key}_prepare"):
        with st.spinner("Requesting GeoTIFF from Earth Engine (may take a few seconds)..."):
            try:
                aoi = aoi_from_geojson(aoi_geojson)
                url = image.getDownloadURL({"scale": scale, "region": aoi, "format": "GEO_TIFF"})
                resp = requests.get(url, timeout=60)
                resp.raise_for_status()
                st.session_state[prepare_key] = resp.content
            except Exception as e:
                st.error(f"GeoTIFF export failed: {e}. Try a smaller AOI or coarser scale.")

    if st.session_state.get(prepare_key):
        st.download_button(
            f"\U0001F4E5 Download {button_label}",
            data=st.session_state[prepare_key],
            file_name=filename,
            mime="image/tiff",
            key=f"{key}_download",
        )


# ---------------- session state ----------------
for k, v in {
    "aoi_geojson": None,
    "heat_result": None,
    "heat_tile_url": None,
    "heat_image": None,
    "flood_result": None,
    "flood_tile_url": None,
    "flood_image": None,
    "map_center": DEFAULT_CENTER,
    "map_zoom": 10,
    "search_marker": None,
    "search_label": None,
    "search_boundary": None,
    "search_bbox": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

init_ee()

# ---------------- sidebar ----------------
st.sidebar.title("\U0001F30D GeoClimate Sentinel")
page = st.sidebar.radio(
    "Menu",
    ["Home", "Global Area Analysis", "Heat Risk", "Flood Risk", "AI Forecast", "Integrated Risk", "Methodology"],
)

# ---------------- HOME ----------------
if page == "Home":
    st.title("\U0001F30D GeoClimate Sentinel")
    st.subheader("A GIS, Remote Sensing and AI-based platform for climate hazard risk assessment")
    st.markdown(
        """
        **Workflow:** search or draw any area on Earth -> pull satellite data from Google Earth Engine
        -> compute Heat Risk, Flood Risk and an AI temperature forecast -> get an
        integrated risk score with decision-support recommendations.

        Start with **Global Area Analysis** to select your area of interest (AOI).
        """
    )

# ---------------- AREA SELECTION ----------------
elif page == "Global Area Analysis":
    st.header("Select an area of interest")
    st.write("Search for a city or district to see its actual boundary highlighted in green, "
             "then either use that boundary directly, or draw your own polygon/rectangle. "
             "Keep it small (city-sized, not country-sized) so Earth Engine can process it quickly.")

    col1, col2 = st.columns([4, 1])
    query = col1.text_input("Search for a location (city, district, place name)", key="search_query",
                             label_visibility="collapsed", placeholder="e.g. Chakwal District, Pakistan")
    search_clicked = col2.button("Search", use_container_width=True)

    if search_clicked and query:
        with st.spinner("Searching for the boundary..."):
            try:
                geolocator = Nominatim(user_agent="geoclimate_sentinel_app")
                location = find_best_boundary_match(geolocator, query)
            except Exception as e:
                location = None
                st.error(f"Search failed: {e}")

        if location:
            st.session_state.map_center = [location.latitude, location.longitude]
            st.session_state.search_marker = [location.latitude, location.longitude]
            st.session_state.search_label = location.address

            geojson_geom = location.raw.get("geojson")
            if geojson_geom and geojson_geom.get("type") in ("Polygon", "MultiPolygon"):
                st.session_state.search_boundary = geojson_geom
            else:
                st.session_state.search_boundary = None
                st.info("No boundary polygon available for this search result "
                         "(common for very small places) - showing a marker instead. "
                         "Try adding 'District' to your search, e.g. 'Chakwal District, Pakistan'.")

            bbox = location.raw.get("boundingbox")
            if bbox:
                south, north, west, east = map(float, bbox)
                st.session_state.search_bbox = [[south, west], [north, east]]
            else:
                st.session_state.search_bbox = None

            st.session_state.map_zoom = 11
            st.success(f"Found: {location.address}")
        else:
            st.warning("Location not found. Try a different or more specific search term.")

    m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)

    if st.session_state.search_boundary:
        folium.GeoJson(
            st.session_state.search_boundary,
            name="Searched boundary",
            style_function=lambda feature: {
                "fillColor": "green",
                "color": "green",
                "weight": 3,
                "fillOpacity": 0.15,
            },
            tooltip=st.session_state.search_label,
        ).add_to(m)
        if st.session_state.search_bbox:
            m.fit_bounds(st.session_state.search_bbox)
    elif st.session_state.search_marker:
        folium.Marker(
            location=st.session_state.search_marker,
            popup=st.session_state.search_label,
            tooltip=st.session_state.search_label,
            icon=folium.Icon(color="green", icon="ok-sign"),
        ).add_to(m)

    Draw(export=False, draw_options={"polygon": True, "rectangle": True,
                                      "circle": False, "marker": False, "polyline": False}).add_to(m)

    output = st_folium(m, height=500, width=None, key="aoi_map")

    if output and output.get("last_active_drawing"):
        st.session_state.aoi_geojson = output["last_active_drawing"]["geometry"]
        st.success("AOI captured from your drawing. Go to Heat Risk / Flood Risk to run the analysis.")
    elif st.session_state.search_boundary:
        if st.button("Use this highlighted boundary as my AOI"):
            st.session_state.aoi_geojson = st.session_state.search_boundary
            st.success("AOI set to the searched boundary. Go to Heat Risk / Flood Risk to run the analysis.")
    elif st.session_state.aoi_geojson:
        st.info("Using previously selected AOI. Draw a new shape or search+use a new boundary to replace it.")

# ---------------- HEAT RISK ----------------
elif page == "Heat Risk":
    st.header("\U0001F525 Heat Risk Assessment")
    if not st.session_state.aoi_geojson:
        st.warning("Select an AOI first under 'Global Area Analysis'.")
    else:
        col1, col2 = st.columns(2)
        start = col1.date_input("Start date")
        end = col2.date_input("End date")

        if start == end:
            st.info("Tip: pick an End date several months after Start date, and make sure both dates "
                     "are in the past - Earth Engine has no data for future dates.")

        if st.button("Analyze heat risk"):
            if start == end:
                st.error("Start date and End date cannot be the same. Please widen the date range.")
            else:
                with st.spinner("Running LST / NDVI / NDBI analysis on Google Earth Engine..."):
                    aoi = aoi_from_geojson(st.session_state.aoi_geojson)
                    hri_image, stats = compute_heat_risk(aoi, str(start), str(end))
                    map_id = hri_image.getMapId({"min": 0, "max": 1, "palette": ["green", "yellow", "orange", "red"]})
                    st.session_state.heat_result = stats
                    st.session_state.heat_tile_url = map_id["tile_fetcher"].url_format
                    st.session_state.heat_image = hri_image
                    st.session_state["heat_tiff_bytes"] = None  # clear any stale export

        if st.session_state.heat_result:
            stats = st.session_state.heat_result
            st.metric("Mean LST (\u00b0C)", round(stats["mean_lst_c"], 1) if stats["mean_lst_c"] else "N/A")
            st.metric("Overall Heat Risk", stats["heat_risk_class"])

            m = folium.Map(location=st.session_state.map_center, zoom_start=9)
            folium.TileLayer(tiles=st.session_state.heat_tile_url, attr="GEE",
                              name="Heat Risk", overlay=True).add_to(m)
            st_folium(m, height=450, width=None, key="heat_map")

            render_legend("Heat Risk Index", [
                ("green", "Low"), ("yellow", "Moderate"), ("orange", "High"), ("red", "Very High"),
            ])

            st.subheader("Download results")
            df = pd.DataFrame([stats])
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            st.download_button("\U0001F4E5 Download stats as CSV", data=csv_bytes,
                                file_name="heat_risk_stats.csv", mime="text/csv", key="heat_csv")
            geotiff_download_button(st.session_state.heat_image, st.session_state.aoi_geojson,
                                     scale=100, filename="heat_risk.tif",
                                     button_label="Heat Risk GeoTIFF", key="heat_tiff")

# ---------------- FLOOD RISK ----------------
elif page == "Flood Risk":
    st.header("\U0001F30A Flood Risk Assessment")
    if not st.session_state.aoi_geojson:
        st.warning("Select an AOI first under 'Global Area Analysis'.")
    else:
        col1, col2 = st.columns(2)
        start = col1.date_input("Season start (e.g. monsoon start)", key="fs")
        end = col2.date_input("Season end", key="fe")

        if start == end:
            st.info("Tip: pick a Season end several months after Season start, and make sure both dates "
                     "are in the past - Earth Engine has no data for future dates.")

        if st.button("Analyze flood risk"):
            if start == end:
                st.error("Season start and Season end cannot be the same. Please widen the date range.")
            else:
                with st.spinner("Running slope / rainfall / surface-water analysis..."):
                    aoi = aoi_from_geojson(st.session_state.aoi_geojson)
                    fri_image, stats = compute_flood_risk(aoi, str(start), str(end))
                    map_id = fri_image.getMapId({"min": 0, "max": 1, "palette": ["white", "lightblue", "blue", "darkblue"]})
                    st.session_state.flood_result = stats
                    st.session_state.flood_tile_url = map_id["tile_fetcher"].url_format
                    st.session_state.flood_image = fri_image
                    st.session_state["flood_tiff_bytes"] = None

        if st.session_state.flood_result:
            stats = st.session_state.flood_result
            st.metric("Total rainfall (mm)", round(stats["total_rainfall_mm"], 1) if stats["total_rainfall_mm"] else "N/A")
            st.metric("Overall Flood Risk", stats["flood_risk_class"])

            m = folium.Map(location=st.session_state.map_center, zoom_start=9)
            folium.TileLayer(tiles=st.session_state.flood_tile_url, attr="GEE",
                              name="Flood Risk", overlay=True).add_to(m)
            st_folium(m, height=450, width=None, key="flood_map")

            render_legend("Flood Risk Index", [
                ("white", "Low"), ("lightblue", "Moderate"), ("blue", "High"), ("darkblue", "Very High"),
            ])

            st.subheader("Download results")
            df = pd.DataFrame([stats])
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            st.download_button("\U0001F4E5 Download stats as CSV", data=csv_bytes,
                                file_name="flood_risk_stats.csv", mime="text/csv", key="flood_csv")
            geotiff_download_button(st.session_state.flood_image, st.session_state.aoi_geojson,
                                     scale=100, filename="flood_risk.tif",
                                     button_label="Flood Risk GeoTIFF", key="flood_tiff")

# ---------------- AI FORECAST ----------------
elif page == "AI Forecast":
    st.header("\U0001F916 AI Temperature Forecast")
    st.caption(
        "You can enter today's temperature readings for **any location** and get a next-day "
        "Tmax prediction. The underlying XGBoost model was trained on Islamabad's temperature "
        "dataset, so predictions are best validated there - for other locations, treat the "
        "output as an indicative estimate rather than a calibrated forecast."
    )

    location_name = st.text_input("Location these readings are for (optional, for your own record)",
                                   placeholder="e.g. Karachi, Pakistan")

    col1, col2, col3 = st.columns(3)
    tmax_c = col1.number_input("Today's Tmax (\u00b0C)", value=35.0, step=0.1, format="%.1f")
    tmin_c = col2.number_input("Today's Tmin (\u00b0C)", value=25.0, step=0.1, format="%.1f")
    tmean_c = col3.number_input("Today's Tmean (\u00b0C)", value=30.0, step=0.1, format="%.1f")

    if st.button("Forecast tomorrow's Tmax"):
        result = forecast_next_value(tmax_c, tmin_c, tmean_c)
        st.session_state.forecast_result = result
        st.session_state.forecast_inputs = (tmax_c, tmin_c, tmean_c)
        st.session_state.forecast_location = location_name or "Unspecified location"

    if st.session_state.get("forecast_result"):
        result = st.session_state.forecast_result
        tmax_in, tmin_in, tmean_in = st.session_state.forecast_inputs
        st.metric(f"Predicted tomorrow's Tmax for {st.session_state.forecast_location} (\u00b0C)",
                  result["predicted_value"])
        st.write("Heat condition:", heat_condition_label(result["predicted_value"]))
        st.caption("Model trained on: Islamabad, Pakistan precipitation/temperature dataset (internship data).")
        if result["is_demo_fallback"]:
            st.warning(
                "No trained model file found in /sample_model - showing a placeholder "
                "value so the app still runs. Drop your saved .json model there to "
                "get real predictions."
            )
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=["Today's Tmax", "Today's Tmin", "Today's Tmean", "Predicted Tomorrow's Tmax"],
            y=[tmax_in, tmin_in, tmean_in, result["predicted_value"]],
            marker_color=["lightgray", "lightgray", "lightgray", "orange"],
        ))
        st.plotly_chart(fig, use_container_width=True)

# ---------------- INTEGRATED RISK ----------------
elif page == "Integrated Risk":
    st.header("\U0001F4CA Integrated Climate Risk")
    heat = st.session_state.heat_result
    flood = st.session_state.flood_result

    if not heat or not flood:
        st.warning("Run Heat Risk and Flood Risk analysis first.")
    else:
        result = compute_integrated_risk(heat["heat_risk_score"], flood["flood_risk_score"])

        c1, c2, c3 = st.columns(3)
        c1.metric("Heat Risk", f"{result['heat_score_100']} / 100")
        c2.metric("Flood Risk", f"{result['flood_score_100']} / 100")
        c3.metric("Overall Risk", f"{result['overall_score_100']} / 100", result["overall_class"])

        st.subheader("Decision-support recommendations")
        for r in result["recommendations"]:
            st.markdown(f"- {r}")

        st.subheader("Download results")
        df = pd.DataFrame([{
            "heat_risk_score_100": result["heat_score_100"],
            "flood_risk_score_100": result["flood_score_100"],
            "overall_risk_score_100": result["overall_score_100"],
            "overall_risk_class": result["overall_class"],
            "recommendations": " | ".join(result["recommendations"]),
        }])
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button("\U0001F4E5 Download integrated risk summary as CSV", data=csv_bytes,
                            file_name="integrated_risk_summary.csv", mime="text/csv", key="integrated_csv")

# ---------------- METHODOLOGY ----------------
elif page == "Methodology":
    st.header("Methodology")
    st.markdown(
    """
    **Heat Risk Index** = 0.35·LST + 0.25·NDBI + 0.25·(1-NDVI) + 0.15·Built-up fraction 
    (MODIS LST, Sentinel-2 NDVI/NDBI, ESA WorldCover) - **works for any location on Earth.** 
    Retrospective: reflects conditions during the selected past date range, not a future forecast.

    **Flood Risk Index** = 0.30·(1-slope) + 0.30·rainfall + 0.25·water occurrence + 0.15·exposed land cover 
    (SRTM DEM, CHIRPS rainfall, JRC Global Surface Water, ESA WorldCover) - **works for any location on Earth.** 
    Retrospective: reflects conditions during the selected past date range, not a future forecast.

    **AI Forecast**: XGBoost model trained on internship-collected daily temperature 
    data for Islamabad (features: today's Tmax/Tmin/Tmean -> predicts tomorrow's Tmax). 
    This is the only genuinely forward-looking component of the app. The tool accepts input 
    for any location, but predictions are validated for Islamabad's climate patterns.

    **Integrated Risk** = weighted combination of Heat Risk and Flood Risk (+ forecast signal).

    Weights are a first-pass calibration for demonstration purposes, not a 
    universally validated standard - state this explicitly in your report.

    **Data availability note**: all satellite datasets used (MODIS, Sentinel-2, CHIRPS, SRTM, 
    ESA WorldCover, JRC Global Surface Water) are historical/retrospective records. Date ranges 
    must be in the past; future dates return no data.
    """
)
