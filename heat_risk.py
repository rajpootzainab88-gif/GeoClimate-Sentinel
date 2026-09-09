"""
Heat Risk Index (HRI)

HRI = w1*LST_norm + w2*NDBI_norm + w3*(1 - NDVI_norm) + w4*BuiltUp_norm

Datasets (all global, all free via GEE):
- LST      : MODIS MOD11A2 (8-day, 1km) - land surface temperature
- NDVI/NDBI: Sentinel-2 SR (10-20m) - vegetation and built-up indices
- Land use : ESA WorldCover 10m - to report % built-up / vegetated / bare
"""

import ee
from modules.gee_utils import normalize, region_stats, classify_risk

# Weights - state clearly in your report that these are a first-pass calibration,
# not a universally validated standard. You can sensitivity-test these later.
WEIGHTS = {"lst": 0.35, "ndbi": 0.25, "ndvi_inv": 0.25, "landcover": 0.15}


def _get_lst(aoi, start, end):
    col = (
        ee.ImageCollection("MODIS/061/MOD11A2")
        .filterDate(start, end)
        .filterBounds(aoi)
        .select("LST_Day_1km")
    )
    lst_k = col.mean().multiply(0.02)  # scale factor -> Kelvin
    lst_c = lst_k.subtract(273.15).rename("LST")
    return lst_c


def _get_s2_indices(aoi, start, end):
    def mask_clouds(img):
        scl = img.select("SCL")
        mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
        return img.updateMask(mask)

    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterDate(start, end)
        .filterBounds(aoi)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30))
        .map(mask_clouds)
    )
    img = col.median()
    ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndbi = img.normalizedDifference(["B11", "B8"]).rename("NDBI")
    return ndvi, ndbi


def _builtup_fraction(aoi):
    """ESA WorldCover 10m -> fraction of AOI classified as built-up (class 50)."""
    lc = ee.ImageCollection("ESA/WorldCover/v200").first()
    builtup_mask = lc.eq(50)
    frac = builtup_mask.rename("builtup").reduceRegion(
        reducer=ee.Reducer.mean(), geometry=aoi, scale=30, maxPixels=1e9, bestEffort=True
    )
    return frac.get("builtup")  # ee.Number, 0-1


def compute_heat_risk(aoi, start="2024-01-01", end="2024-12-31"):
    """
    Returns:
        risk_image : ee.Image, single band 'HRI' (0-1), for map display
        stats      : dict of raw + normalized indicator means and final score
    """
    lst = _get_lst(aoi, start, end)
    ndvi, ndbi = _get_s2_indices(aoi, start, end)

    lst_n = normalize(lst, "LST", aoi, scale=1000)
    ndbi_n = normalize(ndbi, "NDBI", aoi, scale=100)
    ndvi_n = normalize(ndvi, "NDVI", aoi, scale=100)

    builtup_frac = _builtup_fraction(aoi)

    hri = (
        lst_n.multiply(WEIGHTS["lst"])
        .add(ndbi_n.multiply(WEIGHTS["ndbi"]))
        .add(ee.Image(1).subtract(ndvi_n).multiply(WEIGHTS["ndvi_inv"]))
        .add(ee.Image.constant(builtup_frac).multiply(WEIGHTS["landcover"]))
        .rename("HRI")
        .clamp(0, 1)
        .clip(aoi)
    )

    raw_stats = region_stats(lst.addBands(ndvi).addBands(ndbi), aoi, scale=100)
    score = region_stats(hri, aoi, scale=100).get("HRI")

    stats = {
        "mean_lst_c": raw_stats.get("LST"),
        "mean_ndvi": raw_stats.get("NDVI"),
        "mean_ndbi": raw_stats.get("NDBI"),
        "builtup_fraction": builtup_frac.getInfo(),
        "heat_risk_score": score,
        "heat_risk_class": classify_risk(score),
    }
    return hri, stats