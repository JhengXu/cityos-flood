# -*- coding: utf-8 -*-
"""
深圳市行政区 + 街道级采样点（CITY OS · 内涝预测底板 v2）
---------------------------------------------------------------
数据分层策略（诚实标注）：
  - elevation_mean : 由 Open-Elevation 真实 DEM 获取（运行期联网，文件缓存）
  - historical_flood_index : 由真实历史内涝事件知识库聚合得到
  - drainage_design / low_lying_ratio / impervious_ratio / coastal :
        代表性估算值（正式比赛应替换为排水管网、下垫面、地形等权威 GIS/市政数据）
  - SUBDISTRICT_POINTS : 街道级采样点，用于「多点降雨网格 + 空间降尺度」
"""
from . import geo, events

CITY = {
    "name": "深圳市",
    "center": [22.5431, 114.0579],
    "note": "中国特色社会主义先行示范区 · 滨海超大城市",
}

# 10 个行政区（含大鹏新区）。elevation_mean 初值为估算，运行期被真实 DEM 覆盖。
DISTRICTS = [
    {"id": "futian", "name": "福田区", "center": [22.538, 114.058],
     "drainage_design": 36.0, "low_lying_ratio": 0.35, "impervious_ratio": 0.86,
     "elevation_mean": 15.0, "historical_flood_index": 0.6, "coastal": 0.70,
     "tag": "CBD 高密度建成区，沿海低地"},
    {"id": "luohu", "name": "罗湖区", "center": [22.555, 114.135],
     "drainage_design": 28.0, "low_lying_ratio": 0.42, "impervious_ratio": 0.83,
     "elevation_mean": 20.0, "historical_flood_index": 0.66, "coastal": 0.50,
     "tag": "老城区，排水标准偏低"},
    {"id": "nanshan", "name": "南山区", "center": [22.530, 113.930],
     "drainage_design": 36.0, "low_lying_ratio": 0.30, "impervious_ratio": 0.81,
     "elevation_mean": 30.0, "historical_flood_index": 0.50, "coastal": 0.80,
     "tag": "科技园+滨海，地势略高"},
    {"id": "baoan", "name": "宝安区", "center": [22.555, 113.880],
     "drainage_design": 25.0, "low_lying_ratio": 0.50, "impervious_ratio": 0.78,
     "elevation_mean": 10.0, "historical_flood_index": 0.78, "coastal": 0.90,
     "tag": "西部沿海平原，产业密集，最易涝"},
    {"id": "longgang", "name": "龙岗区", "center": [22.720, 114.210],
     "drainage_design": 30.0, "low_lying_ratio": 0.25, "impervious_ratio": 0.70,
     "elevation_mean": 60.0, "historical_flood_index": 0.40, "coastal": 0.10,
     "tag": "东北部，地势较高"},
    {"id": "yantian", "name": "盐田区", "center": [22.560, 114.230],
     "drainage_design": 30.0, "low_lying_ratio": 0.35, "impervious_ratio": 0.65,
     "elevation_mean": 40.0, "historical_flood_index": 0.55, "coastal": 1.00,
     "tag": "滨海港口，感潮影响明显"},
    {"id": "longhua", "name": "龙华区", "center": [22.680, 114.040],
     "drainage_design": 32.0, "low_lying_ratio": 0.30, "impervious_ratio": 0.76,
     "elevation_mean": 50.0, "historical_flood_index": 0.45, "coastal": 0.20,
     "tag": "中部，人口稠密"},
    {"id": "pingshan", "name": "坪山区", "center": [22.690, 114.330],
     "drainage_design": 30.0, "low_lying_ratio": 0.20, "impervious_ratio": 0.66,
     "elevation_mean": 80.0, "historical_flood_index": 0.30, "coastal": 0.05,
     "tag": "东部，地势高，风险较低"},
    {"id": "guangming", "name": "光明区", "center": [22.750, 113.950],
     "drainage_design": 30.0, "low_lying_ratio": 0.25, "impervious_ratio": 0.70,
     "elevation_mean": 50.0, "historical_flood_index": 0.40, "coastal": 0.10,
     "tag": "西北部，新城建设区"},
    {"id": "dapeng", "name": "大鹏新区", "center": [22.610, 114.500],
     "drainage_design": 25.0, "low_lying_ratio": 0.20, "impervious_ratio": 0.50,
     "elevation_mean": 100.0, "historical_flood_index": 0.25, "coastal": 1.00,
     "tag": "半岛山地，生态为主"},
]

