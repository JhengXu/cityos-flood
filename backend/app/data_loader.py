# -*- coding: utf-8 -*-
"""
data_loader.py — 统一数据层加载器（v4.0 多灾种增强）
====================================================
从 shenzhen-flood/data/unified/ 加载四大灾种真实统一数据，
为「深圳全自然灾害预测」提供多灾种展示与 3D 场景数据。

数据源（诚实标注 provenance）：
  - typhoon_track.csv   : IBTrACS 台风最佳路径（WGS84, 2014-2026）
  - typhoon_forecast.csv: 深圳气象局热带气旋预报
  - tide_timeseries.csv : HKO 验潮站潮位（香港海图基准 CD）
  - wave_timeseries.csv : CMEMS WAVERYS 波浪再分析
  - landslide_point.csv : 规自局 300 地质灾害隐患点（坡高/坡度/等级，CGCS2000→WGS84）
  - landslide_warning.csv: 地灾预警史（黄/橙/红）
  - building_point.csv  : OSM 建筑（中心点+高度）
  - population_grid_1km.csv: GHS-POP 人口
  - river_level.csv     : 深圳河水位
  - reservoir_level.csv : 水库水位
  - floodpoint_2019.csv : 206 内涝点（天地图）
"""
import os
import numpy as np
import pandas as pd

# 统一数据层路径：shenzhen-flood/data/unified（与 cityos 仓库同级）
_BASE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "shenzhen-flood", "data", "unified"))

_cache = {}


def _load(name):
    if name not in _cache:
        p = os.path.join(_BASE, name)
        if not os.path.exists(p):
            _cache[name] = None
        else:
            try:
                _cache[name] = pd.read_csv(p, encoding="utf-8-sig")
            except Exception as e:
                print(f"[data_loader] {name} 加载失败: {e}")
                _cache[name] = None
    return _cache[name]


def typhoon_track():
    return _load("typhoon_track.csv")


def typhoon_forecast():
    return _load("typhoon_forecast.csv")


def tide():
    return _load("tide_timeseries.csv")


def wave():
    return _load("wave_timeseries.csv")


def landslide_points():
    return _load("landslide_point.csv")


def landslide_warnings():
    return _load("landslide_warning.csv")


def buildings():
    return _load("building_point.csv")


def building_coords():
    return _load("building_coords.csv")


def population():
    return _load("population_grid_1km.csv")


def rivers():
    return _load("river_level.csv")


def reservoirs():
    return _load("reservoir_level.csv")


def floodpoints():
    return _load("floodpoint_2019.csv")


def catalog():
    return {
        "base": _BASE,
        "files": sorted(os.listdir(_BASE)) if os.path.isdir(_BASE) else [],
    }