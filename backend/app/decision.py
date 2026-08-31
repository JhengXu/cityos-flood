# -*- coding: utf-8 -*-
"""decision.py — WAM 决策工单闭环（建议 → 人工批准 → 执行记录 → 效果回评）。

参照 cityos-command-workbench「待人工决策」理念：
  - WAM 优化输出的是「建议」（advisory），不下发 SCADA
  - 建议生成 → 待人工决策队列 → 批准/驳回（附理由）
  - 批准后生成执行工单 → 执行时间线 → 效果回评（对比建议 vs 实际）

存储：进程内 + JSON 持久化（backend/data/decisions.json）
审计：每个动作记录时间/操作者/理由（模拟 SHA-256 审计链）
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime

_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "decisions.json")


def _load():
    if os.path.exists(_STORE):
        try:
            with open(_STORE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"decisions": []}


def _save(db):
    os.makedirs(os.path.dirname(_STORE), exist_ok=True)
    with open(_STORE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def _hash(action: dict) -> str:
    raw = json.dumps(action, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def submit_suggestion(optimizer_run: dict, plan_summary: str, control_actions: list):
    """WAM 优化完成 → 提交决策建议（进入待人工决策队列）。

    optimizer_run: /api/wam/optimize 返回的关键字段
    plan_summary: 人话方案摘要
    control_actions: [{district, action, value, expected_effect}]
    """
    db = _load()
    decision = {
        "id": f"D-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{len(db['decisions'])+1:03d}",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending",  # pending → approved / rejected → executing → done
        "plan_summary": plan_summary,
        "control_actions": control_actions,
        "optimizer_run": optimizer_run,
        "timeline": [{
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": "submit",
            "by": "WAM 优化器",
            "note": "生成建议，等待人工决策",
            "hash": _hash({"t": time.time(), "plan": plan_summary}),
        }],
    }
    db["decisions"].append(decision)
    _save(db)
    return decision


def approve(decision_id: str, by: str = "值班指挥", note: str = ""):
    """人工批准 → 进入执行队列。"""
    db = _load()
    for d in db["decisions"]:
        if d["id"] == decision_id and d["status"] == "pending":
            d["status"] = "executing"
            d["approved_by"] = by
            d["approved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            d["timeline"].append({
                "at": d["approved_at"], "action": "approve", "by": by, "note": note or "人工批准",
                "hash": _hash({"t": time.time(), "id": decision_id, "act": "approve"}),
            })
            _save(db)
            return d
    return None


def reject(decision_id: str, by: str = "值班指挥", reason: str = ""):
    """人工驳回（附理由，进知识库复盘）。"""
    db = _load()
    for d in db["decisions"]:
        if d["id"] == decision_id and d["status"] == "pending":
            d["status"] = "rejected"
            d["rejected_by"] = by
            d["reject_reason"] = reason
            d["timeline"].append({
                "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": "reject", "by": by, "note": reason or "人工驳回",
                "hash": _hash({"t": time.time(), "id": decision_id, "act": "reject"}),
            })
            _save(db)
            return d
    return None


def complete(decision_id: str, actual_outcome: dict):
    """执行完成 → 效果回评（建议 vs 实际）。

    actual_outcome: {flood_peak_mm_actual, control_applied(bool), note}
    """
    db = _load()
    for d in db["decisions"]:
        if d["id"] == decision_id and d["status"] == "executing":
            d["status"] = "done"
            # 回评：对比建议预期 vs 实际
            expected = d.get("optimizer_run", {}).get("expected_flood_peak_mm")
            actual = actual_outcome.get("flood_peak_mm_actual")
            review = {
                "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "expected_peak_mm": expected,
                "actual_peak_mm": actual,
                "deviation_mm": round((actual - expected), 1) if (expected is not None and actual is not None) else None,
                "control_applied": actual_outcome.get("control_applied", True),
                "note": actual_outcome.get("note", ""),
            }
            d["review"] = review
            d["timeline"].append({
                "at": review["completed_at"], "action": "complete",
                "by": "系统回评", "note": f"实际峰值 {actual}mm vs 预期 {expected}mm",
                "hash": _hash({"t": time.time(), "id": decision_id, "act": "complete"}),
            })
            _save(db)
            return d
    return None


def list_decisions(status: str = ""):
    """决策工单列表（可按状态筛）。"""
    db = _load()
    items = db["decisions"]
    if status:
        items = [d for d in items if d["status"] == status]
    return {
        "decisions": list(reversed(items)),  # 最新在前
        "counts": {
            "pending": sum(1 for d in db["decisions"] if d["status"] == "pending"),
            "executing": sum(1 for d in db["decisions"] if d["status"] == "executing"),
            "done": sum(1 for d in db["decisions"] if d["status"] == "done"),
            "rejected": sum(1 for d in db["decisions"] if d["status"] == "rejected"),
        },
        "store": "backend/data/decisions.json（持久化，含 SHA-256 审计链）",
    }
