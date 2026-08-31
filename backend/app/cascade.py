# -*- coding: utf-8 -*-
"""
cascade.py — 多灾种链式预测：台风 → 降雨场 → 滑坡预警概率
=========================================================
真正的链式预测（每一步可审计）：

  台风路径(IBTrACS 真实数据)
      │ ① 距离衰减参数化（与 typhoon.py forcing 同族）
      ▼
  分区逐时降雨场（10区）
      │ ② 累积成日尺度（24h/72h/168h + 雨强）
      ▼
  ERA5-Land 特征空间（训练时的同构特征）
      │ ③ 监督模型推理（landslide_warning.pkl, 时间外 AUC=0.813）
      ▼
  分区滑坡预警概率（日序列）

provenance：路径=observed(IBTrACS) / 降雨场=estimated(参数化) /
           滑坡概率=predicted(真实标签监督模型)
"""
import os
import numpy as np
import pandas as pd
from . import shenzhen
from . import ml_models
from . import multihazard

# 链式模型的特征顺序（与训练管线一致）
FEATS = ['rain_24h', 'rain_72h', 'rain_168h', 'rain_max24h',
         'sm1_mean', 'sm2_mean', 'sm3_mean', 'sm1_prev', 'sm2_prev', 'sm3_prev', 'month']


def _district_centers():
    return {d['id']: (d['center'][0], d['center'][1], d['name']) for d in shenzhen.DISTRICTS}


def _interp_wind(track_points):
    """路径点风速缺失插值（用气压反推 + 线性插值）。"""
    # pres → wind 经验关系（Atkinson-Holliday 简化）
    def pres_to_wind(pres):
        if pres is None or not np.isfinite(pres) or pres <= 0:
            return None
        if pres >= 1010:
            return 20.0
        # 1010→20kt, 980→60kt, 940→90kt, 905→115kt, 880→135kt
        pts = [(1010, 20), (990, 38), (975, 55), (960, 72), (940, 90), (920, 105), (905, 115), (880, 135), (850, 145)]
        for i in range(len(pts) - 1):
            p1, w1 = pts[i]; p2, w2 = pts[i + 1]
            if p2 <= pres <= p1:
                t = (p1 - pres) / (p1 - p2)
                return w1 + t * (w2 - w1)
        return 145.0

    winds = []
    for p in track_points:
        w = p.get('wind_kt')
        if w is not None and np.isfinite(w) and w > 0:
            winds.append(float(w))
        else:
            winds.append(pres_to_wind(p.get('pres_hpa')))
    # 剩余缺失用前向填充
    out = []
    last = 30.0
    for w in winds:
        if w is None:
            out.append(last)
        else:
            out.append(w)
            last = w
    return out


def rainfall_from_track(track_points):
    """① 台风路径 → 分区逐时降雨（距离衰减参数化）。

    track_points: [{lat, lon, wind_kt, pres_hpa, time}, ...]（IBTrACS 对齐格式）
    返回 {district_id: [逐时雨强 mm/h, ...]}
    """
    centers = _district_centers()
    winds = _interp_wind(track_points)
    rain = {did: [] for did in centers}
    for idx, p in enumerate(track_points):
        lat, lon = float(p['lat']), float(p['lon'])
        wind = winds[idx]
        # 参数化基准雨强（台风环流雨带：风速强 → 雨强指数上升）
        base = max(0.5, (wind / 40.0) ** 2 * 14.0)
        for did, (clat, clon, _) in centers.items():
            dlat = (clat - lat) * 111.0
            dlon = (clon - lon) * 111.0 * np.cos(np.radians(clat))
            dist = np.sqrt(dlat ** 2 + dlon ** 2)
            # 距离衰减（台风降雨 ~200km 半径）
            atten = np.exp(-dist / 170.0)
            rain[did].append(base * atten)
    return rain


def hourly_to_daily_rolls(rain_hourly, track_points, start_date):
    """② 路径点降雨 → 日尺度特征（按时间戳正确分日，北京时间）。

    track_points 间隔 3/6 小时，按各点的实际日期聚合。
    """
    # 北京时间
    times = [pd.Timestamp(p['time']) + pd.Timedelta(hours=8) for p in track_points]
    daily = {did: {} for did in rain_hourly}
    for idx, ts in enumerate(times):
        dkey = ts.strftime('%Y-%m-%d')
        for did in rain_hourly:
            r = rain_hourly[did][idx]
            if dkey not in daily[did]:
                daily[did][dkey] = {'sum': 0.0, 'max': 0.0, 'n': 0}
            daily[did][dkey]['sum'] += r
            daily[did][dkey]['max'] = max(daily[did][dkey]['max'], r)
            daily[did][dkey]['n'] += 1
    # 归一为日雨量（点间隔大时放大到全天：按点数比例折算）
    out = {}
    for did, days in daily.items():
        seq = []
        for dkey in sorted(days):
            v = days[dkey]
            # 每点代表其间隔（平均 4.5h），日雨量 = 均值雨强 × 24
            mean_rate = v['sum'] / max(v['n'], 1)
            seq.append({'date': dkey,
                        'rain_24h': round(mean_rate * 24, 1),
                        'rain_max24h': round(v['max'], 1)})
        out[did] = seq
    return out


