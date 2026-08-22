# -*- coding: utf-8 -*-
"""
模型对比基准（LSTM vs Transformer，§3.1 端到端有监督训练）。
对同一数据/同一固定切分分别训练两种时序模型并评估，输出并排指标，
作为「对 LSTM/Transformer 做端到端监督训练」的对比证据。
"""
import os
import json
import numpy as np
import torch
from sklearn.metrics import roc_auc_score, brier_score_loss

from . import config, dataset, train, evaluate

BENCHMARK_PATH = os.path.join(config.CACHE_DIR, "benchmark.json")


def _eval(model, d):
    import torch
    model.eval()
    with torch.no_grad():
        prob = model(torch.tensor(d["test"][0])).numpy()          # (n, horizon)
    y = evaluate.binarize(d["test"][1])                            # (n, horizon) 0/1
    y_bin = y.max(axis=1).astype(int)
    y_pred = evaluate.binarize(prob).max(axis=1).astype(int)
    score = prob.max(axis=1)
    met = evaluate.event_metrics(y_bin, y_pred)
    auc = float(roc_auc_score(y_bin, score))
    brier = float(brier_score_loss(y_bin, score))
    # 提前量
    lead = []
    for i in range(len(prob)):
        alarm = np.where(evaluate.binarize(prob[i]) == 1)[0]
        flood = np.where(y[i] == 1)[0]
        if len(alarm) and len(flood) and flood[0] >= alarm[0]:
            lead.append(int(flood[0] - alarm[0]))
    return {
        "auc": round(auc, 4), "brier": round(brier, 4),
        "hit_rate": met["hit_rate"], "miss_rate": met["miss_rate"],
        "false_alarm_rate": met["false_alarm_rate"],
        "mean_lead_time_h": round(float(np.mean(lead)), 2) if lead else None,
    }


def run():
    d = dataset.load()
    rows = []
    best = None
    for mtype in ["lstm", "transformer"]:
        cfg = dict(config.MODEL)
        cfg["type"] = mtype
        model = train.train(d, cfg=cfg, verbose=False, save_path=None)
        m = _eval(model, d)
        m["type"] = mtype
        rows.append(m)
        if best is None or m["auc"] > best["auc"]:
            best = m
    # 恢复默认模型（LSTM）作为主模型，保证手动预测/验证一致
    train.train(d, cfg=config.MODEL, verbose=False)
    result = {
        "models": rows,
        "best": best,
        "n_test": len(d["test"][0]),
        "note": "同一数据/同一固定切分/同一种子下对比；指标由固定切分+历史回放得到。",
    }
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    with open(BENCHMARK_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result
