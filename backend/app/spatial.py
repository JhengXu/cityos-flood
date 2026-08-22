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
  - grid↔区：复用 realdata 的真实格点→区映射（observed/realdata）。

这些表是 #4（道路损伤 + 设施动态可达性）与连锁失效图的耦合基底。
"""
import os
import numpy as np
from . import shenzhen


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


def grid_to_district():
    """真实格点→区 映射（observed/realdata）；确保已加载后返回。
    ml/ 与 app/ 是平级包，需把项目根加入 sys.path 才能 import。"""
    import sys, os
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    if root not in sys.path:
        sys.path.insert(0, root)
    import ml.realdata as realdata
    if realdata._GRID_TO_DISTRICT is None:
        realdata._ensure_grid_maps()
    return realdata._GRID_TO_DISTRICT


def summary():
    """供 API/前端展示的耦合表摘要（含 provenance）。"""
    G = district_graph()
    fa = facility_access()
    gd = grid_to_district()
    return {
        "district_edges": {k: len(v) for k, v in G.items()},
        "facility_access": {k: v for k, v in fa.items()},
        "grid_to_district_cells": len(gd) if gd else 0,
        "provenance": {
            "district_graph": "assumed(质心邻近度；OSM 路网待接入)",
            "facility_access": "assumed(区中心近似设施位置)",
            "grid_to_district": "observed(realdata 格点→区)",
        },
        "note": "耦合表是 #4 道路损伤与设施动态可达性的基底；接入 OSM 路网后应替换 district_graph 为真实 edge 列表。",
    }
