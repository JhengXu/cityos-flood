# -*- coding: utf-8 -*-
"""
ml_models.py — 已训练监督模型的推理服务
=======================================
加载本地训练的三个真实标签模型，提供预测接口：
  1. flood_spatial    : 内涝空间风险（206 真实易涝点训练, 空间CV AUC=0.79）
  2. wave_typhoon     : 台风-波浪波高（CMEMS 标签, 事件内 R²=0.70）
  3. landslide_warning: 滑坡预警（905 官方预警训练, 时间外验证）
模型文件：shenzhen-flood/data/ml_models/*.pkl
指标文件：shenzhen-flood/data/ml_models/*_metrics.json
"""
import os
import json
import pickle
import numpy as np

_ML_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "shenzhen-flood", "data", "ml_models"))

_cache = {}


def _load(name):
    if name not in _cache:
        path = os.path.join(_ML_DIR, f"{name}.pkl")
        if not os.path.exists(path):
            return None
        try:
            # v2 集成模型在训练脚本 __main__ 里 pickle，
            # 反序列化需要把类注入 __main__ 命名空间
            import sys as _sys
            from . import ml_model_defs
            for cls_name in ('EnsembleHistGB',):
                cls = getattr(ml_model_defs, cls_name, None)
                if cls is not None:
                    setattr(_sys.modules['__main__'], cls_name, cls)
            with open(path, "rb") as f:
                _cache[name] = pickle.load(f)
        except Exception:
            return None
    return _cache[name]


def _metrics(name):
    path = os.path.join(_ML_DIR, f"{name}_metrics.json")
    if not os.path.exists(path):
        return {}
    try:
        return json.load(open(path))
    except Exception:
        return {}


# ============ ① 内涝空间风险 ============
def flood_spatial_features(lat, lon):
    """提取单点特征（与训练管线一致）。"""
    import pandas as pd
    data_dir = os.path.abspath(os.path.join(_ML_DIR, "..", "processed"))
    dem = np.load(os.path.join(data_dir, "shenzhen_dem30.npy"))
    slope = np.load(os.path.join(data_dir, "shenzhen_slope30.npy"))
    meta = json.load(open(os.path.join(data_dir, "shenzhen_dem30_meta.json")))
    nrow, ncol = dem.shape
    j = int((lon - meta["lon0"]) / meta["cell_deg"])
    i = int((meta["lat0"] - lat) / meta["cell_deg"])
    if not (0 <= i < nrow and 0 <= j < ncol):
        return None
    e = float(dem[i, j]) if np.isfinite(dem[i, j]) else 0.0
    s = float(slope[i, j]) if np.isfinite(slope[i, j]) else 0.0
    # 3x3 邻域相对高程
    k = 3
    win = dem[max(0, i-k):min(nrow, i+k+1), max(0, j-k):min(ncol, j+k+1)]
    win = win[np.isfinite(win)]
    rel = float(np.mean(win) - dem[i, j]) if len(win) else 0.0
    # 建筑密度/道路/水系距离（简化：用缓存点表）
    bu = pd.read_csv(os.path.join(_ML_DIR, "..", "unified", "builtup.csv"))
    rd = pd.read_csv(os.path.join(_ML_DIR, "..", "unified", "roads.csv"))
    def nd(lats, lons):
        d = np.sqrt(((lats - lat) * 111) ** 2 + ((lons - lon) * 111 * np.cos(np.radians(lat))) ** 2)
        return float(np.min(d)) if len(d) else 5000.0
    db = nd(bu["lat"].values, bu["lon"].values)
    bp = 0.0
    if db < 2.0 and len(bu):
        idx = np.argmin(((bu["lat"] - lat) * 111) ** 2 + ((bu["lon"] - lon) * 111 * np.cos(np.radians(lat))) ** 2)
        bp = float(bu["builtup_pct"].iloc[idx])
    dr = nd(rd["lat"].values, rd["lon"].values)
    return {
        "elevation_m": e, "slope_deg": s, "relief_3x3_m": rel,
        "builtup_pct": bp, "dist_road_m": dr, "dist_water_m": 500.0,
    }


def predict_flood_spatial(lat, lon):
    """单点内涝风险概率（真实标签模型）。"""
    bundle = _load("flood_spatial")
    feats = flood_spatial_features(lat, lon)
    if bundle is None or feats is None:
        return None
    X = [[feats[f] for f in bundle["feats"]]]
    p = float(bundle["model"].predict_proba(X)[0][1])
    return {"lat": lat, "lon": lon, "flood_risk_prob": round(p, 4),
            "features": feats, "model_metrics": _metrics("flood_spatial")}


def predict_flood_grid(n=60):
    """全市网格内涝风险（供前端热力）。"""
    bundle = _load("flood_spatial")
    if bundle is None:
        return []
    out = []
    rng = np.random.default_rng(7)
    for _ in range(n):
        lat = rng.uniform(22.46, 22.84)
        lon = rng.uniform(113.78, 114.52)
        feats = flood_spatial_features(lat, lon)
        if feats is None:
            continue
        p = float(bundle["model"].predict_proba([[feats[f] for f in bundle["feats"]]])[0][1])
        out.append({"lat": round(lat, 4), "lon": round(lon, 4), "prob": round(p, 3)})
    return out


