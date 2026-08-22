# -*- coding: utf-8 -*-
"""
天气数据接入 v2：多点 Open-Meteo 降雨网格 + 街道级空间降尺度
---------------------------------------------------------------
- 对 SUBDISTRICT_POINTS（街道级采样点）一次性批量拉取小时降雨（真实、带空间差异）
- 按行政区聚合（区内采样点均值）得到「街道级降尺度」后的分区分时降雨
- 同时取过去24h实况计算前期累计降雨（管网/土壤饱和度）
- 外网不可用 -> 降级为带空间差异的合成暴雨（沿海略强）
"""
import datetime as dt

import numpy as np
import requests

from .shenzhen import SUBDISTRICT_POINTS, DISTRICTS

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _now():
    return dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=8)))


def fetch_grid(forecast_days=3, timeout=20):
    """返回 (grid, fallback)。grid: list of ((name,did,lat,lon), times, precip_list)。"""
    lats = ",".join(str(p[2]) for p in SUBDISTRICT_POINTS)
    lons = ",".join(str(p[3]) for p in SUBDISTRICT_POINTS)
    try:
        params = {
            "latitude": lats,
            "longitude": lons,
            "hourly": "precipitation",
            "past_days": 1,
            "forecast_days": forecast_days,
            "timezone": "Asia/Shanghai",
        }
        r = requests.get(OPEN_METEO_URL, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) == len(SUBDISTRICT_POINTS):
            grid = []
            for p, d in zip(SUBDISTRICT_POINTS, data):
                times = d["hourly"]["time"]
                prec = [float(x) if x is not None else 0.0 for x in d["hourly"]["precipitation"]]
                grid.append((p, times, prec))
            return grid, False
        raise ValueError("open-meteo 多点返回结构异常")
    except Exception as e:
        print(f"[weather] 多点 Open-Meteo 不可用，启用降级网格: {e}")
        return _fallback_grid(forecast_days), True


def _storm_shape(n, peak=28.0):
    """一段典型暴雨形态（升-峰-降），长度 n。"""
    t = np.linspace(0, 1, n)
    base = peak * np.exp(-((t - 0.55) ** 2) / 0.02)
    return base


def _fallback_grid(forecast_days=3):
    total = (forecast_days + 1) * 24
    shape = _storm_shape(total)
    coast = {d["id"]: d["coastal"] for d in DISTRICTS}
    grid = []
    for name, did, lat, lon in SUBDISTRICT_POINTS:
        factor = 0.8 + 0.5 * coast[did]  # 沿海略强
        prec = (shape * factor + np.random.default_rng(hash((lat, lon)) & 0xFFFF).uniform(0, 1, total)).round(2)
        # 时间轴
        start = _now().replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=24)
        times = [(start + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(total)]
        grid.append(((name, did, lat, lon), times, list(prec)))
    return grid


def future_window(times, precip, forecast_days=3):
    now = _now()
    out = []
    n = len(times)
    for i, (tstr, p) in enumerate(zip(times, precip)):
        t = dt.datetime.strptime(tstr, "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
        if t <= now:
            continue
        lo = max(0, i - 24)
        cum24 = sum(precip[lo:i])
        out.append({"time": tstr, "precip": round(float(p), 2), "cum24": round(float(cum24), 2)})
        if len(out) >= forecast_days * 24:
            break
    return out


def downscaled_forecast(forecast_days=3):
    """街道级降尺度后的分区分时降雨。"""
    grid, fallback = fetch_grid(forecast_days)
    times = grid[0][1]
    by_district = {d["id"]: [] for d in DISTRICTS}
    for (name, did, lat, lon), _, prec in grid:
        by_district[did].append(np.array(prec, dtype=float))

    dist_precip = {}
    for did, arr_list in by_district.items():
        if arr_list:
            dist_precip[did] = np.mean(arr_list, axis=0)
        else:
            dist_precip[did] = np.zeros(len(times))

    # 未来窗口 + 每区 cum24
    out_dist, out_cum = {}, {}
    for did, series in dist_precip.items():
        fw = future_window(times, series, forecast_days)
        out_dist[did] = [w["precip"] for w in fw]
        out_cum[did] = [w["cum24"] for w in fw]

    city_series = np.mean([dist_precip[d["id"]] for d in DISTRICTS], axis=0)
    fw_city = future_window(times, city_series, forecast_days)
    future_times = [w["time"] for w in fw_city]

    return {
        "times": future_times,
        "city": [w["precip"] for w in fw_city],
        "city_cum": [w["cum24"] for w in fw_city],
        "districts": out_dist,
        "cum": out_cum,
        "fallback": fallback,
    }
