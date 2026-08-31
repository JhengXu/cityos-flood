# -*- coding: utf-8 -*-
"""
multihazard.py — 全自然灾害真实数据汇总 + 3D 场景数据
======================================================
基于统一数据层，为前端分页多灾种界面提供：
  1. 台风：历史影响事件 + 路径 + 最新预报
  2. 风暴潮：潮位站统计 + 波浪事件峰值
  3. 滑坡：隐患点易发性 + 分区统计 + 预警史
  4. 3D 场景：DEM 地形 + 建筑高度 + 灾种点叠加
"""
import os
import json
import numpy as np
import pandas as pd
from . import data_loader

SZ_CENTER = (22.5431, 114.0579)


def _s(v):
    """NaN/None → ''（JSON 安全）。"""
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return ""
    return str(v)


# ============ 台风 ============
def _dist_to_sz(lat, lon):
    dlat = (lat - SZ_CENTER[0]) * 111.0
    dlon = (lon - SZ_CENTER[1]) * 111.0 * np.cos(np.radians(SZ_CENTER[0]))
    return np.sqrt(dlat**2 + dlon**2)


def _wind_level(kt):
    if kt is None or (isinstance(kt, float) and np.isnan(kt)):
        return "unknown"
    if kt >= 100: return "super_typhoon"
    if kt >= 85: return "severe_typhoon"
    if kt >= 65: return "typhoon"
    if kt >= 48: return "sts"
    if kt >= 34: return "ts"
    return "td"


_LEVEL_LABEL = {
    "super_typhoon": "超强台风", "severe_typhoon": "强台风", "typhoon": "台风",
    "sts": "强热带风暴", "ts": "热带风暴", "td": "热带低压", "unknown": "未知",
}


def typhoon_summary():
    trk = data_loader.typhoon_track()
    if trk is None:
        return {"events": [], "n": 0, "source": "IBTrACS(未接入)"}
    trk = trk.copy()
    trk["lat"] = pd.to_numeric(trk["lat"], errors="coerce")
    trk["lon"] = pd.to_numeric(trk["lon"], errors="coerce")
    trk["wmo_wind"] = pd.to_numeric(trk["wmo_wind"], errors="coerce")
    trk["wmo_pres"] = pd.to_numeric(trk["wmo_pres"], errors="coerce")
    trk = trk.dropna(subset=["lat", "lon"])
    events = []
    for sid, grp in trk.groupby("sid"):
        grp = grp.sort_values("iso_time")
        dists = _dist_to_sz(grp["lat"].values, grp["lon"].values)
        min_dist = float(np.min(dists))
        if min_dist < 300:
            closest = grp.iloc[int(np.argmin(dists))]
            peak_wind = grp["wmo_wind"].max()
            min_pres = grp["wmo_pres"].min()
            level = _wind_level(peak_wind)
            events.append({
                "sid": sid, "name": (grp["name"].iloc[0] or "").strip(),
                "season": int(grp["season"].iloc[0]) if pd.notna(grp["season"].iloc[0]) else 0,
                "min_dist_km": round(min_dist, 1),
                "peak_wind_kt": None if pd.isna(peak_wind) else round(float(peak_wind), 1),
                "min_pres_hpa": None if pd.isna(min_pres) else round(float(min_pres), 1),
                "level": level, "level_label": _LEVEL_LABEL.get(level, level),
                "closest_lat": round(float(closest["lat"]), 3),
                "closest_lon": round(float(closest["lon"]), 3),
                "closest_time": str(closest["iso_time"]),
            })
    events.sort(key=lambda e: e["season"])
    levels = {}
    for e in events:
        levels[e["level"]] = levels.get(e["level"], 0) + 1
    return {"events": events, "n": len(events), "levels": levels,
            "source": "IBTrACS v04r01 (2014-2026)"}


