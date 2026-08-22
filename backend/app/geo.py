# -*- coding: utf-8 -*-
"""
真实高程数据接入：Open-Elevation 免费 DEM API（无需 Key）
-----------------------------------------------------------
- 批量查询坐标点海拔，结果缓存到 data/elevation_cache.json（仅首次联网，之后离线/快速）
- 失败时回退到估算值，保证演示可跑
"""
import json
import os
import time

import requests

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "elevation_cache.json")
OPEN_ELEV_URL = "https://api.open-elevation.com/api/v1/lookup"

# 估算回退值（深圳地形大致区间，单位 m）
_FALLBACK = 30.0


def _load_cache():
    try:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


_cache = _load_cache()
_cache_dirty = False


def get_elevation(lat, lon, timeout=20):
    key = f"{round(lat,4)},{round(lon,4)}"
    if key in _cache:
        return _cache[key]
    try:
        r = requests.get(
            OPEN_ELEV_URL,
            params={"locations": f"{lat},{lon}"},
            timeout=timeout,
        )
        r.raise_for_status()
        elev = float(r.json()["results"][0]["elevation"])
        _cache[key] = elev
        global _cache_dirty
        _cache_dirty = True
        return elev
    except Exception as e:
        print(f"[geo] Open-Elevation 失败({lat},{lon}): {e} -> 回退估算")
        return _FALLBACK


def get_elevations(coords, timeout=30):
    """批量查询；成功项写入缓存。coords: list of (lat, lon)。返回 dict {(lat,lon): elev}。"""
    out = {}
    todo = []
    for lat, lon in coords:
        k = (round(lat, 4), round(lon, 4))
        if f"{k[0]},{k[1]}" in _cache:
            out[k] = _cache[f"{k[0]},{k[1]}"]
        else:
            todo.append(k)
    if todo:
        try:
            locs = "|".join(f"{lat},{lon}" for lat, lon in todo)
            r = requests.get(OPEN_ELEV_URL, params={"locations": locs}, timeout=timeout)
            r.raise_for_status()
            for item, (lat, lon) in zip(r.json()["results"], todo):
                elev = float(item["elevation"])
                _cache[f"{lat:.4f},{lon:.4f}"] = elev
                out[(lat, lon)] = elev
            global _cache_dirty
            _cache_dirty = True
        except Exception as e:
            print(f"[geo] 批量高程失败: {e} -> 估算回退")
            for lat, lon in todo:
                out[(lat, lon)] = _FALLBACK
    if _cache_dirty:
        _save_cache(_cache)
    return out


def flush_cache():
    if _cache_dirty:
        _save_cache(_cache)
