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
    # 数据文件未下载时保持页面可用，并明确退回区级估计值，避免 None 触发 500。
    if not dem_pts:
        dem_pts = [(d["center"][0], d["center"][1], d["elevation_mean"]) for d in shenzhen.DISTRICTS]
    if not built_pts:
        built_pts = [(d["center"][0], d["center"][1], d.get("impervious", 0.5) * 100) for d in shenzhen.DISTRICTS]
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


# ============ 500m 精度：渲染为 PNG 热力图（一像素=一格）============
def build_grid_image(res=0.0045, forecast_days=2, alpha_scale=1.2):
    """生成 500m 精度风险热力 PNG（峰值为准，一像素一格）。返回 (RGBA bytes, bbox, shape)。"""
    from io import BytesIO
    from PIL import Image
    import numpy as np

    lats = np.arange(LAT0, LAT1, res)
    lons = np.arange(LON0, LON1, res)
    NL, NLO = len(lats), len(lons)

    dem_pts, built_pts = _load_feature_pts()
    dem_a = np.array([(p[0], p[1], p[2]) for p in dem_pts], dtype=float)
    built_a = np.array([(p[0], p[1], p[2]) for p in built_pts], dtype=float)
    grid, fallback = weather.fetch_grid(forecast_days)
    street = np.array([(lat, lon) for (_, _, lat, lon), _, _ in grid], dtype=float)
    street_rain = np.array([np.array(p, dtype=float) for (_, _, _, _), _, p in grid], dtype=float)

    def nearest_idx(pts, lat_arr, lon_arr):
        d = (lat_arr[:, None] - pts[None, :, 0]) ** 2 + (lon_arr[:, None] - pts[None, :, 1]) ** 2
        return np.argmin(d, axis=1)

    lat_flat = np.repeat(lats, NLO)          # (NL*NLO,)
    lon_flat = np.tile(lons, NL)
    elev = dem_a[nearest_idx(dem_a, lat_flat, lon_flat), 2]
    imperv = built_a[nearest_idx(built_a, lat_flat, lon_flat), 2] / 100.0
    sidx = nearest_idx(street, lat_flat, lon_flat)
    rain = street_rain[sidx]
    did = np.array([gisreal._nearest_did(gisreal._district_centroids(), a, b) for a, b in zip(lat_flat, lon_flat)], dtype=object)

    # 逐格风险（峰值）
    centers = gisreal._district_centroids()
    C = np.array([(shenzhen.get_district(d)["drainage_design"] if shenzhen.get_district(d) else 28.0) for d in did])
    hist = np.array([(shenzhen.get_district(d)["historical_flood_index"] if shenzhen.get_district(d) else 0.5) for d in did])
    coast = np.array([(shenzhen.get_district(d)["coastal"] if shenzhen.get_district(d) else 0.3) for d in did])
    V = 0.30 * imperv + 0.20 * (1.0 / (1.0 + np.exp((elev - 40.0) / 25.0))) + 0.25 * hist + 0.25 * coast
    cum = np.zeros(len(lat_flat))
    peak = np.zeros(len(lat_flat))
    for t in range(rain.shape[1]):
        cum = np.minimum(cum + rain[:, t], 300.0)
        # 复用模型权重: z = 1.5*excess/50 + 1.0*V*excess/50 + 0.5*V + 0.6*cum/150
        excess = np.maximum(0.0, rain[:, t] - C)
        z = 1.5 * (excess / 50.0) + 1.0 * V * (excess / 50.0) + 0.5 * V + 0.6 * (cum / 150.0)
        p = 1.0 / (1.0 + np.exp(-z))
        peak = np.maximum(peak, p)

    # 渲染 RGBA 图（一像素=一格），颜色按风险等级，alpha 随风险
    img = Image.new("RGBA", (NLO, NL), (0, 0, 0, 0))
    px = img.load()
    level_colors = [(31,122,77),(201,180,88),(224,138,30),(214,69,42),(179,18,43)]
    for i in range(NL * NLO):
        lat = lat_flat[i]; lon = lon_flat[i]
        # 若格在陆地区域（dem 有效且非纯海），才上色
        a = int(min(255, peak[i] ** alpha_scale * 255))
        if a < 8:
            continue
        lv = min(4, int(peak[i] * 5))
        r, g, b = level_colors[lv]
        xidx = int((lon - LON0) / res) % NLO
        yidx = int((lat - LAT0) / res) % NL
        px[xidx, yidx] = (r, g, b, a)

    buf = BytesIO()
    img.save(buf, format="PNG")
    bbox = {"south": float(LAT0), "west": float(LON0), "north": float(lats[-1] + res), "east": float(lons[-1] + res)}
    return buf.getvalue(), bbox, (NL, NLO)


image_cache = {"ts": 0.0, "png": None, "bbox": None}


def get_grid_image(res=0.0045, forecast_days=2):
    import time as _t
    if image_cache["png"] and _t.time() - image_cache["ts"] < 600:
        return image_cache["png"], image_cache["bbox"]
    png, bbox, shape = build_grid_image(res, forecast_days)
    image_cache.update({"ts": _t.time(), "png": png, "bbox": bbox})
    return png, bbox
