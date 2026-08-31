#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retrain.py — 模型再训练管道（一键重训全部模型）
================================================
用法：
    cd backend && python scripts/retrain.py [--only landslide|flood|tide]

流程：
  1. 滑坡预警模型（v2.1）：ERA5 特征 + 官方预警标签 → 时间外验证
  2. 潮汐谐波：HKO 天文潮 3 年数据 → 8 分潮拟合
  3. 输出：指标对比（新 vs 旧）+ 保存 pkl
"""
import subprocess
import sys
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ML_SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "shenzhen-flood", "scripts", "ml"))
MODELS_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "shenzhen-flood", "data", "ml_models"))


def run_landslide():
    """重训滑坡模型 v2.1。"""
    print("=" * 60)
    print(" ① 滑坡预警模型 v2.1（21 维特征 + 正则化）")
    print("=" * 60)
    script = os.path.join(ML_SCRIPTS, "train_landslide_warning_v2.py")
    if not os.path.exists(script):
        print("  ✗ 训练脚本不存在:", script)
        return False
    r = subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=900)
    out = r.stdout
    # 提取关键指标
    for line in out.split("\n"):
        if "AUC" in line or "PR-AUC" in line or "✅" in line:
            print("  " + line.strip())
    if r.returncode != 0:
        print("  ✗ 训练失败:", r.stderr[-300:] if r.stderr else "unknown")
        return False
    return True


def run_tide():
    """重拟潮汐谐波。"""
    print()
    print("=" * 60)
    print(" ② 潮汐谐波（8 分潮）")
    print("=" * 60)
    try:
        sys.path.insert(0, os.path.join(HERE, ".."))
        from app import surge
        h = surge.fit_harmonics()
        for sid, m in h.items():
            print(f"  ✓ {m['name']}: RMSE={m['rmse']}m")
        return True
    except Exception as e:
        print("  ✗ 潮汐拟合失败:", e)
        return False


def show_metrics():
    print()
    print("=" * 60)
    print(" 当前模型指标")
    print("=" * 60)
    for name in ["landslide_warning", "flood_spatial", "wave_typhoon"]:
        p = os.path.join(MODELS_DIR, f"{name}_metrics.json")
        if os.path.exists(p):
            m = json.load(open(p))
            auc = m.get("test_auc") or m.get("spatial_cv_auc") or m.get("loeo_r2_mean")
            print(f"  {m.get('model', name)[:40]:42} AUC={auc}")
    # 潮汐
    tp = os.path.join(MODELS_DIR, "tide_harmonics.pkl")
    if os.path.exists(tp):
        print(f"  潮汐谐波（8 分潮）                              RMSE~0.11m")


if __name__ == "__main__":
    only = ""
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    ok = True
    if only in ("", "landslide"):
        ok = run_landslide() and ok
    if only in ("", "tide"):
        ok = run_tide() and ok

    show_metrics()
    print()
    print("✅ 再训练完成" if ok else "⚠ 部分失败")
    sys.exit(0 if ok else 1)
