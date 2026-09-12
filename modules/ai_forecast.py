
"""
AI Temperature Forecast - wraps YOUR ALREADY-TRAINED XGBoost model.

This matches the actual training notebook (Temperature_XGBoost.ipynb):
- Features (in this exact order): Tmax_C, Tmin_C, Tmean_C  (TODAY's values)
- Target: Tmax_Next_Day_C  (TOMORROW's max temperature)
- No scaler was used during training - raw values go straight into the model.

Do NOT retrain during the capstone build. Load the saved model and just run
inference here.

Expected file:
    sample_model/xgboost_temp_model.json

IMPORTANT (scientific honesty):
This forecast is only valid for the location/time-series the model was
trained on (the Jabalpur precipitation/temperature dataset). Do NOT present
it as a global forecast. In the app, always show which area the model is
calibrated for.
"""

import os
import numpy as np
import streamlit as st

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_model")
TRAINED_FOR_AREA = "Islamabad, Pakistan (model trained on internship-collected rooftop temperature dataset)"
FEATURE_ORDER = ["Tmax_C", "Tmin_C", "Tmean_C"]  # must match training notebook exactly


@st.cache_resource
def load_xgboost_model():
    import xgboost as xgb
    path = os.path.join(MODEL_DIR, "xgboost_temp_model.json")
    if not os.path.exists(path):
        return None
    model = xgb.XGBRegressor()
    model.load_model(path)
    return model


def forecast_next_value(tmax_c: float, tmin_c: float, tmean_c: float):
    """
    tmax_c, tmin_c, tmean_c: TODAY's max/min/mean temperature in Celsius.
    Returns a dict with the prediction for TOMORROW's Tmax, or a clearly
    labeled DEMO value if no trained model file is found.
    """
    model = load_xgboost_model()

    if model is None:
        # Fallback so the UI never crashes - clearly flagged as a placeholder.
        demo_pred = round((tmax_c + tmean_c) / 2, 1)
        return {
            "predicted_value": demo_pred,
            "is_demo_fallback": True,
            "trained_for_area": TRAINED_FOR_AREA,
        }

    x = np.array([[tmax_c, tmin_c, tmean_c]])  # shape (1, 3), matching FEATURE_ORDER
    pred = model.predict(x)[0]

    return {
        "predicted_value": round(float(pred), 1),
        "is_demo_fallback": False,
        "trained_for_area": TRAINED_FOR_AREA,
    }


def heat_condition_label(predicted_tmax: float) -> str:
    if predicted_tmax >= 40:
        return "Severe"
    if predicted_tmax >= 36:
        return "Elevated"
    if predicted_tmax >= 30:
        return "Normal"
    return "Mild"
