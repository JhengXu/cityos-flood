# -*- coding: utf-8 -*-
"""
live_ops.py — 单页指挥中心统一实时预测
======================================
一次调用返回全部灾种的实时状态与预测：
  1. 实时气象：Open-Meteo 逐时预报（降雨/风/气压，3天）
  2. 内涝预测：守恒状态模型（真实 GIS 参数）逐时分区积水深度
  3. 滑坡预警：监督模型（905 官方预警训练）按实时降雨预测预警概率
  4. 台风现状：气象局最新台风 + 影响深圳的历史台风统计
  5. 多灾种卡：四灾种关键数 + 实时等级
"""
import os
import time
import json
import urllib.request
import numpy as np
import pandas as pd

from . import shenzhen, state_model
from . import ml_models, multihazard
from . import surge as surge_mod

_CACHE = {"ts": 0, "data": None, "ttl": 600}  # 10分钟缓存


# 复用 opener（keep-alive 连接池）
_OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler())


def _fetch_open_meteo():
    """多点逐时预报（10 区中心）+ 当前实况 + 过去 6h 已发生时次。"""
    lats = [d["center"][0] for d in shenzhen.DISTRICTS]
    lons = [d["center"][1] for d in shenzhen.DISTRICTS]
    lat_q = ",".join(f"{x:.3f}" for x in lats)
    lon_q = ",".join(f"{x:.3f}" for x in lons)
    url = (f"https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat_q}&longitude={lon_q}"
           f"&hourly=precipitation,wind_speed_10m,pressure_msl"
           f"&current=temperature_2m,precipitation,wind_speed_10m,weather_code"
           f"&past_hours=6&forecast_hours=48&timezone=Asia%2FShanghai")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
            with _OPENER.open(req, timeout=25) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip as _gz
                    raw = _gz.decompress(raw)
                d = json.loads(raw.decode())
            # 多点返回 list
            if isinstance(d, list):
                return d
            return [d]
        except Exception:
            if attempt == 2:
                # past_hours/current 不支持时退回旧参数
                try:
                    url2 = (f"https://api.open-meteo.com/v1/forecast"
                            f"?latitude={lat_q}&longitude={lon_q}"
                            f"&hourly=precipitation,wind_speed_10m,pressure_msl"
                            f"&forecast_days=3&timezone=Asia%2FShanghai")
                    req = urllib.request.Request(url2)
                    with urllib.request.urlopen(req, timeout=25) as r:
                        d = json.loads(r.read().decode())
                    return d if isinstance(d, list) else [d]
                except Exception:
                    return None
            time.sleep(2)
    return None


def _surge_card(surge_live):
    """风暴潮卡（用最高预警等级 + 峰值水位）。"""
    if not surge_live or not surge_live.get("stations"):
        return {"name": "风暴潮", "icon": "🌊", "level": 1,
                "value": "—", "sub": "潮位推算不可用",
                "stations": 0}
    stations = surge_live["stations"]
    # 取两站最高预警等级与最高峰值
    max_lv = max(s["alert"]["level"] for s in stations)
    peak = max(s["peak"]["total_m"] for s in stations if s.get("peak"))
    peak_time = ""
    for s in stations:
        if s.get("peak") and s["peak"]["total_m"] == peak:
            peak_time = str(s["peak"]["t"])[5:16].replace("T", " ")
            break
    surge_m = surge_live.get("surge_estimate_m", 0.0)
    sub = f"天文潮+增水峰值（{peak_time}）"
    return {"name": "风暴潮", "icon": "🌊", "level": max_lv,
            "value": f"{peak:.2f} m",
            "sub": sub,
            "stations": len(stations),
            "surge_m": surge_m}


