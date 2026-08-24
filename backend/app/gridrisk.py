# -*- coding: utf-8 -*-
"""Grid downscaling of the conservative district water-depth ensemble."""
from __future__ import annotations

import base64
import binascii
from collections import OrderedDict
import os
import struct
import threading
import time
import zlib

import numpy as np

from . import forecasting, gisreal, shenzhen, weather
from .risk import DEPTH_LEVEL_THRESHOLDS_MM, bounded_local_depth_factor, district_vulnerability


LAT0, LAT1 = 22.44, 22.88
LON0, LON1 = 113.72, 114.66
DEFAULT_RES = 0.018
MIN_GRID_RES = 0.009
MIN_IMAGE_RES = 0.0045
_GRID_CACHE = OrderedDict()
_GRID_CACHE_LOCK = threading.RLock()
_GRID_CACHE_BYTES = 0
MAX_GRID_CACHE_ENTRIES = 4
MAX_GRID_CACHE_BYTES = 24 * 1024 * 1024
_IMAGE_CACHE = {}
_IMAGE_CACHE_LOCK = threading.RLock()
_IMAGE_STATIC_CACHE = {}
_IMAGE_STATIC_LOCK = threading.RLock()


def _load_feature_pts():
    dem = gisreal._read_rows(os.path.join(gisreal.BASE, "shenzhen_dem.csv"))
    built = gisreal._read_rows(os.path.join(gisreal.BASE, "shenzhen_builtup_density.csv"))
    dem_pts = [(float(row["lat"]), float(row["lon"]), float(row["elevation_m"])) for row in dem]
    built_pts = [(float(row["lat"]), float(row["lon"]), float(row["builtup_pct"])) for row in built]
    if not dem_pts:
        dem_pts = [(d["center"][0], d["center"][1], d["elevation_mean"]) for d in shenzhen.DISTRICTS]
    if not built_pts:
        built_pts = [
            (d["center"][0], d["center"][1], d.get("impervious_ratio", 0.4) * 100.0)
            for d in shenzhen.DISTRICTS
        ]
    return dem_pts, built_pts


def _grid_cells(res):
    return [
        (float(lat), float(lon))
        for lat in np.arange(LAT0, LAT1, float(res))
        for lon in np.arange(LON0, LON1, float(res))
    ]


def _ensemble(forecast_days, n_members, snapshot=None):
    snapshot = snapshot or weather.forecast_snapshot(forecast_days)
    ensemble, _, _ = forecasting.ensemble_for_snapshot(snapshot, n_members=n_members)
    return snapshot, ensemble


