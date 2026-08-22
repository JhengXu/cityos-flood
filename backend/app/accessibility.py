# -*- coding: utf-8 -*-
"""
道路损伤 + 动态可达性（理论 #4）
----------------------------------------------------------------
- 水深(代理) → 道路速度/通行能力折减（assumed 曲线）。
- 在 #3 的 区↔区 耦合图上做动态最短路（Dijkstra），折减后的有效速度决定可达性。
- 输出每个设施（以区中心近似）的可达行政区与“可达人口占比”，以及对比基线(无损伤)的 Δ。

损伤驱动来自 #2 的物理代理状态 h（积水累积代理）。所有参数为 assumed，待真实路网/车速标定。
"""
import math
import heapq
from . import shenzhen, spatial

BASE_SPEED = 30.0      # 假定基础车速 km/h（assumed）
BUDGET_H = 0.5         # 可达性时间预算 30 分钟（assumed）
DAMAGE_CAP = 0.95

# 行政区代表性人口（assumed；应替换为权威人口栅格/七普数据）
ASSUMED_POP = {
    "futian": 1_500_000, "luohu": 1_100_000, "nanshan": 1_800_000,
    "baoan": 4_500_000, "longgang": 4_000_000, "yantian": 600_000,
    "longhua": 2_500_000, "pingshan": 1_000_000, "guangming": 1_100_000,
    "dapeng": 600_000,
}


def depth_to_damage(depth_mm):
    """水深(代理 mm) → 速度/通行能力折减比例（assumed 线性封顶曲线）。"""
    d = max(0.0, float(depth_mm))
    return min(DAMAGE_CAP, d / 500.0 * 0.9)


def _centers():
    return {d["id"]: tuple(d["center"]) for d in shenzhen.DISTRICTS}


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def compute_accessibility(depth_by_district):
    """给定每个区的水深(代理)，返回道路损伤 + 设施动态可达性。

    返回结构含 provenance，区分 assumed（曲线/人口/速度）与 observed（格点→区已有，未在此直接用到）。
    """
    centers = _centers()
    total_pop = sum(ASSUMED_POP.values())
    dmg = {d: depth_to_damage(depth_by_district.get(d, 0.0)) for d in centers}
    fa = spatial.facility_access()

    facilities = {}
    for fid, access in fa.items():
        # 多源 Dijkstra：以设施接入区为源点
        dist = {d: float("inf") for d in centers}
        for a in access:
            dist[a] = 0.0
        pq = [(0.0, a) for a in access]
        while pq:
            c, u = heapq.heappop(pq)
            if c > dist[u]:
                continue
            for v in centers:
                if v == u:
                    continue
                base = _dist(centers[u], centers[v]) * 100.0  # 度→km（assumed 比例）
                eff = base / max(0.05, BASE_SPEED * (1.0 - dmg[v]))
                nc = c + eff
                if nc < dist[v]:
                    dist[v] = nc
                    heapq.heappush(pq, (nc, v))
        reachable = [d for d in centers if dist[d] <= BUDGET_H]
        reach_pop = sum(ASSUMED_POP[d] for d in reachable)
        facilities[fid] = {
            "reachable_districts": reachable,
            "reachable_pop": reach_pop,
            "reachable_pop_share": round(reach_pop / total_pop, 3),
        }

    base_fac = {fid: {"reachable_pop_share": 1.0} for fid in fa}  # 无损伤基线
    delta = {
        fid: round(facilities[fid]["reachable_pop_share"] - base_fac[fid]["reachable_pop_share"], 3)
        for fid in facilities
    }
    city_share = round(sum(f["reachable_pop_share"] for f in facilities.values()) / len(facilities), 3)
    city_share_base = 1.0
    return {
        "damage": {k: round(v, 3) for k, v in dmg.items()},
        "facilities": facilities,
        "city_reachable_pop_share": city_share,
        "city_reachable_pop_share_baseline": city_share_base,
        "city_delta": round(city_share - city_share_base, 3),
        "budget_h": BUDGET_H,
        "provenance": {
            "road_damage_curve": "assumed(水深线性折减曲线)",
            "base_speed": "assumed(30km/h)",
            "population": "assumed(行政区代表性人口；应替换七普/人口栅格)",
            "coupling_graph": "assumed(质心邻近度；OSM 路网待接入)",
            "damage_driver": "estimated(§3.3 物理代理状态 h 作为水深代理)",
        },
        "note": "水深由 #2 物理代理状态 h 驱动；接入真实路网/测速后应替换 depth_to_damage 与区↔区距离。",
    }


def counterfactual(depth_base, close=None, pump=None):
    """反事实并排对比（理论 #5）：基线 vs 干预（封路/抽排提升），输出 Δ。
    - close: 'luohu,baoan' 将这些区道路设为不可通行(水深→极大值)
    - pump:  'futian:0.5' 将该区损伤按指定比例降低(抽排/泵站增效)
    返回 {baseline, intervention, delta_city_reachable_pop_share}。
    """
    depth2 = dict(depth_base)
    if pump:
        for kv in pump.split(","):
            k, v = kv.split(":")
            f = float(v)
            depth2[k.strip()] = max(0.0, depth_base.get(k.strip(), 0.0) * (1.0 - f))
    if close:
        for d in close.split(","):
            depth2[d.strip()] = 999.0
    base = compute_accessibility(depth_base)
    inter = compute_accessibility(depth2)
    return {
        "baseline": base,
        "intervention": inter,
        "delta_city_reachable_pop_share": round(
            inter["city_reachable_pop_share"] - base["city_reachable_pop_share"], 3),
        "provenance": {
            "baseline": "estimated(§3.3 代理状态驱动)",
            "intervention": "simulated(反事实干预；封路=pump/close 假设)",
        },
        "note": "#5 反事实：对比无干预基线 vs 抽排/封路干预下的设施可达人口 Δ。",
    }
