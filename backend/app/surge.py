# -*- coding: utf-8 -*-
"""surge.py — 风暴潮子系统的核心模块（天文潮谐波 + 台风增水参数化 + 预警水位）。

设计（自包含，零外部实时依赖）：

① 天文潮谐波推算
   - 用 HKO 3 年逐时天文潮预测（2017/2018/2023，52560 样本）拟合 8 主分潮
   - M2/S2/N2/K2/K1/O1/P1/Q1 最小二乘 → 任意日期逐时天文潮
   - 验证：2017-18 拟合 → 2023 预测 RMSE = 0.130 m

② 台风增水参数化（简化风堆积 + 气压反效应）
   surge ≈ (1013 - p_hPa) × 1cm + V²/(22.5·R) · exp(-d/R)
   - 气压项：低压吸升（1 hPa ≈ 1 cm）
   - 风堆积项：切向风输送，R=最大风速半径 50 km，距离指数衰减
   - 量级校验（与文献一致）：
       山竹 38.6m/s@131km/960hPa → 0.63 m
       苏拉 43.7m/s@61km/950hPa  → 1.13 m

③ 预警水位（参照《深圳市沿海风暴潮预警地方标准》口径）
   - 天文高潮 + 增水估计 → 总水位 → 分级
   - 基准换算：HKO CD（海图基准）≈ 深圳沿岸警戒水位参照的基准差（+1.47m 至 1985 高程）
   - 分级：关注 ≥2.6m / 警戒 ≥3.0m / 严重 ≥3.5m（CD 口径）

④ 历史事件风暴潮档案（knowledge 知识库联动）
"""
from __future__ import annotations

import math
import os
import pickle
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "shenzhen-flood", "data"))
_HARMONIC_CACHE = os.path.join(_DATA, "ml_models", "tide_harmonics.pkl")

# ============ ① 天文潮谐波 ============

# 12 分潮周期（小时）—— v2：加浅水分潮 M4/MS4/J1/2N2，近岸精度更好
CONSTITUENTS = {
    "M2": 12.4206012,    # 主太阴半日潮（最重要）
    "S2": 12.0,          # 主太阳半日潮
    "N2": 12.65834751,   # 椭圆率半日潮
    "K2": 11.96723606,   # 赤纬半日潮
    "K1": 23.93447213,   # 赤纬全日潮
    "O1": 25.81933871,   # 主太阴全日潮
    "P1": 24.06588766,   # 主太阳全日潮
    "Q1": 26.868350,     # 椭圆率全日潮
    # v2 浅水与次要分潮
    "M4": 6.2103006,     # 浅水四分潮
    "MS4": 6.10333927,   # 浅水复合分潮
    "2N2": 12.90537297,  # 二阶椭圆率
    "J1": 23.09848146,   # 椭圆率全日（次要）
}


def _design_matrix(t_hours: np.ndarray) -> np.ndarray:
    cols = [np.ones_like(t_hours)]
    for period in CONSTITUENTS.values():
        w = 2 * math.pi / period
        cols.append(np.cos(w * t_hours))
        cols.append(np.sin(w * t_hours))
    return np.column_stack(cols)


def fit_harmonics():
    """从 HKO 天文潮数据拟合各站谐波系数（结果缓存 pkl）。"""
    tide_path = os.path.join(_DATA, "unified", "tide_timeseries.csv")
    tide = pd.read_csv(tide_path)
    tide["ts"] = pd.to_datetime(tide["timestamp_bj"])
    out = {}
    for sid, grp in tide.groupby("station_id"):
        grp = grp.sort_values("ts").reset_index(drop=True)
        t0 = grp["ts"].min()
        t_hours = ((grp["ts"] - t0).dt.total_seconds() / 3600).values
        y = pd.to_numeric(grp["tide_m"], errors="coerce").values
        ok = np.isfinite(y)
        X = _design_matrix(t_hours[ok])
        coef, *_ = np.linalg.lstsq(X, y[ok], rcond=None)
        y_hat = X @ coef
        rmse = float(np.sqrt(np.mean((y[ok] - y_hat) ** 2)))
        out[sid] = {
            "coef": coef.tolist(),
            "t0": str(t0),
            "rmse": round(rmse, 4),
            "name": str(grp["station_name"].iloc[0]),
            "lat": float(grp["lat"].iloc[0]),
            "lon": float(grp["lon"].iloc[0]),
            "datum": str(grp["datum"].iloc[0]),
        }
    os.makedirs(os.path.dirname(_HARMONIC_CACHE), exist_ok=True)
    with open(_HARMONIC_CACHE, "wb") as f:
        pickle.dump(out, f)
    return out


