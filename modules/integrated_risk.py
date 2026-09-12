"""Combine Heat Risk + Flood Risk (+ optional forecast signal) into one score."""

from gee_utils import classify_risk

WEIGHTS = {"heat": 0.45, "flood": 0.45, "forecast": 0.10}

RECOMMENDATIONS = {
    "heat": {
        "High": [
            "Increase urban vegetation and tree canopy cover.",
            "Expand shaded public spaces and cool roofs in built-up zones.",
            "Issue heat advisories for vulnerable populations during peak months.",
        ],
        "Very High": [
            "Prioritize urban greening in the highest-NDBI wards immediately.",
            "Establish cooling centers and heat early-warning protocols.",
            "Review zoning to limit further impervious surface expansion.",
        ],
    },
    "flood": {
        "High": [
            "Improve stormwater drainage capacity in low-slope, high-rainfall zones.",
            "Restrict new construction in areas near high water-occurrence zones.",
        ],
        "Very High": [
            "Strengthen flood early-warning and evacuation planning.",
            "Protect critical infrastructure with embankments/drainage upgrades.",
            "Avoid further development in identified flood-prone zones.",
        ],
    },
}


def compute_integrated_risk(heat_score, flood_score, forecast_score=None):
    """All inputs 0-1. forecast_score is optional (e.g. normalized predicted Tmax)."""
    if forecast_score is None:
        # renormalize without the forecast term
        w_heat = WEIGHTS["heat"] / (WEIGHTS["heat"] + WEIGHTS["flood"])
        w_flood = WEIGHTS["flood"] / (WEIGHTS["heat"] + WEIGHTS["flood"])
        overall = heat_score * w_heat + flood_score * w_flood
    else:
        overall = (
            heat_score * WEIGHTS["heat"]
            + flood_score * WEIGHTS["flood"]
            + forecast_score * WEIGHTS["forecast"]
        )

    overall_100 = round(overall * 100)
    overall_class = classify_risk(overall)

    recs = []
    heat_class = classify_risk(heat_score)
    flood_class = classify_risk(flood_score)
    recs += RECOMMENDATIONS["heat"].get(heat_class, [])
    recs += RECOMMENDATIONS["flood"].get(flood_class, [])
    if not recs:
        recs = ["No immediate high-priority actions identified for the current risk levels."]

    return {
        "overall_score_100": overall_100,
        "overall_class": overall_class,
        "heat_score_100": round(heat_score * 100),
        "flood_score_100": round(flood_score * 100),
        "recommendations": recs,
    }
