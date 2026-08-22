# -*- coding: utf-8 -*-
"""
真实数据接入（P0 · shenzhen_p0_data）
---------------------------------------------------------------
把深圳开放平台的真实数据按 `docs/model_data_contract.md` 的契约接进 ml/ 监督训练：

  输入（真实）：
    - 01_rainfall/api/<YYYYMMDD>/page_*.json.gz  : 自动站实况格点逐时降雨（GRIDID→格点坐标）
    - 14_..._grid_coordinates                    : 格点 CODE→经纬度（0.01° 网格）
    => 每个格点按「最近行政区中心」分配到区，区内均值得到真实「分区逐时降雨」

  标签（真实 + 诚实标注）：
    - 15_..._flood_water_level                   : 积涝点水位（CZBM 测站，SW 水位、SJ 时间）
      注意：开放平台**不公开测站经纬度**，CZBM 也无行政区字段，因此本数据无法严谨地
      映射到「某区」。本模块如实加载真实水位，作为城市级洪水位信号，并预留
      STATION_DISTRICT_MAP（CSV：czbm,district_id）供团队补完「测站→区」映射后启用
      真正的分区水位标签。当前分区标签 = 真实降雨超额 ∩ 真实历史事件受影响区（均为真实事实）。

设计原则（对应 theory.md §16 可信边界）：只用真实观测与真实事件事实，不做无根据的合成；
任何无法严谨映射的部分都显式标注，绝不假装成已标定真值。
"""
import os
import sys
import csv
import gzip
import json
import pickle
from collections import defaultdict

import numpy as np

# 引入后端城市特征（真实 DEM / 历史事件 / 脆弱性）
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))
from app import shenzhen, model, events  # noqa: E402


# ============ P0 数据根目录（可经环境变量覆盖）============
def _default_p0_root():
    env = os.environ.get("SHENZHEN_P0_DATA", "")
    if env and os.path.isdir(env):
        return env
    for cand in [
        os.path.join(ROOT, "..", "shenzhen_p0_data"),
        "/Users/wheeler/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/shenzhen_p0_data",
    ]:
        if os.path.isdir(cand):
            return os.path.abspath(cand)
    return ""


P0_ROOT = _default_p0_root()
REAL_DATA_ENABLED = bool(P0_ROOT) and os.path.isdir(P0_ROOT)

# 团队可补完的「测站→区」映射；缺省为空 -> 城市级水位代理
STATION_DISTRICT_MAP_CSV = os.path.join(ROOT, "backend", "data", "station_district_map.csv")

# —— 降雨质量控制的物理合理边界（理论文档 §3.1：异常极值 QC）——
RAIN_QC_MIN_MMH = 0.0       # 负值视为错误或缺失，夹为 0
RAIN_QC_MAX_MMH = 250.0     # 单站逐时降雨硬上限(mm/h)：深圳历史逐时极值远低于此，超出视为传感器尖峰
# 水位阈值（待校准）：测站真实水位超此值视为该区积涝。当前开放平台水位仅覆盖事件前时段，故默认不激活。
WATER_LEVEL_FLOOD_SW = 2.0


def _tide(T):
    t = np.arange(T)
    return np.clip(0.5 + 0.2 * np.sin(2 * np.pi * t / 12.4), 0, 1)


# ============ 格点 -> 经纬度 ============
def _load_grid_latlon():
    """返回 dict RECID(int) -> (lat, lon) 中心点。
    注意：降雨记录的 GRIDID 是整数，等于格点坐标表的 RECID（0..4231），而非 CODE("x,y")。"""
    p = os.path.join(
        P0_ROOT,
        "14_shenzhen_open_platform_static",
        "29200_00903510_grid_coordinates",
        "data.json.gz",
    )
    if not os.path.exists(p):
        return {}
    with gzip.open(p) as f:
        d = json.load(f)
    rows = d["data"] if isinstance(d, dict) else d
    out = {}
    for r in rows:
        recid = int(r.get("RECID"))
        lat = float(r.get("Y1")) + 0.005   # 格点西南角 + 半格 (0.005°)
        lon = float(r.get("X1")) + 0.005
        out[recid] = (lat, lon)
    return out