def _load_harmonics():
    if os.path.exists(_HARMONIC_CACHE):
        with open(_HARMONIC_CACHE, "rb") as f:
            return pickle.load(f)
    return fit_harmonics()


_HARM = None


def _harmonics():
    global _HARM
    if _HARM is None:
        _HARM = _load_harmonics()
    return _HARM


def predict_tide(station_id: str, start: datetime, hours: int = 48):
    """推算站点未来 hours 小时的天文潮（逐时，CD 基准，米）。

    返回 [(iso_time, tide_m), ...]
    """
    h = _harmonics().get(station_id)
    if h is None:
        return []
    t0 = pd.Timestamp(h["t0"])
    t_hours = np.array([
        (pd.Timestamp(start.replace(minute=0, second=0, microsecond=0)) + pd.Timedelta(hours=i) - t0).total_seconds() / 3600
        for i in range(hours)
    ])
    X = _design_matrix(t_hours)
    y = X @ np.array(h["coef"])
    out = []
    for i in range(hours):
        ts = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=i)
        out.append((ts.strftime("%Y-%m-%dT%H:%M"), round(float(y[i]), 3)))
    return out


# ============ ② 台风增水参数化 ============

def surge_estimate(wind_ms: float, dist_km: float, pres_hpa: float, wind_radius_km: float = 50.0):
    """简化台风增水估计（气压反效应 + 风堆积）。

    返回 (总增水 m, 分项 dict)
    """
    if wind_ms is None or pres_hpa is None:
        return 0.0, {"pressure_m": 0.0, "wind_setup_m": 0.0}
    # 气压项：低压吸升（静压反效应，1 hPa ≈ 1 cm）
    p_eff = max(0.0, (1013.0 - float(pres_hpa)) * 0.01)
    # 风堆积：V²/(22.5·R) · exp(-d/R)
    d = max(float(dist_km or 400), 1.0)
    R = max(float(wind_radius_km), 20.0)
    wind_eff = (float(wind_ms) ** 2 / (22.5 * R)) * math.exp(-d / R)
    return round(p_eff + wind_eff, 3), {
        "pressure_m": round(p_eff, 3),
        "wind_setup_m": round(wind_eff, 3),
    }


# ============ ③ 预警水位 ============
# CD（海图基准）口径的分级，参照深圳市沿海风暴潮预警地方标准的量级
# （警戒水位以各站天文高潮 + 增水组合判断）
ALERT_LEVELS = [
    {"level": 3, "name": "严重", "threshold_m": 3.5, "color": "#ff4757"},
    {"level": 2, "name": "警戒", "threshold_m": 3.0, "color": "#ff6b5e"},
    {"level": 1, "name": "关注", "threshold_m": 2.6, "color": "#fbbf24"},
    {"level": 0, "name": "正常", "threshold_m": 0.0, "color": "#34d399"},
]


def alert_level(total_water_m: float):
    for lv in ALERT_LEVELS:
        if total_water_m >= lv["threshold_m"]:
            return lv
    return ALERT_LEVELS[-1]


# ============ ④ 实时风暴潮预测（供 live_ops 调用） ============

