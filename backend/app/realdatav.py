# -*- coding: utf-8 -*-
"""
观测/历史数据资产 + 态势地图（shenzhen-flood 产物 → 证据可视化）
---------------------------------------------------------------
- 真实易涝点（206 个，含区/街道/坐标）
- 测站坐标 + 带观测时间/新鲜度的水位快照（复用 platform_fetch）
- 历史 CHIRPS 逐日降雨（不是实时降雨）
"""
import os
import csv
from datetime import datetime

from .data_paths import real_file

SZ_FLOOD = real_file("shenzhen_floodpoints_geo_v2.csv")
SZ_RAIN = real_file("shenzhen_chirps_rainfall.csv")
SZ_STATION_FEATURES = real_file("shenzhen_station_features.csv")
SZ_WATERLEVEL_HOURLY = real_file("shenzhen_waterlevel_hourly.csv")
SZ_WATERLEVEL_QC = real_file("shenzhen_waterlevel_quality_report.json")


def load_floodpoints(limit=400):
    """真实易涝点（真实区/街道/坐标）。返回 list。"""
    if not os.path.exists(SZ_FLOOD):
        return []
    out = []
    with open(SZ_FLOOD, "r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                out.append({
                    "district": r.get("district", ""), "street": r.get("street", ""),
                    "location": r.get("location", ""),
                    "lat": float(r["lat"]), "lon": float(r["lon"]),
                    "method": r.get("method", ""),
                })
            except (ValueError, KeyError):
                continue
    return out[:limit]