def typhoon_track_points(name=None, sid=None, limit=250):
    """单个台风路径点（供地图/3D 绘制）。支持中文名（name_zh 映射 name_en）。"""
    trk = data_loader.typhoon_track()
    if trk is None:
        return []
    trk = trk.copy()
    sub = None
    if name:
        sub = trk[trk["name"] == name]
        # 中文名 → 经由气象局预报表的 name_zh 映射到 IBTrACS 英文名
        if sub is None or len(sub) == 0:
            try:
                fc = data_loader.typhoon_forecast()
                if fc is not None and len(fc):
                    m = fc[fc["name_zh"] == name]
                    if len(m):
                        en = m.iloc[0].get("name_en")
                        if en and str(en) != "nan":
                            sub = trk[trk["name"] == str(en)]
            except Exception:
                pass
    elif sid:
        sub = trk[trk["sid"] == sid]
    if sub is None or len(sub) == 0:
        return []
    sub = sub.sort_values("iso_time")
    out = []
    for _, r in sub.iterrows():
        out.append({
            "lat": float(r["lat"]), "lon": float(r["lon"]),
            "wind_kt": None if pd.isna(r["wmo_wind"]) else float(r["wmo_wind"]),
            "pres_hpa": None if pd.isna(r["wmo_pres"]) else float(r["wmo_pres"]),
            "time": str(r["iso_time"]), "level": _wind_level(r["wmo_wind"]),
        })
    return out[-limit:]


# ============ 风暴潮 ============
def surge_summary():
    tide = data_loader.tide()
    wv = data_loader.wave()
    stations = []
    if tide is not None:
        tide = tide.copy()
        tide["tide_m"] = pd.to_numeric(tide["tide_m"], errors="coerce")
        tide = tide.dropna(subset=["tide_m"])   # 潮位缺测行剔除，防 NaN
        for sid, grp in tide.groupby("station_id"):
            stations.append({
                "station_id": sid, "name": grp["station_name"].iloc[0],
                "lat": float(grp["lat"].iloc[0]), "lon": float(grp["lon"].iloc[0]),
                "datum": grp["datum"].iloc[0],
                "years": sorted(int(y) for y in grp["year"].unique()),
                "max_tide_m": round(float(grp["tide_m"].max()), 3),
                "mean_tide_m": round(float(grp["tide_m"].mean()), 3),
                "tidal_range_m": round(float(grp["tide_m"].max() - grp["tide_m"].min()), 3),
            })
    ev_names = {"mangkhut_2018": "山竹2018", "hato_2017": "天鸽2017",
                "saola_2023": "苏拉2023", "rain_0907_2023": "9·7暴雨2023"}
    wave_events = []
    if wv is not None:
        wv = wv.copy()
        wv["swh_m"] = pd.to_numeric(wv["swh_m"], errors="coerce")
        wv = wv.dropna(subset=["swh_m"])   # 波高缺测剔除
        for ev, grp in wv.groupby("event_key"):
            pts = {}
            for pt, pgrp in grp.groupby("point_key"):
                pts[pgrp["point_name"].iloc[0]] = round(float(pgrp["swh_m"].max()), 2)
            wave_events.append({"event": ev, "event_name": ev_names.get(ev, ev),
                                "max_swh_m": round(float(grp["swh_m"].max()), 2), "by_point": pts})
    return {"stations": stations, "wave_events": wave_events,
            "source": "HKO 验潮站(CD)+CMEMS WAVERYS"}


# ============ 滑坡 ============
def _susceptibility(slope, height, risk_param):
    s = min((slope or 0) / 80.0 * 50.0, 50.0)
    h = min((height or 0) / 90.0 * 30.0, 30.0)
    r = min((risk_param or 0) / 130.0 * 20.0, 20.0)
    return round(s + h + r, 1)


def _risk_level(score):
    if score >= 70: return {"level": 4, "label": "高风险"}
    if score >= 50: return {"level": 3, "label": "较高风险"}
    if score >= 30: return {"level": 2, "label": "中风险"}
    return {"level": 1, "label": "低风险"}


