# -*- coding: utf-8 -*-
"""Research evidence and architecture descriptions for the demo API.

The repository still contains reports produced by the former synthetic-label
LSTM/Transformer pipeline. They are useful for reproducing old UI experiments,
but they are *not* independent evidence of forecasting skill. This module keeps
those files quarantined as ``legacy_*`` artefacts and never starts training from
an HTTP GET request.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from . import observations


BASE = os.path.dirname(__file__)
ML_DIR = os.path.join(BASE, "..", "..", "ml")
REPORT = os.path.join(ML_DIR, "outputs", "report.json")
BENCHMARK = os.path.join(ML_DIR, "outputs", "benchmark.json")

_LEGACY_REASON = (
    "该产物使用由规则/物理教师或事件事实扩展出的演示标签，训练与评估目标不独立；"
    "因此不能用于宣称模型具有真实内涝预测能力。"
)


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {"value": payload}
    except (OSError, ValueError, TypeError):
        return None


def _legacy_artifact(payload: Optional[Dict[str, Any]], kind: str) -> Optional[Dict[str, Any]]:
    """Wrap an old artefact so consumers cannot mistake it for valid evidence."""
    if payload is None:
        return None
    return {
        "kind": kind,
        "status": "invalid_for_skill_claim",
        "invalid_for_skill_claim": True,
        "reason": _LEGACY_REASON,
        "artifact": payload,
    }


def _evidence_requirements() -> Dict[str, Any]:
    return {
        "split_unit": "event_id (同一事件不得跨 train/validation/test)",
        "time_semantics": (
            "同时保存 observed_at 与 available_at；特征只能使用预测签发时 available_at 已到达的数据"
        ),
        "targets": ["独立观测 water_depth_m", "积水持续时间", "15/30/50cm 阈值超越"],
        "minimum_protocol": [
            "按事件和时间留出、滚动起报回放",
            "与零积水/持续性/守恒状态空间基线在完全相同样本上比较",
            "报告逐提前量 MAE/CRPS/Brier、命中/漏报/误报及可靠性图",
            "按行政区、暴雨强度、潮位状态分层，并给出 bootstrap 置信区间",
        ],
    }


def get_verify():
    """Return an honest validation-readiness result, never a pseudo scorecard."""
    readiness = observations.data_readiness()
    legacy = _legacy_artifact(_read_json(REPORT), "synthetic-label evaluation report")
    ready = bool(readiness.get("forecast_training_ready"))
    status = "evaluation_required" if ready else "insufficient_data"
    hint = (
        "数据覆盖已达到进入独立评估流程的最低门槛，但仍需按事件留出完成审计后才能发布能力指标。"
        if ready
        else (
            "当前项目缓存仅覆盖短时运行切片，且没有独立标注的积水事件；"
            "可用于数据接入、干态先验与同化联调，不能用于监督训练或预测能力宣称。"
        )
    )
    result = {
        "status": status,
        "skill_claim_allowed": False,
        "data_readiness": readiness,
        "evidence_requirements": _evidence_requirements(),
        "hint": hint,
    }
    if legacy is not None:
        result["legacy_report"] = legacy
    return result


def get_ontology():
    """城市 3D 本体（区县属性）。复用后端深圳特征。"""
    from . import shenzhen
    from .risk import district_vulnerability

    districts = []
    for district in shenzhen.DISTRICTS:
        vulnerability, breakdown = district_vulnerability(district)
        districts.append({
            "id": district["id"],
            "name": district["name"],
            "center": district["center"],
            "drainage": district["drainage_design"],
            "elevation": district["elevation_mean"],
            "historical_index": district["historical_flood_index"],
            "coastal": district["coastal"],
            "vulnerability": vulnerability,
            "vuln_breakdown": breakdown,
            "tag": district["tag"],
        })
    return {
        "city": shenzhen.CITY,
        "districts": districts,
        "model": "城市静态特征本体 v0.2",
        "note": (
            "高程/低洼/临海来自项目内 DEM 与 WorldCover 派生特征；排水能力仍是代理参数，"
            "历史指数仅作背景信息，不作为独立积水标签。"
        ),
    }


def get_roles():
    """Describe the three operational roles of the new modelling stack."""
    return {
        "status": "ok",
        "model_family": "守恒图状态空间 + 参数集合 + 局地 EnSRF",
        "formalism": "controlled partially observed state-space world model (POMDP dynamics)",
        "world_model_contract": {
            "static_structure_G": "DEM / land cover / drainage and hydraulic graph",
            "state_x": "district surface-water storage and representative depth ensemble",
            "environment_u": "rainfall, tide and boundary forcing",
            "observation_y": "quality-controlled, time-audited water-depth observations",
            "action_a": "pump efficiency, drainage control, gates and response actions",
            "cost_J": "flood depth/exposure + access disruption + energy/action costs",
        },
        "control_status": (
            "actions are currently scenario inputs and deterministic response rules; "
            "no learned RL policy or calibrated reward model is claimed"
        ),
        "roles": [
            {
                "id": "state_transition",
                "title": "① 守恒状态预测",
                "subtitle": "降雨—产流—两段蓄积—排水—区际汇流—边界外排",
                "desc": (
                    "以分区积水体积为显式状态，同步计算产流、排水、沿地势的区际通量和边界外排；"
                    "每个时间步输出质量守恒账本。"
                ),
                "model": "conservative graph state-space model (m³ state → mm depth)",
                "output": ["P10/P50/P90 积水深度", "阈值超越频率", "水量平衡审计"],
            },
            {
                "id": "uncertainty_assimilation",
                "title": "② 不确定性与观测同化",
                "subtitle": "六类参数集合 + 局地 Ensemble Square-Root Filter",
                "desc": (
                    "用参数集合传播产流、排水、浅层/扩展受淹面积、汇流速度和外排率的不确定性；"
                    "仅在水深观测新鲜且质控通过时，用确定性局地 EnSRF 修正状态及其离散度。"
                ),
                "model": "parameter ensemble + deterministic localised EnSRF update",
                "output": ["深度分位数", "同化前后均值/标准差", "显式同化体积增量"],
            },
            {
                "id": "intervention",
                "title": "③ 同源情景推演",
                "subtitle": "预测与 What-if 共用一套动力学",
                "desc": (
                    "在同一预报签发快照和随机种子上改变降雨、潮位、泵效或排水控制，"
                    "比较积水深度、超阈概率与消退过程。"
                ),
                "model": "shared state transition + controlled counterfactual ensemble",
                "output": ["基线/情景差值", "干预敏感性", "可追溯 run_id/参数来源"],
            },
            {
                "id": "control_roadmap",
                "title": "④ 控制优化边界",
                "subtitle": "稳健 CEM 安全基线已运行，RL 仍在演进路线",
                "desc": (
                    "当前已在同一守恒世界模型上用有限时域鲁棒 CEM 搜索十区排水控制常值动作，"
                    "再经设备边界、变化率、应急预算和成对集合无恶化护栏生成仅供审批的建议。"
                    "它不是严格动作序列 MPC，也不是已训练 RL；只有真实行动结果日志足够后，才评估"
                    "约束 MPC 与离线/残差强化学习。"
                ),
                "model": "finite-horizon robust CEM constant-hold + deterministic safety shield",
                "output": ["基线/优化成本", "安全投影与约束", "唯一审计 ID / 可回放记录"],
            },
        ],
        "validation_status": get_verify()["status"],
    }


def get_benchmark():
    """Return a benchmark plan; never train synthetic models in a GET request."""
    readiness = observations.data_readiness()
    legacy = _legacy_artifact(_read_json(BENCHMARK), "synthetic LSTM/Transformer benchmark")
    candidates = [
        {
            "id": "zero_or_climatology",
            "role": "最低基线",
            "description": "零积水/按区与月份的训练集气候态；用于识别类别不平衡带来的虚高指标。",
            "requires_training": False,
        },
        {
            "id": "persistence",
            "role": "观测持续性基线",
            "description": "把签发时最后一条可用水深向前保持，并与简单线性消退版本比较。",
            "requires_training": False,
        },
        {
            "id": "conservative_state_space",
            "role": "当前可运行灰盒基线",
            "description": "守恒图状态空间模型；报告深度误差、阈值事件指标和质量闭合误差。",
            "requires_training": False,
        },
        {
            "id": "ensemble_enkf",
            "role": "当前候选主模型",
            "description": "状态空间参数集合 + 新鲜水深观测的局地 EnSRF；与无同化版本成对比较。",
            "requires_training": False,
        },
        {
            "id": "gradient_boosted_residual",
            "role": "有独立事件后优先加入的数据驱动基线",
            "description": "只学习物理模型残差，使用发布时可用的雨量、状态和静态 GIS 特征。",
            "requires_training": True,
        },
        {
            "id": "spatiotemporal_neural_operator",
            "role": "数据量充足后的研究候选",
            "description": "TCN/TFT/图时空网络或神经状态空间模型；必须通过事件外推测试才可采用。",
            "requires_training": True,
        },
    ]
    result = {
        "status": "insufficient_data",
        "training_triggered": False,
        "data_readiness": readiness,
        "candidates": candidates,
        "evaluation_plan": _evidence_requirements(),
        "hint": (
            "当前没有独立积水事件测试集，不能诚实地给出模型排名。"
            "补齐事件级观测后，应在同一 rolling-origin/event-held-out 切分上运行上述候选。"
        ),
    }
    if legacy is not None:
        result["legacy_benchmark"] = legacy
    return result


def export_report():
    """Export readiness evidence without presenting legacy metrics as skill."""
    verification = get_verify()
    readiness = verification["data_readiness"]
    lines = [
        "# CITY OS · 深圳内涝模型验证就绪度报告",
        "",
        f"> 当前结论：**{verification['status']}**。预测能力指标暂不可发布。",
        "",
        "## 一、独立观测覆盖",
        "",
        f"- 项目缓存状态：`{readiness.get('status', 'unknown')}`",
        f"- 质控小时记录：{readiness.get('rows', 0)}",
        f"- 站点数 / 已映射站点数：{readiness.get('stations', 0)} / {readiness.get('mapped_stations', 0)}",
        f"- 覆盖起止：{readiness.get('start', '—')} → {readiness.get('end', '—')}",
        f"- 覆盖小时：{readiness.get('duration_hours', 0)}",
        f"- ≥0.15m 记录：{readiness.get('rows_ge_0_15m', 0)}",
        f"- 独立积水事件：{readiness.get('independent_flood_events', 0)}",
        f"- 结论：{readiness.get('reason', '未提供')}",
        "",
        "## 二、当前模型可审计内容",
        "",
        "- 守恒图状态空间模型的逐时水量账本与闭合误差。",
        "- 参数集合的 P10/P50/P90 深度与阈值超越频率。",
        "- EnSRF 同化前后状态、离散度及信息修正体积增量的单独记账。",
        "- 这些是运行与数值审计，不等同于对真实事件的预测技巧验证。",
        "",
        "## 三、发布指标前必须完成",
        "",
    ]
    for item in _evidence_requirements()["minimum_protocol"]:
        lines.append(f"- {item}")
    lines += [
        "",
        "## 四、历史实验产物隔离说明",
        "",
        _LEGACY_REASON,
        "旧 `ml/outputs/report.json` 与 `benchmark.json` 即使存在，也不会在本报告中作为 "
        "AUC、Brier、命中率或模型优劣证据展示。",
        "",
        "---",
        "生成：CITY OS · 守恒状态空间模型验证就绪度审计",
    ]
    return "\n".join(lines)
