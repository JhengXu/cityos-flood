# -*- coding: utf-8 -*-
"""
CITY OS · 数据实验室（结合最新数据 + 用户输入）
---------------------------------------------------------------
- current_conditions : 实时最新数据（Open-Meteo 多点降雨）
- manual_forecast    : 用户手动输入降雨序列 -> 模型预测未来内涝风险轨迹
- upload_data        : 用户上传真实数据 CSV -> 触发监督重训 -> 返回最新指标
"""
import os
import sys
import csv
import io
import json
import subprocess

import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
ML_DIR = os.path.join(ROOT, "ml")
USER_DIR = os.path.join(ROOT, "backend", "data", "user")
VENV_PY = os.path.join(ROOT, ".venv-ml", "bin", "python")


def _import_ml():
    sys.path.insert(0, ROOT)          # 父目录，含 `ml` 包
    from ml import config as cfg, model as m, train as tr  # noqa
    net = tr.load_model(cfg.MODEL)
    return cfg, net


# ---------------- 实时最新数据 ----------------
def current_conditions():
    from . import weather
    fc = weather.downscaled_forecast(forecast_days=1)
    times = fc["times"]
    rainfall = fc["districts"]
    city = fc["city"]
    return {
        "generated_at": fc.get("times", [None])[0],
        "data_source": "fallback-sample" if fc["fallback"] else "open-meteo-multi-point",
        "city_rainfall": city[0] if city else 0,
        "hour": times[0] if times else None,
        "districts": {k: (v[0] if v else 0) for k, v in rainfall.items()},
    }


# ---------------- 手动输入预测 ----------------
def manual_forecast(district_id, rainfall, tide_raise=0.0):
    """用户输入某区逐时降雨序列(未来 N 小时)，用训练好的模型预测内涝风险轨迹。"""
    from . import shenzhen, model
    d = shenzhen.get_district(district_id)
    if d is None:
        return {"error": f"未知行政区: {district_id}"}
    cfg, net = _import_ml()
    V, _ = model.district_vulnerability(d)
    C = d["drainage_design"]
    rain = np.array([float(x) for x in rainfall], dtype=float)
    T = cfg.SEQ_LEN + cfg.HORIZON
    # 若输入不足 SEQ_LEN，前补 0（模拟本场雨从此刻开始）
    if len(rain) < T:
        rain = np.concatenate([np.zeros(T - len(rain)), rain])
    rain = rain[:T]
    tide = np.clip(0.5 + 0.2 * np.sin(2 * np.pi * np.arange(T) / 12.4), 0, 1) + float(tide_raise)
    tide = np.clip(tide, 0, 1)
    cum = 0.0
    X = []
    for t in range(T):
        cum = min(cum + rain[t], 300.0)
        excess = max(0.0, rain[t] - C)
        X.append([excess, cum, V, C, tide[t]])
    X = np.array(X, dtype=np.float32)

    import torch
    Xw = X[:cfg.SEQ_LEN]
    Xt = torch.tensor(Xw[None, :, :], dtype=torch.float32)
    net.eval()

    # 不确定性量化：输入扰动法（蒙特卡洛），采样 N 次得到置信区间带
    N = 60
    scale = np.array([50.0, 150.0, 1.0, 40.0, 1.0], dtype=np.float32)  # 各特征扰动尺度
    samples = []
    with torch.no_grad():
        for _ in range(N):
            noise = (torch.randn_like(Xt) * torch.tensor(scale * 0.06, dtype=torch.float32))
            p = net(Xt + noise).numpy()[0]
            samples.append(p)
    samples = np.array(samples)                    # (N, horizon)
    mean = samples.mean(axis=0)
    lo = np.percentile(samples, 5, axis=0)
    hi = np.percentile(samples, 95, axis=0)

    traj_mean = net(Xt).detach().numpy()[0]          # 确定性主预测
    hours = [f"+{i}h" for i in range(1, len(traj_mean) + 1)]
    peak = float(traj_mean.max())
    peak_idx = int(np.argmax(traj_mean))
    from .model import RISK_LEVELS
    lvl = int((peak >= 0.85) * 4 + (0.65 <= peak < 0.85) * 3 + (0.40 <= peak < 0.65) * 2 + (0.15 <= peak < 0.40) * 1)
    return {
        "district": district_id, "vulnerability": V, "drainage": C,
        "peak_prob": round(peak, 4), "peak_level": RISK_LEVELS[lvl], "peak_level_idx": lvl,
        "peak_time": hours[peak_idx],
        "uncertainty": {
            "method": "MC-perturbation (N=60)",
            "mean_std": round(float(samples[:, peak_idx].std()), 4),
            "ci95": [round(float(lo[peak_idx]), 4), round(float(hi[peak_idx]), 4)],
        },
        "trajectory": [{
            "h": hours[i], "prob": round(float(traj_mean[i]), 4),
            "lo": round(float(lo[i]), 4), "hi": round(float(hi[i]), 4),
        } for i in range(len(traj_mean))],
    }


# ---------------- 用户上传数据 -> 重训 ----------------
def upload_data(filename, content_bytes):
    """保存用户上传 CSV 到 backend/data/user/，并触发监督重训，返回最新验证报告。"""
    os.makedirs(USER_DIR, exist_ok=True)
    safe = os.path.basename(filename or "user_data.csv")
    if not safe.endswith(".csv"):
        safe += ".csv"
    path = os.path.join(USER_DIR, safe)
    # 校验列
    try:
        text = content_bytes.decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
        cols = set(rows[0].keys()) if rows else set()
        need = {"district_id", "rainfall_mm", "flooded"}
        if not need.issubset(cols):
            return {"status": "error",
                    "hint": f"列需包含 {sorted(need)}，当前 {sorted(cols)}。示例：timestamp,district_id,rainfall_mm,flooded"}
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        return {"status": "error", "hint": f"解析失败: {e}"}

    # 触发重训练（隔离的 .venv-ml 子进程），生成新报告
    subprocess.run([VENV_PY, "-m", "ml.main", "all"], cwd=ROOT,
                   capture_output=True, timeout=600)
    report_path = os.path.join(ML_DIR, "outputs", "report.json")
    report = None
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    return {"status": "ok", "saved": safe, "rows": len(rows), "report": report}
