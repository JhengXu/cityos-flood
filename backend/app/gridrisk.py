# -*- coding: utf-8 -*-
"""
分区分时内涝风险热力 —— 细化到加密网格（~1.5km 格）
---------------------------------------------------------------
- 网格：深圳 bbox 内按 res(度) 生成格点。
- 每格真实特征：最近 DEM 高程 + 最近 WorldCover 不透水（真实）。
- 每格脆弱性 V = w·(不透水, 高程低洼, 区历史, 临海)。
- 每格降雨：就近街道采样点降雨（多点 Open-Meteo 空间降尺度）。
- 风险：降雨超额 × 街道脆弱性 + 前期饱和 -> 逐时概率。
"""
import os
import numpy as np

from . import gisreal, weather, model, shenzhen

# 深圳 bbox
LAT0, LAT1 = 22.44, 22.88
LON0, LON1 = 113.72, 114.66
DEFAULT_RES = 0.018   # ≈2km；越小越细

# 街道采样点（含区/坐标）
STREETS = shenzhen.SUBDISTRICT_POINTS  # (name, did, lat, lon)


def _load_feature_pts():
    """加载真实 DEM / WorldCover 点，供最近邻查询。"""
    dem = gisreal._read_rows(os.path.join(gisreal.BASE, "shenzhen_dem.csv"))
    built = gisreal._read_rows(os.path.join(gisreal.BASE, "shenzhen_builtup_density.csv"))
    dem_pts = [(float(r["lat"]), float(r["lon"]), float(r["elevation_m"])) for r in dem]
    built_pts = [(float(r["lat"]), float(r["lon"]), float(r["builtup_pct"])) for r in built]
    return dem_pts, built_pts


def _nearest(pts, lat, lon):
    best, bd = None, 1e9
    for (pl, pn, v) in pts:
        d = (pl - lat) ** 2 + (pn - lon) ** 2
        if d < bd:
            bd, best = d, v
    return best


def _grid_cells(res):
    lats = np.arange(LAT0, LAT1, res)
    lons = np.arange(LON0, LON1, res)
    return [(lat, lon) for lat in lats for lon in lons]


def _cell_vulnerability(elev, imperv, district):
    v_imp = imperv
    v_elev = 1.0 / (1.0 + np.exp((elev - 40.0) / 25.0))
    v_hist = district.get("historical_flood_index", 0.5)
    v_coast = district.get("coastal", 0.3)
    V = 0.30 * v_imp + 0.20 * v_elev + 0.25 * v_hist + 0.25 * v_coast
    return float(min(max(V, 0.0), 1.0))


def build_grid_risk(forecast_days=2, res=DEFAULT_RES):
    dem_pts, built_pts = _load_feature_pts()
    grid, fallback = weather.fetch_grid(forecast_days)
    # 街道点降雨
    street_rain = {}
    for (name, did, lat, lon), ts, prec in grid:
        street_rain[(lat, lon)] = np.array(prec, dtype=float)

    def nearest_street_rain(lat, lon):
        best, bd = None, 1e9
        for (slat, slon), prec in street_rain.items():
            d = (slat - lat) ** 2 + (slon - lon) ** 2
            if d < bd:
                bd, best = d, prec
        return best

    cells = []
    # 预取各区特征（脆弱性分母的区历史/临海/排水）
    for lat, lon in _grid_cells(res):
        elev = _nearest(dem_pts, lat, lon)
        imperv = _nearest(built_pts, lat, lon) / 100.0
        did = gisreal._nearest_did(gisreal._district_centroids(), lat, lon)
        d = shenzhen.get_district(did)
        if d is None:
            continue
        V = _cell_vulnerability(elev, imperv, d)
        C = d["drainage_design"]
        rain = nearest_street_rain(lat, lon)
        if rain is None:
            rain = np.zeros(48)
        risk = []
        cum = 0.0
        for R in rain:
            cum = min(cum + R, 300.0)
            risk.append(float(model.MODEL.predict_one(R, cum, C, V)["prob"]))
        cells.append({
            "lat": round(float(lat), 3), "lon": round(float(lon), 3),
            "elevation": round(float(elev), 1), "impervious": round(float(imperv), 3),
            "vulnerability": round(V, 3), "district_id": did,
            "risk": [round(x, 4) for x in risk], "peak": round(max(risk), 4),
        })
    return {"resolution_deg": res, "n_cells": len(cells),
            "source": "fallback-sample" if fallback else "open-meteo-multi-point",
            "cells": cells}


_grid_cache = {"ts": 0.0, "data": None}
import time as _t


def get_grid_risk(forecast_days=2, res=DEFAULT_RES):
    if _grid_cache["data"] and _t.time() - _grid_cache["ts"] < 600:
        return _grid_cache["data"]
    data = build_grid_risk(forecast_days, res)
    _grid_cache["ts"] = _t.time()
    _grid_cache["data"] = data
    return data
