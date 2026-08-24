# -*- coding: utf-8 -*-
"""
道路损伤 + 动态可达性（理论 #4）
----------------------------------------------------------------
- 集合 P50 代表性水深(mm) → 道路速度/通行能力折减（assumed 曲线）。
- 在 #3 的 区↔区 耦合图上做动态最短路（Dijkstra），折减后的有效速度决定可达性。
- 输出每个设施（以区中心近似）的可达行政区与“可达人口占比”，以及对比基线(无损伤)的 Δ。

损伤驱动来自守恒状态模型的有量纲水深。损伤曲线仍为 assumed，待真实路网/车速标定。
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
    """代表性水深(mm) → 速度/通行能力折减比例（assumed 线性封顶曲线）。"""
    d = float(depth_mm)
    if not math.isfinite(d) or d < 0.0:
        raise ValueError("depth must be a finite non-negative value in millimetres")
    return min(DAMAGE_CAP, d / 500.0 * 0.9)


def damage_ratio_to_depth(damage_ratio):
    """Inverse of the uncapped branch for the deprecated ratio query input."""
    ratio = float(damage_ratio)
    if not math.isfinite(ratio) or not 0.0 <= ratio <= DAMAGE_CAP:
        raise ValueError(f"damage ratio must be between 0 and {DAMAGE_CAP}")
    return ratio / 0.9 * 500.0


def _centers():
    return {d["id"]: tuple(d["center"]) for d in shenzhen.DISTRICTS}


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def compute_accessibility(depth_by_district, closed_districts=None):
    """给定每个区的水深(代理)，返回道路损伤 + 设施动态可达性。

    返回结构含 provenance，区分 assumed（曲线/人口/速度）与 observed（格点→区已有，未在此直接用到）。
    """
    centers = _centers()
    closed = set(closed_districts or ())
    unknown_closed = closed - set(centers)
    if unknown_closed:
        raise ValueError(f"unknown closed districts: {sorted(unknown_closed)}")
    total_pop = sum(ASSUMED_POP.values())
    dmg = {d: depth_to_damage(depth_by_district.get(d, 0.0)) for d in centers}
    fa = spatial.facility_access()
    graph = spatial.district_graph()

    def solve(damage, blocked):
        result = {}
        for fid, access in fa.items():
            # 多源 Dijkstra：以设施接入区为源点，只沿声明的耦合边。
            dist = {d: float("inf") for d in centers}
            open_access = [node for node in access if node not in blocked]
            for node in open_access:
                dist[node] = 0.0
            pq = [(0.0, node) for node in open_access]
            while pq:
                cost, source = heapq.heappop(pq)
                if source in blocked or cost > dist[source]:
                    continue
                for target in graph.get(source, {}):
                    if target in blocked:
                        continue
                    base = _dist(centers[source], centers[target]) * 100.0
                    travel = base / max(
                        0.05, BASE_SPEED * (1.0 - damage[target])
                    )
                    next_cost = cost + travel
                    if next_cost < dist[target]:
                        dist[target] = next_cost
                        heapq.heappush(pq, (next_cost, target))
            reachable = [
                district
                for district in centers
                if district not in blocked and dist[district] <= BUDGET_H
            ]
            reach_pop = sum(ASSUMED_POP[district] for district in reachable)
            result[fid] = {
                "reachable_districts": reachable,
                "reachable_pop": reach_pop,
                "reachable_pop_share": round(reach_pop / total_pop, 3),
            }
        return result

    facilities = solve(dmg, closed)
    base_fac = solve({district: 0.0 for district in centers}, set())
    delta = {
        fid: round(facilities[fid]["reachable_pop_share"] - base_fac[fid]["reachable_pop_share"], 3)
        for fid in facilities
    }
    city_share = round(sum(f["reachable_pop_share"] for f in facilities.values()) / len(facilities), 3)
    city_share_base = round(
        sum(item["reachable_pop_share"] for item in base_fac.values()) / len(base_fac), 3
    )
    return {
        "damage": {k: round(v, 3) for k, v in dmg.items()},
        "facilities": facilities,
        "baseline_facilities": base_fac,
        "city_reachable_pop_share": city_share,
        "city_reachable_pop_share_baseline": city_share_base,
        "city_delta": round(city_share - city_share_base, 3),
        "budget_h": BUDGET_H,
        "closed_districts": sorted(closed),
        "provenance": {
            "road_damage_curve": "assumed(水深线性折减曲线)",
            "base_speed": "assumed(30km/h)",
            "population": "assumed(行政区代表性人口；应替换七普/人口栅格)",
            "coupling_graph": "assumed(质心邻近边；Dijkstra仅沿显式边，OSM路网待接入)",
            "damage_driver": "estimated(守恒集合状态模型 P50 峰值水深，单位mm)",
        },
        "note": "水深由守恒图状态模型驱动；接入真实路网/测速后应替换 depth_to_damage 与区↔区距离。",
    }


def counterfactual(depth_base, close=None, pump=None):
    """反事实并排对比（理论 #5）：基线 vs 干预（封路/抽排提升），输出 Δ。
    - close: 'luohu,baoan' 将这些区道路设为不可通行(水深→极大值)
    - pump:  'futian:0.5' 将该区损伤按指定比例降低(抽排/泵站增效)
    返回 {baseline, intervention, delta_city_reachable_pop_share}。
    """
    valid_districts = {district["id"] for district in shenzhen.DISTRICTS}
    depth2 = dict(depth_base)
    closed_districts = set()
    if pump is not None:
        if not isinstance(pump, str) or not pump.strip():
            raise ValueError("pump 格式必须为 district:fraction，多个区用逗号分隔")
        seen = set()
        for item in pump.split(","):
            if item.count(":") != 1:
                raise ValueError("pump 格式必须为 district:fraction，多个区用逗号分隔")
            raw_district, raw_fraction = (part.strip() for part in item.split(":", 1))
            if raw_district not in valid_districts:
                raise ValueError(f"pump 包含未知行政区: {raw_district}")
            if raw_district in seen:
                raise ValueError(f"pump 重复指定行政区: {raw_district}")
            seen.add(raw_district)
            try:
                fraction = float(raw_fraction)
            except (TypeError, ValueError):
                raise ValueError(f"{raw_district} 的 pump 系数不是数值") from None
            if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
                raise ValueError(f"{raw_district} 的 pump 系数必须在 0..1")
            depth2[raw_district] = max(
                0.0, depth_base.get(raw_district, 0.0) * (1.0 - fraction)
            )
    if close is not None:
        if not isinstance(close, str) or not close.strip():
            raise ValueError("close 必须是逗号分隔的行政区 ID")
        seen = set()
        for item in close.split(","):
            district_id = item.strip()
            if not district_id or district_id not in valid_districts:
                raise ValueError(f"close 包含未知行政区: {district_id or '<empty>'}")
            if district_id in seen:
                raise ValueError(f"close 重复指定行政区: {district_id}")
            seen.add(district_id)
            closed_districts.add(district_id)
    base = compute_accessibility(depth_base)
    inter = compute_accessibility(depth2, closed_districts=closed_districts)
    return {
        "baseline": base,
        "intervention": inter,
        "delta_city_reachable_pop_share": round(
            inter["city_reachable_pop_share"] - base["city_reachable_pop_share"], 3),
        "provenance": {
            "baseline": "estimated(§3.3 代理状态驱动)",
            "intervention": "simulated(反事实干预；close 区从路由图移除，pump 为抽排假设)",
        },
        "note": "#5 反事实：对比无干预基线 vs 抽排/封路干预下的设施可达人口 Δ；关闭区不可进入、离开或穿越。",
    }
