# -*- coding: utf-8 -*-
"""CITY OS · 深圳内涝预测 v3 — FastAPI backend."""
import math
import time
from datetime import datetime
from typing import Annotated, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile

from . import (
    accessibility,
    assimilation,
    coastal,
    demo,
    dispatch,
    events,
    forecasting,
    geohazard,
    multihazard,
    ocean,
    realdatav,
    river,
    shenzhen,
    simulate,
    spatial,
    typhoon,
    userdata,
    wam,
    weather,
)
from .risk import district_vulnerability


_SCENARIO_OVERRIDE_FIELDS = frozenset({
    "rainfall_multiplier",
    "add_peak_mm",
    "peak_offset_h",
    "drainage_factor",
    "pump_efficiency",
    "mean_sea_level_m",
    "tide_raise",
    "tide_amplitude_m",
    "tide_phase_h",
    "surge_peak_m",
    "surge_peak_offset_h",
    "surge_duration_h",
    "rain_tide_peak_offset_h",
})


class ScenarioRequest(BaseModel):
    """Strict scenario body shared by API clients and auditable replay."""

    model_config = ConfigDict(extra="forbid")

    preset: Optional[str] = None
    forecast_run_id: Optional[str] = None
    forecast_days: int = Field(3, ge=1, le=7)
    rainfall_multiplier: float = Field(1.0, ge=0.0, le=5.0)
    add_peak_mm: float = Field(0.0, ge=0.0, le=300.0)
    peak_offset_h: int = Field(18, ge=0, le=167)
    drainage_factor: float = Field(1.0, ge=0.0, le=3.0)
    pump_efficiency: float = Field(1.0, ge=0.0, le=1.0)
    mean_sea_level_m: float = Field(0.0, ge=-3.0, le=5.0)
    tide_raise: Optional[float] = Field(None, ge=-3.0, le=5.0)
    tide_amplitude_m: float = Field(0.75, ge=0.0, le=3.0)
    tide_phase_h: float = Field(0.0, ge=-48.0, le=48.0)
    surge_peak_m: float = Field(0.0, ge=0.0, le=5.0)
    surge_peak_offset_h: float = Field(20.0, ge=0.0, le=167.0)
    surge_duration_h: float = Field(12.0, gt=0.0, le=168.0)
    rain_tide_peak_offset_h: Optional[float] = Field(None, ge=-72.0, le=72.0)


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    simulation_run_id: str = Field(min_length=1)


class WAMPlannerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    method: str = Field(
        "robust_cem_constant_hold",
        pattern="^(robust_cem_constant_hold|cem_mpc)$",
        description="cem_mpc is a deprecated compatibility alias",
    )
    population: int = Field(32, ge=8, le=128)
    iterations: int = Field(3, ge=1, le=8)
    elite_fraction: float = Field(0.20, ge=0.05, le=0.50)
    seed: Optional[int] = Field(None, ge=0, le=4_294_967_295)


class WAMObjectiveWeightsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    flood: float = Field(8.0, ge=0.0, le=1000.0)
    severe: float = Field(18.0, ge=0.0, le=1000.0)
    uncertainty: float = Field(2.0, ge=0.0, le=1000.0)
    energy: float = Field(0.25, ge=0.0, le=1000.0)
    mobilization: float = Field(0.20, ge=0.0, le=1000.0)


class WAMConstraintsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    min_control: float = Field(0.75, ge=0.0, le=1.0)
    max_control: float = Field(1.25, ge=1.0, le=2.0)
    max_first_step_change: float = Field(0.25, ge=0.0, le=1.0)
    emergency_budget_mm_h: float = Field(45.0, ge=0.0, le=500.0)
    no_regret_max_depth_increase_mm: float = Field(5.0, ge=0.0, le=100.0)


class WAMOptimizeRequest(BaseModel):
    """Strict, bounded request for the advisory model-based WAM planner."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    forecast_run_id: Optional[str] = Field(None, min_length=1)
    forecast_days: int = Field(3, ge=1, le=7)
    horizon_hours: int = Field(24, ge=6, le=72)
    pump_efficiency: float = Field(1.0, ge=0.0, le=1.0)
    planner: WAMPlannerRequest = Field(default_factory=WAMPlannerRequest)
    objective_weights: WAMObjectiveWeightsRequest = Field(
        default_factory=WAMObjectiveWeightsRequest
    )
    constraints: WAMConstraintsRequest = Field(default_factory=WAMConstraintsRequest)


RainfallValue = Annotated[float, Field(ge=0.0, le=500.0)]


class ManualForecastRequest(BaseModel):
    """Strict manual experiment input; errors are HTTP 422, never soft 200s."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    district_id: str = Field(min_length=1)
    rainfall: list[RainfallValue] = Field(min_length=1, max_length=240)
    tide_raise: float = Field(0.0, ge=0.0, le=5.0)


class CoastalForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    times: list[str] = Field(min_length=1, max_length=240)
    rainfall_by_district: dict[str, list[RainfallValue]]
    observed_level_m: list[float] = Field(min_length=1, max_length=240)
    predicted_tide_m: Optional[list[float]] = None
    surge_residual_m: Optional[list[float]] = None
    station_id: str = Field(min_length=1)
    datum: str = Field(min_length=1)
    source: str = Field(min_length=1)
    available_at: str = Field(min_length=1)


class RiverForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    basin_rainfall_mm_h: dict[str, list[RainfallValue]]
    upstream_inflow_m3_s: float = Field(0.0, ge=0.0, le=100000.0)


class GeoHazardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    rainfall_mm_h: list[RainfallValue] = Field(min_length=1, max_length=240)
    slope_deg: float = Field(ge=0.0, le=90.0)
    soil_saturation: float = Field(0.35, ge=0.0, le=1.0)
    geology_vulnerability: float = Field(0.5, ge=0.0, le=1.0)
    impervious_ratio: float = Field(0.3, ge=0.0, le=1.0)
    vegetation_fraction: float = Field(0.5, ge=0.0, le=1.0)


class TyphoonTrackPointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    max_wind_m_s: float = Field(ge=0.0, le=120.0)
    central_pressure_hpa: float = Field(ge=850.0, le=1050.0)
    rain_rate_mm_h: float = Field(ge=0.0, le=500.0)


class TyphoonMultiHazardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    times: list[str] = Field(min_length=1, max_length=168)
    track: list[TyphoonTrackPointRequest] = Field(min_length=1, max_length=168)
    upstream_inflow_m3_s: float = Field(0.0, ge=0.0, le=100000.0)
    mean_sea_level_m: float = Field(0.0, ge=-3.0, le=5.0)


def _scenario_from_request(config: ScenarioRequest):
    explicit_overrides = sorted(
        _SCENARIO_OVERRIDE_FIELDS.intersection(config.model_fields_set)
    )
    if config.preset is not None and explicit_overrides:
        raise HTTPException(
            status_code=422,
            detail=(
                "preset 不可与情景覆盖参数混用；请只传 preset，或移除 preset 后提交自定义参数: "
                + ", ".join(explicit_overrides)
            ),
        )
    if config.preset is not None:
        if config.preset not in simulate.SCENARIOS:
            raise HTTPException(status_code=422, detail=f"未知情景预设: {config.preset}")
        return {
            key: value
            for key, value in simulate.SCENARIOS[config.preset].items()
            if key != "label"
        }
    values = config.model_dump(
        exclude={"preset", "forecast_run_id", "forecast_days", "tide_raise"},
        exclude_none=True,
    )
    if config.tide_raise is not None:
        if config.mean_sea_level_m != 0.0:
            raise HTTPException(
                status_code=422,
                detail="请勿同时提供 tide_raise 与 mean_sea_level_m；tide_raise 已弃用。",
            )
        values["mean_sea_level_m"] = float(config.tide_raise)
    return values


def _scenario_request_from_query(
    request: Request,
    *,
    preset,
    forecast_run_id,
    forecast_days,
    scenario_values,
):
    """Preserve which scenario values a GET client explicitly supplied.

    FastAPI has already applied and validated query defaults when this helper is
    called. Passing every resolved default into Pydantic would nevertheless mark
    every field as explicit, making a bare ``?preset=...`` indistinguishable from
    a preset mixed with overrides.
    """
    query_items = list(request.query_params.multi_items())
    query_names = [name for name, _ in query_items]
    allowed_fields = {
        "preset", "forecast_run_id", "forecast_days", *_SCENARIO_OVERRIDE_FIELDS
    }
    unknown_fields = sorted(set(query_names) - allowed_fields)
    if unknown_fields:
        raise HTTPException(
            status_code=422,
            detail="未知情景查询参数: " + ", ".join(unknown_fields),
        )
    repeated_fields = sorted({
        name for name in query_names if query_names.count(name) > 1
    })
    if repeated_fields:
        raise HTTPException(
            status_code=422,
            detail="情景查询参数不可重复: " + ", ".join(repeated_fields),
        )
    explicit_query_fields = set(query_names)
    payload = {
        "preset": preset,
        "forecast_run_id": forecast_run_id,
        "forecast_days": forecast_days,
    }
    payload.update({
        name: value
        for name, value in scenario_values.items()
        if name in explicit_query_fields
    })
    return ScenarioRequest(**payload)


def _raise_simulation_http_error(exc: ValueError):
    message = str(exc)
    status = 409 if (
        "forecast_run_id" in message
        or "pinned snapshot horizon" in message
        or "snapshot does not match" in message
    ) else 422
    raise HTTPException(status_code=status, detail=message) from exc

app = FastAPI(
    title="CITY OS · 深圳多灾种世界模型 v4",
    description="城市内涝、海岸洪涝、河流山洪、地质灾害和台风统一强迫的可审计世界模型",
    version="4.0.0",
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-BBox-South",
        "X-BBox-West",
        "X-BBox-North",
        "X-BBox-East",
        "X-Res-Deg",
        "X-Forecast-Run-Id",
        "X-Forecast-Days",
        "X-Temporal-Slice",
        "X-Visible-Cell-Count",
        "X-Total-Cell-Count",
        "X-Max-Depth-Mm",
        "X-Max-Probability",
        "X-Raster-Empty",
    ],
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

def _get_forecast(forecast_days: int):
    return weather.forecast_snapshot(forecast_days=forecast_days)


def _build_predict(forecast_days: int, forecast_run_id: Optional[str] = None):
    # The API serializer is intentionally centralized so prediction, scenario
    # simulation and data assimilation cannot drift into different dynamics.
    snapshot = weather.resolve_snapshot(forecast_days, forecast_run_id)
    return forecasting.build_predict(snapshot)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "cityos-flood",
        "version": "4.0.0-multihazard",
        "model_version": forecasting.MODEL_VERSION,
        "time": time.time(),
    }


