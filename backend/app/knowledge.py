# -*- coding: utf-8 -*-
"""CITY OS · 沉淀知识库 — 真实数据驱动的案例沉淀 + 城安助手 RAG 问答。

参照 cityos-command-workbench 的「沉淀知识库」设计，但内容全部来自本项目
真实数据层（shenzhen-flood/data/unified）与已训练监督模型的可复现推理：

- 案例沉淀：6 个真实事件（山竹/苏拉/9·7暴雨/天鸽/艾云尼/6·18河流洪水）
  每个案例 = 当时已知（真实观测）+ 关键未知项 + 模型复盘（ML 概率时间线）
- 城市底座：人口/建筑/地形/暴露统计（100m 栅格真实计算）
- 城安助手：本地案例检索（BM25）→ 构建带引用的上下文 → LLM 生成结构化回答；
  LLM 不可达时自动回退到规则化本地回答，保证服务可用。
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from datetime import datetime

# ---------------------------------------------------------------------------
# 数据路径
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_UNIFIED = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "shenzhen-flood", "data", "unified"))
_ML_FEATURES = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "shenzhen-flood", "data", "ml_features"))
_ML_MODELS = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "shenzhen-flood", "data", "ml_models"))


def _unified(name: str) -> str:
    return os.path.join(_UNIFIED, name)


# ---------------------------------------------------------------------------
# 知识库版本
# ---------------------------------------------------------------------------
KB_VERSION = "kb-2026-08-28-v1"
GENERATED_AT = "2026-08-28"


# ---------------------------------------------------------------------------
# LLM 配置（OpenAI 兼容接口；从主项目 .env 读取，缺省安全回退）
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.normpath(os.path.join(_HERE, "..", "..", ".env"))


def _load_env():
    values = {}
    try:
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    values[k.strip()] = v.strip()
    except OSError:
        pass
    return values


_ENV = _load_env()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL") or _ENV.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or _ENV.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL") or _ENV.get("LLM_MODEL", "deepseek-v4-flash-vision-exp")
LLM_TIMEOUT_S = 60

# RAG 语义检索配置（Embedding 召回 + Rerank 精排；缺省回退 BM25 关键词检索）
EMBED_API_BASE = os.environ.get("EMBED_API_BASE") or _ENV.get("EMBED_API_BASE", "")
EMBED_API_KEY = os.environ.get("EMBED_API_KEY") or _ENV.get("EMBED_API_KEY", "")
EMBED_MODEL = os.environ.get("EMBED_MODEL") or _ENV.get("EMBED_MODEL", "Qwen3-Embedding-8B")
RERANK_MODEL = os.environ.get("RERANK_MODEL") or _ENV.get("RERANK_MODEL", "bge-reranker-v2-m3")
RAG_TIMEOUT_S = 25


def llm_status():
    """城安助手智能服务状态（供前端展示连接状态）。"""
    return {
        "configured": bool(LLM_BASE_URL and LLM_API_KEY),
        "model": LLM_MODEL if (LLM_BASE_URL and LLM_API_KEY) else "",
        "endpoint": LLM_BASE_URL,
        "mode": "llm-rag" if (LLM_BASE_URL and LLM_API_KEY) else "local-rules",
        "retrieval": {
            "semantic": bool(EMBED_API_BASE and EMBED_API_KEY),
            "embed_model": EMBED_MODEL if (EMBED_API_BASE and EMBED_API_KEY) else "",
            "rerank_model": RERANK_MODEL if (EMBED_API_BASE and EMBED_API_KEY) else "",
            "fallback": "bm25",
        },
    }


def _llm_chat(system_prompt: str, user_prompt: str, max_tokens: int = 1200) -> str:
    """调用 OpenAI 兼容 /chat/completions；失败抛异常由上层回退。"""
    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    })
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"] or ""


# ---------------------------------------------------------------------------
# RAG 语义检索：Qwen3-Embedding-8B 召回 + bge-reranker-v2-m3 精排
# ---------------------------------------------------------------------------
_EMBED_CACHE: dict = {}  # 文本 hash → 向量（进程内缓存，案例库是静态的）


def _embed(texts):
    """批量文本 → 向量（OpenAI 兼容 /embeddings）。失败返回 None。"""
    if not (EMBED_API_BASE and EMBED_API_KEY):
        return None
    need = [t for t in texts if t not in _EMBED_CACHE]
    if need:
        try:
            url = f"{EMBED_API_BASE.rstrip('/')}/embeddings"
            body = json.dumps({"model": EMBED_MODEL, "input": need}).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="POST", headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {EMBED_API_KEY}",
            })
            with urllib.request.urlopen(req, timeout=RAG_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for item, text in zip(data["data"], need):
                _EMBED_CACHE[text] = item["embedding"]
        except Exception:
            return None
    return [_EMBED_CACHE.get(t) for t in texts]


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _rerank(query, docs, top_n=None):
    """bge-reranker 精排：返回 [(index, score)] 按分数降序。失败返回 None。"""
    if not (EMBED_API_BASE and EMBED_API_KEY) or not docs:
        return None
    try:
        url = f"{EMBED_API_BASE.rstrip('/')}/rerank"
        body = json.dumps({
            "model": RERANK_MODEL,
            "query": query,
            "documents": docs,
            "top_n": top_n or len(docs),
            "return_documents": False,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {EMBED_API_KEY}",
        })
        with urllib.request.urlopen(req, timeout=RAG_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [(r["index"], float(r["relevance_score"])) for r in data["results"]]
    except Exception:
        return None


def _case_search_text(case):
    """案例的检索表示文本（embedding / rerank 输入）。"""
    daily = "；".join(f"{d['date']} 概率{d['prob']*100:.0f}% {d['note']}" for d in case["replay"].get("daily", []))
    metrics = "；".join(f"{k}={v}" for k, v in case["metrics"].items())
    return (
        f"{case['title']}（{case['occurred_at']}，{case['location']}）。"
        f"当时已知：{case['facts']} 关键未知：{case['unknowns']} "
        f"模型回放：{case['replay']['summary']} {daily}。"
        f"指标：{metrics}。经验：{case['lesson']}"
    )


def _event_search_text(ev):
    """历史事件的检索表示文本。"""
    return (
        f"历史内涝事件：{ev['name']}（{ev['date']}）。"
        f"受影响区：{'、'.join(ev['affected'])}。峰值雨强约 {ev['peak_intensity_mm_h']}mm/h。"
        f"{ev['note']} 来源：{ev['source']}"
    )


def retrieve(question, top_k=3):
    """三段式检索：语义召回（全量 6 案例）→ rerank 精排 → 回退 BM25。

    返回 (hits, method)：hits=[(case, score)]，method='semantic'|'rerank'|'bm25'
    """
    # 1) 语义召回：embedding 全量相似度（案例 + 历史事件统一候选池）
    #    事件包装成"伪案例"结构以便复用下游字段
    _event_docs = [
        {"__is_event__": True, **ev} for ev in HISTORICAL_FLOOD_EVENTS
    ]
    if EMBED_API_BASE and EMBED_API_KEY:
        q_vec = _embed([question])
        if q_vec and isinstance(q_vec, list) and q_vec[0] is not None:
            cand_objs = list(CASES) + _event_docs
            texts = [
                _case_search_text(c) if not c.get("__is_event__") else _event_search_text(c)
                for c in cand_objs
            ]
            vecs = _embed(texts)
            if vecs is not None and all(v is not None for v in vecs):
                scored = [
                    (c, _cosine(q_vec[0], v))
                    for c, v in zip(cand_objs, vecs)
                ]
                # 2) rerank 精排：取语义 top_k*2 候选给 reranker
                candidates = sorted(scored, key=lambda x: -x[1])[: max(top_k * 2, 6)]
                cand_texts = [
                    _case_search_text(c) if not c.get("__is_event__") else _event_search_text(c)
                    for c, _ in candidates
                ]
                rer = _rerank(question, cand_texts, top_n=top_k)
                if rer:
                    hits = [(candidates[i][0], s) for i, s in rer if s > 0.05]
                    if hits:
                        return hits[:top_k], "rerank"
                # rerank 失败 → 用语义相似度结果（阈值 0.45：无关问题的噪声分约 0.33）
                sem = [(c, s) for c, s in candidates if s > 0.45]
                if sem:
                    return sem[:top_k], "semantic"

    # 3) BM25 关键词回退（案例 + 历史事件）
    def _bm25_text(obj):
        if obj.get("__is_event__"):
            return _event_search_text(obj)
        return " ".join([obj["title"], obj["location"], obj["facts"], obj["lesson"]])
    all_objs = list(CASES) + _event_docs
    scored = sorted(
        [(c, _score_text(_bm25_text(c), question)) for c in all_objs],
        key=lambda x: -x[1],
    )
    return [(c, s) for c, s in scored if s > 0][:top_k], "bm25"


# ---------------------------------------------------------------------------
# 事件案例（字段全部来自真实数据提取，标注来源；模型概率来自训练模型回放）
# 每个案例结构参照参考站：facts(当时已知) / unknowns(关键未知) / replay(模型复盘)
# ---------------------------------------------------------------------------
DOMAIN_META = {
    "typhoon": {"label": "台风多灾种", "color": "#E5484D", "icon": "🌀"},
    "rainstorm": {"label": "极端暴雨", "color": "#4D9DE0", "icon": "🌧️"},
    "river": {"label": "河流洪水", "color": "#2E9E8F", "icon": "🌊"},
    "landslide": {"label": "地灾预警", "color": "#C26A2E", "icon": "⛰"},
}

CASES = [
    {
        "id": "case-mangkhut-2018",
        "domain": "typhoon",
        "title": "2018 台风山竹 · 城市级多灾种复盘",
        "occurred_at": "2018-09-16",
        "location": "深圳全市（台风中心最近距 131 km，西南方向）",
        "usage": "archived",
        "facts": (
            "IBTrACS 路径 99 点：09-16 05:00 中心位于 21.4°N/113.8°E，风速 75 kt（38.6 m/s）、"
            "中心气压 960 hPa。ERA5 逐日：当日降雨 150.3 mm（2013-2026 全市第 2 位），"
            "雨强峰值 23.6 mm/h；土壤湿度 0-7cm=0.397 / 7-28cm=0.396。"
            "CMEMS 波浪再分析：大鹏湾口外海有效波高 9.51 m、珠江口 3.39 m、深圳湾 2.21 m。"
            "香港天文台潮位（CD 基准）：长洲 2.51 m、鰂魚涌 2.43 m。"
            "风暴潮参数化复算（本项目 surge 模块）：气压反效应 +0.53 m + 风堆积 +0.10 m ≈ 增水 0.63 m，"
            "叠加天文高潮位后总水位可达警戒级。"
            "官方地灾预警升级链：11:55 黄色（全市/龙岗）→ 14:20 橙色 → 18:30 红色（全市+龙岗，第 26 号）。"
        ),
        "unknowns": (
            "各区内涝实际最大积水深度与受灾点位清单未公开；"
            "预警升级的内部决策时刻与雨量阈值无官方文档；"
            "水库调度与泄洪过程未接入本项目数据层；"
            "转移安置人数与经济损失无公开口径。"
        ),
        "replay": {
            "type": "landslide_ml",
            "summary": (
                "滑坡预警模型（时间外 AUC=0.821）用当日 ERA5 特征回放：预警概率 100.0%，"
                "与官方 18:30 红色预警一致。分区链式预测（项目 cascade 参数化 + ML）："
                "福田 150mm→100%、宝安 141mm→100%、大鹏 132mm→99%、龙岗 130mm→99%。"
            ),
            "daily": [
                {"date": "2018-09-15", "prob": 0.000, "note": "台风逼近前，无预警，模型 0.0%"},
                {"date": "2018-09-16", "prob": 1.000, "note": "官方 18:30 红色预警；模型 100%"},
                {"date": "2018-09-17", "prob": 1.000, "note": "雨带滞留 36.7mm；官方续橙转黄"},
                {"date": "2018-09-18", "prob": 0.028, "note": "过程结束，官方取消"},
            ],
        },
        "metrics": {
            "rain_24h_mm": 150.3,
            "rain_max_h_mm": 23.6,
            "sm1": 0.397,
            "wind_kt": 75,
            "pres_hpa": 960,
            "wave_peak_m": {"大鹏湾口外海": 9.51, "珠江口": 3.39, "深圳湾": 2.21},
            "tide_peak_m": {"长洲": 2.51, "鰂魚涌": 2.43},
            "model_prob": 1.0,
            "official_level": "红色",
        },
        "sources": ["IBTrACS 台风路径", "ERA5-Land 逐日特征", "CMEMS WAVERYS 波浪再分析", "香港天文台潮位", "深圳市规自局+气象局官方预警（905 条档案）"],
        "lesson": (
            "台风多灾种链式传导的典型案例：路径 → 降雨（150mm/日）→ 土壤饱和（0.397）→ 滑坡红色预警，"
            "同时波浪（9.5m）与潮位（2.5m）叠加形成沿海复合灾害。"
            "本项目链式模型在仅用路径与 ERA5 特征的情况下完整复现了官方预警升级链。"
        ),
    },
    {
        "id": "case-saola-2023",
        "domain": "typhoon",
        "title": "2023 台风苏拉 · 近距离掠过与分区预警",
        "occurred_at": "2023-09-01",
        "location": "深圳全市（台风中心最近距约 61 km）",
        "usage": "archived",
        "facts": (
            "IBTrACS 路径 215 点：09-01 14:00 中心位于 22.0°N/114.1°E（距市中心约 61 km），"
            "路径点风速最高 105 kt / 920 hPa（9/1 12:00 实测 85 kt / 950 hPa）。"
            "ERA5：09-01 降雨 47.0 mm、土壤湿度 0.389。"
            "CMEMS 波浪：大鹏湾 3.68 m、珠江口 1.63 m。潮位：长洲 2.63 m / 鰂魚涌 2.56 m（三年事件中最高）。"
            "官方预警序列：09-01 黄色（全市）→ 09-02 橙色（罗湖、福田）→ 09-03 黄色，09-04 解除。"
        ),
        "unknowns": (
            "苏拉路径在深港近岸的精细转向机制（气象内部会商资料未公开）；"
            "罗湖/福田橙色预警但当日分区雨量观测未接入；"
            "波浪对东部口岸与海上设施的影响无公开评估。"
        ),
        "replay": {
            "type": "landslide_ml",
            "summary": (
                "模型回放：09-01 概率 97.5%、09-02 82.2%、09-03 84.7%，09-04 骤降至 0.2%——"
                "完整复现官方「发布-维持-解除」节奏。潮位峰值 2.63m 为四个事件最高，"
                "但降雨（47mm/日）远小于山竹，属「风潮主导、雨害次之」的复合类型。"
            ),
            "daily": [
                {"date": "2023-09-01", "prob": 0.975, "note": "官方黄色；模型 97.5%"},
                {"date": "2023-09-02", "prob": 0.822, "note": "官方橙色（罗湖/福田）；模型 82.2%"},
                {"date": "2023-09-03", "prob": 0.847, "note": "官方维持黄色；模型 84.7%"},
                {"date": "2023-09-04", "prob": 0.002, "note": "官方解除；模型 0.2%"},
            ],
        },
        "metrics": {
            "rain_24h_mm": 47.0,
            "sm1": 0.389,
            "wind_kt": 85,
            "pres_hpa": 950,
            "wave_peak_m": {"大鹏湾口外海": 3.68, "珠江口": 1.63, "深圳湾": 1.02},
            "tide_peak_m": {"长洲": 2.63, "鰂魚涌": 2.56},
            "model_prob": 0.975,
            "official_level": "橙色",
        },
        "sources": ["IBTrACS 台风路径", "ERA5-Land 逐日特征", "CMEMS WAVERYS 波浪再分析", "香港天文台潮位", "深圳市规自局+气象局官方预警"],
        "lesson": (
            "近距离掠过的台风不必然带来强降雨：苏拉风潮显著（潮位 2.63m 最高）而雨量中等。"
            "模型能正确把「雨害」与「风潮」分离——降雨驱动的滑坡概率仅由降雨-土壤决定。"
            "复合灾害评估必须分灾种独立建模再耦合，不能用单一台风强度代理。"
        ),
    },
    {
        "id": "case-rain-0907-2023",
        "domain": "rainstorm",
        "title": "2023 9·7 极端暴雨 · 无台风背景的城市内涝",
        "occurred_at": "2023-09-07",
        "location": "深圳全市（罗湖/福田受灾最重）",
        "usage": "demo-active",
        "facts": (
            "无台风直接登陆背景的季风极端降雨。CHIRPS-2.0 卫星估计：09-07 全市均值 96.6 mm、"
            "网格最大 146.0 mm；09-08 均值 42.6 mm。ERA5：09-07 46.3 mm → 09-08 132.6 mm，"
            "168h 累积 237.8 mm；土壤湿度 0.422（四事件最高）。"
            "CMEMS 波浪仅 1.43 m（无风潮）。官方预警：09-07 黄色+橙色（全市）→ 09-09 黄色 → 09-10 黄色（福田）。"
        ),
        "unknowns": (
            "逐时分区雨量站原始观测未公开（仅有卫星与再分析两种网格口径）；"
            "罗湖/福田实际内涝淹没范围与深度无官方逐点数据；"
            "地铁与下穿隧道进水过程的工程复盘报告未公开。"
        ),
        "replay": {
            "type": "landslide_ml",
            "summary": (
                "模型回放：09-06 仅 0.1% → 09-07 96.1%（官方当日发黄+橙）→ 09-08 100% → 09-09 99.4%。"
                "关键机制：168h 前期累积 152.3mm 已使土壤接近饱和（sm1 0.422），"
                "暴雨当日触发概率跃升。CHIRPS（146mm 峰值）与 ERA5（46mm 均值）口径差异 3 倍，"
                "提示内涝复盘必须用多源降雨交叉验证。"
            ),
            "daily": [
                {"date": "2023-09-06", "prob": 0.001, "note": "前日累积已高但当日无雨；模型 0.1%"},
                {"date": "2023-09-07", "prob": 0.961, "note": "官方黄+橙；模型 96.1%"},
                {"date": "2023-09-08", "prob": 1.000, "note": "暴雨持续 132.6mm；模型 100%"},
                {"date": "2023-09-09", "prob": 0.994, "note": "官方维持黄色；模型 99.4%"},
            ],
        },
        "metrics": {
            "rain_24h_mm": 46.3,
            "rain_24h_next_mm": 132.6,
            "rain_168h_mm": 237.8,
            "sm1": 0.422,
            "wave_peak_m": {"大鹏湾口外海": 1.43},
            "model_prob": 0.961,
            "official_level": "橙色",
        },
        "sources": ["CHIRPS-2.0 卫星降雨", "ERA5-Land 逐日特征", "深圳市规自局+气象局官方预警"],
        "lesson": (
            "城市内涝最危险的形态之一：无台风预警背景的季风暴雨，公众警觉性低。"
            "模型显示 168h 前期降雨（152mm）是关键前兆——单日雨量不足以触发，"
            "土壤湿度 0.422 是四年最高。本项目守恒状态空间模型用前期土壤条件作为状态变量，"
            "正是对这类事件的建模响应。"
        ),
    },
    {
        "id": "case-hato-2017",
        "domain": "typhoon",
        "title": "2017 台风天鸽 · 风大于雨的「无滑坡预警」事件",
        "occurred_at": "2017-08-23",
        "location": "深圳全市（台风中心最近距约 82 km）",
        "usage": "archived",
        "facts": (
            "IBTrACS 路径：08-23 03:00 中心 21.9°N/113.7°E（距市中心约 82 km），风速 75 kt / 965 hPa。"
            "ERA5 当日降雨仅 64.2 mm、土壤湿度 0.372（偏低）。"
            "CMEMS 波浪：大鹏湾 5.31 m。官方地灾预警档案：8/23-26 无任何滑坡预警发布；"
            "8/27 起后续季风降雨（50.9/38.0 mm）才触发龙岗/宝安黄色与橙色预警。"
        ),
        "unknowns": (
            "8/23 当日各区阵风与瞬时雨强的地面观测未获取；"
            "8/27-28 后续降雨过程与天鸽残留环流的关联性未做归因分析；"
            "官方未发布滑坡预警的内部判据无文档。"
        ),
        "replay": {
            "type": "landslide_ml",
            "summary": (
                "模型回放给出教科书级对照：8/23 当日概率仅 1.2%（官方同样未发预警——风大但雨不够）；"
                "8/27 概率 97.2%（官方发黄色）、8/28 概率 98.9%（官方升橙色）。"
                "模型不仅复现「不发」，也复现了「何时开始发」。"
            ),
            "daily": [
                {"date": "2017-08-22", "prob": 0.007, "note": "台风来临前；模型 0.7%"},
                {"date": "2017-08-23", "prob": 0.012, "note": "天鸽过境，官方无滑坡预警；模型 1.2% ✓"},
                {"date": "2017-08-27", "prob": 0.972, "note": "后续季风降雨 50.9mm；官方黄色 ✓"},
                {"date": "2017-08-28", "prob": 0.989, "note": "持续 38.0mm；官方橙色（宝安/龙岗）✓"},
            ],
        },
        "metrics": {
            "rain_24h_mm": 64.2,
            "sm1": 0.372,
            "wind_kt": 75,
            "pres_hpa": 965,
            "wave_peak_m": {"大鹏湾口外海": 5.31},
            "model_prob": 0.012,
            "official_level": "无",
        },
        "sources": ["IBTrACS 台风路径", "ERA5-Land 逐日特征", "CMEMS WAVERYS 波浪再分析", "深圳市规自局+气象局官方预警"],
        "lesson": (
            "「不报警」与「报警」同样是模型的考题：天鸽风大（75kt）但降雨 64mm、土壤偏干（0.372），"
            "官方未发滑坡预警，模型 1.2% 正确复现。对比山竹（同 75kt 但雨 150mm/土壤 0.397 → 100%/红色），"
            "说明滑坡预警的真实驱动是降雨-土壤组合而非台风强度本身——"
            "这正是链式预测不能跳过降雨环节的直接证据。"
        ),
    },
    {
        "id": "case-ewiniar-2018",
        "domain": "landslide",
        "title": "2018-06 艾云尼 vs 6·13 大雨 · 前期条件的决定性对照实验",
        "occurred_at": "2018-06-06",
        "location": "宝安 / 龙岗 / 坪山（分区预警）",
        "usage": "archived",
        "facts": (
            "6 月上旬台风艾云尼两次登陆广东：6/6-6/9 连续发布地灾预警（宝安/龙岗/坪山黄色，龙岗橙色）。"
            "ERA5：6/6-6/8 降雨 33.0/35.8/99.4 mm，72h 累积 168.1 mm、168h 累积 203.6 mm，土壤湿度持续 0.41-0.43。"
            "对照：6/13 出现 2013-2026 全市最大单日降雨 156.6 mm（雨强 37.0 mm/h，13 年之最），"
            "但前 5 天仅 26.8mm 前期降雨，官方档案 6/11-6/13 无任何滑坡预警。"
        ),
        "unknowns": (
            "6/13 大暴雨的落区分布（ERA5 为全市均值口径）；"
            "官方对 6/13 不发预警的判断依据无文档（可能是雨带夜间快速过境、落区在建成区）；"
            "艾云尼期间龙岗橙色预警对应的实际滑坡/塌方事件记录未公开。"
        ),
        "replay": {
            "type": "landslide_ml",
            "summary": (
                "模型把这组自然对照完整复现：预警期 6/6=99.2%、6/7=99.6%、6/8=100%、6/9=94.2%；"
                "6/13 大暴雨日仅 0.4%。特征层面：6/13 虽然单日 156.6mm 全国最强，"
                "但 rain_72h 特征（183.5mm）中 78% 来自当日自身，前期 5 天土壤未饱和路径不同。"
                "官方与模型一致认为「前期累积比单日极值更重要」。"
            ),
            "daily": [
                {"date": "2018-06-06", "prob": 0.992, "note": "官方黄色（宝安/坪山/龙岗）；模型 99.2% ✓"},
                {"date": "2018-06-07", "prob": 0.996, "note": "官方黄色→橙色（龙岗）；模型 99.6% ✓"},
                {"date": "2018-06-08", "prob": 1.000, "note": "官方黄（坪山/宝安/龙岗）；模型 100% ✓"},
                {"date": "2018-06-13", "prob": 0.004, "note": "单日 156.6mm 大雨但前期干；官方无预警；模型 0.4% ✓"},
            ],
        },
        "metrics": {
            "rain_24h_mm": 99.4,
            "rain_72h_mm": 168.1,
            "sm1": 0.429,
            "model_prob": 1.0,
            "official_level": "橙色",
            "contrast_rain_24h_mm": 156.6,
            "contrast_model_prob": 0.004,
        },
        "sources": ["ERA5-Land 逐日特征", "深圳市规自局+气象局官方预警（905 条档案）"],
        "lesson": (
            "13 年数据里唯一的「单日极值 vs 无预警」反直觉案例：6/13 雨量 156.6mm > 艾云尼任一天，"
            "但模型与官方都给出「不发」。特征重要性排序（72h 降雨 ΔAUC +0.119 > 土壤湿度 > 168h > 单日）"
            "在这个案例上得到最直接的验证。结论：滑坡预警模型必须包含前期累积特征，"
            "只看单日雨量会在这个案例上发出错误警报。"
        ),
    },
    {
        "id": "case-river-flood-20260618",
        "domain": "river",
        "title": "2026-06-18 布吉河洪水 · 预警滞后于洪峰的实战案例",
        "occurred_at": "2026-06-18",
        "location": "布吉河口（龙岗/罗湖交界）",
        "usage": "demo-active",
        "facts": (
            "深圳开放平台实测水位（3.2 万条档案）：布吉河口站 08:20 水位首破 1.5 m，"
            "13:55 达峰值 3.81 m，>2 m 持续 11 小时（10:05-21:05）。"
            "ERA5 当日降雨 44.2 mm（前日 37.0 mm）。"
            "官方地灾预警：15:00 发布全市黄色（2026 年第 15 号）——比洪峰晚 65 分钟。"
            "6 月为 2026 汛期高地灾风险月：当月官方发布黄色/橙色预警 19 次。"
        ),
        "unknowns": (
            "上游布吉河流域的分区雨量与产流过程未接入；"
            "排涝泵站启停时刻与调度规则无数据；"
            "沿岸受淹具体点位（开放平台仅 15 个 2026 内涝点，无逐场事件标注）。"
        ),
        "replay": {
            "type": "landslide_ml",
            "summary": (
                "模型回放：6/16 概率 99.9%、6/17 98.7%、6/18 97.9%——"
                "即模型在洪峰前 2 天就已给出高概率，而官方预警在洪峰之后才发布。"
                "这是「ML 前瞻量」价值最直接的量化：按 ERA5 日更口径，提前量 ≥48h。"
                "水位-预警时序：08:20 破 1.5m → 13:55 峰值 3.81m → 15:00 官方黄色。"
            ),
            "daily": [
                {"date": "2026-06-16", "prob": 0.999, "note": "模型 99.9%（提前 2 天）"},
                {"date": "2026-06-17", "prob": 0.987, "note": "雨 37mm；模型 98.7%（提前 1 天）"},
                {"date": "2026-06-18", "prob": 0.979, "note": "洪峰 13:55 (3.81m)；官方 15:00 才发黄色；模型 97.9%"},
                {"date": "2026-06-19", "prob": 0.499, "note": "退水期；模型 49.9%"},
            ],
        },
        "metrics": {
            "rain_24h_mm": 44.2,
            "river_peak_level_m": 3.81,
            "river_peak_time": "13:55",
            "warning_time": "15:00",
            "hours_above_2m": 11,
            "model_prob": 0.979,
            "official_level": "黄色",
        },
        "sources": ["深圳开放平台实测水位（7300 万条档案子集）", "ERA5-Land 逐日特征", "深圳市规自局+气象局官方预警"],
        "lesson": (
            "实测数据揭示的现实问题：官方预警发布（15:00）晚于河道洪峰（13:55）65 分钟。"
            "模型在 6/16（洪峰前 2 天）已输出 99.9% 概率。若按模型驱动预警，"
            "提前量可从 0 小时（事后）提升到 48 小时以上。"
            "这是本项目「守恒状态空间 + ML 前瞻」架构对真实调度最有价值的改进点。"
        ),
    },
]


# ---------------------------------------------------------------------------
# 历史内涝事件库（公开报道真实事件，来自 events.py）
# ---------------------------------------------------------------------------
HISTORICAL_FLOOD_EVENTS = [
    {
        "id": "ev-mangkhut-2018",
        "date": "2018-09-16",
        "name": "台风山竹(Mangkhut)",
        "affected": ["盐田", "大鹏", "宝安", "南山", "龙华"],
        "peak_intensity_mm_h": 70,
        "note": "强台风登陆粤港澳，沿海风暴潮+特大暴雨，盐田/大鹏/宝安沿海严重积水。",
        "source": "深圳市气象局/深圳特区报公开报道",
        "linked_case": "case-mangkhut-2018",
    },
    {
        "id": "ev-rain-0907-2023",
        "date": "2023-09-07",
        "name": "9·7极端特大暴雨",
        "affected": ["罗湖", "福田", "南山", "宝安", "龙华", "盐田"],
        "peak_intensity_mm_h": 85,
        "note": "深圳历史罕见极端暴雨，多区严重城市内涝、地铁站倒灌、全市停课停工。",
        "source": "深圳市应急管理局/气象局通报",
        "linked_case": "case-rain-0907-2023",
    },
    {
        "id": "ev-rain-2014-0330",
        "date": "2014-03-30",
        "name": "2014年3·30特大暴雨",
        "affected": ["罗湖", "福田", "宝安", "龙岗"],
        "peak_intensity_mm_h": 60,
        "note": "深圳建市以来最强短时降雨之一，罗湖、福田老城区严重内涝。",
        "source": "深圳水务局历史资料",
        "linked_case": None,
    },
    {
        "id": "ev-convective-2024-0423",
        "date": "2024-04-23",
        "name": "2024年4月极端强对流暴雨",
        "affected": ["宝安", "光明", "龙华", "福田"],
        "peak_intensity_mm_h": 55,
        "note": "短历时强降雨，西部宝安、光明等地出现道路积水与交通中断。",
        "source": "深圳气象局过程回顾",
        "linked_case": None,
    },
    {
        "id": "ev-malisk-2024-0819",
        "date": "2024-08-19",
        "name": "台风马力斯外围暴雨",
        "affected": ["盐田", "大鹏", "宝安", "南山"],
        "peak_intensity_mm_h": 48,
        "note": "台风外围环流持续降雨，滨海与低洼片区积水风险升高。",
        "source": "深圳气象局台风快报",
        "linked_case": None,
    },
]


def historical_events():
    """历史内涝事件库（公开报道）。"""
    return {
        "events": HISTORICAL_FLOOD_EVENTS,
        "n": len(HISTORICAL_FLOOD_EVENTS),
        "source": "events.py 真实历史事件库（公开报道口径）",
        "note": "受影响区为公开报道口径；peak_intensity_mm_h 为报道量级估算。",
    }


# ---------------------------------------------------------------------------
# 城市底座统计（真实栅格/矢量计算结果，非演示数字）
# ---------------------------------------------------------------------------
CITY_BASE = {
    "population": {
        "total_100m": 16_969_020,
        "total_1km": 11_632_139,
        "by_district_1km": {
            "宝安区": 3_064_014, "龙岗区": 2_483_015, "南山区": 1_287_308,
            "龙华区": 1_231_620, "罗湖区": 1_201_472, "福田区": 1_139_706,
            "光明区": 640_832, "坪山区": 392_957, "盐田区": 191_215,
        },
        "source": "WorldPop 100m/1km 栅格（点入多边形聚合）",
    },
    "buildings": {
        "total": 87_495,
        "above_100m": 3_947,
        "by_district_top": {
            "龙岗区": [12_033, 448], "宝安区": [7_991, 127], "南山区": [6_299, 573],
            "龙华区": [4_187, 166], "福田区": [3_364, 249], "罗湖区": [3_165, 144],
        },
        "mean_height_m": 24.4,
        "max_height_m": 599.1,
        "source": "OSM 全市建筑足迹（含高度估计）",
    },
    "terrain": {
        "dem_min_m": -19.2, "dem_max_m": 937.1,
        "below_5m_pct": 27.7, "below_10m_pct": 32.8,
        "above_100m_pct": 19.1, "above_300m_pct": 3.7,
        "slope_above_25deg_pct": 7.63, "slope_above_15deg_pct": 22.2,
        "source": "Copernicus DEM 30m",
    },
    "exposure": {
        "flood_2019_points": 206,
        "flood_2026_points": 15,
        "landslide_points": 300,
        "pop_near_flood_600m": 3_637_525,
        "pop_near_landslide_600m": 1_312_601,
        "flood_expo_top": {"福田区": 989_306, "龙岗区": 985_692, "罗湖区": 636_625, "南山区": 333_500},
        "landslide_expo_top": {"罗湖区": 345_072, "宝安区": 335_383, "龙岗区": 178_375},
        "source": "100m 人口栅格 × 官方隐患点缓冲区分析",
    },
    "landslide_points_by_district": {
        "罗湖区": 56, "坪山区": 51, "南山区": 49, "宝安区": 31, "深汕特别合作区": 30,
        "盐田区": 25, "龙华区": 15, "龙岗区": 15, "福田区": 11, "光明区": 11, "大鹏新区": 6,
    },
    "flood_points_2019_by_district": {
        "龙岗区": 57, "福田区": 32, "罗湖区": 29, "坪山区": 29, "南山区": 19,
        "宝安区": 12, "光明区": 11, "盐田区": 9, "龙华区": 5, "大鹏新区": 3,
    },
}


# ---------------------------------------------------------------------------
# 分区内涝风险画像（历史易涝点密度 + 实时预测辅助）
# ---------------------------------------------------------------------------
DISTRICT_FLOOD_RISK_PROFILE = {
    # 历史易涝点密度（2019 官方名单，每区数量）
    "futian": {"name": "福田区", "flood_points_2019": 32, "tag": "CBD 高密度", "exposure": "高"},
    "luohu": {"name": "罗湖区", "flood_points_2019": 29, "tag": "老城区", "exposure": "高"},
    "longgang": {"name": "龙岗区", "flood_points_2019": 57, "tag": "工业+新城", "exposure": "中"},
    "pingshan": {"name": "坪山区", "flood_points_2019": 29, "tag": "山地+新城", "exposure": "中"},
    "nanshan": {"name": "南山区", "flood_points_2019": 19, "tag": "高新+滨海", "exposure": "中"},
    "baoan": {"name": "宝安区", "flood_points_2019": 12, "tag": "机场+制造", "exposure": "中"},
    "yantian": {"name": "盐田区", "flood_points_2019": 9, "tag": "滨海港口", "exposure": "中"},
    "longhua": {"name": "龙华区", "flood_points_2019": 5, "tag": "居住新城", "exposure": "低"},
    "guangming": {"name": "光明区", "flood_points_2019": 11, "tag": "科学城", "exposure": "中"},
    "dapeng": {"name": "大鹏新区", "flood_points_2019": 3, "tag": "生态旅游", "exposure": "低"},
}


def district_flood_profile():
    """分区内涝风险画像（历史易涝点 + 实时 P50 预测）。"""
    live = _get_live_snapshot()
    fq = (live or {}).get("flood_quantiles") or {}
    out = []
    for did, prof in DISTRICT_FLOOD_RISK_PROFILE.items():
        q = fq.get(did, {})
        # 综合风险：历史易涝密度 + 预测峰值
        hist_score = min(prof["flood_points_2019"] / 57.0, 1.0)  # 龙岗最大
        p50 = q.get("p50_peak_mm", 0.0)
        pred_score = min(p50 / 50.0, 1.0)
        combined = round(hist_score * 0.6 + pred_score * 0.4, 3)
        level = "high" if combined >= 0.6 else ("mid" if combined >= 0.3 else "low")
        out.append({
            "district_id": did, "name": prof["name"], "tag": prof["tag"],
            "flood_points_2019": prof["flood_points_2019"],
            "exposure": prof["exposure"],
            "p50_peak_mm": p50,
            "risk_score": combined,
            "risk_level": level,
            "risk_level_label": {"high": "高风险", "mid": "中风险", "low": "低风险"}[level],
        })
    out.sort(key=lambda x: -x["risk_score"])
    return {"districts": out,
            "source": "历史=官方2019易涝名单 / 预测=集合模拟P50 / 权重=0.6+0.4",
            "note": "综合风险 = 0.6×历史易涝密度 + 0.4×实时预测P50峰值（归一化）"}


# ---------------------------------------------------------------------------
# 模型档案（三个监督模型的真实指标 + 诚实局限）
# ---------------------------------------------------------------------------
MODEL_ARCHIVE = [
    {
        "id": "landslide-warning",
        "name": "滑坡预警发布模型（v2.1）",
        "task": "预测官方是否发布地灾气象风险预警（二分类）",
        "labels": "905 条官方预警（2012-2026：黄 751 / 橙 152 / 红 2）",
        "validation": "时间外验证：2013-2022 训练 → 2023-2026 测试；嵌套时间切分（2013-20→21-22）选型",
        "test_auc": 0.821, "pr_auc": 0.672,
        "baseline_v1_auc": 0.797,
        "precision": 0.76, "recall": 0.36,
        "top_features": ["rain_72h (+0.119)", "sm1 0-7cm (+0.017)", "rain_168h (+0.016)", "rain_24h (+0.015)"],
        "limitation": "召回率 36% 偏保守（F1 阈值 0.65），漏报风险高于误报；预警档案是「发布行为」而非「实际滑坡」标签；v2 特征工程（21 维）相对 v1（11 维）提升 +2.4pp AUC 但在年度噪声边缘；样本实为 293 个独立预警日（同日各区共享城市级特征）。",
    },
    {
        "id": "flood-spatial",
        "name": "内涝空间风险模型（v2 · 12 维）",
        "task": "预测网格点是否为易涝点（二分类）",
        "labels": "206 个官方 2019 易涝路段点（天地图地理编码）+ 环境匹配负样本",
        "validation": "分层 5-fold CV + 置换重要性（v2 加 TWI/汇流/路网/人口特征）",
        "spatial_cv_auc": 0.829, "pr_auc": 0.484, "baseline_v1_cv_auc": 0.804,
        "top_features": ["dist_road_m (+0.119)", "elevation_m (+0.058)"],
        "limitation": "206 正样本偏少；「易涝点」是历史名单而非逐场事件积水真值；v2 的 TWI/汇流特征置换重要性为 0（可能被 elevation 吸收），人口密度（+0.0125）反映报告偏差。",
    },
    {
        "id": "wave-typhoon",
        "name": "台风-波浪模型",
        "task": "台风状态 → 近岸有效波高（回归）",
        "labels": "CMEMS WAVERYS 波浪再分析（卫星高度计同化）：3 台风事件 × 3 近岸点 + 1 暴雨事件",
        "validation": "Leave-One-Event-Out（按台风事件留出）",
        "fit_r2": 0.705, "fit_mae_m": 0.45, "loeo_r2": -0.265,
        "expansion_status": "CMEMS 凭据未配置，事件样本暂无法扩充",
        "limitation": "跨事件外推失败（LOEO R²=-0.265）：3 个训练事件不足以学到普适物理，仅事件内插值有效，不可用于独立台风的波高预报。需扩充事件样本。",
    },
]


# ---------------------------------------------------------------------------
# API: 案例列表 / 详情 / 底座 / 模型档案
# ---------------------------------------------------------------------------
def cases_list(domain: str = "", q: str = ""):
    """案例沉淀列表（支持领域筛选 + 关键词检索）。"""
    out = []
    for c in CASES:
        if domain and c["domain"] != domain:
            continue
        if q:
            hay = " ".join([c["title"], c["location"], c["facts"], c["lesson"]])
            if q.lower() not in hay.lower():
                continue
        meta = DOMAIN_META[c["domain"]]
        out.append({
            "id": c["id"],
            "domain": c["domain"],
            "domain_label": meta["label"],
            "domain_color": meta["color"],
            "icon": meta["icon"],
            "title": c["title"],
            "occurred_at": c["occurred_at"],
            "location": c["location"],
            "usage": c["usage"],
            "summary": c["lesson"][:60] + "…",
            "model_prob": c["metrics"].get("model_prob"),
            "official_level": c["metrics"].get("official_level", "—"),
        })
    return {
        "version": KB_VERSION,
        "total": len(out),
        "demo_active": sum(1 for c in out if c["usage"] == "demo-active"),
        "domains": [{"id": k, "label": v["label"]} for k, v in DOMAIN_META.items()],
        "cases": out,
    }


def case_detail(case_id: str):
    """单个案例完整档案（含模型回放日序列）。"""
    for c in CASES:
        if c["id"] == case_id:
            meta = DOMAIN_META[c["domain"]]
            return {
                **c,
                "domain_label": meta["label"],
                "domain_color": meta["color"],
                "icon": meta["icon"],
                "kb_version": KB_VERSION,
            }
    return None


def city_base():
    """城市底座统计。"""
    return {"version": KB_VERSION, "generated_at": GENERATED_AT, **CITY_BASE}


def model_archive():
    """三个监督模型的档案与诚实局限。"""
    return {"version": KB_VERSION, "models": MODEL_ARCHIVE}


# ---------------------------------------------------------------------------
# 城安助手：本地检索 + 规则化回答生成（不依赖外部 LLM）
# ---------------------------------------------------------------------------
_STOPWORDS = {
    # 高频通用词（在多个案例字段中大量出现，无区分度，只给很低权重）
    "什么", "哪些", "怎么", "可以", "多少", "案例", "模型", "官方", "预警",
    "概率", "降雨", "数据", "深圳", "全市", "日期", "结果", "情况", "问题",
    "说清", "区别", "差异", "不同", "之间", "如何", "之后", "以前", "以后",
}


def _score_case(case, question):
    """BM25 风格打分：问题分词命中案例字段次数，实体词（人名/台风名）加权。"""
    terms = [t for t in _tokenize(question) if len(t) >= 2]
    if not terms:
        return 0.0
    # 只保留非停用词作为有效检索词；停用词命中不计分
    content_terms = [t for t in terms if t not in _STOPWORDS]
    fields = " ".join([
        case["title"], case["location"], case["facts"], case["unknowns"],
        case["lesson"], case["replay"]["summary"],
        " ".join(str(v) for v in case["metrics"].values()),
    ])
    title = case["title"]
    score = 0.0
    for t in content_terms:
        n = fields.count(t)
        if n:
            weight = 1.0
            # 标题命中 = 该案例的核心实体词，权重加倍
            if t in title:
                weight = 3.0
            # 长词（≥3 字符的组合词）更具体，加权
            if len(t) >= 3:
                weight *= 1.5
            score += (1 + math.log(n)) * weight
    return score


def _tokenize(text):
    """中文二元切分 + 英文/数字词。"""
    terms = []
    buf = ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if buf:
                terms.append(buf)
                buf = ""
            terms.append(ch)
        elif ch.isalnum():
            buf += ch.lower()
        else:
            if buf:
                terms.append(buf)
                buf = ""
    if buf:
        terms.append(buf)
    # 二元组合
    bigrams = [terms[i] + terms[i + 1] for i in range(len(terms) - 1) if "\u4e00" <= terms[i] <= "\u9fff" and "\u4e00" <= terms[i + 1] <= "\u9fff"]
    return terms + bigrams


def _score_text(text, question):
    """通用 BM25 风格打分（任意文本）。"""
    terms = [t for t in _tokenize(question) if len(t) >= 2]
    if not terms:
        return 0.0
    content = [t for t in terms if t not in _STOPWORDS]
    score = 0.0
    for t in content:
        n = text.count(t)
        if n:
            weight = 1.0
            if len(t) >= 3:
                weight *= 1.5
            score += (1 + math.log(n)) * weight
    return score


def _needs_confirm_items(case):
    """从 unknowns 提取待确认条目（事件对象无 unknowns 字段）。"""
    if case.get("__is_event__") or not case.get("unknowns"):
        return []
    items = [s.strip().rstrip("；;。") for s in case["unknowns"].split("；") if s.strip()]
    return items


# 人口/暴露/建筑/地形相关的关键词 → 城市底座统计作答
_BASE_KEYWORDS = ["人口", "暴露", "建筑", "地形", "坡度", "高程", "隐患点", "易涝点", "底座", "栅格", "超高层"]

# 实时/当前状态类关键词 → 注入 /api/live 实时上下文
_LIVE_KEYWORDS = [
    "天气", "现在", "当前", "今天", "今日", "此刻", "目前", "实时", "下雨", "降雨",
    "气温", "温度", "风", "台风现", "活跃台风", "会不会", "未来", "预报", "预警现在",
    "风险现在", "情况怎么样", "怎么样了", "内涝现在", "积水", "深圳现在", "深圳市现在",
    "潮位", "潮汐", "涨潮", "退潮", "风暴潮", "海平面", "海况",
]


def _is_live_question(question: str) -> bool:
    """判断是否为实时状态类问题（需要注入 /api/live 数据）。"""
    return any(k in question for k in _LIVE_KEYWORDS)


_LIVE_CACHE = {"ts": 0.0, "data": None}
_LIVE_TTL = 600  # 与 live_ops 缓存对齐：10 分钟


def _get_live_snapshot():
    """获取实时预测快照（带本地缓存，避免每次问答都重算守恒模型）。"""
    import time as _time
    now = _time.time()
    if _LIVE_CACHE["data"] and now - _LIVE_CACHE["ts"] < _LIVE_TTL:
        return _LIVE_CACHE["data"]
    try:
        from . import live_ops
        data = live_ops.build_live()
    except Exception:
        data = None
    _LIVE_CACHE["ts"] = now
    _LIVE_CACHE["data"] = data
    return data


_LEVEL_NAMES = {1: "正常", 2: "关注", 3: "预警", 4: "危险"}


def _build_live_context(question: str):
    """把 /api/live 实时预测组装成 LLM 上下文块；失败返回 None。"""
    live = _get_live_snapshot()
    if not live:
        return None
    cards = live.get("cards", {})
    times = live.get("times", [])
    rain = live.get("city_rain", [])
    wind = live.get("city_wind", [])
    generated = str(live.get("generated_at", ""))[:19]

    def _fmt_card(key):
        c = cards.get(key, {})
        lvl = _LEVEL_NAMES.get(c.get("level", 1), "正常")
        extra = ""
        if key == "typhoon":
            tyn = live.get("typhoon_now")
            if tyn:
                extra = (f"，活跃台风：{tyn.get('name')}"
                         f"（风速 {tyn.get('wind_ms')} m/s，气压 {tyn.get('pres_hpa')} hPa，强度 {tyn.get('intensity')}）")
            else:
                extra = "，无活跃台风"
        if key == "flood":
            extra = f"，最不利区：{c.get('worst', '—')}"
        if key == "landslide":
            extra = f"，在册隐患点 {c.get('points')} 个"
        return (f"{c.get('name', key)}：等级「{lvl}」，{c.get('value', '—')}（{c.get('sub', '')}）{extra}")

    # 当前实况 + 未来 24h（从"现在"起算，含已过去 6h 作背景）
    cur = live.get("current") or {}
    nxt = live.get("next_24h") or {}
    now_idx = live.get("now_idx", 0)
    cur_rain = cur.get("precipitation_mm")
    cur_rain_txt = f"{cur_rain:.1f} mm/h" if cur_rain is not None else "未知"
    cur_temp = cur.get("temperature_2m")
    cur_temp_txt = f"{cur_temp:.0f}°C" if cur_temp is not None else ""
    cur_wind = cur.get("wind_speed_10m")
    cur_wind_txt = f"{cur_wind:.1f} m/s" if cur_wind is not None else ""

    if nxt:
        # v2 修正口径：next_24h 由后端从 now_idx 起算
        rain_24 = nxt.get("rain_total_mm", 0)
        rain_24_max = nxt.get("rain_max_mm_h", 0)
        wind_24_max = nxt.get("wind_max_ms", 0)
    else:
        # 兼容旧 payload
        n24 = min(24, len(rain), len(wind), len(times))
        rain_24 = sum(x or 0 for x in rain[:n24])
        rain_24_max = max((x or 0 for x in rain[:n24]), default=0)
        wind_24_max = max((x or 0 for x in wind[:n24]), default=0)

    # 过去 6h 实况降雨（背景）
    past_rain = sum((x or 0) for x in rain[max(0, now_idx - 5): now_idx + 1])

    # 未来 3 天逐日摘要
    daily_lines = []
    for d in live.get("landslide_daily", [])[:3]:
        daily_lines.append(
            f"    {d['date']}：降雨 {d['rain_24h']} mm，滑坡预警概率 {d['warning_prob']*100:.1f}%"
        )
    # 内涝分区 TOP3
    flood_top = [
        f"{s['district_name']} {s['peak_depth_mm']} mm"
        for s in live.get("flood_summary", [])[:3]
    ]

    rain_state = "当前无降雨" if (cur_rain or 0) < 0.1 else f"当前正在降雨（{cur_rain_txt}）"

    lines = [
        f"[实时状态快照] 生成时间 {generated}（数据源 {live.get('data_source', '—')}）",
        f"当前实况（Open-Meteo 实测）：{rain_state}，气温 {cur_temp_txt}，风速 {cur_wind_txt}；过去 6 小时累计降雨 {past_rain:.1f} mm。",
        "四灾种当前等级（本项目守恒模型 + ML 实时计算，非官方发布）：",
        f"    " + _fmt_card("typhoon"),
        f"    " + _fmt_card("flood"),
        f"    " + _fmt_card("landslide"),
        f"    " + _fmt_card("surge"),
        f"未来 24 小时预报（从现在起算）：累计降雨 {rain_24:.1f} mm，最大雨强 {rain_24_max:.1f} mm/h，最大风速 {wind_24_max:.1f} m/s。",
    ]
    # D-1 提前预警（明日风险）
    adv_lines = []
    for w in (live.get("advance_warnings") or [])[:3]:
        adv_lines.append(
            f"    明日 {w.get('for_date', '?')}：预报降雨 {w.get('tomorrow_rain_mm')}mm → 滑坡预警概率 {w.get('warning_prob', 0)*100:.0f}%"
        )
    if adv_lines:
        lines.append("D-1 提前预警（今日可发布的明日风险评估）：\n" + "\n".join(adv_lines))
    lines += [
        "未来 3 天逐日（ML 滑坡预警模型预测）：",
        *daily_lines,
        f"内涝分区预测峰值 TOP3（守恒模型）：{'、'.join(flood_top) if flood_top else '无数据'}。",
    ]
    # 实时告警流（阈值触发）
    alerts = live.get("alerts") or []
    if alerts:
        al_lines = []
        sev_name = {"critical": "警示", "warning": "关注", "info": "提示"}
        for a in alerts[:6]:
            al_lines.append(f"    [{sev_name.get(a.get('severity'), '?')}] {a.get('domain')}：{a.get('title')}（{a.get('note', '')}）")
        lines.append("当前阈值告警（本项目模型判定，非官方预警）：\n" + "\n".join(al_lines))

    # 风暴潮（天文潮谐波 + 台风增水参数化）
    sg = live.get("surge")
    if sg:
        st_lines = []
        for s in sg.get("stations", []):
            pk = s.get("peak") or {}
            st_lines.append(
                f"    {s['name']}：峰值水位 {pk.get('total_m', '—')}m（天文潮 {pk.get('astro_m', '—')}m + 增水 {pk.get('surge_m', 0)}m，"
                f"峰时 {str(pk.get('t', ''))[5:16]}），预警等级「{s['alert']['name']}」")
        lines.append(
            f"风暴潮（8 分潮谐波推算 + 台风增水参数化，非官方发布）：\n" + "\n".join(st_lines)
            + f"\n    {sg.get('note', '')}"
        )
    return "\n".join(lines)


def _city_base_answer(question: str):
    """城安助手：涉及人口/建筑/地形/暴露统计时，直接用城市底座数据作答。"""
    expo = CITY_BASE["exposure"]
    pop = CITY_BASE["population"]
    bld = CITY_BASE["buildings"]
    ter = CITY_BASE["terrain"]
    parts = []
    parts.append(
        f"城市底座统计（真实栅格计算口径）：全市人口 1km 栅格合计 {pop['total_1km']:,} 人"
        f"（100m 栅格 {pop['total_100m']:,} 人）；人口前三区：宝安 {pop['by_district_1km']['宝安区']:,}、"
        f"龙岗 {pop['by_district_1km']['龙岗区']:,}、南山 {pop['by_district_1km']['南山区']:,}。"
    )
    parts.append(
        f"隐患暴露：官方 2019 易涝点 {expo['flood_2019_points']} 个（2026 新增 {expo['flood_2026_points']} 个）、"
        f"在册滑坡隐患点 {expo['landslide_points']} 个。以 600m 缓冲区计："
        f"易涝点周边人口 {expo['pop_near_flood_600m']:,} 人（福田 {expo['flood_expo_top']['福田区']:,}、"
        f"龙岗 {expo['flood_expo_top']['龙岗区']:,}、罗湖 {expo['flood_expo_top']['罗湖区']:,}）；"
        f"滑坡点周边人口 {expo['pop_near_landslide_600m']:,} 人（罗湖 {expo['landslide_expo_top']['罗湖区']:,}、"
        f"宝安 {expo['landslide_expo_top']['宝安区']:,}）。"
    )
    parts.append(
        f"建筑与地形：OSM 建筑 {bld['total']:,} 栋（100m+ 超高层 {bld['above_100m']:,} 栋，南山 573 / 龙岗 448 / 福田 249）；"
        f"Copernicus DEM 30m 高程 {ter['dem_min_m']}~{ter['dem_max_m']} m，"
        f"<5m 低洼占 {ter['below_5m_pct']}%，坡度>25°（滑坡敏感）占 {ter['slope_above_25deg_pct']}%。"
    )
    return {
        "answer": "\n\n".join(parts),
        "citations": [{
            "case_id": "city-base",
            "title": "城市底座统计（人口/建筑/地形/暴露）",
            "occurred_at": GENERATED_AT,
            "score": 0,
            "facts": expo["source"],
            "sources": [pop["source"], bld["source"], ter["source"], expo["source"]],
        }],
        "needs_confirm": [
            {"case": "城市底座", "item": "人口栅格为 WorldPop 估计值，与统计公报常住人口口径有差异"},
            {"case": "城市底座", "item": "600m 缓冲区为简化暴露口径，未做建筑层数与地下空间精细化"},
        ],
        "actions": [
            {"label": "打开城市底座页", "detail": "查看分区分级明细（人口/建筑/隐患点分布）。", "requires_approval": False},
        ],
        "kb_version": KB_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": {
            "cases_total": len(CASES),
            "matched": 1,
            "production_knowledge": 0,
            "external_retrieval": "未接入",
        },
        "disclaimer": "统计数字来自真实栅格/矢量计算（WorldPop / OSM / Copernicus DEM / 官方隐患点），非演示数据。",
    }


def _build_rag_context(hits, question):
    """把检索到的案例/事件字段组装成 LLM 上下文（带明确的事实边界声明）。"""
    blocks = []
    for rank, (c, s) in enumerate(hits, 1):
        # 历史事件文档（公开报道）
        if c.get("__is_event__"):
            blocks.append(
                f"[历史事件{rank}] {c['name']}（{c['date']}，公开报道）\n"
                f"  受影响区：{'、'.join(c['affected']) or '—'}；峰值雨强约 {c['peak_intensity_mm_h']}mm/h。\n"
                f"  事件描述：{c['note']}\n"
                f"  数据来源：{c['source']}"
            )
            continue
        daily = "\n".join(
            f"    {d['date']}: 概率 {d['prob']*100:.1f}% | {d['note']}"
            for d in c["replay"].get("daily", [])
        )
        metrics = "\n".join(f"    {k}: {v}" for k, v in c["metrics"].items())
        blocks.append(
            f"[案例{rank}] {c['title']}（{c['occurred_at']}，{c['location']}，相关度 {s:.1f}）\n"
            f"  当时已知（真实观测）：\n    {c['facts']}\n"
            f"  关键未知项：\n    {c['unknowns']}\n"
            f"  模型回放：\n    {c['replay']['summary']}\n"
            f"  模型回放日序列：\n{daily}\n"
            f"  关键指标：\n{metrics}\n"
            f"  可复用经验：\n    {c['lesson']}\n"
            f"  数据来源：{('、'.join(c['sources']))}"
        )
    return "\n\n".join(blocks)


_SYSTEM_PROMPT = """你是 CITY OS 城安助手，服务于深圳城市安全（内涝/滑坡/台风/风暴潮）指挥中心的沉淀知识库。