# 街道级采样点（用于多点降雨网格 + 空间降尺度）
SUBDISTRICT_POINTS = [
    ("市民中心", "futian", 22.538, 114.058), ("华强北", "futian", 22.547, 114.085), ("车公庙", "futian", 22.530, 114.030),
    ("东门", "luohu", 22.545, 114.120), ("罗湖口岸", "luohu", 22.530, 114.115), ("笋岗", "luohu", 22.565, 114.100),
    ("科技园", "nanshan", 22.540, 113.950), ("蛇口", "nanshan", 22.480, 113.880), ("前海", "nanshan", 22.520, 113.890),
    ("宝安中心", "baoan", 22.555, 113.880), ("福永", "baoan", 22.650, 113.810), ("沙井", "baoan", 22.720, 113.820),
    ("龙岗中心城", "longgang", 22.720, 114.210), ("布吉", "longgang", 22.610, 114.130), ("坂田", "longgang", 22.680, 114.060),
    ("沙头角", "yantian", 22.560, 114.230), ("盐田港", "yantian", 22.590, 114.270), ("梅沙", "yantian", 22.600, 114.300),
    ("龙华中心", "longhua", 22.680, 114.040), ("民治", "longhua", 22.620, 114.040), ("观澜", "longhua", 22.720, 114.030),
    ("坪山中心", "pingshan", 22.690, 114.330), ("坑梓", "pingshan", 22.730, 114.400), ("碧岭", "pingshan", 22.660, 114.310),
    ("光明中心", "guangming", 22.750, 113.950), ("公明", "guangming", 22.730, 113.900), ("科学城", "guangming", 22.780, 113.970),
    ("大鹏", "dapeng", 22.610, 114.500), ("葵涌", "dapeng", 22.630, 114.430), ("南澳", "dapeng", 22.550, 114.500),
]


def _load_gis_features():
    """读取从真实 GIS（DEM/WorldCover）计算的区特征缓存，替换估算值。"""
    import os, json
    p = os.path.join(os.path.dirname(__file__), "..", "data", "gis_features.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _enrich():
    """用真实数据覆盖估算初值：真实 DEM 高程 + 真实事件指数 + 真实 GIS 低洼/不透水/临海。"""
    hidx = events.historical_index()
    gis = _load_gis_features()
    # 项目内已有区级 DEM 聚合时直接使用，避免每次启动重复请求公网的
    # 单点高程。仅对本地确实缺失的区触发 Open-Elevation 兜底。
    missing_coords = [
        tuple(d["center"]) for d in DISTRICTS
        if "elevation_mean" not in gis.get(d["id"], {})
    ]
    elevs = geo.get_elevations(missing_coords) if missing_coords else {}
    for d in DISTRICTS:
        lat, lon = tuple(d["center"])
        d["historical_flood_index"] = hidx.get(d["id"], d["historical_flood_index"])
        # 真实 GIS 特征（DEM 低洼 / WorldCover 不透水 / 临海），替换估算
        g = gis.get(d["id"])
        if g:
            d["elevation_mean"] = round(float(g.get("elevation_mean", d["elevation_mean"])), 1)
            d["low_lying_ratio"] = g.get("low_lying_ratio", d["low_lying_ratio"])
            d["impervious_ratio"] = g.get("impervious_ratio", d["impervious_ratio"])
            d["coastal"] = g.get("coastal", d["coastal"])
            if "drainage_design" in g:
                d["drainage_design"] = g["drainage_design"]   # 真实派生排水标准
            # 用区级真实高程均值兜底更可信（Open-Elevation 单点 vs 区域 DEM）
            d["gis_note"] = (f"真实GIS: DEM均值{g.get('elevation_mean')}m, "
                             f"低洼{d['low_lying_ratio']}, 不透水{d['impervious_ratio']}, "
                             f"临海{d['coastal']}, 排水{d['drainage_design']}mm/h"
                             f"(道路网{round(g.get('road_km',0),1)}km)")
        else:
            d["elevation_mean"] = round(float(
                elevs.get((round(lat, 4), round(lon, 4)), d["elevation_mean"])
            ), 1)
    geo.flush_cache()


_enrich()

DRAINAGE_AVG = sum(d["drainage_design"] for d in DISTRICTS) / len(DISTRICTS)


def get_district(district_id: str):
    for d in DISTRICTS:
        if d["id"] == district_id:
            return d
    return None