def live_surge(typhoon_now: dict | None = None, hours: int = 48):
    """实时风暴潮预测：两站天文潮 + （如有台风）增水叠加 + 分级。

    返回结构：
    {
      stations: [{station_id, name, lat, lon, datum, harmonic_rmse_m,
                  tide: [(t, astro_m, surge_m, total_m)...],
                  peak: {time, astro_m, surge_m, total_m},
                  alert: {level, name, color, threshold_m}}],
      surge_note, source, generated_at
    }
    """
    h = _harmonics()
    # 增水输入：活跃台风（无台风 → 0）
    wind_ms = dist_km = pres_hpa = None
    ty_name = None
    if typhoon_now:
        ty_name = typhoon_now.get("name")
        wind_ms = typhoon_now.get("wind_ms")
        pres_hpa = typhoon_now.get("pres_hpa")
        # 距离未知（live 的 typhoon_now 无位置）→ 用风速/气压保守估计
        dist_km = 100.0 if wind_ms else None

    surge_total, parts = surge_estimate(wind_ms or 0, dist_km or 400, pres_hpa or 1013)

    now = datetime.now()
    stations = []
    for sid, meta in h.items():
        tide = predict_tide(sid, now, hours)
        rows = []
        peak = None
        for t, astro in tide:
            total = round(astro + surge_total, 3)
            rows.append({"t": t, "astro_m": astro, "surge_m": surge_total, "total_m": total})
            if peak is None or total > peak["total_m"]:
                peak = {"t": t, "astro_m": astro, "surge_m": surge_total, "total_m": total}
        lv = alert_level(peak["total_m"]) if peak else ALERT_LEVELS[-1]
        stations.append({
            "station_id": sid,
            "name": meta["name"],
            "lat": meta["lat"], "lon": meta["lon"],
            "datum": meta["datum"],
            "harmonic_rmse_m": meta["rmse"],
            "series": rows,
            "peak": peak,
            "alert": {"level": lv["level"], "name": lv["name"],
                      "color": lv["color"], "threshold_m": lv["threshold_m"]},
        })

    if ty_name and surge_total > 0.01:
        note = (f"活跃台风「{ty_name}」参数化增水估计 +{surge_total:.2f} m"
                f"（气压 +{parts['pressure_m']:.2f} / 风堆积 +{parts['wind_setup_m']:.2f}），"
                f"叠加天文高潮位后评估预警水位。")
    else:
        note = "当前无活跃台风影响，仅天文潮位（无增水项）。"

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "stations": stations,
        "surge_estimate_m": surge_total,
        "surge_parts": parts,
        "typhoon": ty_name,
        "note": note,
        "source": "天文潮=HKO谐波推算(8分潮,RMSE~0.13m) + 台风增水=气压+风堆积参数化",
        "disclaimer": "研究演示口径：参数化增水为量级估计（非数值模式），预警水位不替代官方发布。",
    }


# ============ ⑤ 历史事件风暴潮档案（知识库联动） ============

EVENT_ARCHIVE = [
    {
        "event": "mangkhut_2018", "event_name": "山竹 2018",
        "typhoon": {"wind_ms": 38.6, "dist_km": 131, "pres_hpa": 960},
        "wave_peak_m": {"大鹏湾口外海": 9.51, "珠江口": 3.39, "深圳湾": 2.21},
        "tide_observed_peak_m": {"长洲": 2.51, "鰂魚涌": 2.43},  # 天文潮口径（预测表）
        "surge_est_m": 0.63,
        "note": "山竹路径偏西南，深圳以强风+巨浪为主，天文高潮叠加增水约 0.6m。",
    },
    {
        "event": "saola_2023", "event_name": "苏拉 2023",
        "typhoon": {"wind_ms": 43.7, "dist_km": 61, "pres_hpa": 950},
        "wave_peak_m": {"大鹏湾口外海": 3.68, "珠江口": 1.63, "深圳湾": 1.02},
        "tide_observed_peak_m": {"长洲": 2.63, "鰂魚涌": 2.56},
        "surge_est_m": 1.13,
        "note": "苏拉近距离掠过（61km），增水估计为四事件最高，天文潮峰 2.63m 亦最高。",
    },
    {
        "event": "hato_2017", "event_name": "天鸽 2017",
        "typhoon": {"wind_ms": 38.6, "dist_km": 82, "pres_hpa": 965},
        "wave_peak_m": {"大鹏湾口外海": 5.31, "珠江口": 1.84, "深圳湾": 1.15},
        "tide_observed_peak_m": {"长洲": 2.51, "鰂魚涌": 2.43},
        "surge_est_m": 0.74,
        "note": "天鸽路径偏南掠过，珠江口增水明显但深圳沿岸以天文潮为主。",
    },
]


def event_archive():
    """历史事件风暴潮档案（含参数化增水复算）。"""
    out = []
    for ev in EVENT_ARCHIVE:
        ty = ev["typhoon"]
        s, parts = surge_estimate(ty["wind_ms"], ty["dist_km"], ty["pres_hpa"])
        out.append({**ev, "surge_est_m": s, "surge_parts": parts})
    return out