def build_grid_risk(
    forecast_days=3,
    res=DEFAULT_RES,
    n_members=forecasting.ENSEMBLE_SIZE,
    snapshot=None,
):
    resolution = float(res)
    if not MIN_GRID_RES <= resolution <= 0.1:
        raise ValueError(f"grid res must be between {MIN_GRID_RES} and 0.1 degrees")
    dem_points, built_points = _load_feature_pts()
    snapshot, ensemble = _ensemble(forecast_days, n_members, snapshot)
    members = np.asarray(ensemble["members_depth_mm"], dtype=float)
    district_ids = list(ensemble["district_ids"])
    centroids = gisreal._district_centroids()
    coordinates = _grid_cells(resolution)
    if not coordinates:
        raise ValueError("resolution produced an empty grid")
    latitudes = np.asarray([point[0] for point in coordinates], dtype=float)
    longitudes = np.asarray([point[1] for point in coordinates], dtype=float)
    dem_array = np.asarray(dem_points, dtype=float)
    built_array = np.asarray(built_points, dtype=float)
    elevation_values = dem_array[
        _nearest_indices(dem_array, latitudes, longitudes), 2
    ]
    impervious_values = built_array[
        _nearest_indices(built_array, latitudes, longitudes), 2
    ] / 100.0
    cells = []
    risk_bytes = bytearray()
    depth_bytes = bytearray()
    for (lat, lon), elevation, impervious in zip(
        coordinates, elevation_values, impervious_values
    ):
        elevation = float(elevation)
        impervious = float(impervious)
        district_id = gisreal._nearest_did(centroids, lat, lon)
        district = shenzhen.get_district(district_id)
        if district is None:
            continue
        factor = bounded_local_depth_factor(elevation, impervious, district)
        base_vulnerability, _ = district_vulnerability(district)
        vulnerability = float(np.clip(base_vulnerability * factor, 0.0, 1.0))
        local = members[:, :, district_ids.index(district_id)] * factor
        probability = np.mean(local >= 150.0, axis=0)
        any_time_probability = float(np.mean(np.max(local, axis=1) >= 150.0))
        p10, p50, p90 = np.quantile(local, (0.1, 0.5, 0.9), axis=0) / 1000.0
        peak_index = forecasting.select_peak_index(p50, probability)
        # Cell-major compact encoding avoids retaining two Python-float lists
        # per cell (millions of boxed objects at 7 days / 0.009 degrees).
        # Risk has <= 1/510 absolute quantization error; depth is nearest mm.
        risk_bytes.extend(
            np.rint(np.clip(probability, 0.0, 1.0) * 255.0)
            .astype(np.uint8)
            .tobytes()
        )
        depth_bytes.extend(
            np.asarray(
                np.clip(np.rint(p50 * 1000.0), 0.0, 65535.0), dtype="<u2"
            ).tobytes()
        )
        cells.append({
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "elevation": round(elevation, 1),
            "impervious": round(impervious, 3),
            "district_id": district_id,
            "vulnerability": round(vulnerability, 3),
            "downscale_factor": round(factor, 3),
            "peak": round(any_time_probability, 4),
            "peak_probability_definition": "P(max over displayed horizon depth >= 0.15 m)",
            "peak_hour": peak_index,
            "peak_depth_p10_m": round(float(p10[peak_index]), 4),
            "peak_depth_p50_m": round(float(p50[peak_index]), 4),
            "peak_depth_p90_m": round(float(p90[peak_index]), 4),
        })
    flags = [
        "bounded_gis_downscale",
        "compact_quantized_timeseries",
        "not_2d_hydraulics",
        "uncalibrated_parameters",
        "rectangular_grid_not_boundary_clipped",
    ]
    if snapshot.get("fallback"):
        flags.append("synthetic_rainfall_fallback")
    return {
        "resolution_deg": resolution,
        "n_cells": len(cells),
        "source": "fallback-sample" if snapshot.get("fallback") else "open-meteo-multi-point",
        "forecast_run_id": snapshot.get("forecast_run_id"),
        "forecast_days": max(1, int(np.ceil(len(snapshot["times"]) / 24.0))),
        "model_run_id": ensemble["model_run_id"],
        "times": snapshot["times"],
        "timeseries_encoding": {
            "layout": "cell-major",
            "shape": [len(cells), len(snapshot["times"])],
            "risk": {
                "field": "risk_u8_b64",
                "dtype": "uint8",
                "decode": "value / 255",
                "max_abs_quantization_error": round(0.5 / 255.0, 6),
            },
            "depth_p50": {
                "field": "depth_mm_u16le_b64",
                "dtype": "uint16-little-endian",
                "unit": "mm",
                "decode": "value / 1000 metres",
                "max_abs_quantization_error_m": 0.0005,
            },
        },
        "risk_u8_b64": base64.b64encode(bytes(risk_bytes)).decode("ascii"),
        "depth_mm_u16le_b64": base64.b64encode(bytes(depth_bytes)).decode("ascii"),
        "probability_definition": "P(representative local depth >= 0.15 m)",
        "quality_flags": flags,
        "provenance": {
            "district_dynamics": "estimated(conservative ensemble state-space)",
            "elevation_impervious": "observed-derived(project local DEM/WorldCover)",
            "local_downscale": "estimated(bounded ranking factor; not pipe/2-D flow)",
        },
        "cells": cells,
}