def landslide_summary():
    pts = data_loader.landslide_points()
    if pts is None:
        return {"points": [], "n": 0}
    pts = pts.copy()
    out = []
    for _, r in pts.iterrows():
        if pd.isna(r.get("lon")) or pd.isna(r.get("lat")):
            continue
        slope = float(r["slope_max_deg"]) if pd.notna(r.get("slope_max_deg")) else 0
        height = float(r["height_max_m"]) if pd.notna(r.get("height_max_m")) else 0
        rp = float(r["risk_param"]) if pd.notna(r.get("risk_param")) else 0
        score = _susceptibility(slope, height, rp)
        lv = _risk_level(score)
        out.append({
            "lon": float(r["lon"]), "lat": float(r["lat"]),
            "district": _s(r.get("district")), "street": _s(r.get("street")),
            "site": _s(r.get("site_desc")),
            "slope_deg": None if pd.isna(r.get("slope_max_deg")) else float(r["slope_max_deg"]),
            "height_m": None if pd.isna(r.get("height_max_m")) else float(r["height_max_m"]),
            "susceptibility": score,
            "risk_level": lv["level"], "risk_label": lv["label"],
        })
    # 分区统计
    df = pd.DataFrame(out)
    districts = []
    if len(df):
        for dist, grp in df.groupby("district"):
            districts.append({"district": dist, "n": int(len(grp)),
                              "n_high": int((grp["risk_level"] >= 3).sum()),
                              "max_susceptibility": float(grp["susceptibility"].max())})
        districts.sort(key=lambda x: -x["n"])
    warnings = {}
    w = data_loader.landslide_warnings()
    if w is not None and "warning_level" in w.columns:
        warnings = w["warning_level"].value_counts().to_dict()
    return {"points": out, "n": len(out), "districts": districts, "warnings": warnings,
            "source": "深圳市规划和自然资源局 300 隐患点"}


# ============ 3D 场景 ============
def scene3d(dem_step=8, building_min_height=40, building_limit=5000):
    """3D 场景数据：地形高度图 + 建筑 + 灾种点。"""
    # DEM
    dem_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "shenzhen-flood",
        "data", "processed", "shenzhen_dem30.npy"))
    meta_path = dem_path.replace("shenzhen_dem30.npy", "shenzhen_dem30_meta.json")
    terrain = None
    if os.path.exists(dem_path):
        dem = np.load(dem_path)
        meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
        dem_small = dem[::dem_step, ::dem_step]
        # NaN → 0（海面/无数据），确保 JSON 兼容
        dem_small = np.nan_to_num(dem_small, nan=0.0, posinf=0.0, neginf=0.0)
        h, w = dem_small.shape
        lon0 = meta.get("lon0", 113.72); lat0 = meta.get("lat0", 22.87)
        cell = meta.get("cell_deg", 0.00027777778) * dem_step
        terrain = {
            "shape": [h, w], "lon0": lon0, "lat0": lat0, "cell_deg": cell,
            "lon1": round(lon0 + w * cell, 5), "lat1": round(lat0 - h * cell, 5),
            "elev_min": float(np.nanmin(dem_small)), "elev_max": float(np.nanmax(dem_small)),
            "heights": dem_small.astype(np.float32).tolist(),
        }
    # 建筑
    buildings = []
    b = data_loader.buildings()
    if b is not None:
        b = b.copy()
        b = b[b["coord_status"] == "with_geom"].dropna(subset=["lon", "lat", "height_m"])
        b["height_m"] = pd.to_numeric(b["height_m"], errors="coerce")
        b = b[b["height_m"] >= building_min_height].sort_values("height_m", ascending=False)
        if len(b) > building_limit:
            b = b.head(building_limit)
        for _, r in b.iterrows():
            h = float(r["height_m"])
            if not np.isfinite(h):
                continue
            nm = r.get("name")
            if nm is None or (isinstance(nm, float) and not np.isfinite(nm)):
                nm = ""
            buildings.append({"lon": float(r["lon"]), "lat": float(r["lat"]),
                              "height_m": h, "name": str(nm)})
    # 灾种点
    pts = {"flood": [], "landslide": [], "marine": []}
    fp = data_loader.floodpoints()
    if fp is not None:
        fp = fp.dropna(subset=["lat", "lon"])
        for _, r in fp.head(200).iterrows():
            pts["flood"].append({"lon": float(r["lon"]), "lat": float(r["lat"]),
                                 "district": r.get("district")})
    ls = landslide_summary()["points"]
    for p in ls:
        pts["landslide"].append({"lon": p["lon"], "lat": p["lat"],
                                 "risk_level": p["risk_level"], "district": p["district"]})
    su = surge_summary()
    for st in su["stations"]:
        pts["marine"].append({"lon": st["lon"], "lat": st["lat"], "name": st["name"], "type": "tide"})
    return {"terrain": terrain, "buildings": buildings, "points": pts,
            "provenance": "DEM(Copernicus 30m)/建筑(OSM)/滑坡(规自局)/潮位(HKO)/内涝点(天地图)"}