def predict_landslide_cascade(track_points, start_date, soil=(0.32, 0.34, 0.36)):
    """③ 完整链式预测：台风路径 → 分区滑坡预警概率（按日）。

    soil: 当前土壤湿度初值（三层, m³/m³）。可被实时 ERA5 替换。
    """
    bundle = ml_models._load('landslide_warning')
    if bundle is None:
        return None
    # ① 降雨场
    rain_h = rainfall_from_track(track_points)
    # ② 日尺度（时间感知分日）
    daily = hourly_to_daily_rolls(rain_h, track_points, start_date)
    sm1, sm2, sm3 = soil

    centers = _district_centers()
    results = []
    for did, days in daily.items():
        # 滚动累积（链内自累积：72h = 前两日+当日；168h = 前六日+当日）
        cum72, cum168 = [], []
        for i, d in enumerate(days):
            cum72.append(sum(x['rain_24h'] for x in days[max(0, i - 2):i + 1]))
            cum168.append(sum(x['rain_24h'] for x in days[max(0, i - 6):i + 1]))
        for i, d in enumerate(days):
            month = pd.Timestamp(d['date']).month
            # 土壤湿度响应：降雨越多土壤越湿（线性近似，可被 ERA5 实况替换）
            wet = min(0.12, d['rain_24h'] * 0.0025 + (cum72[i] * 0.0008))
            s1 = min(sm1 + wet, 0.45)
            s2 = min(sm2 + wet * 0.6, 0.44)
            s3 = min(sm3 + wet * 0.3, 0.43)
            X = [[d['rain_24h'], cum72[i], cum168[i], d['rain_max24h'],
                  s1, s2, s3, sm1, sm2, sm3, month]]
            p = float(bundle['model'].predict_proba(X)[0][1])
            results.append({
                'district_id': did, 'district_name': centers[did][2],
                'date': d['date'],
                'rain_24h': round(d['rain_24h'], 1),
                'rain_72h': round(cum72[i], 1),
                'soil_wetness': round(wet, 3),
                'landslide_warning_prob': round(p, 4),
            })
    return results


def _flood_branch(rain_hourly):
    """内涝支路：分区逐时降雨 → 守恒状态模型 → 分区积水深度（mm）。

    返回 {district_id: [depth_mm, ...]}（逐时序列）。
    """
    from . import state_model
    model = state_model.DEFAULT_MODEL
    # 模型小时步长：路径点间隔 3/6h，模型 dt 假定 1h —— 输入按路径点序列直供，
    # depth 输出与输入序列等长（dt_hours 记录在结果里）。
    try:
        res = model.simulate(rain_hourly)
    except Exception:
        return None
    depth = np.asarray(res.get("depth_mm"))
    ids = list(res.get("district_ids"))
    out = {}
    for i, did in enumerate(ids):
        out[did] = depth[:, i].tolist() if depth.ndim == 2 else depth.tolist()
    return out


def _hourly_index_dates(track_points):
    """每个路径点对应的北京时间日期（用于内涝/滑坡日对齐）。"""
    return [(pd.Timestamp(p['time']) + pd.Timedelta(hours=8)).strftime('%Y-%m-%d')
            for p in track_points]


