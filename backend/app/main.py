# -*- coding: utf-8 -*-
"""CITY OS · 深圳内涝预测 v2 — FastAPI 后端"""
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from . import shenzhen, weather, model, events, simulate, dispatch, demo, userdata, hazard, spatial, accessibility, assimilation, realdatav, streets

app = FastAPI(
    title="CITY OS · 深圳内涝预测 v2",
    description="基于城市数据 + 天气数据 + 时序推演(LSTM) 的深圳内涝预测与情景沙盘",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _warm_platform_cache():
    """后台预热水位缓存，避免首次请求实时抓取慢。"""
    import threading
    def _w():
        try:
            from . import platform_fetch
            ok = platform_fetch._refresh_live()
            print(f"[cityos] 平台水位 live 刷新{'成功' if ok else '失败，使用缓存真实数据'}")
        except Exception as e:
            print(f"[cityos] 平台水位预热失败: {e}")
    threading.Thread(target=_w, daemon=True).start()


@app.on_event("startup")
def _startup():
    _warm_platform_cache()

_cache = {"ts": 0.0, "data": None, "ttl": 600}


def _get_forecast(forecast_days: int):
    now = time.time()
    if _cache["data"] and now - _cache["ts"] < _cache["ttl"]:
        return _cache["data"]
    payload = weather.downscaled_forecast(forecast_days=forecast_days)
    _cache["ts"] = now
    _cache["data"] = payload
    return payload


def _build_predict(forecast_days: int):
    f = _get_forecast(forecast_days)
    times = f["times"]
    rainfall_city = f["city"]
    districts_rain = f["districts"]
    districts_cum = f["cum"]

    districts_out = []
    rainfall_by_district = {}
    for d in shenzhen.DISTRICTS:
        V, vbreak = model.district_vulnerability(d)
        rseq = districts_rain[d["id"]]
        cseq = districts_cum[d["id"]]
        rainfall_by_district[d["id"]] = rseq
        series = []
        for i, (R, C) in enumerate(zip(rseq, cseq)):
            res = model.MODEL.predict_one(R, C, d["drainage_design"], V)
            res["hour_index"] = i
            res["time"] = times[i]
            series.append(res)
        current = series[0] if series else None
        peak = max(series, key=lambda s: s["prob"]) if series else None
        districts_out.append({
            "id": d["id"], "name": d["name"], "center": d["center"],
            "drainage": d["drainage_design"], "elevation": d["elevation_mean"],
            "historical_index": d["historical_flood_index"],
            "vulnerability": V, "vuln_breakdown": vbreak, "tag": d["tag"],
            "rainfall": [round(x, 2) for x in rseq], "cum24": [round(x, 2) for x in cseq],
            "series": series,
            "current": current,
            "peak": {"hour_index": peak["hour_index"], "time": peak["time"],
                     "prob": peak["prob"], "level": peak["level"],
                     "level_label": peak["level_label"], "driver": peak["driver"]} if peak else None,
        })

    # —— #2 物理代理层（理论 §3.3）：数据校准的节点状态方程（物理提供边界，ML 提供校准）——
    haz_params = hazard._load_params()
    haz_risk = hazard.risk_batch(rainfall_by_district)
    for d_out in districts_out:
        did = d_out["id"]
        for i, s in enumerate(d_out["series"]):
            s["surrogate"] = {
                "prob": round(float(haz_risk[did][i]), 4),
                "alpha": round(haz_params[did]["alpha"], 5),
                "beta": round(haz_params[did]["beta"], 5),
                "provenance": haz_params[did].get("provenance", "estimated"),
            }

    n_hours = len(times)
    cur_levels = [d["current"]["level"] for d in districts_out if d["current"]]
    cur_max = max(cur_levels) if cur_levels else 0
    peak_idx = max(range(n_hours), key=lambda i: max(d["series"][i]["prob"] for d in districts_out), default=0) if n_hours else 0
    peak_max = max((d["series"][peak_idx]["prob"] for d in districts_out), default=0)
    peak_level = model.FloodRiskModel._level(peak_max)
    alerts = []
    for d in districts_out:
        if d["peak"] and d["peak"]["level"] >= 3:
            alerts.append({
                "level": d["peak"]["level"], "level_label": d["peak"]["level_label"],
                "district": d["name"], "time": d["peak"]["time"], "driver": d["peak"]["driver"],
                "message": f"{d['name']} 预计 {d['peak']['time']} 前后出现{d['peak']['level_label']}内涝风险，主因：{d['peak']['driver']}",
            })
    alerts.sort(key=lambda a: a["level"], reverse=True)
    high_now = [d["name"] for d in districts_out if d["current"] and d["current"]["level"] >= 3]

    overview = {
        "current_risk_level": cur_max, "current_risk_label": model.RISK_LEVELS[cur_max],
        "current_risk_prob": round(max((d["current"]["prob"] for d in districts_out if d["current"]), default=0), 4),
        "high_risk_now": high_now, "high_risk_now_count": len(high_now),
        "peak_hour_index": peak_idx, "peak_time": times[peak_idx] if n_hours else None,
        "peak_risk_level": peak_level, "peak_risk_label": model.RISK_LEVELS[peak_level],
        "alerts": alerts, "alert_count": len(alerts),
    }

    return {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "city": shenzhen.CITY, "forecast_days": forecast_days,
        "scale": "district·hourly scenario",
        "simulated": False,
        "data_source": "fallback-sample" if f["fallback"] else "open-meteo-multi-point",
        "drainage_avg": round(shenzhen.DRAINAGE_AVG, 2),
        "hours": times, "rainfall": rainfall_city, "districts": districts_out,
        "overview": overview,
        "model": {
            "name": "城市内涝世界行为模型 v2（混合物理 + LSTM 时序推演）",
            "hybrid_weights": {model.FEATURE_NAMES[i]: round(float(model.MODEL.weights[i]), 4) for i in range(4)},
            "hybrid_bias": round(model.MODEL.bias, 4),
            "hybrid_feature_importance": model.MODEL.feature_importance(),
            "hybrid_feature_labels": model.FEATURE_LABELS,
            "lstm": {"input_dim": 5, "hidden": 16, "features": ["降雨超额", "累计", "脆弱性", "排水标准", "潮位"]},
            "levels": model.RISK_LEVELS,
            "notes": "城市特征中高程来自 Open-Elevation 真实 DEM、历史指数来自真实内涝事件库；排水/下垫面等为代表性估算，应替换为权威 GIS。LSTM 权重由物理教师模型合成序列训练并缓存。",
        },
        "hazard_model": {
            "name": "暴雨—产流—积水 物理代理（理论 §3.3 节点状态方程）",
            "equation": "h_i(t+Δt)=max[0, h_i(t)+α_i·(R_i−C_i)_+ + Σw_ji·h_j(t) − β_i·h_i(t)]",
            "provenance": "estimated（α,β,w 由混合教师模型校准；真实积涝点水位就位后可替换为观测标定）",
            "note": "物理方程提供边界，数据（ML）提供校准，而非端到端黑箱；每个序列点的 series[].surrogate 含 α,β 与 provenance 标签。",
        },
        "provenance": {
            "rainfall_forecast": "estimated" if not f.get("fallback") else "assumed(fallback-sample)",
            "district_risk_hybrid": "estimated（混合物理 + 合成序列训练）",
            "district_risk_surrogate": "estimated（§3.3 物理代理，α,β 数据校准）",
            "dem_elevation": "observed(Open-Elevation)",
            "historical_flood_index": "observed(真实内涝事件库)",
            "drainage_design": "assumed(代表性估算，应替换权威 GIS)",
            "note": "各信号按 理论 §16 标注 observed/estimated/assumed；前端应据此着色区分。",
        },
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "cityos-flood", "time": time.time()}


@app.get("/api/districts")
def districts():
    return {
        "city": shenzhen.CITY, "drainage_avg": round(shenzhen.DRAINAGE_AVG, 2),
        "districts": [
            {"id": d["id"], "name": d["name"], "center": d["center"], "drainage": d["drainage_design"],
             "elevation": d["elevation_mean"], "historical_index": d["historical_flood_index"],
             "tag": d["tag"], "vulnerability": model.district_vulnerability(d)[0]}
            for d in shenzhen.DISTRICTS
        ],
    }


@app.get("/api/forecast")
def forecast(forecast_days: int = Query(3, ge=1, le=7)):
    f = _get_forecast(forecast_days)
    return {
        "data_source": "fallback-sample" if f["fallback"] else "open-meteo-multi-point",
        "times": f["times"], "rainfall_city": f["city"], "city_cum24": f["city_cum"],
        "districts": {k: v for k, v in f["districts"].items()},
        "cum": {k: v for k, v in f["cum"].items()},
    }


@app.get("/api/predict")
def predict(forecast_days: int = Query(3, ge=1, le=7)):
    return _build_predict(forecast_days)


@app.get("/api/spatial")
def get_spatial():
    """显式空间耦合表（理论 §2.1）：区↔区路网、设施↔区、格点↔区，含 provenance。"""
    return spatial.summary()


@app.get("/api/accessibility")
def get_accessibility(forecast_days: int = 2, damage: str = None):
    """道路损伤 + 设施动态可达性（理论 #4）。
    damage 可选，形如 'futian:0.7,luohu:0.5'（反事实注入，供 #5 对比）。
    缺省时用 #2 物理代理状态 h 作水深代理驱动。"""
    if damage:
        depth = {}
        for kv in damage.split(","):
            k, v = kv.split(":")
            depth[k.strip()] = float(v)
    else:
        f = weather.downscaled_forecast(forecast_days=forecast_days)
        rain = {d["id"]: f["districts"][d["id"]] for d in shenzhen.DISTRICTS}
        hs = hazard.simulate_batch(rain)
        depth = {did: max(seq) for did, seq in hs.items()}
    return accessibility.compute_accessibility(depth)


@app.get("/api/counterfactual")
def get_counterfactual(forecast_days: int = 2, close: str = None, pump: str = None):
    """反事实并排对比（理论 #5）：基线 vs 干预(封路/抽排)，输出设施可达人口 Δ。"""
    f = weather.downscaled_forecast(forecast_days=forecast_days)
    rain = {d["id"]: f["districts"][d["id"]] for d in shenzhen.DISTRICTS}
    hs = hazard.simulate_batch(rain)
    depth = {did: max(seq) for did, seq in hs.items()}
    return accessibility.counterfactual(depth, close=close, pump=pump)


@app.get("/api/assimilate")
def get_assimilate(district: str, observed_h: float, at_hour: int = 6, forecast_days: int = 2, k: float = 0.3):
    """数据同化钩子（理论 #6）：注入真实观测(水深代理)，残差修正 #2 物理代理隐状态。"""
    f = weather.downscaled_forecast(forecast_days=forecast_days)
    rseq = f["districts"].get(district)
    if rseq is None:
        return {"error": f"未知行政区: {district}"}
    return assimilation.assimilate_at(district, rseq, observed_h, at_hour, K=k)


@app.get("/api/events")
def get_events():
    return {"events": events.HISTORICAL_EVENTS, "historical_index": events.historical_index()}


@app.get("/api/scenarios")
def get_scenarios():
    return {"scenarios": simulate.SCENARIOS}


@app.get("/api/simulate")
def get_simulate(
    preset: Optional[str] = None,
    rainfall_multiplier: float = 1.0,
    add_peak_mm: float = 0.0,
    peak_offset_h: int = 18,
    drainage_factor: float = 1.0,
    tide_raise: float = 0.0,
):
    if preset and preset in simulate.SCENARIOS:
        sc = {k: v for k, v in simulate.SCENARIOS[preset].items() if k != "label"}
    else:
        sc = dict(rainfall_multiplier=rainfall_multiplier, add_peak_mm=add_peak_mm,
                  peak_offset_h=peak_offset_h, drainage_factor=drainage_factor, tide_raise=tide_raise)
    res = simulate.simulate(sc)
    res["scale"] = "district·hourly scenario"
    res["simulated"] = True
    return res


@app.post("/api/simulate")
async def post_simulate(request: Request):
    try:
        sc = await request.json()
    except Exception:
        sc = {}
    res = simulate.simulate(sc or {})
    res["scale"] = "district·hourly scenario"
    res["simulated"] = True
    return res


@app.post("/api/dispatch")
async def dispatch_action(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    scenario = payload.get("scenario") or simulate.SCENARIOS.get(payload.get("preset", "typhoon_tide"))
    result = simulate.simulate(scenario)
    pushes = [{"district": a["district"], "status": dispatch.push_alert(a)} for a in result["alerts"]]
    return {"simulate": result, "push": pushes, "pushed": len(pushes)}


@app.get("/api/alerts")
def get_alerts(limit: int = 50):
    return {"alerts": dispatch.get_pushed_alerts(limit)}


# ============ 研究验证演示（§3.1 + §3.2 + AI 三重角色）============

@app.get("/api/verify")
def api_verify():
    return demo.get_verify()


@app.get("/api/ontology")
def api_ontology():
    return demo.get_ontology()


@app.get("/api/roles")
def api_roles():
    return demo.get_roles()


@app.get("/api/benchmark")
def api_benchmark():
    return demo.get_benchmark()


@app.get("/api/verify/export")
def api_verify_export():
    from fastapi.responses import PlainTextResponse
    md = demo.export_report()
    return PlainTextResponse(md, media_type="text/markdown",
                             headers={"Content-Disposition": "attachment; filename=cityos_verify_report.md"})


# ============ 数据实验室（最新数据 + 用户输入）============

@app.get("/api/data/current")
def api_data_current():
    return userdata.current_conditions()


@app.post("/api/data/upload")
async def api_data_upload(request: Request):
    try:
        form = await request.form()
    except Exception:
        return {"status": "error", "hint": "请以 multipart/form-data 上传 CSV 文件"}
    file = form.get("file")
    filename = file.filename if hasattr(file, "filename") else "user_data.csv"
    content = await file.read() if hasattr(file, "read") else b""
    return userdata.upload_data(filename, content)


@app.post("/api/forecast/manual")
async def api_forecast_manual(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    district_id = body.get("district_id", "baoan")
    rainfall = body.get("rainfall", [])
    tide_raise = body.get("tide_raise", 0.0)
    return userdata.manual_forecast(district_id, rainfall, tide_raise=tide_raise)


# ============ 实时抓取平台数据 ============

@app.get("/api/platform/realtime")
def api_platform_realtime():
    """实时抓取：深圳开放平台积水点水位 + 天地图地理编码 + 免费源状态。"""
    from . import platform_fetch
    return platform_fetch.fetch_realtime()


@app.get("/api/platform/geocode")
def api_platform_geocode(q: str = "深圳市宝安区政府"):
    """天地图地理编码。"""
    from . import platform_fetch
    loc = platform_fetch.geocode(q)
    return {"query": q, "location": loc}


# ============ 真实数据资产 + 态势图 / 数据同化闭环 ============

@app.get("/api/geo/realtime")
def api_geo_realtime():
    """真实数据态势：易涝点 + 实时水位站 + 真实降雨。"""
    return realdatav.realtime_snapshot()


@app.get("/api/assimilate/realtime")
def api_assimilate_realtime(district: str = "baoan", observed_h: float = None, at_hour: int = 8):
    """数据同化闭环：真实观测注入物理代理状态，返回修正后风险轨迹。"""
    return realdatav.assimilate_realtime(district, observed_h, at_hour)


# ============ 街道级风险（真实 GIS 特征，精确到街道采样点）============

@app.get("/api/risk/street")
def api_risk_street(forecast_days: int = 3):
    """街道级内涝风险：30 个街道采样点，真实高程/不透水 + 街道降雨。"""
    return streets.get_street_risk(forecast_days)
