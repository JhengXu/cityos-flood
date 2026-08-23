# -*- coding: utf-8 -*-
"""
街道级内涝风险（精确到街道采样点）
---------------------------------------------------------------
- 街道特征：真实 DEM 高程 + WorldCover 不透水（gisreal 生成 street_features.json）
- 街道降雨：多点 Open-Meteo 街道采样点逐时降雨（空间降尺度）
- 街道脆弱性 V = w·(不透水, 低洼, 区历史, 临海) ，用街道级真实特征 + 区级真实历史/临海
- 风险：降雨超额 × 街道脆弱性 → 逐时风险概率
"""
import os
import json
import numpy as np

from . import weather, model, shenzhen

STREET_FEATURES = os.path.join(os.path.dirname(__file__), "..", "data", "street_features.json")


def _load_street_features():
    if not os.path.exists(STREET_FEATURES):
        return {}
    with open(STREET_FEATURES, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {r["name"]: r for r in rows}


def _street_vulnerability(feat, district):
    """街道脆弱性 V (0-1)：街道级真实高程/不透水 + 区级真实历史/临海。"""
    v_imp = feat.get("impervious", 0.5)
    elev = feat.get("elevation", 30.0)
    v_elev = 1.0 / (1.0 + np.exp((elev - 40.0) / 25.0))   # 高程越低越易涝（sigmoid）
    v_hist = district.get("historical_flood_index", 0.5)
    v_coast = district.get("coastal", 0.3)
    V = 0.30 * v_imp + 0.20 * v_elev + 0.25 * v_hist + 0.25 * v_coast
    return float(min(max(V, 0.0), 1.0))


def build_street_risk(forecast_days=3):
    """对 30 个街道采样点：街道降雨 + 街道脆弱性 -> 逐时风险。返回 list。"""
    grid, fallback = weather.fetch_grid(forecast_days)
    feats = _load_street_features()
    times = grid[0][1]
    out = []
    for (name, did, lat, lon), ts, prec in grid:
        d = shenzhen.get_district(did)
        if d is None:
            continue
        feat = feats.get(name, {})
        V = _street_vulnerability(feat, d)
        C = d["drainage_design"]
        risk = []
        cum = 0.0
        for p in prec:
            cum = min(cum + float(p), 300.0)
            excess = max(0.0, float(p) - C)
            # 街道级风险：超额 × 街道脆弱性 + 前期饱和
            z = (excess / 50.0) * V + 0.3 * (cum / 150.0)
            prob = model.MODEL._sigmoid(-4.0 * (z - 0.5))
            risk.append(round(float(prob), 4))
        out.append({
            "name": name, "district_id": did, "lat": lat, "lon": lon,
            "vulnerability": round(V, 3),
            "impervious": feat.get("impervious", 0.5), "elevation": feat.get("elevation", 30.0),
            "risk": risk, "peak": round(max(risk), 4),
            "peak_hour": int(risk.index(max(risk))),
        })
    out.sort(key=lambda s: s["peak"], reverse=True)
    return {"source": "fallback-sample" if fallback else "open-meteo-multi-point",
            "n_streets": len(out), "streets": out}


street_risk_cache = {"ts": 0.0, "data": None}
import time as _t


def get_street_risk(forecast_days=3):
    if street_risk_cache["data"] and _t.time() - street_risk_cache["ts"] < 300:
        return street_risk_cache["data"]
    data = build_street_risk(forecast_days)
    street_risk_cache["ts"] = _t.time()
    street_risk_cache["data"] = data
    return data