def cascade_for_typhoon(name=None, sid=None):
    """用真实 IBTrACS 台风跑完整链式预测（双灾种：滑坡 + 内涝）。"""
    from . import multihazard
    pts = multihazard.typhoon_track_points(name=name, sid=sid, limit=240)
    if not pts or len(pts) < 6:
        return None
    start = pts[0]['time'][:10]
    # ① 降雨场（逐路径点）
    rain_h = rainfall_from_track(pts)
    # ② 滑坡支路（日尺度）
    daily = hourly_to_daily_rolls(rain_h, pts, start)
    sm1, sm2, sm3 = 0.32, 0.34, 0.36
    centers = _district_centers()
    results = []
    for did, days in daily.items():
        cum72, cum168 = [], []
        for i, d in enumerate(days):
            cum72.append(sum(x['rain_24h'] for x in days[max(0, i - 2):i + 1]))
            cum168.append(sum(x['rain_24h'] for x in days[max(0, i - 6):i + 1]))
        for i, d in enumerate(days):
            month = pd.Timestamp(d['date']).month
            wet = min(0.12, d['rain_24h'] * 0.0025 + (cum72[i] * 0.0008))
            s1 = min(sm1 + wet, 0.45)
            s2 = min(sm2 + wet * 0.6, 0.44)
            s3 = min(sm3 + wet * 0.3, 0.43)
            X = [[d['rain_24h'], cum72[i], cum168[i], d['rain_max24h'],
                  s1, s2, s3, sm1, sm2, sm3, month]]
            p = float(ml_models._load('landslide_warning')['model'].predict_proba(X)[0][1])
            results.append({
                'district_id': did, 'district_name': centers[did][2],
                'date': d['date'],
                'rain_24h': round(d['rain_24h'], 1),
                'rain_72h': round(cum72[i], 1),
                'soil_wetness': round(wet, 3),
                'landslide_warning_prob': round(p, 4),
            })
    # ③ 内涝支路（守恒模型，逐路径点）
    flood_depth = _flood_branch(rain_h)
    # 内涝日峰值（按日期聚合 depth 最大值）
    flood_daily = {}
    if flood_depth:
        dates = _hourly_index_dates(pts)
        for did, seq in flood_depth.items():
            byday = {}
            for dt_val, dep in zip(dates, seq):
                byday[dt_val] = max(byday.get(dt_val, 0.0), float(dep))
            flood_daily[did] = byday
        for r in results:
            fd = flood_daily.get(r['district_id'], {})
            r['flood_depth_mm'] = round(fd.get(r['date'], 0.0), 1)

    # 事件峰值摘要
    summary = []
    if results:
        df = pd.DataFrame(results)
        for did, grp in df.groupby('district_id'):
            peak = grp.loc[grp['landslide_warning_prob'].idxmax()]
            fmax = grp['flood_depth_mm'].max() if 'flood_depth_mm' in grp else None
            summary.append({
                'district_id': did, 'district_name': peak['district_name'],
                'peak_prob': round(float(peak['landslide_warning_prob']), 4),
                'peak_date': peak['date'],
                'max_rain_24h': round(float(grp['rain_24h'].max()), 1),
                'max_flood_depth_mm': round(float(fmax), 1) if fmax is not None else None,
            })
        summary.sort(key=lambda x: -x['peak_prob'])
    return {
        'typhoon': {'name': name or sid, 'n_track_points': len(pts),
                    'start': start, 'end': pts[-1]['time'][:10]},
        'daily': results,
        'district_peak': summary[:10],
        'flood_branch': 'conservation state-space model (real GIS parameters)' if flood_depth else 'unavailable',
        'chain': ['台风路径(IBTrACS observed)',
                  '→ 距离衰减降雨场(estimated 参数化)',
                  '→ [滑坡支路] 日尺度累积 + 监督模型(AUC=0.813)',
                  '→ [内涝支路] 守恒状态模型 → 分区积水深度',
                  '→ 双灾种联动输出'],
        'provenance': 'path=observed / rainfall=estimated(parametric) / landslide=ml_predicted / flood=conservation_model',
    }


# ============ 台风情景 What-if 推演（方向 2b）============

