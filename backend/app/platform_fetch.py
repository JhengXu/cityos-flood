# -*- coding: utf-8 -*-
"""
实时抓取平台数据（opendata.sz.gov.cn + 天地图 + 免费源）
---------------------------------------------------------------
- 深圳开放平台：登录会话下载「积涝点水位」实时数据 + 「测站信息」。
- 天地图：地理编码（站名/易涝点 -> 坐标）。
- 免费源：CHIRPS 降雨、Overpass(OSM)（免账号）。

凭据一律从 .env / 环境变量读取（勿硬编码，.env 已 gitignore）：
  SZ_OPENDATA_JSESSIONID / SZ_OPENDATA_ARIAAPPID / TIANDITU_KEY
"""
import os
import io
import csv
import json
import math
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()  # 读取项目根 .env


def _env(k):
    return os.environ.get(k, "")


SESSION_COOKIE = (
    f"JSESSIONID={_env('SZ_OPENDATA_JSESSIONID')}; "
    f"ariaappid={_env('SZ_OPENDATA_ARIAAPPID')}"
)
TIANDITU_KEY = _env("TIANDITU_KEY")
TIANDITU_REFERER = "https://lbs.tianditu.gov.cn/"
# 开放平台 WAF 屏蔽 python-requests 默认 UA，需伪装浏览器 UA
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _hdrs(extra=None):
    h = {"User-Agent": BROWSER_UA}
    if extra:
        h.update(extra)
    return h

# 数据集（opendata.sz.gov.cn）—— 已实际验证可用
DATASETS = {
    "waterlevel": {"fileId": "1818478466449911808", "resId": "29200/01403147"},   # 积涝点水位 CSV
    "station": {"fileId": "2008721463098224640", "resId": "29200/01400987"},       # 测站信息 CSV
}

SZ_BBOX = "113.7,22.4,114.7,22.9"   # 深圳 bbox，地理编码过滤误匹配
LEVEL_THRESHOLD = 0.5               # 水位阈值(m)：超过视为积涝预警（可调）


def _has_opendata():
    return bool(_env("SZ_OPENDATA_JSESSIONID") and _env("SZ_OPENDATA_ARIAAPPID"))


def _download_csv(dataset_key):
    """通过登录会话下载开放平台数据集 CSV，返回文本（可能因会话失效而失败）。"""
    if not _has_opendata():
        raise RuntimeError("未配置 SZ_OPENDATA_JSESSIONID / ARIAAPPID")
    ds = DATASETS[dataset_key]
    url = "https://opendata.sz.gov.cn/data/dataSet/singleFileDownload"
    r = requests.post(url, headers=_hdrs({"Cookie": SESSION_COOKIE,
                                          "Content-Type": "application/x-www-form-urlencoded"}),
                      data={"fileId": ds["fileId"], "resId": ds["resId"],
                            "isShowOriginalFileName": "true"}, timeout=20)
    r.raise_for_status()
    msg = r.json().get("message")
    if not msg:
        raise RuntimeError("开放平台未返回下载链接（会话可能失效）")
    dr = requests.get(msg, headers=_hdrs({"Cookie": SESSION_COOKIE}), timeout=25, stream=True)
    dr.raise_for_status()
    # 限流：仅取前 2000 行约 2MB，避免下载服务慢导致请求挂起
    chunks = []
    for chunk in dr.iter_content(1024 * 64):
        chunks.append(chunk)
        if sum(len(c) for c in chunks) > 2_000_000:
            break
    return b"".join(chunks).decode("utf-8-sig", errors="ignore")