def _json_arrays(value):
    """Recursively convert NumPy results into API-safe JSON values."""
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {key: _json_arrays(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_arrays(item) for item in value]
    return value


@app.post("/api/hazards/coastal")
def forecast_coastal(payload: CoastalForecastRequest):
    """Observed/forecast sea level plus rainfall, with marine volume accounting."""
    try:
        boundary = coastal.boundary_from_levels(
            payload.times, payload.observed_level_m,
            predicted_tide_m=payload.predicted_tide_m,
            surge_residual_m=payload.surge_residual_m,
            station_id=payload.station_id, datum=payload.datum,
            source=payload.source, available_at=payload.available_at,
        )
        return _json_arrays(coastal.DEFAULT_MODEL.simulate(payload.rainfall_by_district, boundary))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/hazards/river")
def forecast_river(payload: RiverForecastRequest):
    """Basin rainfall and upstream-boundary river/floodplain forecast."""
    try:
        return _json_arrays(river.DEFAULT_MODEL.simulate(
            payload.basin_rainfall_mm_h, payload.upstream_inflow_m3_s
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/hazards/geology")
def forecast_geology(payload: GeoHazardRequest):
    """Dynamic runoff coefficient, soil saturation and slope-failure belief."""
    try:
        return _json_arrays(geohazard.DEFAULT_MODEL.simulate(**payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/hazards/typhoon")
def forecast_typhoon(payload: TyphoonMultiHazardRequest):
    """One typhoon track drives rainfall, wind, tide, river and terrain hazards."""
    if len(payload.times) != len(payload.track):
        raise HTTPException(status_code=422, detail="times and track lengths must match")
    try:
        result = typhoon.simulate(
            payload.times, [point.model_dump() for point in payload.track],
            upstream_inflow_m3_s=payload.upstream_inflow_m3_s,
            mean_sea_level_m=payload.mean_sea_level_m,
        )
        return _json_arrays(result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/districts")
def districts():
    return {
        "city": shenzhen.CITY, "drainage_avg": round(shenzhen.DRAINAGE_AVG, 2),
        "districts": [
            {"id": d["id"], "name": d["name"], "center": d["center"], "drainage": d["drainage_design"],
             "elevation": d["elevation_mean"], "historical_index": d["historical_flood_index"],
             "tag": d["tag"], "vulnerability": district_vulnerability(d)[0]}
            for d in shenzhen.DISTRICTS
        ],
    }


@app.get("/api/forecast")
def forecast(
    forecast_days: int = Query(3, ge=1, le=7),
    forecast_run_id: Optional[str] = None,
):
    try:
        f = weather.resolve_snapshot(forecast_days, forecast_run_id)
    except ValueError as exc:
        _raise_simulation_http_error(exc)
    return {
        "data_source": "fallback-sample" if f["fallback"] else "open-meteo-multi-point",
        "forecast_run_id": f.get("forecast_run_id"),
        "forecast_days": forecast_days,
        "issued_at": f.get("issued_at"),
        "snapshot_created_at": f.get("snapshot_created_at"),
        "available_at": f.get("available_at"),
        "forcing_selection_as_of": f.get("forcing_selection_as_of"),
        "provider_forecast_issued_at": f.get("provider_forecast_issued_at"),
        "issued_at_semantics": f.get("issued_at_semantics"),
        "times": f["times"], "rainfall_city": f["city"], "city_cum24": f["city_cum"],
        "districts": {k: v for k, v in f["districts"].items()},
        "cum": {k: v for k, v in f["cum"].items()},
    }


@app.get("/api/predict")
def predict(
    forecast_days: int = Query(3, ge=1, le=7),
    forecast_run_id: Optional[str] = None,
):
    try:
        return _build_predict(forecast_days, forecast_run_id)
    except ValueError as exc:
        _raise_simulation_http_error(exc)


@app.get("/api/spatial")
def get_spatial():
    """显式空间耦合表（理论 §2.1）：区↔区路网、设施↔区、格点↔区，含 provenance。"""
    return spatial.summary()


@app.get("/api/accessibility")
def get_accessibility(
    forecast_days: int = Query(3, ge=1, le=7),
    depth_mm: str = None,
    damage: str = None,
    forecast_run_id: Optional[str] = None,
):
    """道路损伤 + 设施动态可达性（理论 #4）。
    depth_mm 可选，形如 'futian:350,luohu:120'。
    damage 为兼容参数，值是0..0.95损伤比例，会显式反算为水深。
    缺省时用守恒集合模型的 P50 峰值水深(mm)驱动。"""
    if depth_mm is not None and damage is not None:
        raise HTTPException(
            status_code=422,
            detail="depth_mm 与兼容参数 damage 互斥，请只提供一种。",
        )
    if depth_mm is not None or damage is not None:
        depth = {}
        try:
            raw_depth = depth_mm if depth_mm is not None else damage
            if not isinstance(raw_depth, str) or not raw_depth.strip():
                raise ValueError("水深输入不能为空")
            for kv in raw_depth.split(","):
                if kv.count(":") != 1:
                    raise ValueError("输入格式必须为 district:value，多个区用逗号分隔")
                key, value = (part.strip() for part in kv.split(":", 1))
                district_id = key
                if shenzhen.get_district(district_id) is None:
                    raise ValueError(f"未知行政区: {district_id}")
                number = float(value)
                if not math.isfinite(number) or number < 0.0:
                    raise ValueError(f"{district_id} 的输入必须是有限非负数")
                depth[district_id] = (
                    number
                    if depth_mm is not None
                    else accessibility.damage_ratio_to_depth(number)
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        snapshot = weather.resolve_snapshot(forecast_days, forecast_run_id)
    except ValueError as exc:
        _raise_simulation_http_error(exc)
    if depth_mm is None and damage is None:
        depth = forecasting.peak_depth_by_district(snapshot)
    result = accessibility.compute_accessibility(depth)
    return {
        **result,
        "forecast_run_id": snapshot.get("forecast_run_id"),
        "forecast_days": forecast_days,
    }


@app.get("/api/counterfactual")
def get_counterfactual(
    forecast_days: int = Query(3, ge=1, le=7),
    close: str = None,
    pump: str = None,
    forecast_run_id: Optional[str] = None,
):
    """反事实并排对比（理论 #5）：基线 vs 干预(封路/抽排)，输出设施可达人口 Δ。"""
    try:
        snapshot = weather.resolve_snapshot(forecast_days, forecast_run_id)
    except ValueError as exc:
        _raise_simulation_http_error(exc)
    depth = forecasting.peak_depth_by_district(snapshot)
    try:
        result = accessibility.counterfactual(depth, close=close, pump=pump)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **result,
        "forecast_run_id": snapshot.get("forecast_run_id"),
        "forecast_days": forecast_days,
    }


@app.get("/api/assimilate")
def get_assimilate(
    district: str,
    observed_h: float = Query(..., ge=0.0, le=5.0),
    at_hour: int = Query(6, ge=0, le=167),
    forecast_days: int = Query(3, ge=1, le=7),
    k: float = 0.3,
    forecast_run_id: Optional[str] = None,
):
    """Inject a metre-valued observation using the localized ensemble filter.

    ``k`` is retained as an ignored compatibility query parameter; the gain is
    now derived from the ensemble covariance and observation error.
    """
    try:
        snapshot = weather.resolve_snapshot(forecast_days, forecast_run_id)
        return assimilation.assimilate_snapshot(
            snapshot, district, observed_h, at_hour
        )
    except ValueError as exc:
        _raise_simulation_http_error(exc)


@app.get("/api/events")
def get_events():
    return {"events": events.HISTORICAL_EVENTS, "historical_index": events.historical_index()}


@app.get("/api/scenarios")
def get_scenarios():
    return {"scenarios": simulate.SCENARIOS}


@app.get("/api/simulate")
def get_simulate(
    request: Request,
    preset: Optional[str] = None,
    forecast_run_id: Optional[str] = None,
    forecast_days: int = Query(3, ge=1, le=7),
    rainfall_multiplier: float = Query(1.0, ge=0.0, le=5.0),
    add_peak_mm: float = Query(0.0, ge=0.0, le=300.0),
    peak_offset_h: int = Query(18, ge=0, le=167),
    drainage_factor: float = Query(1.0, ge=0.0, le=3.0),
    pump_efficiency: float = Query(1.0, ge=0.0, le=1.0),
    mean_sea_level_m: float = Query(0.0, ge=-3.0, le=5.0),
    tide_raise: Optional[float] = Query(None, ge=-3.0, le=5.0),
    tide_amplitude_m: float = Query(0.75, ge=0.0, le=3.0),
    tide_phase_h: float = Query(0.0, ge=-48.0, le=48.0),
    surge_peak_m: float = Query(0.0, ge=0.0, le=5.0),
    surge_peak_offset_h: float = Query(20.0, ge=0.0, le=167.0),
    surge_duration_h: float = Query(12.0, gt=0.0, le=168.0),
    rain_tide_peak_offset_h: Optional[float] = Query(None, ge=-72.0, le=72.0),
):
    config = _scenario_request_from_query(
        request,
        preset=preset,
        forecast_run_id=forecast_run_id,
        forecast_days=forecast_days,
        scenario_values={
            "rainfall_multiplier": rainfall_multiplier,
            "add_peak_mm": add_peak_mm,
            "peak_offset_h": peak_offset_h,
            "drainage_factor": drainage_factor,
            "pump_efficiency": pump_efficiency,
            "mean_sea_level_m": mean_sea_level_m,
            "tide_raise": tide_raise,
            "tide_amplitude_m": tide_amplitude_m,
            "tide_phase_h": tide_phase_h,
            "surge_peak_m": surge_peak_m,
            "surge_peak_offset_h": surge_peak_offset_h,
            "surge_duration_h": surge_duration_h,
            "rain_tide_peak_offset_h": rain_tide_peak_offset_h,
        },
    )
    sc = _scenario_from_request(config)
    try:
        res = simulate.simulate(
            sc,
            forecast_days=forecast_days,
            forecast_run_id=forecast_run_id,
        )
    except ValueError as exc:
        _raise_simulation_http_error(exc)
    res["scale"] = "district·hourly scenario"
    res["simulated"] = True
    return res


@app.get("/api/ocean/boundary")
def get_ocean_boundary(
    forecast_days: int = Query(3, ge=1, le=7),
    tide_amplitude_m: float = Query(0.75, ge=0.0, le=3.0),
    tide_phase_h: float = Query(0.0, ge=-48.0, le=48.0),
    surge_peak_m: float = Query(0.0, ge=0.0, le=5.0),
    surge_peak_offset_h: float = Query(20.0, ge=0.0, le=167.0),
    surge_duration_h: float = Query(12.0, gt=0.0, le=168.0),
    forecast_run_id: Optional[str] = None,
):
    """调和潮 + 参数化风暴增水预览；明确为预测/模拟代理而非潮位站实测。"""
    try:
        fc = weather.resolve_snapshot(forecast_days, forecast_run_id)
    except ValueError as exc:
        _raise_simulation_http_error(exc)
    scenario = dict(tide_amplitude_m=tide_amplitude_m, tide_phase_h=tide_phase_h,
                    surge_peak_m=surge_peak_m, surge_peak_offset_h=surge_peak_offset_h,
                    surge_duration_h=surge_duration_h)
    try:
        boundary = ocean.build_boundary(fc["times"], scenario, fc.get("city"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **boundary,
        "forecast_run_id": fc.get("forecast_run_id"),
        "forecast_days": forecast_days,
        "forcing_issued_at": fc.get("issued_at"),
        "provider_forecast_issued_at": fc.get("provider_forecast_issued_at"),
        "forcing_issued_at_semantics": fc.get("issued_at_semantics"),
    }


@app.get("/api/ocean/catalog")
def get_ocean_catalog():
    """站点/岸段目录与事件采集清单；catalogued 不代表已有观测。"""
    import csv
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "data"
    def read_csv(name):
        with (root / name).open(encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    return {
        "stations": read_csv("ocean_stations.csv"),
        "events": read_csv("ocean_events.csv"),
        "district_boundaries": ocean.DISTRICT_BOUNDARIES,
        "observation_status": "awaiting_source_data",
        "datum_guard": "different datums must not be compared before traceable conversion",
    }


@app.get("/api/ocean/offset-experiment")
def get_ocean_offset_experiment(
    forecast_days: int = Query(3, ge=1, le=3),
    forecast_run_id: Optional[str] = None,
):
    """固定海洋/降雨强度，仅改变雨峰−潮峰时间差。"""
    try:
        snapshot = weather.resolve_snapshot(forecast_days, forecast_run_id)
    except ValueError as exc:
        _raise_simulation_http_error(exc)
    pinned_run_id = snapshot.get("forecast_run_id")
    rows = []
    for offset in (-6, 0, 6):
        sc = dict(rainfall_multiplier=1.3, add_peak_mm=22, drainage_factor=1.0,
                  tide_amplitude_m=0.95, surge_peak_m=0.65,
                  surge_peak_offset_h=20, surge_duration_h=14,
                  rain_tide_peak_offset_h=offset)
        result = simulate.simulate(
            sc,
            forecast_days=forecast_days,
            snapshot=snapshot,
            forecast_run_id=pinned_run_id,
        )
        worst = max(result["districts"], key=lambda d: d["scenario_peak"]["depth_p50_m"])
        rows.append({"offset_h": offset, "label": "提前6小时" if offset < 0 else "同时发生" if offset == 0 else "滞后6小时",
                     "worst_district": worst["name"], "peak_probability": worst["scenario_peak"]["prob"],
                     "peak_depth_p50_m": worst["scenario_peak"]["depth_p50_m"],
                     "compound_index": result["ocean"]["compound_index"]})
    return {
        "forecast_run_id": pinned_run_id,
        "forecast_days": forecast_days,
        "forcing_issued_at": snapshot.get("issued_at"),
        "provider_forecast_issued_at": snapshot.get("provider_forecast_issued_at"),
        "forcing_issued_at_semantics": snapshot.get("issued_at_semantics"),
        "controlled_variables": "same rainfall amount and same ocean boundary; peak timing only",
        "results": rows,
    }


@app.post("/api/simulate")
def post_simulate(config: ScenarioRequest):
    sc = _scenario_from_request(config)
    try:
        res = simulate.simulate(
            sc,
            forecast_days=config.forecast_days,
            forecast_run_id=config.forecast_run_id,
        )
    except ValueError as exc:
        _raise_simulation_http_error(exc)
    res["scale"] = "district·hourly scenario"
    res["simulated"] = True
    return res


@app.post("/api/dispatch")
def dispatch_action(payload: DispatchRequest):
    requested_run = payload.simulation_run_id
    result = simulate.get_cached(requested_run)
    if result is None:
        raise HTTPException(
            status_code=409,
            detail="该 simulation_run_id 已不在当前进程缓存中，请重新运行情景后再下发。",
        )
    pushes = [{"district": a["district"], "status": dispatch.push_alert(a)} for a in result["alerts"]]
    return {"simulate": result, "push": pushes, "pushed": len(pushes)}


@app.get("/api/alerts")
def get_alerts(limit: int = Query(50, ge=1, le=200)):
    return {"alerts": dispatch.get_pushed_alerts(limit)}


# ============ 自主优化行动 WAM（模型式安全基线，非已训练 RL）============

@app.get("/api/wam/architecture")
def get_wam_architecture():
    """Return the implemented decision contract and the honest RL roadmap."""
    return wam.architecture()


@app.post("/api/wam/optimize")
def optimize_wam_action(payload: WAMOptimizeRequest):
    """Search a constrained action; never writes the result to an actuator."""
    try:
        snapshot = weather.resolve_snapshot(
            payload.forecast_days, payload.forecast_run_id
        )
    except ValueError as exc:
        _raise_simulation_http_error(exc)
    try:
        return wam.optimize(
            snapshot,
            payload.model_dump(exclude={"forecast_run_id", "forecast_days"}),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/wam/audits/{decision_run_id}")
def get_wam_audit(decision_run_id: str):
    """Retrieve an exact advisory-decision audit record when still retained."""
    if not decision_run_id or len(decision_run_id) > 128:
        raise HTTPException(status_code=422, detail="decision_run_id 格式无效")
    record = wam.get_audit(decision_run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="未找到该 WAM 决策审计记录")
    return record


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
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "multipart/form-data":
        raise HTTPException(
            status_code=422,
            detail="请以 multipart/form-data 上传 file 字段中的 CSV 文件。",
        )
    try:
        form = await request.form()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="multipart 表单无法解析。") from exc
    raw_file = form.get("file")
    if (
        not isinstance(raw_file, UploadFile)
        or not getattr(raw_file, "filename", "")
    ):
        raise HTTPException(status_code=422, detail="multipart 表单缺少有效的 file 文件字段。")
    file = raw_file

    content = bytearray()
    read_limit = userdata.MAX_UPLOAD_BYTES + 1
    try:
        while len(content) < read_limit:
            chunk = await file.read(min(1024 * 1024, read_limit - len(content)))
            if not chunk:
                break
            content.extend(chunk)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="上传文件读取失败。") from exc
    if len(content) > userdata.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {userdata.MAX_UPLOAD_BYTES // 1024 // 1024}MB 限制。",
        )

    result = userdata.upload_data(file.filename, bytes(content))
    if result.get("status") not in {"ok", "accepted"}:
        raise HTTPException(
            status_code=422,
            detail=result.get("hint") or "CSV Schema/QC 未通过。",
        )
    return result


@app.post("/api/forecast/manual")
def api_forecast_manual(payload: ManualForecastRequest):
    result = userdata.manual_forecast(
        payload.district_id,
        payload.rainfall,
        tide_raise=payload.tide_raise,
    )
    if result.get("status") == "error":
        raise HTTPException(
            status_code=422,
            detail=result.get("error") or "手动推演参数无效。",
        )
    return result


# ============ 实时抓取平台数据 ============

@app.get("/api/platform/realtime")
def api_platform_realtime():
    """开放平台水位快照；响应显式标注观测时间、新鲜度和缓存状态。"""
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
    """观测资产态势：易涝点、带新鲜度水位快照与历史 CHIRPS 日雨。"""
    return realdatav.realtime_snapshot()


@app.get("/api/assimilate/realtime")
def api_assimilate_realtime(
    district: str = Query("baoan", min_length=1),
    observed_h: Optional[float] = Query(None, ge=0.0, le=5.0),
    at_hour: Optional[int] = Query(None, ge=0, le=167),
    forecast_days: int = Query(3, ge=1, le=7),
    forecast_run_id: Optional[str] = None,
):
    """数据同化闭环：米制水深观测注入体积状态，返回修正后轨迹。"""
    if shenzhen.get_district(district) is None:
        raise HTTPException(status_code=422, detail=f"未知行政区: {district}")
    if observed_h is not None and at_hour is None:
        raise HTTPException(
            status_code=422,
            detail="显式输入 observed_h 时必须同时指定其预报有效时效 at_hour。",
        )
    try:
        result = realdatav.assimilate_realtime(
            district,
            observed_h,
            at_hour,
            forecast_days=forecast_days,
            forecast_run_id=forecast_run_id,
        )
    except ValueError as exc:
        _raise_simulation_http_error(exc)
    if result.get("status") == "error":
        raise HTTPException(
            status_code=422,
            detail=result.get("error") or result.get("hint") or "实时同化参数无效。",
        )
    return result


# ============ 街道代表点风险排序（真实 GIS 特征的有界下尺度）============

@app.get("/api/risk/street")
def api_risk_street(
    forecast_days: int = Query(3, ge=1, le=7), forecast_run_id: Optional[str] = None
):
    """代表点风险排序：区级动力学 + 30 个点位静态因子；不是街道水动力水深。"""
    from . import streets
    try:
        snapshot = weather.resolve_snapshot(forecast_days, forecast_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return streets.get_street_risk(forecast_days, snapshot=snapshot)


# ============ 分区分时风险热力 · 加密网格 ============

@app.get("/api/risk/grid")
def api_risk_grid(
    forecast_days: int = Query(3, ge=1, le=7),
    res: float = Query(0.018, ge=0.009, le=0.1),
    forecast_run_id: Optional[str] = None,
):
    """加密网格风险热力（~2km 格，区级聚合降雨 + DEM/WorldCover 因子）。"""
    from . import gridrisk
    try:
        snapshot = weather.resolve_snapshot(forecast_days, forecast_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return gridrisk.get_grid_risk(forecast_days, res, snapshot=snapshot)


@app.head("/api/risk/grid/image")
@app.get("/api/risk/grid/image")
def api_risk_grid_image(
    res: float = Query(0.0045, ge=0.0045, le=0.05),
    forecast_days: int = Query(3, ge=1, le=7),
    forecast_run_id: Optional[str] = None,
    hour_index: Optional[int] = Query(None, ge=0, le=167),
):
    """约500m风险 PNG；hour_index 缺省时表示全预报期成员峰值。"""
    from fastapi.responses import Response
    from . import gridrisk
    try:
        snapshot = weather.resolve_snapshot(forecast_days, forecast_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        png, bbox, metadata = gridrisk.get_grid_image(
            res,
            forecast_days,
            snapshot=snapshot,
            hour_index=hour_index,
            include_metadata=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(content=png, media_type="image/png", headers={
        "X-BBox-South": str(bbox["south"]), "X-BBox-West": str(bbox["west"]),
        "X-BBox-North": str(bbox["north"]), "X-BBox-East": str(bbox["east"]),
        "X-Res-Deg": str(res),
        "X-Forecast-Run-Id": str(snapshot.get("forecast_run_id") or ""),
        "X-Forecast-Days": str(forecast_days),
        "X-Temporal-Slice": "horizon-peak" if hour_index is None else f"hour-{hour_index}",
        "X-Visible-Cell-Count": str(metadata["visible_cell_count"]),
        "X-Total-Cell-Count": str(metadata["total_cell_count"]),
        "X-Max-Depth-Mm": str(metadata["max_depth_mm"]),
        "X-Max-Probability": str(metadata["max_probability"]),
        "X-Raster-Empty": "true" if metadata["empty"] else "false",
        "Cache-Control": "private, max-age=600",
        "X-Content-Type-Options": "nosniff",
    })


# ============ 全自然灾害（v4 多灾种展示 + 3D 场景）============

@app.get("/api/hazards/summary")
def api_hazards_summary():
    """四大灾种真实数据总览：台风/风暴潮/内涝/滑坡。"""
    return {
        "typhoon": multihazard.typhoon_summary(),
        "surge": multihazard.surge_summary(),
        "landslide": multihazard.landslide_summary(),
        "flood": {
            "name": "内涝",
            "note": "沿用守恒状态空间集合模型（forecasting/state_model）",
            "provenance": "Open-Meteo 降雨预报 + DEM/WorldCover/OSM 派生城市特征",
        },
        "provenance": "四大灾种真实数据来自 shenzhen-flood/data/unified 统一数据层",
    }


@app.get("/api/hazards/typhoon/track")
def api_typhoon_track(name: str = "", sid: str = ""):
    """单个台风路径点序列（供地图/3D 绘制）。"""
    if name:
        pts = multihazard.typhoon_track_points(name=name)
    elif sid:
        pts = multihazard.typhoon_track_points(sid=sid)
    else:
        pts = []
    return {"points": pts, "n": len(pts), "query": {"name": name, "sid": sid}}


@app.get("/api/scene3d")
def api_scene3d(
    dem_step: int = Query(8, ge=2, le=32),
    building_min_height: float = Query(40.0, ge=0.0, le=200.0),
    building_limit: int = Query(5000, ge=100, le=20000),
):
    """3D 场景数据：DEM 地形 + 建筑高度 + 灾种点叠加。"""
    return multihazard.scene3d(
        dem_step=dem_step,
        building_min_height=building_min_height,
        building_limit=building_limit,
    )


# ============ 已训练监督模型（真实标签 ML）============

@app.get("/api/ml/landslide-sensitivity")
def api_ml_landslide_sensitivity(
    rain_max_mm: float = Query(200.0, ge=20.0, le=500.0),
    sm1: float = Query(0.35, ge=0.1, le=0.6),
    month: int = Query(9, ge=1, le=12),
):
    """滑坡概率对降雨量的敏感性曲线（模型可解释性）。"""
    from . import ml_models
    r = ml_models.landslide_sensitivity(rain_max_mm=rain_max_mm, sm1=sm1, month=month)
    if r is None:
        raise HTTPException(status_code=503, detail="模型未就绪")
    return r


@app.get("/api/ml/metrics")
def api_ml_metrics():
    """全部本地训练模型的指标（真实标签训练）。"""
    from . import ml_models
    return ml_models.all_metrics()


@app.get("/api/ml/flood-spatial")
def api_ml_flood_spatial(lat: float, lon: float):
    """单点内涝空间风险（206 真实易涝点训练的模型）。"""
    from . import ml_models
    r = ml_models.predict_flood_spatial(lat, lon)
    if r is None:
        raise HTTPException(status_code=503, detail="模型未就绪")
    return r


@app.get("/api/ml/flood-grid")
def api_ml_flood_grid(n: int = Query(60, ge=10, le=300)):
    """全市网格内涝风险采样（模型热力）。"""
    from . import ml_models
    return {"points": ml_models.predict_flood_grid(n)}


@app.get("/api/ml/wave")
def api_ml_wave(
    tc_lat: float, tc_lon: float,
    wind_kt: float = 80.0, pres_hpa: float = 965.0,
    hours: float = 0.0, pt_lat: float = 22.2, pt_lon: float = 114.6,
):
    """台风状态 → 近岸波高预测（CMEMS 真实波高标签训练）。"""
    from . import ml_models
    r = ml_models.predict_wave(tc_lat, tc_lon, wind_kt, pres_hpa, hours, pt_lat, pt_lon)
    if r is None:
        raise HTTPException(status_code=503, detail="模型未就绪")
    return r


@app.get("/api/ml/landslide-warning")
def api_ml_landslide_warning(
    rain_24h: float, rain_72h: float = None,
    rain_168h: float = None, rain_max24h: float = None,
    sm1: float = 0.3, sm2: float = 0.32, sm3: float = 0.34, month: int = 7,
):
    """气象状态 → 地灾预警发布概率（905 条官方预警训练）。"""
    from . import ml_models
    rain_72h = rain_72h if rain_72h is not None else rain_24h
    rain_168h = rain_168h if rain_168h is not None else rain_24h
    rain_max24h = rain_max24h if rain_max24h is not None else rain_24h / 6.0
    r = ml_models.predict_landslide_warning(rain_24h, rain_72h, rain_168h, rain_max24h, sm1, sm2, sm3, month)
    if r is None:
        raise HTTPException(status_code=503, detail="滑坡预警模型未就绪（ERA5特征下载中）")
    return r


# ============ 多灾种链式预测：台风 → 降雨 → 滑坡 ============

@app.get("/api/ml/cascade/typhoon")
def api_ml_cascade_typhoon(name: str = "", sid: str = ""):
    """真实台风 → 降雨场 → 分区滑坡预警概率（链式预测）。"""
    from . import cascade
    r = cascade.cascade_for_typhoon(name=name or None, sid=sid or None)
    if r is None:
        raise HTTPException(status_code=404, detail="台风路径数据不足")
    return r


@app.post("/api/ml/cascade/track")
async def api_ml_cascade_track(request: Request):
    """自定义台风路径 → 滑坡概率（供沙盘推演）。"""
    from . import cascade
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON")
    track = body.get("track") or []
    start = body.get("start_date") or "2026-09-01"
    soil = body.get("soil") or [0.32, 0.34, 0.36]
    if len(track) < 6:
        raise HTTPException(status_code=422, detail="track 需要至少 6 个路径点")
    r = cascade.predict_landslide_cascade(track, start, soil=tuple(soil))
    return {"daily": r, "chain": cascade.predict_landslide_cascade.__doc__ or ""}


# ============ 单页指挥中心：统一实时预测 ============

@app.get("/api/live")
def api_live():
    """一次返回全部灾种实时状态与预测（Open-Meteo 实时 + 守恒模型 + ML）。"""
    import json as _json
    from fastapi import Response as _Resp
    from . import live_ops
    data = live_ops.build_live()
    # 短缓存：60s 内代理/浏览器可复用（数据本身 10 分钟更新）
    return _Resp(
        content=_json.dumps(data, ensure_ascii=False, default=str),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=60"},
    )


@app.get("/api/live/refresh")
def api_live_refresh():
    """强制刷新实时数据（绕过缓存）。"""
    from . import live_ops
    return live_ops.refresh()


# ============ WAM 决策工单闭环（建议→批准→执行→回评）============

class DecisionSubmitRequest(BaseModel):
    """WAM 建议提交（进入待人工决策队列）。"""
    model_config = ConfigDict(extra="forbid")
    plan_summary: str = Field(min_length=4, max_length=500)
    control_actions: list = Field(default_factory=list, max_length=20)
    expected_flood_peak_mm: Optional[float] = None
    method: str = Field(default="robust_cem_constant_hold", max_length=64)


@app.post("/api/decisions/submit")
def api_decision_submit(payload: DecisionSubmitRequest):
    """WAM 优化建议 → 待人工决策队列。"""
    from . import decision
    return decision.submit_suggestion(
        optimizer_run={"method": payload.method,
                       "expected_flood_peak_mm": payload.expected_flood_peak_mm},
        plan_summary=payload.plan_summary,
        control_actions=payload.control_actions,
    )


class DecisionActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_id: str = Field(min_length=1)
    by: str = Field(default="值班指挥", max_length=64)
    note: str = Field(default="", max_length=500)


@app.post("/api/decisions/approve")
def api_decision_approve(payload: DecisionActionRequest):
    """人工批准决策（进入执行队列）。"""
    from . import decision
    r = decision.approve(payload.decision_id, payload.by, payload.note)
    if r is None:
        raise HTTPException(status_code=404, detail="工单不存在或状态不允许")
    return r


@app.post("/api/decisions/reject")
def api_decision_reject(payload: DecisionActionRequest):
    """人工驳回（附理由）。"""
    from . import decision
    r = decision.reject(payload.decision_id, payload.by, payload.note)
    if r is None:
        raise HTTPException(status_code=404, detail="工单不存在或状态不允许")
    return r


class DecisionCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_id: str = Field(min_length=1)
    flood_peak_mm_actual: Optional[float] = None
    control_applied: bool = True
    note: str = Field(default="", max_length=500)


@app.post("/api/decisions/complete")
def api_decision_complete(payload: DecisionCompleteRequest):
    """执行完成 → 效果回评（建议 vs 实际）。"""
    from . import decision
    r = decision.complete(payload.decision_id, {
        "flood_peak_mm_actual": payload.flood_peak_mm_actual,
        "control_applied": payload.control_applied,
        "note": payload.note,
    })
    if r is None:
        raise HTTPException(status_code=404, detail="工单不存在或状态不允许")
    return r


@app.get("/api/decisions")
def api_decisions(status: str = ""):
    """决策工单列表（含状态统计与审计链）。"""
    from . import decision
    return decision.list_decisions(status)


# ============ 台风情景 What-if 推演 ============

@app.get("/api/cascade/whatif")
def api_cascade_whatif(
    name: str = "",
    dist_shift_km: float = Query(0.0, ge=-300.0, le=300.0),
    wind_factor: float = Query(1.0, ge=0.5, le=2.0),
):
    """台风情景推演：路径平移/强度缩放 → 灾害链（降雨/滑坡/内涝）对比。"""
    from . import cascade
    r = cascade.whatif_typhoon(
        name=name or None,
        dist_shift_km=dist_shift_km,
        wind_factor=wind_factor,
    )
    if r is None:
        raise HTTPException(status_code=404, detail="台风路径数据不足")
    return r


# ============ 实时告警推送（SSE）============

@app.get("/api/alerts/stream")
async def alerts_stream():
    """SSE 告警流：每 60s 推送当前告警快照（长连接，自动断线重连）。"""
    import asyncio
    import json as _json
    from fastapi.responses import StreamingResponse
    from . import live_ops

    async def gen():
        last_sig = None
        for _ in range(1440):  # 最长 24h，客户端自动重连
            try:
                live = live_ops.build_live()
                alerts = live.get("alerts", [])
                sig = _json.dumps([a["id"] for a in alerts])
                payload = {
                    "type": "alerts" if sig != last_sig else "heartbeat",
                    "alerts": alerts if sig != last_sig else [],
                    "generated_at": live.get("generated_at"),
                }
                yield f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"
                last_sig = sig
            except Exception:
                yield f"data: {_json.dumps({'type': 'heartbeat'})}\n\n"
            await asyncio.sleep(60)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============ 风暴潮（天文潮谐波 + 台风增水参数化）============

@app.get("/api/surge/live")
def api_surge_live(hours: int = Query(48, ge=6, le=120)):
    """实时风暴潮：两站天文潮推算 + 活跃台风增水叠加 + 预警水位分级。"""
    from . import live_ops, surge
    live = live_ops.build_live()
    ty = live.get("typhoon_now")
    return surge.live_surge(ty, hours=hours)


@app.get("/api/surge/tide/{station_id}")
def api_surge_tide(station_id: str, hours: int = Query(48, ge=6, le=168)):
    """单站天文潮谐波推算（逐时，CD 基准）。"""
    from . import surge
    pts = surge.predict_tide(station_id, datetime.now(), hours=hours)
    if not pts:
        raise HTTPException(status_code=404, detail="站点不存在")
    return {"station_id": station_id, "n": len(pts), "tide": pts,
            "source": "HKO 8 分潮谐波（RMSE~0.13m）"}


@app.post("/api/surge/estimate")
async def api_surge_estimate(request: Request):
    """台风增水参数化估计：风速/距离/气压 → 增水（m）与分项。"""
    from . import surge
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON")
    wind = body.get("wind_ms")
    dist = body.get("dist_km", 100.0)
    pres = body.get("pres_hpa", 1013.0)
    radius = body.get("wind_radius_km", 50.0)
    if wind is None:
        raise HTTPException(status_code=422, detail="wind_ms required")
    total, parts = surge.surge_estimate(float(wind), float(dist), float(pres), float(radius))
    return {"surge_m": total, "parts": parts,
            "inputs": {"wind_ms": wind, "dist_km": dist, "pres_hpa": pres, "wind_radius_km": radius}}


@app.get("/api/surge/archive")
def api_surge_archive():
    """历史事件风暴潮档案（含参数化增水复算）。"""
    from . import surge
    return {"events": surge.event_archive(),
            "source": "CMEMS 波浪 + HKO 天文潮 + 参数化增水复算"}


# ============ 沉淀知识库（真实事件案例 + 城安助手 RAG 问答）============

@app.get("/api/knowledge/cases")
def api_knowledge_cases(domain: str = "", q: str = ""):
    """案例沉淀列表（6 个真实事件，支持领域筛选与检索）。"""
    from . import knowledge
    return knowledge.cases_list(domain=domain, q=q)


@app.get("/api/knowledge/cases/{case_id}")
def api_knowledge_case(case_id: str):
    """单个案例完整档案：当时已知 / 关键未知 / 模型回放日序列 / 关联来源。"""
    from . import knowledge
    r = knowledge.case_detail(case_id)
    if r is None:
        raise HTTPException(status_code=404, detail="案例不存在")
    return r


@app.get("/api/knowledge/city-base")
def api_knowledge_city_base():
    """城市底座统计：人口 / 建筑 / 地形 / 隐患点人口暴露（真实栅格计算）。"""
    from . import knowledge
    return knowledge.city_base()


@app.get("/api/knowledge/models")
def api_knowledge_models():
    """三个监督模型档案：真实指标 + 验证方式 + 诚实局限。"""
    from . import knowledge
    return knowledge.model_archive()


class KnowledgeAskHistoryItem(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=2000)


class KnowledgeAskRequest(BaseModel):
    """城安助手问答请求（支持多轮历史）。"""
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    history: list[KnowledgeAskHistoryItem] = Field(default_factory=list, max_length=10)


@app.post("/api/knowledge/ask")
def api_knowledge_ask(payload: KnowledgeAskRequest):
    """城安助手：本地案例检索 + 结构化回答（回答依据 / 还需确认 / 建议动作）。"""
    from . import knowledge
    return knowledge.ask(
        payload.question,
        history=[h.model_dump() for h in payload.history] or None,
    )


@app.get("/api/knowledge/briefing")
def api_knowledge_briefing():
    """今日态势简报（LLM 生成，实况+告警+展望）。"""
    from . import knowledge
    return knowledge.daily_briefing()


@app.get("/api/knowledge/events")
def api_knowledge_events():
    """历史内涝事件库（公开报道真实事件，含受影响区与来源）。"""
    from . import knowledge
    return knowledge.historical_events()


@app.get("/api/knowledge/suggestions")
def api_knowledge_suggestions():
    """预置追问建议（前端快捷按钮）。"""
    from . import knowledge
    return {"questions": knowledge.suggested_questions()}


@app.get("/api/knowledge/status")
def api_knowledge_status():
    """城安助手智能服务状态（LLM 连接 / 模式）。"""
    from . import knowledge
    return knowledge.llm_status()