# ============ ③ 台风-波浪 ============
def predict_wave(tc_lat, tc_lon, wind_kt, pres_hpa, hours=0, pt_lat=22.2, pt_lon=114.6):
    """由台风状态预测近岸波高。"""
    bundle = _load("wave_typhoon")
    if bundle is None:
        return None
    dlat = (pt_lat - tc_lat) * 111.0
    dlon = (pt_lon - tc_lon) * 111.0 * np.cos(np.radians(pt_lat))
    dist = float(np.sqrt(dlat ** 2 + dlon ** 2))
    X = [[dist, wind_kt, pres_hpa, tc_lat, tc_lon, hours]]
    h = float(bundle["model"].predict(X)[0])
    return {"predicted_swh_m": round(max(h, 0.0), 2), "tc_dist_km": round(dist, 1),
            "model_metrics": _metrics("wave_typhoon")}


# ============ ② 滑坡预警 ============
def predict_landslide_warning(rain_24h, rain_72h, rain_168h, rain_max24h,
                              sm1=0.3, sm2=0.32, sm3=0.34, month=7):
    """由气象状态预测发布地灾预警的概率。

    v2 模型（21 维特征）自动从 11 维基础入参派生新特征；
    v1 模型（11 维）保持原样。按 bundle['feats'] 对齐列序。
    """
    import math
    bundle = _load("landslide_warning")
    if bundle is None:
        return None
    feats = bundle.get("feats")
    model = bundle["model"]

    # 基础量（v1 全集）
    base = {
        'rain_24h': rain_24h, 'rain_72h': rain_72h, 'rain_168h': rain_168h,
        'rain_max24h': rain_max24h,
        'sm1_mean': sm1, 'sm2_mean': sm2, 'sm3_mean': sm3,
        'sm1_prev': sm1, 'sm2_prev': sm2, 'sm3_prev': sm3,
        'month': month,
    }
    if feats and len(feats) > 11:
        # v2 派生特征（与训练管线一致的近似）
        base['rain_maxh_3d'] = rain_max24h          # 3 日窗最大雨强 ≈ 当日
        base['rain_maxh_7d'] = rain_max24h          # 7 日窗最大雨强 ≈ 当日
        base['sm1_delta'] = 0.0                     # 无前期数据时变化率取 0
        base['sm2_delta'] = 0.0
        base['sm1_anom'] = 0.0                      # 距平未知取 0
        base['dry_days'] = 0 if rain_24h >= 2 else 1
        base['rain_conc'] = min(rain_24h / max(rain_168h, 1.0), 1.0)
        base['api_7d'] = (rain_72h - rain_24h) * 0.55 + rain_24h * 0.5
        doy_approx = 30.4 * month
        base['season_sin'] = math.sin(2 * math.pi * doy_approx / 365.25)
        base['season_cos'] = math.cos(2 * math.pi * doy_approx / 365.25)

    X = [[base.get(f, 0.0) for f in feats]] if feats else [[
        rain_24h, rain_72h, rain_168h, rain_max24h,
        sm1, sm2, sm3, sm1, sm2, sm3, month]]
    p = float(model.predict_proba(X)[0][1])
    return {"warning_prob": round(p, 4), "model_metrics": _metrics("landslide_warning")}


def landslide_sensitivity(rain_max_mm=200.0, steps=9, sm1=0.35, sm2=0.36, sm3=0.37, month=9):
    """滑坡预警概率对 24h 降雨量的敏感性曲线（供前端可视化）。"""
    bundle = _load("landslide_warning")
    if bundle is None:
        return None
    feats = bundle.get("feats")
    model = bundle["model"]
    import math
    out = []
    for i in range(steps + 1):
        r24 = rain_max_mm * i / steps
        r72 = r24 * 1.6
        r168 = r24 * 2.2
        if feats and len(feats) > 11:
            base = {
                'rain_24h': r24, 'rain_72h': r72, 'rain_168h': r168,
                'rain_max24h': r24 / 6.0,
                'sm1_mean': sm1, 'sm2_mean': sm2, 'sm3_mean': sm3,
                'sm1_prev': sm1, 'sm2_prev': sm2, 'sm3_prev': sm3,
                'month': month,
                'rain_maxh_3d': r24 / 6.0, 'rain_maxh_7d': r24 / 6.0,
                'sm1_delta': 0.0, 'sm2_delta': 0.0, 'sm1_anom': 0.0,
                'dry_days': 0 if r24 >= 2 else 1,
                'rain_conc': min(r24 / max(r168, 1.0), 1.0),
                'api_7d': r72 * 0.5,
                'season_sin': math.sin(2 * math.pi * 30.4 * month / 365.25),
                'season_cos': math.cos(2 * math.pi * 30.4 * month / 365.25),
            }
            X = [[base.get(f, 0.0) for f in feats]]
        else:
            X = [[r24, r72, r168, r24 / 6.0, sm1, sm2, sm3, sm1, sm2, sm3, month]]
        p = float(model.predict_proba(X)[0][1])
        out.append({"rain_24h": round(r24, 1), "prob": round(p, 4)})
    return {"curve": out, "soil": {"sm1": sm1, "sm2": sm2}, "month": month,
            "note": "v2.1 模型敏感性扫描（土壤湿度固定，仅变降雨）"}


def all_metrics():
    """全部模型指标汇总。"""
    return {
        "flood_spatial": _metrics("flood_spatial"),
        "wave_typhoon": _metrics("wave_typhoon"),
        "landslide_warning": _metrics("landslide_warning"),
    }
