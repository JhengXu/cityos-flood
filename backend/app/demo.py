# -*- coding: utf-8 -*-
"""
CITY OS · 内涝 WAM 研究验证演示 —— 后端服务（§3.1 + §3.2 + AI 三重角色）
---------------------------------------------------------------
提供：
  - /api/verify   : 可复现验证（训练/评估报告：指标 + 校准曲线 + 历史回放）
  - /api/ontology : 城市 3D 本体（区县属性 / 本底脆弱性）
  - /api/roles    : AI 三重角色
复用现有 /api/predict（预测）与 /api/simulate（推演/干预）。
"""
import os
import json

BASE = os.path.dirname(__file__)
ML_DIR = os.path.join(BASE, "..", "..", "ml")        # 指向项目 ml/
REPORT = os.path.join(ML_DIR, "outputs", "report.json")
BENCHMARK = os.path.join(ML_DIR, "outputs", "benchmark.json")


def _read_report():
    """读取 ml 管线生成的评估报告（若存在）。"""
    if os.path.exists(REPORT):
        try:
            with open(REPORT, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def get_verify():
    report = _read_report()
    if report is None:
        return {
            "status": "no_report",
            "hint": "尚未生成验证报告。请在项目根目录运行 `source .venv-ml/bin/activate && python -m ml.main all` 生成。",
        }
    return {"status": "ok", "report": report}


def _verify_meta():
    """可复现配置元信息（数据版本/种子/切分）。"""
    import sys
    sys.path.insert(0, os.path.join(ML_DIR, ".."))   # 父目录，含 `ml` 包
    try:
        from ml import config as cfg
        return {
            "seed": cfg.SEED,
            "split": {"train": cfg.SPLIT["train"], "val": cfg.SPLIT["val"], "test": cfg.SPLIT["test"]},
            "seq_len": cfg.SEQ_LEN, "horizon": cfg.HORIZON,
            "dataset_version": "v0.1-real-contract",
            "data_fallback": "real-events-anchored",
        }
    except Exception:
        return {}


def get_verify():
    report = _read_report()
    if report is None:
        return {
            "status": "no_report",
            "hint": "尚未生成验证报告。请在项目根目录运行 `source .venv-ml/bin/activate && python -m ml.main all` 生成。",
        }
    return {"status": "ok", "report": report, "config": _verify_meta()}


def get_ontology():
    """城市 3D 本体（区县属性）。复用后端 shenzhen 特征。"""
    from . import shenzhen, model
    districts = []
    for d in shenzhen.DISTRICTS:
        V, breakdown = model.district_vulnerability(d)
        districts.append({
            "id": d["id"], "name": d["name"], "center": d["center"],
            "drainage": d["drainage_design"],
            "elevation": d["elevation_mean"],
            "historical_index": d["historical_flood_index"],
            "coastal": d["coastal"],
            "vulnerability": V,
            "vuln_breakdown": breakdown,
            "tag": d["tag"],
        })
    return {
        "city": shenzhen.CITY,
        "districts": districts,
        "model": "城市 3D 本体（Ontology）v0.1",
        "note": "高程来自真实 DEM；历史指数来自真实内涝事件；排水/下垫面为代表性估算，可替换权威 GIS。",
    }


def get_roles():
    """AI 三重角色。"""
    return {
        "status": "ok",
        "roles": [
            {
                "id": "spatiotemporal",
                "title": "① 时序与空间特征学习",
                "subtitle": "街道级风险画像",
                "desc": "LSTM/Transformer 学习『降雨—城市状态—内涝』的时序动力学；结合区县 3D 本体属性做空间特征，输出街道/分区级风险画像。",
                "model": "5维时序特征 × (excess, cum24, vuln, drainage, tide) → 逐小时风险轨迹",
                "output": ["分区逐时风险概率", "街道级风险画像", "主因归因"],
            },
            {
                "id": "uncertainty",
                "title": "② 不确定性量化",
                "subtitle": "概率化分级预警",
                "desc": "输出概率而非点估计，并用校准曲线与 Brier 分数校准可信度；按概率分级（无/低/中/高/极高）下发预警。",
                "model": "概率输出 + 置信区间 + 概率校准(calibration_curve/Brier)",
                "output": ["概率化分级预警", "可信区间", "校准曲线"],
            },
            {
                "id": "intervention",
                "title": "③ 干预方案择优",
                "subtitle": "推演-评估-优化决策层",
                "desc": "对多个干预方案（泵站调度/资源调配）在 What-if 沙盘上做推演比较，按『处置后风险回落』择优。",
                "model": "SIMULATE 沙盘 + 处置后风险回落评估",
                "output": ["多方案推演对比", "最优干预建议", "处置后风险回落"],
            },
        ],
    }


# ============ 模型对比（LSTM vs Transformer）============
def get_benchmark():
    """读取模型对比结果；若无则触发一次对比（训练两模型，约数十秒）。"""
    import subprocess
    if os.path.exists(BENCHMARK):
        try:
            with open(BENCHMARK, "r", encoding="utf-8") as f:
                return {"status": "ok", "benchmark": json.load(f)}
        except Exception:
            pass
    ROOT = os.path.join(ML_DIR, "..")
    venv = os.path.join(ROOT, ".venv-ml", "bin", "python")
    try:
        subprocess.run([venv, "-c", "from ml import benchmark; benchmark.run()"],
                       cwd=ROOT, capture_output=True, timeout=1800)
        with open(BENCHMARK, "r", encoding="utf-8") as f:
            return {"status": "ok", "benchmark": json.load(f)}
    except Exception as e:
        return {"status": "error", "hint": f"模型对比失败: {e}"}


def export_report():
    """导出可复现验证证据（Markdown）：总体指标 + 校准 + 历史回放 + 模型对比。"""
    report = _read_report()
    bench = None
    if os.path.exists(BENCHMARK):
        try:
            with open(BENCHMARK, "r", encoding="utf-8") as f:
                bench = json.load(f)
        except Exception:
            pass
    lines = ["# CITY OS · 深圳内涝 WAM 可复现验证证据\n",
             "> 真实数据训练 + 可复现回放 + 量化指标（评审可复核）\n"]
    if report:
        m = report["metrics"]
        lines += ["## 一、总体指标（测试集）", "",
                  f"- AUC：**{report['auc']}**",
                  f"- Brier：**{report['brier']}**",
                  f"- 命中率 Hit：**{m['hit_rate']}**",
                  f"- 漏报率 Miss：**{m['miss_rate']}**",
                  f"- 误报率 False Alarm：**{m['false_alarm_rate']}**",
                  f"- 平均预警提前量：**{report['mean_lead_time_h']} h**",
                  f"- 最大预警提前量：**{report['max_lead_time_h']} h**",
                  "", f"- 测试样本数：**{report['n_test']}**",
                  "## 二、概率校准曲线", "",
                  "| 预测概率区间(横轴中点) | 实际频率 |", "|---|---|"]
        fop = report["calibration"]["fop"]; mpv = report["calibration"]["mpv"]
        for f, p in zip(fop, mpv):
            lines.append(f"| {f:.2f} | {p:.2f} |")
    if bench:
        lines += ["", "## 三、模型对比（LSTM vs Transformer）", "",
                  "| 模型 | AUC | Brier | 命中 | 漏报 | 误报 | 提前量 |", "|---|---|---|---|---|---|---|"]
        for mm in bench["models"]:
            lines.append(
                f"| {mm['type']} | {mm['auc']} | {mm['brier']} | {mm['hit_rate']} | "
                f"{mm['miss_rate']} | {mm['false_alarm_rate']} | {mm['mean_lead_time_h']}h |")
    if report and report.get("replay"):
        lines += ["", "## 四、历史事件系统回放", "",
                  "| 事件 | 行政区 | 影响 | 峰值强度 | 预测峰值 | 实际 | 提前量 |", "|---|---|---|---|---|---|---|"]
        for r in report["replay"][:40]:
            lines.append(f"| {r['event']} | {r['district']} | {'受影响' if r['affected'] else '未影响'} | "
                         f"{r['peak_mm_h']}mm/h | {r['pred_peak_prob']} | {r['actual_flood']} | "
                         f"{r['lead_h'] if r['lead_h'] is not None else '—'}h |")
    lines += ["", "---", "生成：CITY OS · 深圳内涝 WAM · 可复现验证体系（固定随机种子/固定切分/数据版本化）"]
    return "\n".join(lines)