def whatif_typhoon(name=None, sid=None, dist_shift_km=0.0, wind_factor=1.0):
    """台风情景推演：调整路径距离/强度 → 重新计算灾害链。

    参数：
      name/sid: 台风（真实路径）
      dist_shift_km: 路径整体向深圳平移（负值=更近，正值=更远）
      wind_factor: 风速缩放（1.0=实际，1.2=增强 20%）

    返回：基准 vs 情景 的对比（降雨/滑坡/内涝三链路）
    """
    import math as _math
    if name:
        pts = multihazard.typhoon_track_points(name=name)
    elif sid:
        pts = multihazard.typhoon_track_points(sid=sid)
    else:
        # 默认取活跃台风
        fc = multihazard.data_loader.typhoon_forecast()
        if fc is None or not len(fc):
            return None
        fc2 = fc.copy()
        fc2["pt"] = pd.to_datetime(fc2.get("publish_time"), errors="coerce")
        latest = fc2.loc[fc2["pt"].idxmax()]
        nm = latest.get("name_zh") or latest.get("name_en")
        pts = multihazard.typhoon_track_points(name=str(nm))
        name = str(nm)

    if not pts or len(pts) < 6:
        return None

    # 深圳中心
    SZ_LAT, SZ_LON = 22.55, 114.06

    # 基准：原始路径
    base_track = [{"lat": p["lat"], "lon": p["lon"], "wind_kt": p.get("wind_kt") or 75,
                   "pres_hpa": p.get("pres_hpa") or 960, "time": p.get("time", "")} for p in pts]

    # 情景：平移 + 缩放
    shift_deg = dist_shift_km / 111.0
    # 计算路径整体相对深圳的方位，向深圳方向平移
    mid_lat = sum(p["lat"] for p in base_track) / len(base_track)
    mid_lon = sum(p["lon"] for p in base_track) / len(base_track)
    # 单位向量：路径中心 → 深圳
    dlat = SZ_LAT - mid_lat
    dlon = SZ_LON - mid_lon
    norm = _math.sqrt(dlat**2 + dlon**2) or 1.0
    ux, uy = dlon / norm, dlat / norm  # 向深圳的单位向量

    scenario_track = []
    # dist_shift_km < 0 = 靠近深圳（位移方向 = 向深圳 × |shift|）
    # dist_shift_km > 0 = 远离深圳（位移方向 = 背离深圳 × shift）
    move_deg = -shift_deg  # 负值 shift → 正向（向深圳）位移
    for p in base_track:
        new_lat = p["lat"] + uy * move_deg
        new_lon = p["lon"] + ux * move_deg
        new_wind = (p["wind_kt"] or 75) * wind_factor
        scenario_track.append({
            "lat": new_lat, "lon": new_lon,
            "wind_kt": new_wind,
            "pres_hpa": max(880, (p["pres_hpa"] or 960) - (wind_factor - 1) * 50),
            "time": p["time"],
        })

    # 跑两条链
    start_date = base_track[0]["time"][:10] if base_track[0].get("time") else "2026-09-01"
    try:
        base_daily = predict_landslide_cascade(base_track, start_date)
    except Exception:
        base_daily = []
    try:
        scen_daily = predict_landslide_cascade(scenario_track, start_date)
    except Exception:
        scen_daily = []

    def _peak_summ(daily):
        if not daily:
            return {"max_rain": 0, "max_prob": 0, "max_flood": 0, "n_alert_days": 0}
        rains = [r.get("rain_24h", 0) for r in daily]
        probs = [r.get("landslide_warning_prob", 0) for r in daily]
        floods = [r.get("flood_depth_mm", 0) or 0 for r in daily]
        return {
            "max_rain": round(max(rains), 1),
            "max_prob": round(max(probs), 4),
            "max_flood": round(max(floods), 1),
            "n_alert_days": sum(1 for p in probs if p >= 0.4),
        }

    base_summ = _peak_summ(base_daily)
    scen_summ = _peak_summ(scen_daily)

    # 最近距离对比
    def _min_dist(track):
        ds = []
        for p in track:
            d = _math.hypot((p["lat"] - SZ_LAT) * 111, (p["lon"] - SZ_LON) * 111 * _math.cos(_math.radians(SZ_LAT)))
            ds.append(d)
        return round(min(ds), 0)

    # 增水联动：情景风速/气压 → 增水估计
    try:
        from . import surge as _surge
        base_wind = max((p["wind_kt"] or 75) for p in base_track) * 0.5144
        base_pres = min((p["pres_hpa"] or 960) for p in base_track)
        scen_wind = max((p["wind_kt"] or 75) for p in scenario_track) * 0.5144
        scen_pres = min((p["pres_hpa"] or 960) for p in scenario_track)
        base_surge, _ = _surge.surge_estimate(base_wind, _min_dist(base_track), base_pres)
        scen_surge, _ = _surge.surge_estimate(scen_wind, _min_dist(scenario_track), scen_pres)
        surge_delta = round(scen_surge - base_surge, 3)
    except Exception:
        base_surge = scen_surge = None
        surge_delta = None

    return {
        "typhoon": name,
        "surge": {
            "baseline_m": base_surge,
            "whatif_m": scen_surge,
            "delta_m": surge_delta,
        },
        "scenario": {
            "dist_shift_km": dist_shift_km,
            "wind_factor": wind_factor,
            "label": (f"路径{'靠近' if dist_shift_km < 0 else '远离'} {abs(dist_shift_km):.0f}km"
                      + (f" + 风速×{wind_factor:.1f}" if wind_factor != 1.0 else "")),
        },
        "baseline": {
            "min_dist_km": _min_dist(base_track),
            **base_summ,
        },
        "whatif": {
            "min_dist_km": _min_dist(scenario_track),
            **scen_summ,
        },
        "delta": {
            "min_dist_km": round(_min_dist(scenario_track) - _min_dist(base_track), 0),
            "max_rain_mm": round(scen_summ["max_rain"] - base_summ["max_rain"], 1),
            "max_prob": round(scen_summ["max_prob"] - base_summ["max_prob"], 4),
            "max_flood_mm": round(scen_summ["max_flood"] - base_summ["max_flood"], 1),
            "n_alert_days": scen_summ["n_alert_days"] - base_summ["n_alert_days"],
        },
        "baseline_daily": base_daily[:7],
        "whatif_daily": scen_daily[:7],
        "provenance": "path=observed(shifted) / rainfall=estimated(parametric) / landslide=ml / flood=conservation_model",
        "note": "What-if 情景推演：路径平移与强度缩放后的链式灾害对比，非台风预报。",
    }
