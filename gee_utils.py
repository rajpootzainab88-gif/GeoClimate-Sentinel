"""
GEE connection + shared helper functions.

SETUP (do this first, before anything else in the app):
1. Create a Google Cloud project and enable the Earth Engine API:
   https://console.cloud.google.com/  ->  "Earth Engine API" -> Enable
2. Register the project for Earth Engine access:
   https://code.earthengine.google.com/register
3. Locally, run once in your terminal:
       earthengine authenticate
   This opens a browser login and caches a token on your machine.
4. Set EE_PROJECT below to your Cloud project ID.

For deployment (Streamlit Community Cloud etc.) use a SERVICE ACCOUNT
instead of interactive auth - see the "SERVICE ACCOUNT" block below.
"""

import ee
import streamlit as st

EE_PROJECT = "skilful-webbing-475409-t1"  # <-- replace with your GEE Cloud project ID


@st.cache_resource
def init_ee():
    """Initialize Earth Engine once per app session."""
    try:
        ee.Initialize(project=EE_PROJECT)
    except Exception:
        try:
            key_dict = dict(st.secrets["gee_service_account"])
            
            # Clean and reformat private key robustly
            pk = key_dict["private_key"]
            pk = pk.replace("\\n", "\n")
            if not pk.startswith("-----BEGIN PRIVATE KEY-----"):
                pk = f"-----BEGIN PRIVATE KEY-----\n{pk}\n-----END PRIVATE KEY-----\n"
            
            credentials = ee.ServiceAccountCredentials(
                key_dict["client_email"],
                key_data=pk
            )
            ee.Initialize(credentials, project=EE_PROJECT)
        except Exception as e:
            st.error(f"Could not connect to Google Earth Engine: {e}")
        except Exception as e:
            st.error(
                "Could not connect to Google Earth Engine. "
                "Run `earthengine authenticate` locally, or configure a service "
                "account in st.secrets for deployment. "
                f"Details: {e}"
            )
            st.stop()
    return True


def aoi_from_geojson(geojson_geom: dict) -> "ee.Geometry":
    """Convert a GeoJSON geometry (from the drawn/searched AOI) into an ee.Geometry."""
    return ee.Geometry(geojson_geom)


def region_stats(image: "ee.Image", aoi: "ee.Geometry", scale: int = 100, band_names=None) -> dict:
    """Mean-reduce an image over the AOI and return a plain python dict of stats."""
    reducer = ee.Reducer.mean()
    stats = image.reduceRegion(reducer=reducer, geometry=aoi, scale=scale, maxPixels=1e9, bestEffort=True)
    result = stats.getInfo()
    if band_names:
        result = {k: result.get(k) for k in band_names}
    return result


def normalize(image: "ee.Image", band: str, aoi: "ee.Geometry", scale: int = 100) -> "ee.Image":
    """Min-max normalize a single band of an image to 0-1 over the AOI."""
    stats = image.select(band).reduceRegion(
        reducer=ee.Reducer.minMax(), geometry=aoi, scale=scale, maxPixels=1e9, bestEffort=True
    )
    lo = ee.Number(stats.get(band + "_min"))
    hi = ee.Number(stats.get(band + "_max"))
    return image.select(band).subtract(lo).divide(hi.subtract(lo).max(1e-6)).rename(band + "_norm")


def classify_risk(score: float) -> str:
    """Map a 0-1 risk score to a class label."""
    if score is None:
        return "No data"
    if score < 0.20:
        return "Very Low"
    if score < 0.40:
        return "Low"
    if score < 0.60:
        return "Moderate"
    if score < 0.80:
        return "High"
    return "Very High"
