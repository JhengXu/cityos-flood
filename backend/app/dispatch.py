# -*- coding: utf-8 -*-
"""
ACT 闭环：泵站调度模型 + 处置建议 + 预警推送
---------------------------------------------------------------
- 各行政区泵站/排涝能力（代表性估算，应替换为水务部门真实泵站台账）
- 基于推演得到的峰值风险，生成分级处置建议（预置泵车、开泵、封路、推送）
- push_alert：写入本地日志 / 可选 POST 到 ALERT_WEBHOOK（对接短信、APP、大屏等真实通道）
"""
import os
import json
from collections import deque
import threading
import urllib.request

from .risk import RISK_LEVELS

ALERT_LOG = "/tmp/cityos_alerts.log"
ALERT_LOG_MAX_BYTES = 5 * 1024 * 1024
_ALERT_LOG_LOCK = threading.Lock()

# 各区排涝能力（代表性估算：泵站规模等级 1-5 + 等效排涝能力 m³/s 量级）
PUMP = {
    "futian":   {"level": 4, "capacity": 320, "depots": ["滨河", "下沙", "梅林"]},
    "luohu":    {"level": 4, "capacity": 300, "depots": ["罗雨", "布心", "笋岗"]},
    "nanshan":  {"level": 4, "capacity": 340, "depots": ["后海", "前海", "蛇口"]},
    "baoan":    {"level": 5, "capacity": 520, "depots": ["福永", "沙井", "松岗", "西乡"]},
    "longgang": {"level": 3, "capacity": 260, "depots": ["中心城", "布吉", "坂田"]},
    "yantian":  {"level": 3, "capacity": 180, "depots": ["盐田港", "沙头角"]},
    "longhua":  {"level": 3, "capacity": 230, "depots": ["观澜", "民治"]},
    "pingshan": {"level": 2, "capacity": 150, "depots": ["坪山", "坑梓"]},
    "guangming": {"level": 3, "capacity": 200, "depots": ["公明", "光明"]},
    "dapeng":   {"level": 2, "capacity": 120, "depots": ["葵涌", "南澳"]},
}


def recommend(district_id, peak_level, peak_prob, tide_high=False):
    p = PUMP.get(district_id, {"level": 3, "capacity": 200, "depots": ["中心"]})
    lv = peak_level
    actions = []
    if lv >= 1:
        actions.append(f"排涝单元待命（泵站等级 {p['level']}，等效能力约 {p['capacity']} m³/s）")
    if lv >= 2:
        actions.append(f"预置移动泵车 {max(2, p['level'] * 2)} 台至 {('、'.join(p['depots'][:2]))} 等易涝点")
    if lv >= 3:
        actions.append(f"开启泵站至 {min(100, 60 + lv * 10)}% 负荷，加密巡查管网溢流")
        actions.append("对低洼路段实施交通管制/封闭，联动交警与街道")
    if lv >= 4:
        actions.append("启动应急排涝预案，请求跨区泵车支援，开放就近避险场所")
        actions.append("向重点片区居民推送停课停工/绕行指引")
    if tide_high:
        actions.append("潮位偏高：关闭沿河/沿海闸门，防范潮水顶托倒灌")
    return actions


def generate_alerts(district_results, times):
    """district_results: list of {id,name,peak_level,peak_prob,peak_index,tide_high}"""
    alerts = []
    for r in district_results:
        if r["peak_level"] >= 3:
            actions = recommend(r["id"], r["peak_level"], r["peak_prob"], r.get("tide_high"))
            alerts.append({
                "severity": r["peak_level"],
                "severity_label": RISK_LEVELS[r["peak_level"]],
                "district": r["name"],
                "district_id": r["id"],
                "time": times[r["peak_index"]] if 0 <= r["peak_index"] < len(times) else None,
                "prob": round(r["peak_prob"], 3),
                "channels": ["APP推送", "短信", "应急大屏", "网格员"],
                "actions": actions,
                "message": (
                    f"{r['name']} 推演峰值内涝风险【{RISK_LEVELS[r['peak_level']]}】"
                    f"（代表性水深≥0.15m 的集合概率 {r['peak_prob']*100:.0f}%"
                    + (f"，P50深度 {r['peak_depth_m']:.2f}m" if r.get("peak_depth_m") is not None else "")
                    + "），建议启动分级处置。"
                ),
            })
    alerts.sort(key=lambda a: a["severity"], reverse=True)
    return alerts


def push_alert(alert):
    """写入本地日志；若设置 ALERT_WEBHOOK 则 POST（对接真实短信/APP/大屏通道）。"""
    line = json.dumps(alert, ensure_ascii=False)
    encoded_size = len((line + "\n").encode("utf-8"))
    try:
        with _ALERT_LOG_LOCK:
            current_size = os.path.getsize(ALERT_LOG) if os.path.exists(ALERT_LOG) else 0
            if (
                current_size > 0
                and current_size + encoded_size > ALERT_LOG_MAX_BYTES
            ):
                os.replace(ALERT_LOG, f"{ALERT_LOG}.1")
            with open(ALERT_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass
    wh = os.environ.get("ALERT_WEBHOOK")
    if wh:
        try:
            req = urllib.request.Request(
                wh, data=json.dumps(alert).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            return "pushed+webhook"
        except Exception:
            return "logged-only(webhook-failed)"
    return "logged"


def get_pushed_alerts(limit=50):
    count = int(limit)
    if count < 1 or count > 200:
        raise ValueError("limit must be between 1 and 200")
    recent = deque(maxlen=count)
    try:
        with _ALERT_LOG_LOCK:
            for path in (f"{ALERT_LOG}.1", ALERT_LOG):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                recent.append(json.loads(line))
                            except (TypeError, ValueError):
                                continue
                except FileNotFoundError:
                    continue
        return list(recent)
    except OSError:
        return []
