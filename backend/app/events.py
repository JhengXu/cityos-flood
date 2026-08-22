# -*- coding: utf-8 -*-
"""
深圳真实历史内涝事件知识库（公开报道，附出处）
-----------------------------------------------------------
用途：
  1) 由受影响行政区聚合，得到「历史内涝易发指数」(history_flood_index) —— 比纯估算更可信
  2) 作为序列模型 / What-if 推演的「真实情景参考」
  3) 暴露给前端做事件时间线

说明：以下事件为公开新闻报道的真实极端降雨/内涝过程；强度为基于报道的量级估算，
用于模型标定与演示，正式比赛应替换为水务/应急部门的权威积水点台账与逐次过程记录。
"""
HISTORICAL_EVENTS = [
    {
        "date": "2018-09-16",
        "name": "台风“山竹”(Mangkhut)",
        "affected": ["yantian", "dapeng", "baoan", "nanshan", "longhua"],
        "peak_intensity_mm_h": 70,
        "note": "强台风登陆粤港澳，沿海风暴潮+特大暴雨，盐田/大鹏/宝安沿海严重积水。",
        "source": "深圳市气象局/深圳特区报公开报道",
    },
    {
        "date": "2023-09-07",
        "name": "“9·7”极端特大暴雨",
        "affected": ["luohu", "futian", "nanshan", "baoan", "longhua", "yantian"],
        "peak_intensity_mm_h": 85,
        "note": "深圳历史罕见极端暴雨，多区出现严重城市内涝、地铁站倒灌、全市停课停工。",
        "source": "深圳市应急管理局/气象局通报",
    },
    {
        "date": "2024-04-23",
        "name": "2024年4月极端强对流暴雨",
        "affected": ["baoan", "guangming", "longhua", "futian"],
        "peak_intensity_mm_h": 55,
        "note": "短历时强降雨，西部宝安、光明等地出现道路积水与交通中断。",
        "source": "深圳气象局过程回顾",
    },
    {
        "date": "2024-05-04",
        "name": "2024年5月初强降雨（实测）",
        "affected": [],
        "peak_intensity_mm_h": 38.7,
        "note": "实测降雨峰值 38.7mm/h（南山，2024-05-04），05-05 仍有 ~14mm/h 后续降雨。"
                "无权威“受影响区”清单，故标签由真实降雨超额决定，不编造受影响区。",
        "source": "shenzhen_p0_data 01_rainfall/api/20240503-06（自动站实测）",
    },
    {
        "date": "2024-08-19",
        "name": "台风“马力斯”外围暴雨",
        "affected": ["yantian", "dapeng", "baoan", "nanshan"],
        "peak_intensity_mm_h": 48,
        "note": "台风外围环流带来持续降雨，滨海与低洼片区积水风险升高。",
        "source": "深圳气象局台风快报",
    },
    {
        "date": "2014-03-30",
        "name": "2014年“3·30”特大暴雨",
        "affected": ["luohu", "futian", "baoan", "longgang"],
        "peak_intensity_mm_h": 60,
        "note": "深圳建市以来最强短时降雨之一，罗湖、福田老城区严重内涝。",
        "source": "深圳水务局历史资料",
    },
]


def historical_index():
    """由真实事件受影响频次聚合 -> 归一化(0-1)历史内涝易发指数。"""
    from .shenzhen import DISTRICTS

    counts = {d["id"]: 0 for d in DISTRICTS}
    for ev in HISTORICAL_EVENTS:
        for did in ev["affected"]:
            if did in counts:
                counts[did] += 1
    mx = max(counts.values()) or 1
    # 平滑：min 0.15 避免完全为0
    return {k: round(0.15 + 0.8 * (v / mx), 3) for k, v in counts.items()}


def load_real_labels(path=None):
    """
    接入真实标注数据（水务/应急部门的积水点台账，CSV）。
    列建议：date,district_id,rainfall_mm_h,flooded(0/1 或等级)。
    若存在则返回 DataFrame 风格的列表；不存在返回 None（走合成训练）。
    """
    import csv
    import os

    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "flood_labels.csv")
    if not os.path.exists(path):
        return None
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows
