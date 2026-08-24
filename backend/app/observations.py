# -*- coding: utf-8 -*-
"""Observed flood-water data utilities.

This module is deliberately conservative about provenance:

* station coordinates are read from the project-local feature catalogue;
* stations are mapped to districts by polygon containment where possible;
* cached observations are never treated as live when they are stale;
* the short cached series is exposed as a data-readiness signal, not as proof
  that a forecasting model has been trained on independent flood events.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from pathlib import Path
from statistics import median

from .data_paths import REAL_GIS
from . import shenzhen


WATERLEVEL = REAL_GIS / "shenzhen_waterlevel_hourly.csv"
STATIONS = REAL_GIS / "shenzhen_station_features.csv"
DISTRICTS_GEOJSON = REAL_GIS / "shenzhen_districts.geojson"
FLOODPOINTS = REAL_GIS / "shenzhen_floodpoints_geo_v2.csv"
MAPPING = REAL_GIS.parent / "station_district_map.csv"

_NAME_TO_ID = {d["name"]: d["id"] for d in shenzhen.DISTRICTS}
_STATION_CODE_DISTRICT = {
    "440303": "luohu",
    "440304": "futian",
    "440305": "nanshan",
    "440306": "baoan",
    "440307": "longgang",
    "440308": "yantian",
    "440309": "longhua",
    "440310": "pingshan",
    "440311": "guangming",
    "440312": "dapeng",
}


def _as_float(value, default=None):
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
        return dt
    except ValueError:
        return None


def _ring_contains(ring, lon, lat):
    """Ray-casting point-in-ring; GeoJSON coordinates are lon/lat."""
    inside = False
    if not ring:
        return False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][:2]
        xj, yj = ring[j][:2]
        crosses = ((yi > lat) != (yj > lat))
        if crosses:
            x_at_lat = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < x_at_lat:
                inside = not inside
        j = i
    return inside


def _polygon_contains(coordinates, lon, lat):
    if not coordinates or not _ring_contains(coordinates[0], lon, lat):
        return False
    return not any(_ring_contains(hole, lon, lat) for hole in coordinates[1:])


def _geometry_contains(geometry, lon, lat):
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        return _polygon_contains(coords, lon, lat)
    if kind == "MultiPolygon":
        return any(_polygon_contains(poly, lon, lat) for poly in coords)
    return False


def _same_endpoint(a, b, digits=7):
    return (
        round(float(a[0]), digits) == round(float(b[0]), digits)
        and round(float(a[1]), digits) == round(float(b[1]), digits)
    )


def _stitch_boundary_segments(paths):
    """Join OSM relation way fragments into closed boundary rings.

    The checked-in GeoJSON exporter preserved every relation member as a
    separate coordinate path even though it labelled the geometry ``Polygon``.
    Reconstructing rings here recovers the actual local boundary evidence and
    avoids silently treating every open way as a polygon.
    """

    segments = [
        [list(map(float, point[:2])) for point in path]
        for path in paths
        if isinstance(path, list) and len(path) >= 2
    ]
    unused = set(range(len(segments)))
    rings = []
    while unused:
        index = min(unused)
        unused.remove(index)
        ring = list(segments[index])
        while unused and not _same_endpoint(ring[0], ring[-1]):
            match = None
            reverse = False
            for candidate in sorted(unused):
                segment = segments[candidate]
                if _same_endpoint(ring[-1], segment[0]):
                    match = candidate
                    break
                if _same_endpoint(ring[-1], segment[-1]):
                    match = candidate
                    reverse = True
                    break
            if match is None:
                break
            unused.remove(match)
            extension = list(reversed(segments[match])) if reverse else segments[match]
            ring.extend(extension[1:])
        if len(ring) >= 4 and _same_endpoint(ring[0], ring[-1]):
            rings.append(ring)
    return rings


def _repair_fragmented_polygon(geometry):
    """Return a containment-ready geometry and its auditable mapping method."""

    if geometry.get("type") != "Polygon":
        return geometry, "district-polygon"
    paths = geometry.get("coordinates") or []
    if paths and all(
        len(path) >= 4 and _same_endpoint(path[0], path[-1]) for path in paths
    ):
        return geometry, "district-polygon"
    rings = _stitch_boundary_segments(paths)
    if not rings:
        return geometry, "district-polygon-unrepaired"
    # Relation exports can contain detached outer rings (islands/enclaves).
    # Represent each stitched ring as an outer polygon; no hole role survived
    # in the derived GeoJSON, so claiming more topology would be misleading.
    repaired = {"type": "MultiPolygon", "coordinates": [[ring] for ring in rings]}
    return repaired, "district-polygon-repaired-segments"


def _district_shapes():
    if not DISTRICTS_GEOJSON.exists():
        return []
    payload = json.loads(DISTRICTS_GEOJSON.read_text(encoding="utf-8"))
    out = []
    for feature in payload.get("features", []):
        name = (feature.get("properties") or {}).get("name")
        did = _NAME_TO_ID.get(name)
        if did:
            geometry, method = _repair_fragmented_polygon(feature.get("geometry") or {})
            out.append((did, geometry, method))
    return out


def load_station_catalog():
    """Return station metadata keyed by station code."""
    if not STATIONS.exists():
        return {}
    out = {}
    with STATIONS.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("station_code") or "").strip()
            lat = _as_float(row.get("lat"))
            lon = _as_float(row.get("lon"))
            if not code:
                continue
            out[code] = {
                "station_code": code,
                "station_name": row.get("station_name", ""),
                "lat": lat,
                "lon": lon,
                "elevation_m": _as_float(row.get("elevation_m")),
                "road_density": _as_float(row.get("road_density")),
                "impervious_pct": _as_float(row.get("impervious_pct")),
                "dist_to_water_km": _as_float(row.get("dist_to_water_km")),
            }
    return out


@lru_cache(maxsize=1)
def _labelled_floodpoints():
    if not FLOODPOINTS.exists():
        return []
    points = []
    with FLOODPOINTS.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            district_id = _NAME_TO_ID.get((row.get("district") or "").strip())
            lat = _as_float(row.get("lat"))
            lon = _as_float(row.get("lon"))
            if district_id and lat is not None and lon is not None:
                points.append((lat, lon, district_id))
    return points


def _nearest_district(lat, lon):
    """Prefer a nearby real labelled point; retain centroid as final fallback."""
    points = _labelled_floodpoints()
    if points:
        plat, plon, district_id = min(
            points, key=lambda item: (item[0] - lat) ** 2 + (item[1] - lon) ** 2
        )
        distance_km = ((plat - lat) ** 2 + (plon - lon) ** 2) ** 0.5 * 111.0
        if distance_km <= 15.0:
            return district_id, "nearest-labelled-floodpoint", distance_km
    district = min(
        shenzhen.DISTRICTS,
        key=lambda d: (float(d["center"][0]) - lat) ** 2 + (float(d["center"][1]) - lon) ** 2,
    )
    clat, clon = map(float, district["center"])
    distance_km = ((clat - lat) ** 2 + (clon - lon) ** 2) ** 0.5 * 111.0
    return district["id"], "nearest-district-center", distance_km


def build_station_district_map():
    """Map all located stations to districts, with an auditable method."""
    shapes = _district_shapes()
    result = {}
    for code, station in load_station_catalog().items():
        lat, lon = station.get("lat"), station.get("lon")
        if lat is None or lon is None:
            continue
        matched = next(
            (
                (did, method)
                for did, geom, method in shapes
                if _geometry_contains(geom, lon, lat)
            ),
            None,
        )
        code_district = next(
            (
                did
                for marker, did in _STATION_CODE_DISTRICT.items()
                if code.startswith("MS110") and marker in code
            ),
            None,
        )
        if code_district:
            did = code_district
            method = "station-code-district-segment"
            distance_km = None
            coordinate_check = (
                "inside_encoded_district"
                if matched and matched[0] == did
                else "conflicts_with_derived_polygon"
                if matched
                else "outside_available_boundaries"
            )
        elif matched:
            did, method = matched
            distance_km = 0.0
            coordinate_check = "inside_derived_polygon"
        else:
            did, method, distance_km = _nearest_district(lat, lon)
            coordinate_check = "spatial_fallback"
        result[code] = {
            "district_id": did,
            "method": method,
            "reference_distance_km": (
                round(float(distance_km), 4) if distance_km is not None else None
            ),
            "coordinate_check": coordinate_check,
            "lat": lat,
            "lon": lon,
        }
    return result


def load_station_district_map():
    """Use an explicit mapping when supplied; otherwise derive it locally."""
    explicit = {}
    if MAPPING.exists():
        with MAPPING.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                code = (row.get("czbm") or row.get("station_code") or "").strip()
                did = (row.get("district_id") or "").strip()
                if code and shenzhen.get_district(did):
                    explicit[code] = {
                        "district_id": did,
                        "method": row.get("method") or "explicit",
                        "reference_distance_km": _as_float(row.get("reference_distance_km")),
                        "coordinate_check": row.get("coordinate_check") or "explicit-unchecked",
                        "lat": _as_float(row.get("lat")),
                        "lon": _as_float(row.get("lon")),
                    }
    derived = build_station_district_map()
    derived.update(explicit)
    return derived


def load_waterlevel_rows():
    """Load quality-controlled project-local hourly depth-proxy observations."""
    if not WATERLEVEL.exists():
        return []
    catalog = load_station_catalog()
    mapping = load_station_district_map()
    rows = []
    with WATERLEVEL.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("quality_flag") not in {"good", "review"}:
                continue
            code = (row.get("station_code") or "").strip()
            dt = _parse_time(row.get("timestamp_bjt"))
            value = _as_float(row.get("level_m_max"))
            if not code or dt is None or value is None or value < 0:
                continue
            station = catalog.get(code, {})
            mapped = mapping.get(code, {})
            rows.append({
                "station_code": code,
                "station_name": row.get("station_name") or station.get("station_name", ""),
                "timestamp": dt,
                "available_at": _parse_time(row.get("available_at")),
                "depth_proxy_m": value,
                "mean_depth_proxy_m": _as_float(row.get("level_m_mean"), value),
                "district_id": mapped.get("district_id"),
                "mapping_method": mapped.get("method"),
                "lat": _as_float(row.get("lat"), station.get("lat")),
                "lon": _as_float(row.get("lon"), station.get("lon")),
                "quality_flag": row.get("quality_flag"),
                "source": row.get("source") or "深圳市水务局开放平台",
            })
    rows.sort(key=lambda r: (r["timestamp"], r["station_code"]))
    return rows


def latest_district_observations(
    now=None,
    max_age_hours=3.0,
    available_before=None,
):
    """Return fresh district observations only; stale cache is never assimilated."""
    now = now or datetime.now(timezone(timedelta(hours=8)))
    by_station = {}
    for row in load_waterlevel_rows():
        if available_before is not None:
            cutoff = available_before.astimezone(row["timestamp"].tzinfo)
            available_at = row.get("available_at")
            # Historical forecast replay is fail-closed: without an audited
            # availability time we cannot prove this observation was visible.
            if (
                available_at is None
                or available_at.astimezone(cutoff.tzinfo) > cutoff
                or row["timestamp"] > cutoff
            ):
                continue
        previous = by_station.get(row["station_code"])
        if previous is None or row["timestamp"] > previous["timestamp"]:
            by_station[row["station_code"]] = row
    by_district = defaultdict(list)
    for row in by_station.values():
        age_h = (now.astimezone(row["timestamp"].tzinfo) - row["timestamp"]).total_seconds() / 3600.0
        if row.get("district_id") and -0.1 <= age_h <= float(max_age_hours):
            by_district[row["district_id"]].append(row)
    out = {}
    for did, values in by_district.items():
        depths = [r["depth_proxy_m"] for r in values]
        out[did] = {
            "depth_m": float(median(depths)),
            "max_depth_m": float(max(depths)),
            "station_count": len(values),
            "observed_at": max(r["timestamp"] for r in values).isoformat(),
            "available_at": max(
                (r["available_at"] for r in values if r.get("available_at")),
                default=None,
            ).isoformat() if any(r.get("available_at") for r in values) else None,
            "provenance": "observed(fresh project/open-platform water-level depth proxy)",
        }
    return out


def data_readiness():
    """Summarize whether the repository can support independent model training."""
    rows = load_waterlevel_rows()
    mapping = load_station_district_map()
    if not rows:
        return {
            "status": "missing",
            "forecast_training_ready": False,
            "reason": "no quality-controlled hourly water-level observations",
        }
    start = min(r["timestamp"] for r in rows)
    end = max(r["timestamp"] for r in rows)
    stations = {r["station_code"] for r in rows}
    positives = [r for r in rows if r["depth_proxy_m"] > 0]
    high = [r for r in rows if r["depth_proxy_m"] >= 0.15]
    availability_rows = [r for r in rows if r.get("available_at") is not None]
    availability_time_auditable = len(availability_rows) == len(rows)
    duration = (end - start).total_seconds() / 3600.0
    ingestion_coverage_ready = duration >= 24 * 30 and len(high) >= 100
    independent_flood_events = 0
    minimum_independent_events = 10
    ready = (
        ingestion_coverage_ready
        and availability_time_auditable
        and independent_flood_events >= minimum_independent_events
    )
    blockers = []
    if not ingestion_coverage_ready:
        blockers.append("insufficient temporal/high-water coverage")
    if independent_flood_events < minimum_independent_events:
        blockers.append("no independently identified flood events with available_at audit")
    if not availability_time_auditable:
        blockers.append("cached rows lack audited available_at timestamps")
    return {
        "status": "ready" if ready else "insufficient-event-coverage",
        "forecast_training_ready": ready,
        "rows": len(rows),
        "stations": len(stations),
        "mapped_stations": sum(1 for code in stations if code in mapping),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_hours": round(duration, 2),
        "positive_rows": len(positives),
        "rows_ge_0_15m": len(high),
        "rows_with_available_at": len(availability_rows),
        "availability_time_auditable": availability_time_auditable,
        "max_depth_proxy_m": max(r["depth_proxy_m"] for r in rows),
        "ingestion_coverage_ready": ingestion_coverage_ready,
        "independent_flood_events": independent_flood_events,
        "minimum_independent_events": minimum_independent_events,
        "blockers": blockers,
        "reason": (
            "Current cache is a short operational slice without independently labelled flood events; "
            "use it for ingestion/assimilation tests and dry-state priors, not supervised skill claims."
        ),
        "provenance": "observed(project-local quality-controlled cache)",
    }