def _estimated_grid_bytes(data):
    """Conservative-enough cache accounting without serializing twice."""
    encoded = len(data.get("risk_u8_b64") or "") + len(
        data.get("depth_mm_u16le_b64") or ""
    )
    # Repeated JSON keys dominate small cell records; 512 B/cell intentionally
    # overestimates the current compact metadata payload.
    return int(encoded + len(data.get("cells") or []) * 512 + len(data.get("times") or []) * 64)


def _cache_grid_result(key, data, cached_at=None):
    global _GRID_CACHE_BYTES
    size = _estimated_grid_bytes(data)
    if size > MAX_GRID_CACHE_BYTES:
        return
    with _GRID_CACHE_LOCK:
        previous = _GRID_CACHE.pop(key, None)
        if previous:
            _GRID_CACHE_BYTES -= int(previous.get("size_bytes", 0))
        _GRID_CACHE[key] = {
            "ts": float(cached_at if cached_at is not None else time.time()),
            "size_bytes": size,
            "data": data,
        }
        _GRID_CACHE_BYTES += size
        while (
            len(_GRID_CACHE) > MAX_GRID_CACHE_ENTRIES
            or _GRID_CACHE_BYTES > MAX_GRID_CACHE_BYTES
        ):
            _, evicted = _GRID_CACHE.popitem(last=False)
            _GRID_CACHE_BYTES -= int(evicted.get("size_bytes", 0))


def get_grid_risk(forecast_days=3, res=DEFAULT_RES, snapshot=None):
    key = (
        snapshot.get("forecast_run_id") if snapshot else None,
        int(forecast_days),
        round(float(res), 6),
    )
    now = time.time()
    global _GRID_CACHE_BYTES
    with _GRID_CACHE_LOCK:
        cached = _GRID_CACHE.get(key)
        if cached and now - cached["ts"] < 600:
            _GRID_CACHE.move_to_end(key)
            return cached["data"]
        if cached:
            _GRID_CACHE.pop(key, None)
            _GRID_CACHE_BYTES -= int(cached.get("size_bytes", 0))
    data = build_grid_risk(forecast_days, res, snapshot=snapshot)
    _cache_grid_result(key, data)
    return data


def _nearest_indices(points, lat_values, lon_values, chunk_size=128):
    """Nearest-neighbour lookup with bounded memory.

    The high-resolution PNG contains about 20k query cells and the WorldCover
    layer contains about 20k source cells.  A full pairwise matrix would require
    several gigabytes, so process fixed-size query chunks instead.
    """

    array = np.asarray(points, dtype=float)
    lat_values = np.asarray(lat_values, dtype=float)
    lon_values = np.asarray(lon_values, dtype=float)
    if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] < 2:
        raise ValueError("nearest-neighbour source points must be non-empty")
    if lat_values.shape != lon_values.shape:
        raise ValueError("latitude and longitude query arrays must have equal shape")
    result = np.empty(lat_values.size, dtype=np.int64)
    step = max(1, int(chunk_size))
    source_lat = array[:, 0]
    source_lon = array[:, 1]
    for start in range(0, lat_values.size, step):
        stop = min(start + step, lat_values.size)
        distances = (
            (lat_values[start:stop, None] - source_lat[None, :]) ** 2
            + (lon_values[start:stop, None] - source_lon[None, :]) ** 2
        )
        result[start:stop] = np.argmin(distances, axis=1)
    return result


