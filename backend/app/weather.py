# -*- coding: utf-8 -*-
"""
天气数据接入 v2：多点 Open-Meteo 采样 + 行政区空间聚合
---------------------------------------------------------------
- 对 SUBDISTRICT_POINTS（街道代表采样点）批量拉取小时降雨（带空间差异）
- 按行政区聚合（区内采样点均值）得到分区分时降雨；这不是雷达或街道级水动力降尺度
- 使用接口返回的近期小时段计算前期累计代理；尚未独立核验为深圳站点实况
- 外网不可用 -> 降级为带空间差异的合成暴雨（沿海略强）
"""
import datetime as dt
import hashlib
import json
import threading
import time

import numpy as np
import requests

from .shenzhen import SUBDISTRICT_POINTS, DISTRICTS

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_SNAPSHOT_CACHE = {}
_FORECAST_ARCHIVE = {}
_SNAPSHOT_LOCK = threading.RLock()
MAX_FORECAST_DAYS = 7


def _now():
    return dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=8)))


def _first_valid_is_future(snapshot, now=None):
    """A cached run is reusable only while its first valid time is still future."""
    times = snapshot.get("times") or []
    if not times:
        return False
    try:
        first = dt.datetime.fromisoformat(str(times[0]).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if first.tzinfo is None:
        first = first.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    reference = now or _now()
    return first > reference.astimezone(first.tzinfo)


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
            # Open-Meteo counts calendar days, not a rolling N*24h horizon.
            # Request one extra day, then `future_window` selects exactly the
            # next forecast_days*24 future hours.
            "forecast_days": min(16, int(forecast_days) + 1),
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


def _storm_shape(n, peak=28.0, peak_index=42.0, sigma_h=7.0):
    """Fixed-timing fallback storm, independent of requested horizon."""
    hours = np.arange(int(n), dtype=float)
    return float(peak) * np.exp(-0.5 * ((hours - float(peak_index)) / float(sigma_h)) ** 2)


def _fallback_grid(forecast_days=3):
    # One past day plus enough future calendar time to guarantee a rolling
    # N*24-hour window even when the process starts late in the day.
    # Always generate one canonical maximum-horizon forcing and slice it later.
    # Otherwise changing ?forecast_days would move the synthetic storm peak and
    # alter the overlapping first day of the very same fallback forecast.
    total = (MAX_FORECAST_DAYS + 2) * 24
    shape = _storm_shape(total)
    coast = {d["id"]: d["coastal"] for d in DISTRICTS}
    grid = []
    for name, did, lat, lon in SUBDISTRICT_POINTS:
        factor = 0.8 + 0.5 * coast[did]  # 沿海略强
        # Python's hash() is randomized per process; use a stable seed so the
        # same fallback snapshot is reproducible and dispatch can replay it.
        seed = int(hashlib.sha256(f"{lat:.6f},{lon:.6f}".encode()).hexdigest()[:8], 16)
        prec = (shape * factor + np.random.default_rng(seed).uniform(0, 1, total)).round(2)
        # 时间轴
        start = _now().replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=24)
        times = [(start + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(total)]
        grid.append(((name, did, lat, lon), times, list(prec)))
    return grid


def _provider_time(value):
    """Parse provider-local hourly labels as timezone-aware Asia/Shanghai time."""
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    return parsed


def future_window(times, precip, forecast_days=3, now=None):
    now = now or _now()
    out = []
    n = len(times)
    for i, (tstr, p) in enumerate(zip(times, precip)):
        t = _provider_time(tstr)
        if t <= now:
            continue
        lo = max(0, i - 24)
        cum24 = sum(precip[lo:i])
        out.append({"time": t.isoformat(), "precip": round(float(p), 2), "cum24": round(float(cum24), 2)})
        if len(out) >= forecast_days * 24:
            break
    return out


def downscaled_forecast(forecast_days=3, as_of=None):
    """Return district forcing plus the last 24 available hours for spin-up."""
    grid, fallback = fetch_grid(forecast_days)
    if not grid:
        raise ValueError("weather grid is empty")
    times = list(grid[0][1])
    # With no explicit replay time, select the rolling window *after* the
    # provider response arrives.  A network request can cross an hour boundary;
    # selecting before it starts would publish an already-expired first step.
    reference_now = as_of or _now()
    if reference_now.tzinfo is None:
        raise ValueError("weather snapshot as_of must include a timezone")
    parsed_times = [_provider_time(value) for value in times]
    if any(
        (right - left).total_seconds() != 3600.0
        for left, right in zip(parsed_times, parsed_times[1:])
    ):
        raise ValueError("weather hourly time axis must be continuous and strictly hourly")
    by_district = {d["id"]: [] for d in DISTRICTS}
    for (name, did, lat, lon), point_times, prec in grid:
        if list(point_times) != times or len(prec) != len(times):
            raise ValueError("weather sampling points must share one complete hourly time axis")
        values = np.asarray(prec, dtype=float)
        if np.any(~np.isfinite(values)) or np.any(values < 0.0):
            raise ValueError("weather precipitation must be finite and non-negative")
        by_district[did].append(values)

    dist_precip = {}
    for did, arr_list in by_district.items():
        if arr_list:
            dist_precip[did] = np.mean(arr_list, axis=0)
        else:
            dist_precip[did] = np.zeros(len(times))

    # 未来窗口 + 每区 cum24
    out_dist, out_cum = {}, {}
    for did, series in dist_precip.items():
        fw = future_window(times, series, forecast_days, now=reference_now)
        out_dist[did] = [w["precip"] for w in fw]
        out_cum[did] = [w["cum24"] for w in fw]

    city_series = np.mean([dist_precip[d["id"]] for d in DISTRICTS], axis=0)
    fw_city = future_window(times, city_series, forecast_days, now=reference_now)
    future_times = [w["time"] for w in fw_city]

    future_indices = [index for index, value in enumerate(parsed_times) if value > reference_now]
    first_future_index = future_indices[0] if future_indices else len(times)
    antecedent_indices = list(range(max(0, first_future_index - 24), first_future_index))
    antecedent_complete = (
        len(antecedent_indices) == 24
        and all(parsed_times[index] <= reference_now for index in antecedent_indices)
    )
    if not antecedent_complete:
        antecedent_indices = []
    antecedent_times = [parsed_times[index].isoformat() for index in antecedent_indices]
    antecedent_dist = {
        did: [round(float(series[index]), 2) for index in antecedent_indices]
        for did, series in dist_precip.items()
    }
    antecedent_city = [round(float(city_series[index]), 2) for index in antecedent_indices]

    expected_steps = int(forecast_days) * 24
    if len(future_times) != expected_steps:
        raise ValueError(
            f"weather provider returned {len(future_times)} future hours; expected {expected_steps}"
        )
    if any(len(out_dist[did]) != expected_steps for did in out_dist) or any(
        len(out_cum[did]) != expected_steps for did in out_cum
    ):
        raise ValueError("district weather forcing has an incomplete forecast horizon")

    return {
        "times": future_times,
        "city": [w["precip"] for w in fw_city],
        "city_cum": [w["cum24"] for w in fw_city],
        "districts": out_dist,
        "cum": out_cum,
        "antecedent_times": antecedent_times,
        "antecedent_city": antecedent_city,
        "antecedent_districts": antecedent_dist,
        "antecedent_provenance": (
            "simulated(fallback forcing)"
            if fallback
            else "estimated(Open-Meteo recent-hour precipitation; not verified station observation)"
        ),
        "antecedent_complete": antecedent_complete,
        "antecedent_interval_semantics": (
            "timestamp is interval end; precipitation is the preceding-hour sum"
        ),
        "antecedent_cutoff": antecedent_times[-1] if antecedent_times else None,
        "forcing_selection_as_of": reference_now.isoformat(),
        # Compatibility alias retained for older consumers.
        "forcing_as_of": reference_now.isoformat(),
        "fallback": fallback,
    }


def forecast_snapshot(forecast_days=3, ttl_seconds=600, force=False):
    """Return a versioned forecast snapshot shared by predict and simulate.

    The cache is keyed by horizon, avoiding the previous bug where a 1-day
    request could receive a cached 3-day response.  ``forecast_run_id`` pins
    the exact forcing so stochastic ensemble simulations and dispatch replays
    remain auditable.
    """
    days = int(forecast_days)
    if days < 1 or days > MAX_FORECAST_DAYS:
        raise ValueError(f"forecast_days must be 1..{MAX_FORECAST_DAYS}")
    with _SNAPSHOT_LOCK:
        now = time.time()
        cache_check_time = _now()
        cached = _SNAPSHOT_CACHE.get(days)
        if (
            not force
            and cached
            and now - cached["cached_at"] < float(ttl_seconds)
            and _first_valid_is_future(cached["data"], now=cache_check_time)
        ):
            return cached["data"]

        # Freeze time is the instant the fully processed response becomes
        # available, never the instant the request began.  If processing spans
        # an hour boundary, refetch/reselect once so the archived first valid
        # hour is still genuinely in the future at publication time.
        data = None
        snapshot_time = None
        for attempt in range(2):
            data = downscaled_forecast(days)
            snapshot_time = _now()
            if _first_valid_is_future(data, now=snapshot_time):
                break
            if attempt == 1:
                raise ValueError(
                    "weather forcing became stale before snapshot publication"
                )
        assert data is not None and snapshot_time is not None
        expected_steps = days * 24
        expected_districts = {district["id"] for district in DISTRICTS}
        if (
            len(data.get("times") or []) != expected_steps
            or len(data.get("city") or []) != expected_steps
            or set(data.get("districts") or {}) != expected_districts
            or set(data.get("cum") or {}) != expected_districts
            or any(
                len((data.get("districts") or {})[did]) != expected_steps
                or len((data.get("cum") or {})[did]) != expected_steps
                for did in expected_districts
            )
        ):
            raise ValueError("refusing to archive an incomplete weather forcing horizon")
        issued_at = snapshot_time.isoformat()
        fingerprint = {
            "issued_at": issued_at,
            "forcing_selection_as_of": data.get("forcing_selection_as_of"),
            "times": data.get("times", []),
            "city": data.get("city", []),
            "districts": data.get("districts", {}),
            "antecedent_times": data.get("antecedent_times", []),
            "antecedent_city": data.get("antecedent_city", []),
            "antecedent_districts": data.get("antecedent_districts", {}),
            "antecedent_provenance": data.get("antecedent_provenance"),
            "antecedent_interval_semantics": data.get("antecedent_interval_semantics"),
            "antecedent_cutoff": data.get("antecedent_cutoff"),
            "fallback": bool(data.get("fallback")),
        }
        run_id = hashlib.sha256(
            json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        data = {
            **data,
            # This is the time our service froze the forcing, not a provider
            # model-cycle time. Open-Meteo's response used here does not expose
            # an auditable forecast-as-issued identifier.
            "issued_at": issued_at,
            "snapshot_created_at": issued_at,
            "available_at": issued_at,
            "provider_forecast_issued_at": None,
            "issued_at_semantics": (
                "service snapshot freeze/availability time after provider response; "
                "not provider model-cycle time"
            ),
            "forecast_run_id": run_id,
        }
        _SNAPSHOT_CACHE[days] = {"cached_at": time.time(), "data": data}
        _FORECAST_ARCHIVE[run_id] = data
        while len(_FORECAST_ARCHIVE) > 32:
            _FORECAST_ARCHIVE.pop(next(iter(_FORECAST_ARCHIVE)))
        return data


def archived_snapshot(forecast_run_id):
    """Return an immutable-by-convention forcing snapshot for exact replay."""
    if not forecast_run_id:
        return None
    with _SNAPSHOT_LOCK:
        return _FORECAST_ARCHIVE.get(str(forecast_run_id))


def resolve_snapshot(forecast_days=3, forecast_run_id=None):
    if forecast_run_id:
        snapshot = archived_snapshot(forecast_run_id)
        if snapshot is None:
            raise ValueError("forecast_run_id is not available in this process archive")
        actual_days = max(1, int(np.ceil(len(snapshot.get("times") or []) / 24.0)))
        if int(forecast_days) != actual_days:
            raise ValueError(
                f"forecast_days={forecast_days} conflicts with pinned snapshot horizon {actual_days}"
            )
        return snapshot
    return forecast_snapshot(forecast_days)