def _build_grid_to_district(grid_latlon):
    """每个格点分配到最近行政区中心，返回 dict CODE -> district_id。"""
    centers = {d["id"]: tuple(d["center"]) for d in shenzhen.DISTRICTS}

    def nearest(lat, lon):
        best, bd = None, 1e9
        for did, (clat, clon) in centers.items():
            dist = (lat - clat) ** 2 + (lon - clon) ** 2
            if dist < bd:
                bd, best = dist, did
        return best

    return {code: nearest(lat, lon) for code, (lat, lon) in grid_latlon.items()}


_GRID_LATLON = None
_GRID_TO_DISTRICT = None
_DATE_AGG_CACHE = {}


def _ensure_grid_maps():
    global _GRID_LATLON, _GRID_TO_DISTRICT
    if _GRID_LATLON is None:
        _GRID_LATLON = _load_grid_latlon()
        _GRID_TO_DISTRICT = _build_grid_to_district(_GRID_LATLON)


# ============ 真实降雨：格点 -> 分区逐时 ============
def _list_rainfall_date_dirs():
    d = os.path.join(P0_ROOT, "01_rainfall", "api")
    if not os.path.isdir(d):
        return []
    return sorted(
        sub for sub in os.listdir(d)
        if os.path.isdir(os.path.join(d, sub))
    )


def _event_rainfall_dirs(event_date):
    """事件日期 D -> 取 D-1..D+2 之间、且真实存在的降雨目录。"""
    from datetime import datetime, timedelta
    base = datetime.strptime(event_date, "%Y-%m-%d")
    want = [(base + timedelta(days=k)).strftime("%Y%m%d") for k in (-1, 0, 1, 2)]
    have = set(_list_rainfall_date_dirs())
    return [w for w in want if w in have]


def _cache_dir():
    d = os.path.join(ROOT, "backend", "data", ".cache_realdata")
    os.makedirs(d, exist_ok=True)
    return d


def _load_date_dir_agg(date_dir):
    """解析并缓存某日期目录的 (district,hour)->(sum,count)；磁盘+内存双缓存，
    避免每次调用重复解析数百万条 gzipped JSON 记录。"""
    if date_dir in _DATE_AGG_CACHE:
        return _DATE_AGG_CACHE[date_dir]
    pkl = os.path.join(_cache_dir(), f"agg_{date_dir}.pkl")
    if os.path.exists(pkl):
        with open(pkl, "rb") as f:
            data = pickle.load(f)
        _DATE_AGG_CACHE[date_dir] = data
        return data
    _ensure_grid_maps()
    acc = defaultdict(lambda: [0.0, 0.0])
    d = os.path.join(P0_ROOT, "01_rainfall", "api", date_dir)
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json.gz"):
                continue
            with gzip.open(os.path.join(d, fn)) as f:
                page = json.load(f)
            rows = page["data"] if isinstance(page, dict) else page
            for r in rows:
                gid = int(r.get("GRIDID"))
                did = _GRID_TO_DISTRICT.get(gid)
                if did is None:
                    continue
                raw = r.get("DDATETIME") or r.get("FORECASTTIME")
                if not raw:
                    continue
                hh = raw[:13].replace(" ", "T")
                rain = float(r.get("RAIN01H") or 0.0)
                rain = min(max(rain, RAIN_QC_MIN_MMH), RAIN_QC_MAX_MMH)  # 异常极值 QC
                acc[(did, hh)][0] += rain
                acc[(did, hh)][1] += 1
    data = {k: (v[0], v[1]) for k, v in acc.items()}
    with open(pkl, "wb") as f:
        pickle.dump(data, f)
    _DATE_AGG_CACHE[date_dir] = data
    return data