def _image_static_fields(resolution):
    """Cache the expensive GIS lookup shared by every temporal image slice."""
    key = round(float(resolution), 7)
    with _IMAGE_STATIC_LOCK:
        cached = _IMAGE_STATIC_CACHE.get(key)
        if cached is not None:
            return cached
        lats = np.arange(LAT0, LAT1, resolution)
        lons = np.arange(LON0, LON1, resolution)
        rows, columns = len(lats), len(lons)
        lat_flat = np.repeat(lats, columns)
        lon_flat = np.tile(lons, rows)
        dem_points, built_points = _load_feature_pts()
        dem_array = np.asarray(dem_points, dtype=float)
        built_array = np.asarray(built_points, dtype=float)
        elevation = dem_array[_nearest_indices(dem_array, lat_flat, lon_flat), 2]
        impervious = built_array[_nearest_indices(built_array, lat_flat, lon_flat), 2] / 100.0
        centroids = gisreal._district_centroids()
        district_ids = np.asarray(
            [gisreal._nearest_did(centroids, lat, lon) for lat, lon in zip(lat_flat, lon_flat)],
            dtype=object,
        )
        factors = np.asarray([
            bounded_local_depth_factor(elev, imp, shenzhen.get_district(did))
            for elev, imp, did in zip(elevation, impervious, district_ids)
        ])
        # Keep stable district identifiers in the static cache.  Resolving the
        # indices against the actual ensemble below avoids silently assigning
        # one district's depths to another if a future model changes ordering.
        result = (lats, lons, rows, columns, district_ids, factors)
        _IMAGE_STATIC_CACHE[key] = result
        while len(_IMAGE_STATIC_CACHE) > 8:
            _IMAGE_STATIC_CACHE.pop(next(iter(_IMAGE_STATIC_CACHE)))
        return result


def build_grid_image(
    res=0.0045,
    forecast_days=3,
    alpha_scale=1.1,
    snapshot=None,
    hour_index=None,
    include_metadata=False,
):
    resolution = float(res)
    if not MIN_IMAGE_RES <= resolution <= 0.1:
        raise ValueError(f"image res must be between {MIN_IMAGE_RES} and 0.1 degrees")
    scale = float(alpha_scale)
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("alpha_scale must be a finite positive number")
    lats, lons, rows, columns, district_ids, factors = _image_static_fields(resolution)

    _, ensemble = _ensemble(forecast_days, forecasting.ENSEMBLE_SIZE, snapshot)
    member_depth = np.asarray(ensemble["members_depth_mm"], dtype=float)
    ensemble_ids = list(ensemble["district_ids"])
    if len(set(ensemble_ids)) != len(ensemble_ids):
        raise ValueError("ensemble district_ids must be unique")
    try:
        district_index = np.asarray(
            [ensemble_ids.index(str(district_id)) for district_id in district_ids],
            dtype=int,
        )
    except ValueError as exc:
        raise ValueError("image grid district is missing from ensemble output") from exc
    if hour_index is None:
        selected_depth = member_depth.max(axis=1)
        temporal_slice = "horizon-peak"
    else:
        selected_hour = int(hour_index)
        if selected_hour != hour_index or not 0 <= selected_hour < member_depth.shape[1]:
            raise ValueError(
                f"hour_index must be an integer between 0 and {member_depth.shape[1] - 1}"
            )
        selected_depth = member_depth[:, selected_hour, :]
        temporal_slice = f"hour-{selected_hour}"
    local_depth = selected_depth[:, district_index] * factors[None, :]
    probability = np.mean(local_depth >= 150.0, axis=0)
    median_depth = np.quantile(local_depth, 0.5, axis=0)
    levels = np.digitize(median_depth, DEPTH_LEVEL_THRESHOLDS_MM, right=False)
    alpha = _depth_probability_alpha(probability, median_depth, scale)

    rgba = np.zeros((rows, columns, 4), dtype=np.uint8)
    # Keep the PNG contract identical to the P50 legend used by RiskMap:
    # sky blue → teal → lime → orange → rose.
    colors = [(56, 189, 248), (45, 212, 191), (163, 230, 53), (251, 146, 60), (244, 63, 94)]
    for index, alpha_value in enumerate(alpha):
        if alpha_value == 0:
            continue
        x = index % columns
        y = index // columns
        red, green, blue = colors[int(np.clip(levels[index], 0, 4))]
        rgba[y, x] = (red, green, blue, int(alpha_value))

    # Image row zero is rendered at the north edge by Leaflet, while the model
    # grid is generated south-to-north.  Flip once before PNG encoding.
    rgba = _leaflet_oriented_rgba(rgba)

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    scanlines = b"".join(b"\x00" + rgba[row].tobytes() for row in range(rows))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", columns, rows, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, level=6))
        + chunk(b"IEND", b"")
    )
    bbox = {
        "south": float(LAT0),
        "west": float(LON0),
        "north": float(lats[-1] + resolution),
        "east": float(lons[-1] + resolution),
    }
    metadata = {
        "temporal_slice": temporal_slice,
        "visible_cell_count": int(np.count_nonzero(alpha)),
        "total_cell_count": int(alpha.size),
        "max_depth_mm": round(float(np.max(median_depth, initial=0.0)), 3),
        "max_probability": round(float(np.max(probability, initial=0.0)), 6),
        "empty": not bool(np.any(alpha)),
        "color_metric": "ensemble_median_local_depth_mm",
        "opacity_metric": "continuous median depth plus P(local depth >= 150 mm)",
    }
    if include_metadata:
        return png, bbox, (rows, columns), metadata
    return png, bbox, (rows, columns)


