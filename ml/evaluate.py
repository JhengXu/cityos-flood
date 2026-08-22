# -*- coding: utf-8 -*-
"""
评估与可复现验证（§3.2 量化指标）
---------------------------------------------------------------
指标：命中率(Hit) / 漏报率(Miss) / 误报率(False Alarm) /
      预警提前量(小时) / AUC / 概率校准曲线 / Brier 分数。
并支持对每个历史事件做「系统回放」(replay)，输出可复核的验证证据。
"""
import os
import json
import numpy as np
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.calibration import calibration_curve

from . import config
from . import dataset as ds


def binarize(prob, thr=config.RISK_THRESHOLD):
    return (prob >= thr).astype(int)


def confusion(y_true, y_pred):
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    return tp, fn, fp, tn


def event_metrics(y_true, y_pred):
    """单事件/区间指标：命中、漏报、误报、提前量。"""
    tp, fn, fp, tn = confusion(y_true, y_pred)
    hit = tp / (tp + fn) if (tp + fn) else 0.0        # 命中率（检出）
    miss = fn / (tp + fn) if (tp + fn) else 0.0       # 漏报率
    fa = fp / (fp + tn) if (fp + tn) else 0.0          # 误报率（假阳性率）
    return {"tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "hit_rate": round(hit, 4), "miss_rate": round(miss, 4),
            "false_alarm_rate": round(fa, 4)}


def lead_time(prob_seq, y_seq, thr=config.RISK_THRESHOLD):
    """预警提前量：首次报警 到 首个真实内涝 的小时数。无内涝返回 None。"""
    alarm_idx = np.where(prob_seq >= thr)[0]
    flood_idx = np.where(y_seq == 1)[0]
    if len(alarm_idx) == 0 or len(flood_idx) == 0:
        return None
    return float(max(0, flood_idx[0] - alarm_idx[0]))


def calibration(y_true, y_score, bins=10):
    """概率校准曲线 + Brier 分数。返回 (fop, mpv, brier)。"""
    fop, mpv = calibration_curve(y_true, y_score, n_bins=bins)
    return fop.tolist(), mpv.tolist(), float(brier_score_loss(y_true, y_score))


def aggregate(test_X, test_Y, test_meta, model):
    """在测试集上输出总体指标 + 逐事件回放（基于未来 HORIZON 轨迹）。"""
    import torch
    model.eval()
    with torch.no_grad():
        prob = model(torch.tensor(test_X)).numpy()        # (n, horizon)
    y = binarize(test_Y)                                  # (n, horizon) 0/1
    yp = binarize(prob)
    # "未来 horizon 内是否发生内涝"：取轨迹最大值判定
    y_bin = (y.max(axis=1)).astype(int)
    y_pred_bin = (yp.max(axis=1)).astype(int)
    score = prob.max(axis=1)                              # 用于 AUC 的得分
    met = event_metrics(y_bin, y_pred_bin)
    auc = float(roc_auc_score(y_bin, score))
    fop, mpv, brier = calibration(y_bin, score)
    # 预警提前量：首次报警 到 首个真实内涝 的小时数（同一样本内）
    lead = []
    for i in range(len(prob)):
        alarm = np.where(yp[i] == 1)[0]
        flood = np.where(y[i] == 1)[0]
        if len(alarm) and len(flood):
            lt = int(flood[0] - alarm[0])
            if lt >= 0:
                lead.append(lt)
    report = {
        "n_test": int(len(y)),
        "auc": round(auc, 4),
        "brier": round(brier, 4),
        "calibration": {"fop": fop, "mpv": mpv},
        "metrics": met,
        "mean_lead_time_h": round(float(np.mean(lead)), 2) if lead else None,
        "max_lead_time_h": round(float(np.max(lead)), 2) if lead else None,
        "events": sorted(set(m["event"] for m in test_meta)),
    }
    return report


