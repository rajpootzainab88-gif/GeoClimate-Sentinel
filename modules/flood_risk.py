"""
Flood Risk Index (FRI) - simplified for a 2-3 day build.

Full Sentinel-1 SAR change-detection flood mapping (comparing pre/post-flood
imagery) is powerful but slow to get right. For the timeline you have, use
these globally available, fast-to-compute proxies instead - they are
defensible in a report and still produce a convincing map:

FRI = w1*(1 - slope_norm) + w2*rainfall_norm + w3*water_proximity_norm + w4*low_ndvi_norm

Datasets:
- DEM        : SRTM 30m -> slope (flat land = higher risk)
- Rainfall   : CHIRPS daily, summed over period -> rainfall_norm
- Surface water: JRC Global Surface Water (occurrence) -> proximity/occurrence proxy
- Land cover : ESA WorldCover -> flag cropland/bare/built-up as more exposed than forest

If you also have Sentinel-1 working, add it as a bonus 5th factor - see the
optional function at the bottom.
"""

import ee
from modules.gee_utils import normalize, region_stats, classify_risk

WEIGHTS = {"slope_inv": 0.30, "rainfall": 0.30, "water_occurrence": 0.25, "landcover": 0.15}


def _slope(aoi):
    dem = ee.Image("USGS/SRTMGL1_003")
    slope = ee.Terrain.slope(dem).rename("slope")
    return slope


def _rainfall_sum(aoi, start, end):
    col = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate(start, end).filterBounds(aoi)
    return col.sum().rename("rainfall")


def _water_occurrence(aoi):
    gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
    return gsw.unmask(0).rename("water_occ")  # 0-100 scale


def _flood_exposed_landcover_fraction(aoi):
    """Fraction of AOI in cropland/built-up/bare (more exposed) vs forest/wetland (buffer)."""
    lc = ee.ImageCollection("ESA/WorldCover/v200").first()
    exposed = lc.eq(40).Or(lc.eq(50)).Or(lc.eq(60))  # cropland, built-up, bare
    frac = exposed.rename("exposed").reduceRegion(
        reducer=ee.Reducer.mean(), geometry=aoi, scale=30, maxPixels=1e9, bestEffort=True
    )
    return frac.get("exposed")


def compute_flood_risk(aoi, start="2024-06-01", end="2024-09-30"):
    """
    `start`/`end` should typically cover the wet/monsoon season for the AOI's region.
    Returns:
        risk_image : ee.Image, single band 'FRI' (0-1)
        stats      : dict of raw + normalized indicator means and final score
    """
    slope = _slope(aoi)
    rainfall = _rainfall_sum(aoi, start, end)
    water_occ = _water_occurrence(aoi)
    exposed_frac = _flood_exposed_landcover_fraction(aoi)

    slope_n = normalize(slope, "slope", aoi, scale=90)
    rainfall_n = normalize(rainfall, "rainfall", aoi, scale=5000)
    water_n = normalize(water_occ, "water_occ", aoi, scale=30)

    fri = (
        ee.Image(1).subtract(slope_n).multiply(WEIGHTS["slope_inv"])
        .add(rainfall_n.multiply(WEIGHTS["rainfall"]))
        .add(water_n.multiply(WEIGHTS["water_occurrence"]))
        .add(ee.Image.constant(exposed_frac).multiply(WEIGHTS["landcover"]))
        .rename("FRI")
        .clamp(0, 1)
        .clip(aoi)
    )

    raw_stats = region_stats(slope.addBands(rainfall), aoi, scale=200)
    score = region_stats(fri, aoi, scale=100).get("FRI")

    stats = {
        "mean_slope_deg": raw_stats.get("slope"),
        "total_rainfall_mm": raw_stats.get("rainfall"),
        "exposed_landcover_fraction": exposed_frac.getInfo(),
        "flood_risk_score": score,
        "flood_risk_class": classify_risk(score),
    }
    return fri, stats


# --- OPTIONAL bonus factor if you get Sentinel-1 working (adds real SAR evidence) ---
def sentinel1_water_signal(aoi, flood_start, flood_end, baseline_start, baseline_end):
    """
    Simple SAR flood proxy: VH backscatter drop during a flood period vs a dry baseline.
    Water surfaces have low VH backscatter, so a large negative change suggests inundation.
    """
    def vh_mean(s, e):
        col = (
            ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterBounds(aoi)
            .filterDate(s, e)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
            .select("VH")
        )
        return col.mean()

    flood_vh = vh_mean(flood_start, flood_end)
    baseline_vh = vh_mean(baseline_start, baseline_end)
    diff = baseline_vh.subtract(flood_vh).rename("VH_drop")  # positive = likely water
    return diff
