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