回答纪律（必须严格遵守）：
1. 只能依据下方提供的实时状态快照与案例条目回答，不得编造不存在的事实、数字或结论。
2. 用户问当前/实时状况时，优先使用[实时状态快照]的数据回答；快照来自 Open-Meteo 预报 + 本项目模型预测（守恒模型 + ML），不是官方发布，要如实说明这一点并给出快照生成时间。
3. 案例里的"模型概率/模型回放"是本项目训练模型对历史事件的重放结果，不是实时预报；表述时要说明这一点。
4. 条目中标注"未公开/未接入"的信息就是缺口，回答时如实列为"还需确认"，不要推测补全。
5. 引用具体数字时保留原始精度与单位（mm、kt、hPa、m、%）。
6. 回答用简体中文，直接给出结论再给依据，克制、专业、不夸张。

输出格式（普通文本，段落间用空行分隔，不要用 Markdown 标记）：
先直接回答问题（1-3 段，涉及数字对比时可用简短列点，用「·」开头）。

然后固定输出三个小节，标题必须逐字使用：
【回答要点】本回答依据了哪些数据源/案例、核心数字是什么（简短列点）
【还需确认】仍未核实的缺口（没有则写"本回答涉及的字段均已核实"）
【建议动作】1-3 条可执行的下一步（简短）"""


def ask(question: str, top_k: int = 3, history=None):
    """城安助手：实时状态注入 + 语义召回 + rerank 精排 → LLM 生成带引用回答。

    history: [{'role': 'user'|'assistant', 'content': str}, ...]（最近几轮，
    用于指代消解——"那场呢？"这类追问需要上文）。
    """
    question = (question or "").strip()
    if not question:
        return {"error": "问题不能为空"}

    # 多轮：把历史并入问题供检索（指代消解）
    search_query = question
    if history:
        # 取最近 2 轮 user 消息，拼成检索 query
        recent_user = [h["content"] for h in history if h.get("role") == "user"][-2:]
        if recent_user:
            search_query = " ".join(recent_user) + " " + question

    is_live = _is_live_question(question)
    live_ctx = _build_live_context(question) if is_live else None

    # 城市底座类问题优先走统计作答（纯数字汇总，无需 LLM）
    if any(k in question for k in _BASE_KEYWORDS):
        r = _city_base_answer(question)
        r["retrieval"] = {"method": "city-base", "label": "城市底座统计"}
        return r

    # 三段式检索（用消解后的 query）：embedding 召回 → rerank 精排 → BM25 回退
    hits, method = retrieve(search_query, top_k=top_k)
    # 实时类问题：即便案例检索弱命中也照常回答（用实时数据作答）
    if is_live and not hits:
        hits, method = [], "live"
    method_label = {
        "rerank": f"语义召回 + {RERANK_MODEL} 精排",
        "semantic": f"语义召回（{EMBED_MODEL}）",
        "bm25": "BM25 关键词",
        "live": "实时状态注入",
    }.get(method, method)
    if is_live and hits:
        method_label += " + 实时状态注入"

    # --- 引用与待确认（无论 LLM 是否可用都由本地结构化生成，保证真实可溯）---
    citations = []
    for c, s in hits:
        if c.get("__is_event__"):
            citations.append({
                "case_id": c.get("id", "event"),
                "title": f"历史事件：{c['name']}",
                "occurred_at": c["date"],
                "score": round(s, 2),
                "facts": c["note"][:120] + "…",
                "sources": [c["source"]],
            })
            continue
        citations.append({
            "case_id": c["id"],
            "title": c["title"],
            "occurred_at": c["occurred_at"],
            "score": round(s, 2),
            "facts": c["facts"][:120] + "…",
            "sources": c["sources"],
        })

    needs_confirm = []
    for c, _ in hits[:2]:
        if c.get("__is_event__"):
            needs_confirm.append({"case": c["name"], "item": "受影响区为报道口径，精确积水点位未公开"})
            continue
        for item in _needs_confirm_items(c)[:3]:
            needs_confirm.append({"case": c["title"], "item": item})

    actions = [
        {"label": "打开案例详情", "detail": "查看对应案例的完整字段与模型回放日序列。", "requires_approval": False},
        {"label": "对比官方与模型时序", "detail": "在案例详情中核对每日「模型概率 vs 官方预警等级」对齐情况。", "requires_approval": False},
        {"label": "补充缺失数据源", "detail": f"相关案例待确认项共 {sum(len(_needs_confirm_items(c)) for c, _ in hits[:2])} 条，补充后可升级为完整复盘。", "requires_approval": True},
    ]

    if not hits and not is_live:
        fallback_intro = (
            "知识库没有直接匹配的案例。知识库覆盖 6 个真实事件"
            "（山竹 2018 / 苏拉 2023 / 9·7 暴雨 2023 / 天鸽 2017 / 艾云尼 2018 / 2026-06-18 布吉河洪水）"
            "与城市底座统计（人口/建筑/地形/隐患点暴露）。"
        )
        if llm_status()["configured"]:
            try:
                ans = _llm_chat(
                    _SYSTEM_PROMPT,
                    f"用户问题：{question}\n\n检索结果：无直接匹配案例。{fallback_intro}\n"
                    "请向用户说明知识库覆盖范围，并建议可以从这些事件切入提问。输出仍遵循规定格式。",
                    max_tokens=700,
                )
                if ans.strip():
                    return _wrap_answer(ans, [], [], llm_mode="llm",
                                        retrieval={"method": method, "label": method_label})
            except Exception:
                pass
        return {
            "answer": fallback_intro + "可以问：某案例说清了什么？模型与官方预警差在哪？哪些信息还缺？",
            "citations": [], "needs_confirm": [], "actions": [],
            "kb_version": KB_VERSION,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "local",
        }

    primary = next((c for c, _ in hits if not c.get("__is_event__")), None)
    others = [c for c, _ in hits[1:] if not c.get("__is_event__")]

    # --- 尝试 LLM 生成 ---
    llm_error = None
    if llm_status()["configured"]:
        try:
            sections = []
            if live_ctx:
                sections.append(live_ctx)
            if hits:
                ctx = _build_rag_context(hits, question)
                sections.append(
                    f"知识库检索结果（按相关度排序，共 {len(hits)} 条）：\n\n{ctx}"
                )
            else:
                sections.append("知识库检索结果：无直接匹配案例（本问题以实时状态作答）。")
            history_block = ""
            if history:
                lines = []
                for h in history[-4:]:
                    role = "用户" if h.get("role") == "user" else "助手"
                    lines.append(f"{role}：{str(h.get('content', ''))[:200]}")
                history_block = "对话历史（供指代消解，回答仍以最新问题为准）：\n" + "\n".join(lines) + "\n\n"
            user_prompt = (
                f"{history_block}用户问题：{question}\n\n" + "\n\n".join(sections) +
                "\n\n请依据以上信息回答用户问题，遵循规定的输出格式。"
                + ("注意：用户问的是当前/实时状况，请优先用[实时状态快照]的数据回答，"
                   "并在回答中说明数据生成时间与来源（Open-Meteo 预报 + 本项目模型预测，非官方发布）。"
                   if is_live else "")
            )
            ans = _llm_chat(_SYSTEM_PROMPT, user_prompt)
            if ans.strip():
                return _wrap_answer(ans, citations, needs_confirm, actions, llm_mode="llm",
                                    retrieval={"method": method, "label": method_label})
        except Exception as exc:
            llm_error = f"LLM 调用失败（{type(exc).__name__}），已回退本地规则回答"
    else:
        llm_error = "LLM 未配置，使用本地规则回答"

    # --- 本地规则回退 ---
    # 实时类问题且无案例命中：直接用实时快照作答
    if is_live and live_ctx:
        return {
            "answer": live_ctx.replace("[实时状态快照]", "【实时状态快照】")
                     + "\n\n以上为本项目守恒模型与 ML 模型的实时预测（Open-Meteo 预报驱动，非官方发布）。",
            "citations": [{
                "case_id": "live-snapshot",
                "title": "实时状态快照（Open-Meteo + 守恒模型 + ML）",
                "occurred_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "score": 1.0,
                "facts": "四灾种等级 / 24h 降雨风速 / 3 日滑坡概率 / 内涝分区峰值",
                "sources": ["Open-Meteo 实时预报", "守恒状态空间模型", "滑坡预警 ML 模型（AUC=0.821）"],
            }],
            "needs_confirm": [{"case": "实时快照", "item": "风暴潮暂无实时潮位接入（历史展示）"}],
            "actions": [{"label": "查看指挥中心", "detail": "上半屏实时四灾种卡与预测曲线。", "requires_approval": False}],
            "kb_version": KB_VERSION,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "local",
            "mode_note": llm_error,
            "retrieval": {"method": "live", "label": "实时状态注入"},
        }

    # 无案例命中且非实时问题（LLM 也失败的兜底已在上方返回，此处防御）
    if primary is None:
        return {
            "answer": "知识库没有匹配的案例条目。可以问：某案例说清了什么？模型与官方预警差在哪？深圳现在的天气怎么样？",
            "citations": [], "needs_confirm": [], "actions": [],
            "kb_version": KB_VERSION,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "local",
            "retrieval": {"method": method, "label": method_label},
        }

    parts = []
    parts.append(f"「{primary['title']}」（{primary['occurred_at']}，{primary['location']}）")
    parts.append("【当时已知】" + primary["facts"])
    parts.append("【模型复盘】" + primary["replay"]["summary"])

    if len(others) > 0:
        cmp_lines = []
        for o in others[:2]:
            cmp_lines.append(f"{o['title']}（{o['occurred_at']}）：{o['lesson'][:80]}…")
        parts.append("【关联案例】" + " / ".join(cmp_lines))

    parts.append("【可复用经验】" + primary["lesson"])

    return {
        "answer": "\n\n".join(parts),
        "citations": citations,
        "needs_confirm": needs_confirm,
        "actions": actions,
        "kb_version": KB_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "local",
        "mode_note": llm_error,
        "retrieval": {"method": method, "label": method_label},
        "scope": {
            "cases_total": len(CASES),
            "matched": len(hits),
            "production_knowledge": 0,
            "external_retrieval": "未接入",
        },
        "disclaimer": "回答内容来自本地知识条目（真实观测 + 训练模型回放）；模型概率为历史回放结果，不代表实时预报。",
    }


def _wrap_answer(answer_text, citations, needs_confirm, actions=None, llm_mode="llm", retrieval=None):
    """把 LLM 输出包装为统一响应结构。"""
    if actions is None:
        actions = [
            {"label": "打开案例详情", "detail": "查看对应案例的完整字段与模型回放日序列。", "requires_approval": False},
        ]
    return {
        "answer": answer_text.strip(),
        "citations": citations,
        "needs_confirm": needs_confirm,
        "actions": actions,
        "kb_version": KB_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": llm_mode,
        "model": LLM_MODEL if llm_mode == "llm" else None,
        "retrieval": retrieval or {"method": "bm25", "label": "BM25 关键词"},
        "scope": {
            "cases_total": len(CASES),
            "matched": len(citations),
            "production_knowledge": 0,
            "external_retrieval": "未接入",
        },
        "disclaimer": "回答由大模型基于本地案例条目生成（检索增强），引用与待确认项来自结构化字段；模型概率为历史回放结果，不代表实时预报。",
    }


# ---------------------------------------------------------------------------
# 每日态势简报（LLM 生成，供打开页面时主动展示）
# ---------------------------------------------------------------------------

def daily_briefing():
    """生成当日态势简报：实况 + 告警 + D-1 预警 + 三日展望。

    LLM 不可达时回退本地规则简报。
    """
    live = _get_live_snapshot()
    if not live:
        return {"error": "实时数据不可用"}

    # 本地结构化素材
    cur = live.get("current") or {}
    nxt = live.get("next_24h") or {}
    alerts = live.get("alerts") or []
    adv = [w for w in (live.get("advance_warnings") or []) if w.get("warning_prob", 0) >= 0.15]
    cards = live.get("cards") or {}
    tyn = live.get("typhoon_now")

    fallback_parts = []
    rain_state = "无降雨" if (cur.get("precipitation_mm") or 0) < 0.1 else f"降雨 {cur['precipitation_mm']}mm/h"
    fallback_parts.append(
        f"当前深圳{rain_state}，气温 {cur.get('temperature_2m')}°C，风速 {cur.get('wind_speed_10m')}m/s。"
    )
    if tyn:
        fallback_parts.append(f"活跃台风「{tyn['name']}」（{tyn['wind_ms']}m/s），深圳市 3 天预报最大风速 {cards.get('typhoon',{}).get('value')}。")
    if alerts:
        sev = {"critical": "警示", "warning": "关注", "info": "提示"}
        summary = "、".join(f"{sev.get(a['severity'],'提示')}·{a['title']}" for a in alerts[:3])
        fallback_parts.append(f"当前告警 {len(alerts)} 条：{summary}。")
    else:
        fallback_parts.append("当前无阈值告警，四灾种平稳。")
    if adv:
        for w in adv[:2]:
            fallback_parts.append(f"明日（{w['for_date'][5:]}）滑坡预警概率 {w['warning_prob']*100:.0f}%（预报降雨 {w['tomorrow_rain_mm']}mm）。")
    ld = live.get("landslide_daily") or []
    if ld:
        outlook = "；".join(f"{d['date'][5:]} 雨{d['rain_24h']}mm/概率{d['warning_prob']*100:.0f}%" for d in ld[:3])
        fallback_parts.append(f"三日展望：{outlook}。")

    fallback_text = "\n".join(fallback_parts)

    if not llm_status()["configured"]:
        return {"briefing": fallback_text, "mode": "local",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}

    try:
        prompt = (
            f"以下是 CITY OS 指挥中心的实时数据快照，请写一份 3-5 句话的「今日态势简报」"
            f"（面向值班指挥，克制专业，先结论后细节，最后给 1 条最重要的建议）：\n\n"
            f"{fallback_text}\n\n"
            f"格式：纯文本段落，不要标题不要列表。"
        )
        ans = _llm_chat(
            "你是城市安全指挥中心的值班简报助手。简报必须基于给定数据，不编造，末尾附一句建议。",
            prompt, max_tokens=400,
        )
        if ans.strip():
            return {"briefing": ans.strip(), "mode": "llm", "model": LLM_MODEL,
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    except Exception:
        pass
    return {"briefing": fallback_text, "mode": "local",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


# ---------------------------------------------------------------------------
# 预置追问建议（前端快捷按钮）
# ---------------------------------------------------------------------------
def suggested_questions():
    """预置追问建议：基础 + 根据当前态势动态生成。"""
    base = [
        "深圳现在的天气和灾害风险怎么样？",
        "未来 24 小时会下多大雨？需要担心内涝吗？",
        "当前有活跃台风吗？对深圳有影响吗？",
        "山竹案例说清了什么？模型和官方预警对得上吗？",
        "哪个案例最能证明前期土壤湿度比单日雨量重要？",
        "2026 年 6·18 布吉河洪水的预警提前量是多少？",
        "深圳滑坡隐患点和易涝点周边各有多少人口暴露？",
    ]
    # 动态：根据活跃台风 / 告警追加
    try:
        live = _get_live_snapshot()
        if live:
            tyn = live.get("typhoon_now")
            if tyn:
                base.insert(1, f"台风「{tyn['name']}」对深圳的影响评估？")
            alerts = live.get("alerts") or []
            if any(a.get("severity") == "critical" for a in alerts):
                base.insert(0, "当前的警示级告警是什么情况？该怎么处置？")
    except Exception:
        pass
    return base[:8]


SUGGESTED_QUESTIONS_UNUSED = [
    "深圳现在的天气和灾害风险怎么样？",
    "现在潮位多高？有风暴潮风险吗？",
    "未来 24 小时会下多大雨？需要担心内涝吗？",
    "当前有活跃台风吗？对深圳有影响吗？",
    "山竹案例说清了什么？模型和官方预警对得上吗？",
    "为什么天鸽没有触发滑坡预警，山竹却发了红色？",
    "哪个案例最能证明前期土壤湿度比单日雨量重要？",
    "2026 年 6·18 布吉河洪水的预警提前量是多少？",
    "深圳滑坡隐患点和易涝点周边各有多少人口暴露？",
]
