# -*- coding: utf-8 -*-
"""LSTM vs Transformer 的遗留代理标签复现实验。

结果只比较两种网络拟合规则标签的能力，不构成真实预报技巧证据。
"""
import os
import json
import numpy as np

from . import config, dataset

BENCHMARK_PATH = os.path.join(config.CACHE_DIR, "benchmark.json")


def _eval(model, d):
    import torch
    from sklearn.metrics import roc_auc_score, brier_score_loss
    from . import evaluate

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


def run(allow_proxy_labels=False):
    d = dataset.load(allow_proxy_labels=allow_proxy_labels)
    from . import train

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
    # 恢复历史实验默认网络；它不是在线主模型。
    train.train(d, cfg=config.MODEL, verbose=False)
    result = {
        "models": rows,
        "best": best,
        "n_test": len(d["test"][0]),
        "invalid_for_skill_claim": True,
        "valid_for_skill_claim": False,
        "independent_event_labels": False,
        "label_provenance": "proxy labels derived from rainfall/drainage rules and affected-area facts",
        "warning": "Historical reproduction only; metrics do not measure real-world flood forecast skill.",
        "note": "同一代理标签数据/同一固定切分/同一种子下的历史网络拟合对比。",
    }
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    with open(BENCHMARK_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result
