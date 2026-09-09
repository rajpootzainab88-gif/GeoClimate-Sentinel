import json
import ee
import streamlit as st

EE_PROJECT = "skilful-webbing-475409-t1"

@st.cache_resource
def init_ee():
    """Initialize Earth Engine once per app session."""
    try:
        ee.Initialize(project=EE_PROJECT)
    except Exception:
        try:
            # Read JSON string directly from secrets
            json_str = st.secrets["gee_service_account"]["json_key"]
            key_info = json.loads(json_str)
            
            credentials = ee.ServiceAccountCredentials(
                key_info["client_email"],
                key_data=key_info["private_key"]
            )
            ee.Initialize(credentials, project=EE_PROJECT)
        except Exception as e:
            st.error(f"Could not connect to Google Earth Engine: {e}")
def aoi_from_geojson(geojson_data):
    """Convert Streamlit Folium drawn GeoJSON features to Earth Engine Geometry."""
    try:
        coords = geojson_data["geometry"]["coordinates"]
        geom_type = geojson_data["geometry"]["type"]
        if geom_type == "Polygon":
            return ee.Geometry.Polygon(coords)
        elif geom_type == "MultiPolygon":
            return ee.Geometry.MultiPolygon(coords)
        elif geom_type == "Point":
            return ee.Geometry.Point(coords)
        else:
            def normalize(image, min_val=0, max_val=1):
    """Normalize an EE image to a specified range."""
    bv = image.reduceRegion(
        reducer=ee.Reducer.minMax(),
        geometry=image.geometry(),
        scale=1000,
        maxPixels=1e9
    )
    # Simple min-max scaling helper
    return image.unitScale(0, 100).clamp(min_val, max_val)

def region_stats(image, geometry, scale=1000):
    """Calculate mean statistics for an image over a region."""
    stats = image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geometry,
        scale=scale,
        maxPixels=1e9
    )
    return stats

def classify_risk(value):
    """Classify continuous risk values into distinct levels."""
    if value > 0.75:
        return "High Risk"
    elif value > 0.4:
        return "Moderate Risk"
    else:
        return "Low Risk"
            return ee.Geometry(geojson_data["geometry"])
    except Exception as e:
        st.error(f"Error parsing spatial boundary: {e}")
        return None
