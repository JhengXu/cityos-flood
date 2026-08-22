# -*- coding: utf-8 -*-
"""
数据集构建（§3.1 真实数据监督训练）
---------------------------------------------------------------
设计目标：直接读「真实内涝事件数据」做监督训练。
  1. 优先读真实数据：backend/data/events/<事件>/waterlogging.csv（逐时积水/灾情）
  2. 若无真实逐时台账，则用真实历史事件库（真实日期/真实受影响区/真实峰值强度）
     生成「遵循数据契约、锚定真实事件」的演示序列作为占位（明确标注）。
固定数据切分（§3.2）。

数据字段（每区每小时）：
  X: [excess, cum24, vuln, drainage, tide]  —— 5 维特征
  y: flood 概率/0-1 标签（监督目标，来自真实积水/受影响事实）
"""
import os
import csv
import sys
import numpy as np

from . import config

# 引入后端城市特征与事件库（真实 DEM / 历史事件索引 / 脆弱性）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app import shenzhen, model, events  # noqa: E402


def _tide(T):
    t = np.arange(T)
    return np.clip(0.5 + 0.2 * np.sin(2 * np.pi * t / 12.4), 0, 1)


def _storm(T, peak, shift=0.55):
    t = np.linspace(0, 1, T)
    return peak * np.exp(-((t - shift) ** 2) / 0.02)


def _real_data_root():
    return os.path.join(os.path.dirname(__file__), "..", "backend", "data", "events")