def build_live():
    """构建统一实时预测 payload。"""
    now = time.time()
    if _CACHE["data"] and now - _CACHE["ts"] < _CACHE["ttl"]:
        return _CACHE["data"]

    # ---------- ① 实时气象（多点 + 当前实况） ----------
    meteo = _fetch_open_meteo()
    districts = {d["id"]: d for d in shenzhen.DISTRICTS}
    dids = list(districts.keys())
    rain_by_district = {}
    wind_city = []
    times = None
    current = None  # 当前实况（Open-Meteo current）
    if meteo:
        for i, did in enumerate(dids):
            m = meteo[min(i, len(meteo) - 1)] if meteo else None
            if m and m.get("hourly"):
                h = m["hourly"]
                times = h.get("time") or times
                rain_by_district[did] = [x if x is not None else 0.0 for x in h.get("precipitation", [])]
                if i == 0:
                    wind_city = [x or 0 for x in h.get("wind_speed_10m", [])]
                    current = m.get("current") or None
    fallback = meteo is None

    # 时间轴（缺省 72h 合成）
    if not times:
        times = [(pd.Timestamp.now().floor("h") + pd.Timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")
                 for i in range(72)]
        rain_by_district = {did: [0.0] * 72 for did in dids}

    n = len(times)

    # ---------- ①b 「现在」索引（实况/预报分界） ----------
    # Open-Meteo 带 past_hours 时，times 序列包含已过去时次；
    # now_idx = 最后一个已发生（<= 当前时刻）的时次下标。
    now_ts = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None).floor("h")
    now_idx = 0
    for k, t in enumerate(times):
        try:
            if pd.Timestamp(str(t)) <= now_ts:
                now_idx = k
        except Exception:
            pass
    # 实况降雨（当前小时，而非"从 0 点起累加"）
    current_rain = None
    if current is not None and current.get("precipitation") is not None:
        current_rain = round(float(current["precipitation"]), 2)
    elif now_idx < len(rain_by_district.get(dids[0], [])):
        current_rain = rain_by_district[dids[0]][now_idx]
    # 未来 24h（从现在起，不含已过去时次）
    fut_rain = rain_by_district.get(dids[0], [0] * n)[now_idx + 1: now_idx + 25]
    rain_next_24h = round(float(sum(fut_rain)), 1)
    rain_24h_max = round(float(max(fut_rain, default=0.0)), 1)
    fut_wind = wind_city[now_idx + 1: now_idx + 25] if len(wind_city) > now_idx else []
    wind_next_24h_max = round(float(max(fut_wind, default=0.0)), 1)
    current_wind = None
    if current is not None and current.get("wind_speed_10m") is not None:
        current_wind = round(float(current["wind_speed_10m"]), 1)
    current_temp = None
    if current is not None and current.get("temperature_2m") is not None:
        current_temp = round(float(current["temperature_2m"]), 1)
    current_weather_code = (current or {}).get("weather_code")

    # ---------- ② 内涝预测（守恒模型，逐时 + 前期湿润初值） ----------
    # 精度升级：用过去 6h 实况降雨折算各分区初始水深（预湿状态），
    # 替代原先的固定 0 初值 —— 雨后场景的内涝预测显著更真实。
    flood_series = {}
    flood_summary = []
    try:
        initial_depth = {}
        if now_idx > 0 and not fallback:
            past_rain = {
                did: series[:now_idx + 1]
                for did, series in rain_by_district.items()
            }
            for did, hrs in past_rain.items():
                # 前期累积降雨（mm）→ 折算初始水深：排水能力抵扣后残留
                d = districts[did]
                cap_mm_h = d.get("drainage_design", 20.0)  # 设计排水能力
                cum = sum(hrs)
                # 简单产流残留：超出排水能力的部分 × 0.35 蓄滞系数
                excess = max(0.0, cum - cap_mm_h * len(hrs) * 0.6)
                initial_depth[did] = round(min(excess * 0.35, 80.0), 2)
        res = state_model.DEFAULT_MODEL.simulate(
            rain_by_district,
            initial_depth_mm=initial_depth if initial_depth else None,
        )
        depth = np.asarray(res.get("depth_mm"))
        ids = list(res.get("district_ids"))
        for i, did in enumerate(ids):
            if depth.ndim == 2:
                flood_series[did] = [round(float(x), 1) for x in depth[:, i]]
            peak = max(flood_series.get(did, [0]))
            flood_summary.append({
                "district_id": did, "district_name": districts[did]["name"],
                "peak_depth_mm": round(peak, 1),
            })
        flood_summary.sort(key=lambda x: -x["peak_depth_mm"])
    except Exception:
        flood_series = {}

    # 全城峰值
    city_peak_mm = max((s["peak_depth_mm"] for s in flood_summary), default=0.0)
    # 城市逐时（各区最大）
    city_series = []
    for t in range(n):
        vals = [flood_series.get(did, [0] * n)[t] for did in dids]
        city_series.append(round(max(vals), 1))

    # ---------- ②b 内涝概率桶（集合模拟 P10/P50/P90 + 超阈概率） ----------
    flood_quantiles = {}
    try:
        if fallback:
            # 回退样本：结构稳定的空桶（各区 P50=0），前端热力不崩
            flood_quantiles = {
                did: {"district_name": districts[did]["name"],
                      "p10_peak_mm": 0.0, "p50_peak_mm": 0.0, "p90_peak_mm": 0.0,
                      "p50_peak_hour": 0, "exc_15mm": 0.0, "exc_50mm": 0.0}
                for did in dids
            }
        else:
            ens = state_model.DEFAULT_MODEL.simulate_ensemble(
                rain_by_district, n_members=50,
                thresholds_mm=[15, 50, 100],
            )
            ids = list(ens.get("district_ids"))
            p50 = np.asarray(ens.get("depth_p50_mm"))     # (t, d)
            p10 = np.asarray(ens.get("depth_p10_mm"))
            p90 = np.asarray(ens.get("depth_p90_mm"))
            exc = ens.get("exceedance_probability") or {}
            for di, did in enumerate(ids):
                flood_quantiles[did] = {
                    "district_name": districts[did]["name"],
                    "p10_peak_mm": round(float(p10[:, di].max()), 1),
                    "p50_peak_mm": round(float(p50[:, di].max()), 1),
                    "p90_peak_mm": round(float(p90[:, di].max()), 1),
                    "p50_peak_hour": int(np.argmax(p50[:, di])),
                    "exc_15mm": round(float(np.asarray(exc[15.0])[:, di].max() if 15.0 in exc else 0.0), 3),
                    "exc_50mm": round(float(np.asarray(exc[50.0])[:, di].max() if 50.0 in exc else 0.0), 3),
                }
    except Exception as exc:
        print(f"[live_ops] flood quantiles failed: {exc}")
        flood_quantiles = {}

    # ---------- ③ 滑坡预警概率（监督模型 v2，按日聚合） ----------
    landslide_daily = []
    try:
        bundle = ml_models._load("landslide_warning")
        if bundle and not fallback:
            model = bundle["model"]
            feats = bundle.get("feats") or []
            # 逐日聚合城市降雨（小时 → 日）
            ts = pd.to_datetime([str(t) for t in times])
            df_rain = pd.DataFrame({"t": ts, "rain": rain_by_district[dids[0]]})
            df_rain["date"] = df_rain["t"].dt.strftime("%Y-%m-%d")
            daily = df_rain.groupby("date").agg(
                rain=("rain", "sum"), rain_max=("rain", "max")).reset_index()
            cum24 = daily["rain"].tolist()
            for i in range(len(cum24)):
                c72 = sum(cum24[max(0, i - 2):i + 1])
                c168 = sum(cum24[max(0, i - 6):i + 1])
                date_str = str(daily["date"].iloc[i])
                month = int(date_str[5:7])
                r = ml_models.predict_landslide_warning(
                    cum24[i], c72, c168,
                    max(daily["rain_max"].iloc[i] * 3, 1),
                    sm1=0.35, sm2=0.36, sm3=0.37, month=month)
                p = r["warning_prob"] if r else 0.0
                # 置信度标注：v2.1 时间外验证口径
                conf = "高" if p >= 0.8 or p <= 0.1 else ("中" if p >= 0.4 else "低")
                landslide_daily.append({
                    "date": date_str,
                    "rain_24h": round(cum24[i], 1),
                    "warning_prob": round(p, 4),
                    "confidence": conf,
                    "note": ("历史回放口径（时间外 AUC=0.821，召回 36% 偏保守）"
                             if p >= 0.4 else "低概率区间（模型召回有限，仅参考）"),
                })
    except Exception as exc:
        print(f"[live_ops] landslide daily failed: {exc}")
    slide_peak = max((d["warning_prob"] for d in landslide_daily), default=0.0)

    # ---------- ③b D-1 提前预警（用逐时预报聚合的明日降雨，今日发布预警概率） ----------
    # 方法：把「明日 00-24 时预报降雨」作为 D 日雨量喂给模型，
    # 同时用「今明两日预报」构成 72h 窗口 —— 模拟明天早上决策时已知的信息。
    advance_warnings = []
    try:
        if not fallback and len(times) > 24:
            rain_city = rain_by_district.get(dids[0], [])
            ts_dt = pd.to_datetime([str(t) for t in times])
            df_h = pd.DataFrame({"t": ts_dt, "rain": rain_city[:len(ts_dt)]})
            df_h["date"] = df_h["t"].dt.strftime("%Y-%m-%d")
            daily_h = df_h.groupby("date")["rain"].sum()
            dates_h = list(daily_h.index)
            for di in range(len(dates_h) - 1):
                d0, d1 = dates_h[di], dates_h[di + 1]
                r_d0 = float(daily_h.iloc[di])
                r_d1 = float(daily_h.iloc[di + 1])
                # D-1 口径：今天特征 + 明天的降雨（预报）→ 预测明天是否发预警
                c72 = r_d0 + r_d1
                month = int(d1[5:7])
                r = ml_models.predict_landslide_warning(
                    r_d1, c72, c72 * 1.3,
                    max(df_h[df_h["date"] == d1]["rain"].max() * 3, 1) if len(df_h[df_h["date"] == d1]) else max(r_d1 / 6, 1),
                    sm1=0.35, sm2=0.36, sm3=0.37, month=month)
                advance_warnings.append({
                    "for_date": d1,           # 预测的目标日
                    "issued_on": d0,          # 可以发布预警的日期（提前 1 天）
                    "tomorrow_rain_mm": round(r_d1, 1),
                    "warning_prob": r["warning_prob"] if r else 0.0,
                    "lead_hours": 24,
                })
    except Exception as exc:
        print(f"[live_ops] advance warning failed: {exc}")

    # ---------- ④ 台风现状 ----------
    ty_now = None
    try:
        fc = multihazard.data_loader.typhoon_forecast()
        if fc is not None and len(fc):
            fc2 = fc.copy()
            fc2["pt"] = pd.to_datetime(fc2.get("publish_time"), errors="coerce")
            if fc2["pt"].notna().any():
                latest = fc2.loc[fc2["pt"].idxmax()]
                nm = latest.get("name_zh") or latest.get("name_en")
                if nm and str(nm) != "nan":
                    ty_now = {
                        "name": str(nm),
                        "intensity": latest.get("intensity"),
                        "wind_ms": None if pd.isna(latest.get("wind_ms")) else float(latest["wind_ms"]),
                        "pres_hpa": None if pd.isna(latest.get("pres_hpa")) else float(latest["pres_hpa"]),
                    }
    except Exception:
        pass
    ty_stats = multihazard.typhoon_summary()
    ty_events = ty_stats.get("n", 0)

    # ---------- ④b 风暴潮实时预测（天文潮谐波 + 台风增水参数化） ----------
    surge_live = None
    try:
        surge_live = surge_mod.live_surge(ty_now)
    except Exception as exc:
        print(f"[live_ops] surge failed: {exc}")

    # ---------- ⑤ 多灾种卡 ----------
    # 内涝等级（全城峰值 mm）
    if city_peak_mm >= 150: flood_lvl = 4
    elif city_peak_mm >= 50: flood_lvl = 3
    elif city_peak_mm >= 15: flood_lvl = 2
    else: flood_lvl = 1
    # 滑坡等级
    if slide_peak >= 0.6: slide_lvl = 4
    elif slide_peak >= 0.3: slide_lvl = 3
    elif slide_peak >= 0.1: slide_lvl = 2
    else: slide_lvl = 1
    # 风等级（最大风速 km/h → m/s）
    wind_max = max(wind_city) if wind_city else 0
    if wind_max >= 32.7: wind_lvl = 4
    elif wind_max >= 17.2: wind_lvl = 3
    elif wind_max >= 10.8: wind_lvl = 2
    else: wind_lvl = 1

    cards = {
        "typhoon": {"name": "台风", "icon": "🌀", "level": wind_lvl,
                    "value": f"{wind_max:.0f} m/s", "sub": "最大风速（3天预报）",
                    "active": ty_now["name"] if ty_now else "无活跃台风",
                    "events": ty_events},
        "flood": {"name": "内涝", "icon": "🌧️", "level": flood_lvl,
                  "value": f"{city_peak_mm:.0f} mm", "sub": "全城峰值积水（守恒模型）",
                  "worst": flood_summary[0]["district_name"] if flood_summary else "—"},
        "landslide": {"name": "滑坡", "icon": "⛰", "level": slide_lvl,
                      "value": f"{slide_peak*100:.0f}%", "sub": "预警概率（ML模型）",
                      "points": 300},
        "surge": _surge_card(surge_live),
    }

    # ---------- ⑥ 实时告警流（阈值触发） ----------
    alerts = []
    try:
        cur = locals().get("current") or {}
        # ① 实况强降雨
        cur_rain_v = cur.get("precipitation_mm")
        if cur_rain_v is not None and cur_rain_v >= 20:
            alerts.append({"id": "al-rain-now", "severity": "critical" if cur_rain_v >= 50 else "warning",
                           "domain": "降雨", "title": f"当前实况雨强 {cur_rain_v:.0f} mm/h",
                           "note": "已达短时强降雨量级，低洼区注意积水", "source": "Open-Meteo 实况"})
        elif cur_rain_v is not None and cur_rain_v >= 8:
            alerts.append({"id": "al-rain-light", "severity": "info", "domain": "降雨",
                           "title": f"当前降雨 {cur_rain_v:.1f} mm/h", "note": "降雨持续中", "source": "Open-Meteo 实况"})
        # ② 未来 24h 降雨预警
        nxt = locals().get("rain_next_24h") or 0
        rain_peak_v = locals().get("rain_24h_max") or 0
        if rain_peak_v >= 30:
            alerts.append({"id": "al-rain-fc", "severity": "warning" if rain_peak_v < 60 else "critical",
                           "domain": "降雨预报", "title": f"未来 24h 累计 {nxt:.0f}mm（峰值 {rain_peak_v:.0f} mm/h）",
                           "note": "预报强降雨，提前布防", "source": "Open-Meteo 预报"})
        # ③ 滑坡预警概率
        if slide_peak >= 0.4:
            alerts.append({"id": "al-slide", "severity": "critical" if slide_peak >= 0.7 else "warning",
                           "domain": "滑坡", "title": f"滑坡预警概率 {slide_peak*100:.0f}%",
                           "note": "300 个在册隐患点需巡查", "source": "ML 模型（AUC=0.821）"})
        # ④ D-1 提前预警
        for w in (locals().get("advance_warnings") or []):
            if w.get("warning_prob", 0) >= 0.4:
                alerts.append({"id": f"al-adv-{w['for_date']}", "severity": "warning",
                               "domain": "滑坡·提前预警", "title": f"明日（{w['for_date'][5:]}）滑坡概率 {w['warning_prob']*100:.0f}%",
                               "note": f"预报降雨 {w['tomorrow_rain_mm']}mm，建议今日预置力量", "source": "D-1 模型"})
        # ⑤ 风暴潮
        if surge_live:
            for s in surge_live.get("stations", []):
                if s.get("alert", {}).get("level", 0) >= 2:
                    alerts.append({"id": f"al-surge-{s['station_id']}", "severity": "critical",
                                   "domain": "风暴潮", "title": f"{s['name']} 预计峰值 {s['peak']['total_m']}m（警戒级）",
                                   "note": s["peak"]["t"] + " 前后，沿海低洼区注意", "source": "潮汐谐波+增水参数化"})
                elif s.get("alert", {}).get("level", 0) == 1:
                    alerts.append({"id": f"al-surge-w-{s['station_id']}", "severity": "info",
                                   "domain": "风暴潮", "title": f"{s['name']} 峰值 {s['peak']['total_m']}m（关注级）",
                                   "note": "接近关注阈值", "source": "潮汐谐波"})
        # ⑥ 大风
        wind_peak_v = locals().get("wind_next_24h_max") or 0
        if wind_peak_v >= 17.2:
            alerts.append({"id": "al-wind", "severity": "warning" if wind_peak_v < 24.5 else "critical",
                           "domain": "大风", "title": f"未来 24h 最大风速 {wind_peak_v:.0f} m/s",
                           "note": "阵风可达更高，注意户外设施", "source": "Open-Meteo 预报"})
    except Exception as exc:
        print(f"[live_ops] alerts failed: {exc}")

    payload = {
        "generated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "data_source": "fallback-sample" if fallback else "open-meteo-realtime",
        "times": [str(t) for t in times],
        "now_idx": now_idx,
        "now_time": str(times[now_idx]) if now_idx < n else "",
        "current": {
            "temperature_2m": current_temp,
            "precipitation_mm": current_rain,
            "wind_speed_10m": current_wind,
            "weather_code": current_weather_code,
        },
        "next_24h": {
            "rain_total_mm": rain_next_24h,
            "rain_max_mm_h": rain_24h_max,
            "wind_max_ms": wind_next_24h_max,
        },
        "city_rain": rain_by_district.get(dids[0], [0] * n),
        "city_wind": wind_city,
        "city_flood_series": city_series,
        "flood_by_district": {did: flood_series.get(did, []) for did in dids[:10]},
        "flood_quantiles": flood_quantiles,
        "flood_summary": flood_summary[:10],
        "landslide_daily": landslide_daily,
        "advance_warnings": advance_warnings,
        "alerts": alerts,
        "typhoon_now": ty_now,
        "surge": surge_live,
        "cards": cards,
        "provenance": {
            "weather": "predicted(Open-Meteo 实时预报+实况)" if not fallback else "assumed(fallback)",
            "flood": "conservation-model(守恒状态模型, 真实GIS参数)",
            "landslide": "ml-predicted(905官方预警训练, 时间外AUC=0.821(±区间见模型档案))",
            "typhoon": "observed(IBTrACS) + forecast(气象局)",
        },
    }
    # 回退样本不进缓存（下次请求自动重试真实 API）
    if not fallback:
        _CACHE["ts"] = now
        _CACHE["data"] = payload
    return payload


def refresh():
    _CACHE["ts"] = 0
    _CACHE["data"] = None
    return build_live()
