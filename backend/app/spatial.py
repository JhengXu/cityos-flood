# -*- coding: utf-8 -*-
"""
显式空间耦合表（理论 §2.1）：grid ↔ road ↔ facility
----------------------------------------------------------------
世界模型的因果耦合不能只把不同层在地图上叠加，必须显式保存映射：
  - grid_id   → road_edge_ids   （格点降雨如何进入路网损伤）
  - facility_id → nearest_access_nodes（设施功能失效如何由入口道路决定）

当前数据现状（诚实标注）：
  - 区↔区 路网：用行政区质心邻近度构造（assumed；OSM 路网尚未接入）。
  - 设施↔区：以行政区中心近似设施位置（assumed；需权威 POI 坐标替换）。
  - grid↔区：WorldCover 格点坐标按最近行政区代表点分配
    （observed-derived；当前行政区边界文件不完整，不能声称是精确空间相交）。
  - 水动力区际边：来自 v3 守恒状态模型的 DEM 下坡有向图（estimated）。

这些表是 #4（道路损伤 + 设施动态可达性）与连锁失效图的耦合基底。
"""
from collections import Counter
from functools import lru_cache
import os
import numpy as np
from . import gisreal, shenzhen, state_model


def _dist(a, b):
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def district_graph():
    """区↔区 邻接权重（质心邻近度），作为路网耦合基底（assumed）。"""
    centers = {d["id"]: tuple(d["center"]) for d in shenzhen.DISTRICTS}
    G = {}
    for di, ci in centers.items():
        ws = {}
        for dj, cj in centers.items():
            if dj == di:
                continue
            w = float(np.exp(-_dist(ci, cj) ** 2 / 0.02))
            if w > 0.05:
                ws[dj] = w
        G[di] = ws
    return G


def facility_access(topk=2):
    """设施(以区中心近似) → 最近接入区列表（assumed）。
    返回 {district_id: [自身, 最近1, 最近2, ...]}。"""
    centers = {d["id"]: tuple(d["center"]) for d in shenzhen.DISTRICTS}
    out = {}
    for cid, c in centers.items():
        others = sorted(centers.items(), key=lambda kv: _dist(c, kv[1]))
        out[cid] = [k for k, _ in others[: topk + 1]]
    return out


@lru_cache(maxsize=1)
def grid_to_district():
    """Return the local GIS grid-to-district assignment without legacy imports.

    The checked-in district boundary GeoJSON contains incomplete fragments, so
    treating a point-in-polygon result as authoritative would silently drop or
    misassign many cells.  Until a complete authoritative boundary layer is
    installed, assign each observed WorldCover grid coordinate to the nearest
    district representative point and expose that limitation in ``summary``.
    """

    rows = gisreal._read_rows(
        os.path.join(gisreal.BASE, "shenzhen_builtup_density.csv")
    )
    if not rows:
        rows = gisreal._read_rows(os.path.join(gisreal.BASE, "shenzhen_dem.csv"))
    centroids = gisreal._district_centroids()
    mapping = {}
    for row in rows:
        try:
            lat, lon = float(row["lat"]), float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        grid_id = f"{lat:.5f},{lon:.5f}"
        mapping[grid_id] = gisreal._nearest_did(centroids, lat, lon)
    return mapping


def summary():
    """供 API/前端展示的耦合表摘要（含 provenance）。"""
    G = district_graph()
    fa = facility_access()
    gd = grid_to_district()
    hydraulic_edges = [edge.to_dict() for edge in state_model.DEFAULT_MODEL.edges]
    grid_counts = dict(sorted(Counter(gd.values()).items())) if gd else {}
    return {
        "district_edges": {k: len(v) for k, v in G.items()},
        "hydraulic_edges": hydraulic_edges,
        "facility_access": {k: v for k, v in fa.items()},
        "grid_to_district_cells": len(gd) if gd else 0,
        "grid_cells_by_district": grid_counts,
        "provenance": {
            "district_graph": "assumed(质心邻近度；OSM 路网待接入)",
            "hydraulic_edges": "estimated(v3 守恒模型 DEM 下坡有向图；非管网拓扑)",
            "facility_access": "assumed(区中心近似设施位置)",
            "grid_to_district": "observed-derived(WorldCover 格点坐标；最近行政区代表点分配)",
        },
        "quality_flags": [
            "district_boundaries_incomplete",
            "nearest_representative_assignment",
            "road_and_facility_topology_assumed",
        ],
        "note": "耦合表是道路损伤与设施动态可达性的基底；接入完整行政区边界、排水管网和设施入口后，应重建这些映射。",
    }