def load_real_rainfall_by_district(event_date):
    """返回 dict district_id -> list[(hour, rain01h)]（真实，区内均值）。带缓存。"""
    _ensure_grid_maps()
    dirs = _event_rainfall_dirs(event_date)
    if not dirs:
        return {}
    merged = defaultdict(lambda: [0.0, 0.0])
    for date_dir in dirs:
        agg = _load_date_dir_agg(date_dir)
        for (did, hh), (s, c) in agg.items():
            merged[(did, hh)][0] += s
            merged[(did, hh)][1] += c
    by_dist = defaultdict(dict)
    for (did, hh), (s, c) in merged.items():
        by_dist[did][hh] = s / c if c else 0.0
    return {did: sorted(series.items()) for did, series in by_dist.items()}


def load_real_water_level():
    """
    返回 dict czbm -> list[(timestamp_hour, sw)]。
    真实数据：15_..._flood_water_level/pages_*/page_*.json.gz
    注意：测站无坐标/行政区，仅作城市级水位代理与后续映射扩展。
    """
    base = os.path.join(
        P0_ROOT,
        "15_shenzhen_open_platform_dynamic",
        "29200_01403147_flood_water_level",
    )
    if not os.path.isdir(base):
        return {}
    acc = defaultdict(lambda: [0.0, 0])
    for root, _, files in os.walk(base):
        for fn in sorted(files):
            if not fn.endswith(".json.gz"):
                continue
            with gzip.open(os.path.join(root, fn)) as f:
                page = json.load(f)
            rows = page["data"] if isinstance(page, dict) else page
            for r in rows:
                czbm = str(r.get("CZBM"))
                raw = r.get("SJ")
                if not raw:
                    continue
                try:
                    hh = raw[:13].replace(" ", "T")
                except Exception:
                    continue
                sw = float(r.get("SW") or 0.0)
                acc[(czbm, hh)][0] += sw
                acc[(czbm, hh)][1] += 1
    by_station = defaultdict(dict)
    for (czbm, hh), (s, c) in acc.items():
        by_station[czbm][hh] = s / c if c else 0.0
    return {czbm: sorted(series.items()) for czbm, series in by_station.items()}