def load_rainfall(days=14):
    """项目缓存的历史 CHIRPS 逐日降雨；返回文件末尾 days 天。"""
    if not os.path.exists(SZ_RAIN):
        return []
    rows = []
    with open(SZ_RAIN, "r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                d = r["date"].replace(".", "-")
                rows.append({"date": d, "mean_mm": float(r["mean_mm"]),
                             "max_mm": float(r["max_mm"])})
            except (ValueError, KeyError):
                continue
    rows.sort(key=lambda x: x["date"])
    return rows[-days:]


def load_station_features(limit=200):
    if not os.path.exists(SZ_STATION_FEATURES):
        return []
    with open(SZ_STATION_FEATURES, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return rows[:limit]


def waterlevel_quality():
    import json
    if not os.path.exists(SZ_WATERLEVEL_QC):
        return {"status": "missing"}
    with open(SZ_WATERLEVEL_QC, encoding="utf-8") as fh:
        return {"status": "ready", **json.load(fh)}


def asset_summary():
    def count_csv(name):
        path = real_file(name)
        if not os.path.exists(path): return 0
        with open(path, encoding="utf-8-sig") as fh:
            return max(0, sum(1 for _ in fh) - 1)
    return {
        "dem_points": count_csv("shenzhen_dem.csv"),
        "impervious_cells": count_csv("shenzhen_builtup_density.csv"),
        "road_segments": count_csv("shenzhen_roads_summary.csv"),
        "district_boundaries": 9,
        "water_features": 5965,
    }


def realtime_snapshot():
    """资产态势；每个动态源必须依其时间字段判断是否仍然新鲜。"""
    from . import platform_fetch
    wl = None
    try:
        wl = platform_fetch.fetch_waterlevel()
    except Exception:
        wl = None
    fp = load_floodpoints()
    rain = load_rainfall()
    from . import observations
    return {
        "floodpoints": {"count": len(fp), "items": fp},
        "waterlevel": wl,
        "rainfall": {"count": len(rain), "items": rain},
        "station_features": {"count": len(load_station_features()), "items": load_station_features()},
        "waterlevel_quality": waterlevel_quality(),
        "forecast_training_readiness": observations.data_readiness(),
        "fresh_district_observations": observations.latest_district_observations(),
        "gis_assets": asset_summary(),
        "provenance": {
            "floodpoints": "observed(206 真实易涝点，天地图/OSM 定位)",
            "waterlevel": "observed(深圳开放平台积涝点水位；以 freshness 字段判定时效)",
            "rainfall": "observed-historical(CHIRPS 逐日降雨；非实时强迫)",
        },
    }


def assimilate_realtime(
    district_id,
    observed_h=None,
    at_hour=None,
    forecast_days=3,
    forecast_run_id=None,
):
    """Assimilate a fresh mapped observation or an explicitly supplied value.

    ``observed_h`` is metres.  A stale cache is never replaced by a fabricated
    default: callers receive an explicit unavailable response instead.
    """
    from . import assimilation, forecasting, observations, shenzhen, weather

    if shenzhen.get_district(district_id) is None:
        return {"status": "error", "error": f"未知行政区: {district_id}"}
    snapshot = weather.resolve_snapshot(forecast_days, forecast_run_id)
    source = "user-supplied"
    timestamp = None
    quality = "provided"

    def unavailable(reason, hint):
        return {
            "status": "unavailable",
            "district_id": district_id,
            "forecast_run_id": snapshot.get("forecast_run_id"),
            "forecast_days": int(forecast_days),
            "rainfall_source": "fallback-sample" if snapshot.get("fallback") else "open-meteo-multi-point",
            "assimilation": {
                "status": "unavailable",
                "raw_risk": [],
                "corrected_risk": [],
                "residual": None,
                "gain": None,
                "provenance": f"unavailable({reason})",
            },
            "data_readiness": observations.data_readiness(),
            "hint": hint,
        }

    if observed_h is None:
        issued_at = snapshot.get("issued_at")
        if not issued_at:
            return unavailable(
                "forecast snapshot has no audited issuance time",
                "预报快照缺少签发时间，系统已拒绝自动同化；请检查强迫数据时间契约。",
            )
        try:
            cutoff = datetime.fromisoformat(str(issued_at).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return unavailable(
                "forecast issuance time is invalid",
                "预报签发时间无法解析，系统已拒绝自动同化。",
            )
        if cutoff.tzinfo is None:
            return unavailable(
                "forecast issuance time has no timezone",
                "预报签发时间缺少时区，系统已拒绝自动同化。",
            )
        fresh = observations.latest_district_observations(
            now=cutoff,
            available_before=cutoff,
        )
        item = fresh.get(district_id)
        if item is None or not item.get("available_at"):
            return unavailable(
                "no fresh audit-safe district-mapped water-level observation",
                "请显式输入米制观测水深，或接入三小时内、已映射到行政区且带 available_at 审计时间的测站数据。",
            )
        ensemble, _, observations_used = forecasting.ensemble_for_snapshot(snapshot)
        analysis = ensemble["initial_analysis"]
        if (
            not analysis.get("applied")
            or district_id not in analysis.get("observed_districts", [])
            or district_id not in observations_used
        ):
            return unavailable(
                "fresh observation was not admitted to the frozen initial analysis",
                "观测未通过当前预报快照的初始分析时间审计，系统已保持原预报而未注入。",
            )
        item = observations_used[district_id]
        return {
            "status": "ok",
            "district_id": district_id,
            "forecast_run_id": snapshot.get("forecast_run_id"),
            "forecast_days": int(forecast_days),
            "assimilation": {
                "status": "initial_analysis_applied",
                "at_hour": -1,
                "at_time": item["observed_at"],
                "prior_mean_depth_m": analysis["prior_mean_depth_m"].get(district_id),
                "posterior_mean_depth_m": analysis["posterior_mean_depth_m"].get(district_id),
                "prior_std_m": analysis["prior_std_depth_m"].get(district_id),
                "posterior_std_m": analysis["posterior_std_depth_m"].get(district_id),
                "observation": {
                    "value": item["depth_m"],
                    "unit": "m",
                    "timestamp": item["observed_at"],
                    "source": item["provenance"],
                    "quality": "fresh-district-median-proxy",
                    "error_std_m": analysis["observation_error_m"].get(district_id),
                },
                "raw_risk": [],
                "corrected_risk": [],
                "provenance": analysis["observation_operator"],
                "mass_accounting_note": analysis["mass_accounting_note"],
                "note": "当前观测仅在预报初始分析时刻使用一次，未重复注入未来时次。",
            },
            "rainfall_source": "fallback-sample" if snapshot.get("fallback") else "open-meteo-multi-point",
        }

    if at_hour is None:
        return {
            "status": "error",
            "district_id": district_id,
            "forecast_run_id": snapshot.get("forecast_run_id"),
            "forecast_days": int(forecast_days),
            "hint": "显式输入 observed_h 时必须同时指定其预报有效时效 at_hour。",
        }
    hour = int(at_hour)
    result = assimilation.assimilate_snapshot(
        snapshot,
        district_id,
        float(observed_h),
        hour,
        observation_source=source,
        observation_timestamp=timestamp,
        observation_quality=quality,
    )
    return {
        "status": "ok",
        "district_id": district_id,
        "forecast_run_id": snapshot.get("forecast_run_id"),
        "forecast_days": int(forecast_days),
        "assimilation": result,
        "rainfall_source": "fallback-sample" if snapshot.get("fallback") else "open-meteo-multi-point",
    }