def replay(model):
    """历史事件系统回放（修复提前量计算）：
    - 优先用真实降雨序列做「滚动窗口预测」，得到完整时间轴上的预测内涝时间线，
      再与真实内涝时间线比较，算出真实预警提前量（小时）。
    - 无真实数据时回退到原有的单窗口回放（合成/演示数据）。
    """
    import torch
    try:
        from . import realdata
        real_series = realdata.build_real_event_series() if realdata.REAL_DATA_ENABLED else {}
    except Exception:
        real_series = {}
    if real_series:
        H = config.HORIZON
        THR = config.RISK_THRESHOLD
        rows = []
        for (event, did), info in real_series.items():
            rain = np.array(info["rain"], dtype=float)
            C = info["drainage"]; V = info["vuln"]
            T = len(rain)
            if T < config.SEQ_LEN + 1:
                continue
            tide = np.clip(0.5 + 0.2 * np.sin(2 * np.pi * np.arange(T) / 12.4), 0, 1)
            pred_t = np.full(T, np.nan)
            for i in range(0, T - config.SEQ_LEN + 1):
                Xw = np.zeros((config.SEQ_LEN, 5), dtype=np.float32)
                c = 0.0
                for j in range(config.SEQ_LEN):
                    rj = rain[i + j]
                    c = min(c + rj, 300.0)
                    excess = max(0.0, rj - C)
                    Xw[j] = [excess, c, V, C, tide[i + j]]
                with torch.no_grad():
                    traj = model(torch.tensor(Xw[None, :, :]).float()).numpy()[0]  # (H,)
                for k in range(H):
                    tt = i + config.SEQ_LEN + k
                    if tt < T:
                        cur = traj[k]
                        pred_t[tt] = cur if np.isnan(pred_t[tt]) else max(pred_t[tt], cur)
            real_flood = (np.maximum(rain - C, 0.0) > 0).astype(int)
            pred_flood = (pred_t >= THR).astype(int)
            alarm = np.where(pred_flood == 1)[0]
            flood = np.where(real_flood == 1)[0]
            lead = int(flood[0] - alarm[0]) if (len(alarm) and len(flood) and flood[0] >= alarm[0]) else None
            pv = float(np.nanmax(pred_t)) if T else 0.0
            rows.append({
                "event": event, "district": did,
                "affected": info["affected"],
                "peak_mm_h": round(float(rain.max()), 1),
                "pred_peak_prob": round(pv, 3),
                "actual_flood": int(real_flood.max()),
                "lead_h": lead, "real": True,
            })
        return rows
    # 回退：原有单窗口回放（合成/演示数据）
    samples = ds.build_samples()
    H = config.HORIZON
    rows = []
    for s in samples:
        X = s["X"]
        w = X[:config.SEQ_LEN]
        with torch.no_grad():
            traj = model(torch.tensor(w[None, :, :])).numpy()[0]
        y_actual = s["y"][config.SEQ_LEN:config.SEQ_LEN + H]
        if len(y_actual) < H:
            y_actual = np.pad(y_actual, (0, H - len(y_actual)), constant_values=y_actual[-1] if len(y_actual) else 0.0)
        yb = binarize(y_actual)
        alarm = np.where(binarize(traj) == 1)[0]
        flood = np.where(yb == 1)[0]
        lt = int(flood[0] - alarm[0]) if (len(alarm) and len(flood) and flood[0] >= alarm[0]) else None
        rows.append({
            "event": s["meta"]["event"], "district": s["meta"]["district"],
            "affected": s["meta"]["affected"],
            "peak_mm_h": s["meta"]["peak"],
            "pred_peak_prob": round(float(traj.max()), 3),
            "actual_flood": int(yb.max()),
            "lead_h": lt,
        })
    return rows


def run():
    import torch
    from .train import load_model
    from .dataset import load
    d = load()
    model = load_model()
    rep = aggregate(d["test"][0], d["test"][1], d["test_meta"], model)
    rep["replay"] = replay(model)
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    with open(config.REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    return rep


def fmt_report(rep):
    lines = []
    lines.append("【测试集总体】")
    lines.append(f"  AUC            = {rep['auc']}")
    lines.append(f"  Brier          = {rep['brier']}")
    lines.append(f"  命中率 Hit      = {rep['metrics']['hit_rate']}")
    lines.append(f"  漏报率 Miss     = {rep['metrics']['miss_rate']}")
    lines.append(f"  误报率 FA       = {rep['metrics']['false_alarm_rate']}")
    lines.append(f"  平均预警提前量  = {rep['mean_lead_time_h']} h")
    lines.append(f"  最大预警提前量  = {rep['max_lead_time_h']} h")
    lines.append("【历史事件回放】")
    for r in rep["replay"][:24]:
        aff = "受影响" if r["affected"] else "未受影响"
        lines.append(
            f"  {r['event']} {r['district']:8s} {aff:4s} peak={r['peak_mm_h']:3.0f}mm/h  "
            f"pred峰值={r['pred_peak_prob']:.2f}  actual={r['actual_flood']}  lead={r['lead_h']}h"
        )
    return "\n".join(lines)