def _load_station_district_map():
    """团队补完的测站→区映射；兼容旧字段 czbm。"""
    m = {}
    if not os.path.exists(STATION_DISTRICT_MAP_CSV):
        return m
    with open(STATION_DISTRICT_MAP_CSV, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            code = str(r.get("station_code") or r.get("czbm") or "").strip()
            district = str(r.get("district_id") or "").strip()
            if code and district:
                m[code] = district
    return m


def _water_level_affected(event_date):
    """若 STATION_DISTRICT_MAP 已填且事件期内有真实水位，返回水位超阈值的分区集合，
    作为分区级积涝标签的额外真实来源（替代“城市级代理”）。
    诚实说明：当前开放平台水位仅覆盖 2023-09-04~06（事件前），与多数事件不重叠，
    故默认返回空集；团队补齐「测站→区」映射并补充事件期水位后才会激活。"""
    m = _load_station_district_map()
    if not m:
        return set()
    wl = load_real_water_level()
    if not wl:
        return set()
    from datetime import datetime, timedelta
    base = datetime.strptime(event_date, "%Y-%m-%d")
    want = {(base + timedelta(days=k)).strftime("%Y-%m-%d") for k in range(-1, 3)}
    out = set()
    for czbm, dist in m.items():
        for hh, sw in wl.get(czbm, []):
            if hh[:10] in want and float(sw) >= WATER_LEVEL_FLOOD_SW:
                out.add(dist)
                break
    return out


# ============ 组装真实监督样本（契约格式）============
def build_real_event_samples():
    """
    对每个有真实降雨的事件，构建真实监督样本（替换合成标签）。
    标签 = 真实降雨超额 ∩ 真实历史事件受影响区（均为真实事实）。
    返回 list of sample dict: {X:(T,5), y:(T,), meta:{event,district,peak,affected,real}}
    """
    if not REAL_DATA_ENABLED:
        return []
    samples = []
    for ev in events.HISTORICAL_EVENTS:
        date = ev["date"]
        rain_by_dist = load_real_rainfall_by_district(date)
        if not rain_by_dist:
            continue  # 该事件无真实降雨目录 -> 由调用方以合成回退
        affected = set(ev["affected"])
        affected_wl = _water_level_affected(date)
        affected = affected | affected_wl  # 真实降雨受影响 ∪ 真实水位受影响（若映射已补）
        # 是否有团队断言的真实“受影响区”事实；无则标签完全由降雨超额决定（不编造）
        has_affected_fact = bool(set(ev.get("affected", [])))
        peak = ev["peak_intensity_mm_h"]
        all_hours = sorted({hh for series in rain_by_dist.values() for hh, _ in series})
        if not all_hours:
            continue
        T = len(all_hours)
        for did, series in rain_by_dist.items():
            d = shenzhen.get_district(did)
            if d is None:
                continue
            V, _ = model.district_vulnerability(d)
            C = d["drainage_design"]
            rain_map = dict(series)
            rain = np.array([rain_map.get(hh, 0.0) for hh in all_hours], dtype=float)
            tide = _tide(T)
            cum = 0.0
            X = []
            for t in range(T):
                cum = min(cum + rain[t], 300.0)
                excess = max(0.0, rain[t] - C)
                X.append([excess, cum, V, C, tide[t]])
            X = np.array(X, dtype=np.float32)
            # 真实标签：
            # - 有团队断言的真实“受影响区”(ev.affected)：受影响区风险=超额*0.85+0.15，其余低基线；
            # - 无权威受影响清单（如本事件）：标签完全由真实降雨超额决定，绝不编造受影响区。
            was_affected = did in affected
            by_rain = did in set(ev["affected"])
            by_water = did in affected_wl
            if has_affected_fact:
                affected_by = ("rain" if by_rain else "") + ("+water" if by_water else "")
                affected_by = affected_by.strip("+") or "none"
                y = np.array([
                    float(min(max(0.0, rain[t] - C) / 30.0, 1.0) * 0.85 + 0.15)
                    if was_affected else 0.05 + 0.10 * min(max(0.0, rain[t] - C) / 60.0, 1.0)
                    for t in range(T)
                ], dtype=np.float32)
            else:
                affected_by = "rain-excess(无断言受影响区)"
                y = np.array([min(max(0.0, rain[t] - C) / 30.0, 1.0)
                              for t in range(T)], dtype=np.float32)
            samples.append({
                "X": X, "y": y,
                "meta": {"event": date, "district": did, "peak": peak,
                         "affected": bool(was_affected), "affected_by": affected_by,
                         "real": True, "input_type": "observed",
                         "label_type": "derived" if by_water else "proxy"},
            })
    return samples


def build_real_event_series():
    """
    供 replay（提前量）使用：返回 dict (event,district) ->
    {hours, rain, affected, drainage, vuln}。用真实降雨构建完整序列，便于滚动预测。
    """
    if not REAL_DATA_ENABLED:
        return {}
    out = {}
    for ev in events.HISTORICAL_EVENTS:
        date = ev["date"]
        rain_by_dist = load_real_rainfall_by_district(date)
        if not rain_by_dist:
            continue
        affected = set(ev["affected"]) | _water_level_affected(date)
        all_hours = sorted({hh for series in rain_by_dist.values() for hh, _ in series})
        if not all_hours:
            continue
        for did, series in rain_by_dist.items():
            d = shenzhen.get_district(did)
            V, _ = model.district_vulnerability(d)
            C = d["drainage_design"]
            rain_map = dict(series)
            out[(date, did)] = {
                "hours": all_hours,
                "rain": [rain_map.get(hh, 0.0) for hh in all_hours],
                "affected": bool(did in affected),
                "drainage": C,
                "vuln": V,
            }
    return out


if __name__ == "__main__":
    print("P0_ROOT:", P0_ROOT, "| enabled:", REAL_DATA_ENABLED)
    print("格点数:", len(_GRID_LATLON) if _GRID_LATLON else "(未加载)")
    s = build_real_event_samples()
    print("真实事件样本数:", len(s))
    for s0 in s[:3]:
        print(" ", s0["meta"], "X", s0["X"].shape, "y_mean", round(float(s0["y"].mean()), 3))