def _load_real_waterlogging(district_id):
    """按数据契约读取该区真实逐时积水记录（若存在）。返回 (timestamps, flooded|depth) 或 None。"""
    root = _real_data_root()
    if not os.path.isdir(root):
        return None
    rows = []
    for sub in os.listdir(root):
        wl = os.path.join(root, sub, "waterlogging.csv")
        if not os.path.exists(wl):
            continue
        with open(wl, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(r)
    if not rows:
        return None
    # 过滤该区样本
    rec = [r for r in rows if r.get("district_id") == district_id]
    return rec if rec else None


def _labels_from_real_event(rainfall_seq, drainage, was_affected):
    """监督标签：锚定真实事件事实。
    若该区在真实事件中被波及（was_affected=真），则降雨超出排水能力越多判为内涝；
    否则为低风险。标签为逐小时 flood 概率(0-1)。"""
    def grade(R):
        excess = max(0.0, R - drainage)
        if not was_affected:
            return 0.05 + 0.10 * min(excess / 60.0, 1.0)
        return float(np.clip(min(excess / 30.0, 1.0) * 0.85 + 0.15, 0, 1))
    return np.array([grade(R) for R in rainfall_seq], dtype=np.float32)


def _user_data_root():
    return os.path.join(os.path.dirname(__file__), "..", "backend", "data", "user")


def _load_user_samples():
    """读取用户上传的真实数据（backend/data/user/*.csv），合入监督样本集。
    契约列：timestamp,district_id,rainfall_mm,flooded(0/1)。"""
    root = _user_data_root()
    if not os.path.isdir(root):
        return []
    tide = _tide(config.SEQ_LEN + config.HORIZON)
    samples = []
    for fn in os.listdir(root):
        if not fn.endswith(".csv"):
            continue
        rows = []
        with open(os.path.join(root, fn), "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(r)
        if not rows:
            continue
        # 按区聚合，按时间排序
        from collections import defaultdict
        by_dist = defaultdict(list)
        for r in rows:
            by_dist[r.get("district_id") or r.get("district")].append(r)
        for did, recs in by_dist.items():
            recs.sort(key=lambda x: x.get("timestamp", ""))
            rain = np.array([float(r.get("rainfall_mm", 0) or 0) for r in recs], dtype=float)
            flood = np.array([float(r.get("flooded", 0) or 0) for r in recs], dtype=float)
            if len(rain) < config.SEQ_LEN + 1:
                continue
            d = shenzhen.get_district(did)
            if d is None:
                # 用默认脆弱性
                V, C = 0.5, 28.0
            else:
                V, _ = model.district_vulnerability(d)
                C = d["drainage_design"]
            cum = 0.0
            X = []
            for t in range(len(rain)):
                cum = min(cum + rain[t], 300.0)
                excess = max(0.0, rain[t] - C)
                X.append([excess, cum, V, C, tide[t % (config.SEQ_LEN + config.HORIZON)]])
            X = np.array(X, dtype=np.float32)
            samples.append({
                "X": X, "y": np.clip(flood, 0, 1).astype(np.float32),
                "meta": {"event": "user-data", "district": did, "peak": round(float(rain.max()), 1),
                         "affected": bool(flood.max() > 0)},
            })
    return samples


def build_samples(neg_per_event=3):
    """构建监督样本集。

    优先使用 P0 真实数据（见 ml/realdata.py）：对「有真实降雨目录」的事件，
    用真实格点降雨 -> 分区逐时降雨 作输入，标签 = 真实降雨超额 ∩ 真实事件受影响区。
    真实数据缺失的事件/整体回退到「锚定真实事件事实」的演示序列（契约不变）。
    """
    # —— 真实监督优先（P0）——
    real = []
    try:
        from . import realdata
        if realdata.REAL_DATA_ENABLED:
            real = realdata.build_real_event_samples()
    except Exception as e:
        real = []
        print(f"[dataset] 真实数据加载失败，回退合成: {e}")
    if real:
        events_used = sorted({s["meta"]["event"] for s in real})
        print(f"[dataset] 真实监督模式：{len(real)} 样本，事件 {events_used}")
        samples = real
        samples.extend(_load_user_samples())
        return samples

    # —— 回退：合成（锚定真实事件事实）——
    samples = []
    tide = _tide(config.SEQ_LEN + config.HORIZON)
    all_ids = [d["id"] for d in shenzhen.DISTRICTS]
    for ev in events.HISTORICAL_EVENTS:
        peak = ev["peak_intensity_mm_h"]
        affected = set(ev["affected"])
        pos_ids = [did for did in affected if shenzhen.get_district(did)]
        neg_ids = [did for did in all_ids if did not in affected][:neg_per_event]
        for did in pos_ids + neg_ids:
            d = shenzhen.get_district(did)
            r = np.random.default_rng(config.SEED + hash(ev["date"]) % 1000)
            T = config.SEQ_LEN + config.HORIZON
            rain = np.clip(_storm(T, peak, shift=0.45 + 0.25 * r.random()) *
                           (0.7 + 0.5 * r.random()), 0, None)
            V, _ = model.district_vulnerability(d)
            C = d["drainage_design"]
            cum = 0.0
            X = []
            for t in range(T):
                cum = min(cum + rain[t], 300.0)
                excess = max(0.0, rain[t] - C)
                X.append([excess, cum, V, C, tide[t]])
            X = np.array(X, dtype=np.float32)
            y = _labels_from_real_event(rain, C, did in affected)
            samples.append({
                "X": X, "y": y,
                "meta": {"event": ev["date"], "district": did, "peak": peak,
                         "affected": bool(did in affected)},
            })
    # 合入用户上传的真实数据样本（backend/data/user/*.csv）
    samples.extend(_load_user_samples())
    return samples


def _to_windows(samples):
    """把 (T,5) 序列切成 (seq_len,5)->(5,) 输入 + (horizon, ) 目标。
    用「前 SEQ_LEN 小时 -> 预测未来 HORIZON 小时的内涝风险轨迹」，可算提前量。"""
    Xs, Ys, metas = [], [], []
    H = config.HORIZON
    for s in samples:
        X = s["X"]; y = s["y"]; T = len(X)
        if T < config.SEQ_LEN + 1:
            continue
        for t in range(0, T - config.SEQ_LEN):
            Xs.append(X[t:t + config.SEQ_LEN])
            vec = y[t + config.SEQ_LEN:t + config.SEQ_LEN + H]
            if len(vec) < H:
                vec = np.pad(vec, (0, H - len(vec)), constant_values=vec[-1] if len(vec) else 0.0)
            Ys.append(vec)
            metas.append(s["meta"])
    return np.array(Xs, dtype=np.float32), np.array(Ys, dtype=np.float32), metas


def split(X, Y, metas):
    """固定数据切分（§3.2）：按「事件」分组切分，避免同一事件的时窗样本
    跨 train/val/test 造成数据泄漏（修复此前随机样本切分的泄漏问题）。
    事件按固定种子打乱后分配；事件数较少时保证三集均非空（可运行的最小切分）。"""
    from collections import defaultdict
    by_event = defaultdict(list)
    for i, m in enumerate(metas):
        by_event[m.get("event", "unknown")].append(i)
    events_list = list(by_event.keys())
    rng = np.random.default_rng(config.SEED)
    rng.shuffle(events_list)
    n = len(events_list)
    n_tr = int(round(n * config.SPLIT["train"]))
    n_va = int(round(n * config.SPLIT["val"]))
    n_te = n - n_tr - n_va
    # 事件数充足时，保证 train/val/test 各至少 1 个事件；否则退化为可运行的最小切分
    if n >= 3:
        n_te = max(n_te, 1)
        n_va = max(n_va, 1)
        n_tr = n - n_va - n_te
        if n_tr < 1:
            n_tr = 1
            n_te = n - n_va - 1
    elif n == 2:
        n_tr, n_va, n_te = 1, 0, 1
    else:  # n == 1：单事件，训练与测试同源（接受泄漏，保证可运行）
        n_tr, n_va, n_te = 1, 0, 1

    tr_ev = events_list[:n_tr]
    va_ev = events_list[n_tr:n_tr + n_va]
    te_ev = events_list[n_tr + n_va:]
    if not te_ev and events_list:  # 兜底：test 为空时回退到最后 1 个事件
        te_ev = [events_list[-1]]

    def collect(ev_list):
        idx = []
        for e in ev_list:
            idx.extend(by_event[e])
        return idx

    tr, va, te = collect(tr_ev), collect(va_ev), collect(te_ev)
    return {
        "train": (X[tr], Y[tr]),
        "val": (X[va], Y[va]),
        "test": (X[te], Y[te]),
        "train_meta": [metas[i] for i in tr],
        "test_meta": [metas[i] for i in te],
    }


def load():
    """完整入口：构建数据集 -> 固定切分。返回 split 字典 + meta。"""
    samples = build_samples()
    X, Y, metas = _to_windows(samples)
    return split(X, Y, metas)


if __name__ == "__main__":
    d = load()
    print("数据集：")
    for k in ["train", "val", "test"]:
        Xk, Yk = d[k]
        print(f"  {k:6s} 样本 {len(Xk):5d}  特征 {Xk.shape[1:]}  标签均值 {Yk.mean():.3f}")
    print("标签来源：真实历史事件受影响事实（遵循数据契约；真实逐时台账注入后零改动）。")