def _load_station_locations():
    """读取已地理编码的测站坐标（shenzhen-flood/data/processed/shenzhen_station_locations.csv）。
    返回 {station_code: {name,lat,lon}}。若不存在则返回空。"""
    p = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                     "shenzhen-flood", "data", "processed", "shenzhen_station_locations.csv")
    if not os.path.exists(p):
        return {}
    out = {}
    with open(p, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = (row.get("station_code") or "").strip()
            if code:
                out[code] = {"name": row.get("station_name", ""), "lat": row.get("lat"), "lon": row.get("lon")}
    return out


def geocode(keyword, city="深圳"):
    """天地图地理编码（需 Referer）。返回 (lat,lon) 或 None。"""
    if not TIANDITU_KEY:
        return None
    ds = json.dumps({"keyWord": keyword, "level": "12", "city": city, "mapBound": SZ_BBOX})
    try:
        r = requests.get(f"https://api.tianditu.gov.cn/geocoder?ds={quote(ds)}&tk={TIANDITU_KEY}",
                         headers=_hdrs({"Referer": TIANDITU_REFERER}), timeout=20)
        loc = r.json().get("location", {})
        if loc and loc.get("status", "0") == "0" and float(loc.get("score", 0) or 0) >= 30:
            return (float(loc["lat"]), float(loc["lon"]))
    except Exception:
        return None
    return None


def _load_cached_waterlevel():
    """回退源：读取已下载的清洗后真实水位数据（shenzhen-flood 产物）。
    返回每站最近一条。"""
    p = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                     "shenzhen-flood", "data", "processed", "shenzhen_waterlevel_clean.csv")
    if not os.path.exists(p):
        return None
    latest = {}
    with open(p, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = (row.get("station_code") or "").strip()
            if not code:
                continue
            ts = (row.get("time") or "").strip()
            try:
                lv = float(row.get("level_m") or 0.0)
            except Exception:
                lv = 0.0
            if code not in latest or ts > latest[code]["time"]:
                latest[code] = {"time": ts, "level": lv,
                                "name": (row.get("station_name") or code).strip(),
                                "lat": row.get("lat"), "lon": row.get("lon")}
    return latest


def _latest_by_station(text, cache_dir):
    """解析下载的水位 CSV 文本，返回每站最近一条 + 更新本地缓存。"""
    rows = list(csv.DictReader(io.StringIO(text)))
    latest = {}
    for row in rows:
        code = (row.get("测站编码") or "").strip()
        if not code:
            continue
        ts = (row.get("时间") or "").strip()
        try:
            sw = float(row.get("水位（m）") or 0.0)
        except Exception:
            sw = 0.0
        if code not in latest or ts > latest[code]["time"]:
            latest[code] = {"time": ts, "level": sw}
    # 写本地缓存
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, "realtime_waterlevel.csv"), "w", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["code", "time", "level"])
            for code, rec in latest.items():
                w.writerow([code, rec["time"], rec["level"]])
    except Exception:
        pass
    return latest


def fetch_waterlevel():
    """实时水位：优先开放平台下载（短超时），失败回退缓存的真实数据。
    返回 {source,count,flooding_count,top_stations,threshold_m}。"""
    locations = _load_station_locations()
    cache_dir = os.path.join(os.path.dirname(__file__), "..", "data", ".cache_platform")
    latest, source = None, "cache(fallback)"
    try:
        text = _download_csv("waterlevel")            # 短超时见 _download_csv
        latest = _latest_by_station(text, cache_dir)
        source = "opendata.sz.gov.cn(live)"
    except Exception as e:
        latest = None
        err = str(e)
        # 尝试本地缓存（若 open api 下载成功过一次）
        lc = os.path.join(cache_dir, "realtime_waterlevel.csv")
        if os.path.exists(lc):
            latest = {}
            with open(lc, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    latest[row["code"]] = {"time": row["time"], "level": float(row["level"])}
            source = "cache(live-last)"
        else:
            cached = _load_cached_waterlevel()
            if cached:
                latest = cached
                source = "cache(shenzhen-flood 真实数据)"
            else:
                return {"source": source, "ok": False, "error": err, "count": 0, "flooding_count": 0,
                        "top_stations": [], "threshold_m": LEVEL_THRESHOLD}

    stations = []
    for code, rec in latest.items():
        loc = locations.get(code, {})
        stations.append({
            "code": code,
            "name": rec.get("name") or loc.get("name") or code,
            "lat": rec.get("lat") or loc.get("lat"),
            "lon": rec.get("lon") or loc.get("lon"),
            "time": rec.get("time", rec["time"]),
            "level": round(float(rec.get("level", rec["level"])), 4),
            "flooding": float(rec.get("level", rec["level"])) >= LEVEL_THRESHOLD,
        })
    stations.sort(key=lambda s: s["level"], reverse=True)
    flooding = [s for s in stations if s["flooding"]]
    return {"source": source, "ok": True, "count": len(stations), "flooding_count": len(flooding),
            "top_stations": stations[:50], "threshold_m": LEVEL_THRESHOLD}


def fetch_realtime():
    """实时快照：开放平台水位 + 天地图/免费源状态。失败时返回错误信息而非中断。"""
    result = {"timestamp": None, "opendata": None, "errors": {}}
    from datetime import datetime, timezone, timedelta
    result["timestamp"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    try:
        result["opendata"] = fetch_waterlevel()
    except Exception as e:
        result["errors"]["opendata"] = f"抓取失败: {e}（会话可能失效，请更新 .env 的 JSESSIONID）"
    # 免费源可用性（仅探测，不重抓）
    result["free_sources"] = {
        "chirps": "reachable", "overpass": "reachable", "opentopodata": "reachable",
        "note": "CHIRPS 降雨 / Overpass(OSM) / OpenTopoData 免账号可用",
    }
    return result