def _depth_probability_alpha(probability, median_depth_mm, alpha_scale=1.1):
    """Return a visible, semantically aligned alpha channel for P50 depth.

    The former raster used only ``P(depth >= 150 mm)`` as alpha.  That made
    every sub-threshold P50 depth fully transparent, so a valid image looked
    like a broken layer.  Preserve exceedance probability as an uncertainty
    signal, while adding a continuous P50-depth signal.  Truly dry cells stay
    transparent; even shallow positive depths remain inspectable.
    """

    probability = np.clip(np.asarray(probability, dtype=float), 0.0, 1.0)
    depth = np.maximum(np.asarray(median_depth_mm, dtype=float), 0.0)
    if probability.shape != depth.shape:
        raise ValueError("probability and median depth arrays must have equal shape")
    scale = float(alpha_scale)
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("alpha_scale must be a finite positive number")

    probability_signal = np.power(probability, scale)
    # A square-root response keeps 5--50 mm shallow-water structure visible
    # without making it as opaque as genuinely hazardous (>150 mm) water.
    depth_signal = 0.78 * np.sqrt(np.clip(depth / 500.0, 0.0, 1.0))
    combined = np.maximum(probability_signal, depth_signal)
    alpha = np.rint(combined * 255.0).astype(np.uint8)
    alpha[(probability <= 0.0) & (depth <= 0.0)] = 0
    return alpha


def _leaflet_oriented_rgba(south_to_north_rgba):
    """Convert a south-first model raster to Leaflet's north-first image rows."""
    return np.flipud(np.asarray(south_to_north_rgba))


def get_grid_image(
    res=0.0045,
    forecast_days=3,
    snapshot=None,
    hour_index=None,
    include_metadata=False,
):
    key = (
        snapshot.get("forecast_run_id") if snapshot else None,
        int(forecast_days),
        round(float(res), 7),
        None if hour_index is None else int(hour_index),
    )
    now = time.time()
    with _IMAGE_CACHE_LOCK:
        cached = _IMAGE_CACHE.get(key)
        if cached and now - cached["ts"] < 600:
            if include_metadata:
                return cached["png"], cached["bbox"], cached["metadata"]
            return cached["png"], cached["bbox"]
        if cached:
            _IMAGE_CACHE.pop(key, None)
    png, bbox, _, metadata = build_grid_image(
        res,
        forecast_days,
        snapshot=snapshot,
        hour_index=hour_index,
        include_metadata=True,
    )
    with _IMAGE_CACHE_LOCK:
        _IMAGE_CACHE[key] = {
            "ts": time.time(),
            "png": png,
            "bbox": bbox,
            "metadata": metadata,
        }
        while len(_IMAGE_CACHE) > 192:
            _IMAGE_CACHE.pop(next(iter(_IMAGE_CACHE)))
    if include_metadata:
        return png, bbox, metadata
    return png, bbox


__all__ = [
    "build_grid_risk",
    "get_grid_risk",
    "build_grid_image",
    "get_grid_image",
]
