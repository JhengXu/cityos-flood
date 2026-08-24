# -*- coding: utf-8 -*-
"""旧时序实验的数据集构建器。

默认 *fail closed*：项目当前没有足够的独立、带可用时间审计的积水深度标签，
因此不会训练或评估 LSTM/Transformer。历史代理标签实验只能通过显式
``allow_proxy_labels=True`` 复现，且产物不得用于真实预测能力声明。
"""
import os
import csv
import hashlib
import sys
import numpy as np

from . import config

# 引入后端城市特征与事件库（真实 DEM / 历史事件索引 / 脆弱性）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app import shenzhen, events  # noqa: E402
from app.risk import district_vulnerability  # noqa: E402


class InsufficientIndependentLabels(RuntimeError):
    """没有独立事件标签时，拒绝启动旧监督学习实验。"""


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
    """历史代理标签：由受影响区事实与超排水规则派生，不是逐时真值。"""
    def grade(R):
        excess = max(0.0, R - drainage)
        if not was_affected:
            return 0.05 + 0.10 * min(excess / 60.0, 1.0)
        return float(np.clip(min(excess / 30.0, 1.0) * 0.85 + 0.15, 0, 1))
    return np.array([grade(R) for R in rainfall_seq], dtype=np.float32)


def _user_data_root():
    return os.path.join(os.path.dirname(__file__), "..", "backend", "data", "user")


def _load_user_samples():
    """读取旧格式用户数据（backend/data/user/*.csv），仅供历史复现实验。
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
                V, _ = district_vulnerability(d)
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


def build_samples(neg_per_event=3, allow_proxy_labels=False):
    """构建旧实验样本；默认拒绝使用规则派生的代理标签。

    ``allow_proxy_labels=True`` 仅用于复现历史实验。即使降雨来自实测，当前标签仍
    主要由“降雨超排水阈值 + 事件受影响区”规则派生，并非独立积水深度真值。
    """
    if not allow_proxy_labels:
        raise InsufficientIndependentLabels(
            "缺少足量、独立且带 available_at 审计的积水深度标签；旧 LSTM/Transformer "
            "训练已默认关闭。仅为复现历史无效实验时可显式传 allow_proxy_labels=True，"
            "其指标不得用于预测能力声明。"
        )

    # —— 历史代理标签实验：观测降雨优先 ——
    real = []
    try:
        from . import realdata
        if realdata.REAL_DATA_ENABLED:
            real = realdata.build_real_event_samples(allow_proxy_labels=True)
    except Exception as e:
        real = []
        print(f"[dataset] 观测输入加载失败，回退历史代理序列: {e}")
    if real:
        events_used = sorted({s["meta"]["event"] for s in real})
        print(f"[dataset] 代理标签实验：{len(real)} 样本，事件 {events_used}")
        samples = real
        samples.extend(_load_user_samples())
        return samples

    # —— 回退：由事件事实和规则构造的代理序列 ——
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
            stable_seed = int.from_bytes(
                hashlib.sha256(ev["date"].encode("utf-8")).digest()[:4], "big"
            )
            r = np.random.default_rng(config.SEED + stable_seed % 1000)
            T = config.SEQ_LEN + config.HORIZON
            rain = np.clip(_storm(T, peak, shift=0.45 + 0.25 * r.random()) *
                           (0.7 + 0.5 * r.random()), 0, None)
            V, _ = district_vulnerability(d)
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
    # 合入旧格式用户数据样本（backend/data/user/*.csv）
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
    事件按固定种子打乱后分配。少于两个非空事件 ID 时无法构造独立测试集，
    必须拒绝运行，不能让 train/test 复用同一事件。"""
    from collections import defaultdict

    if not (len(X) == len(Y) == len(metas)):
        raise ValueError("X、Y 与 metas 的样本数必须一致")

    by_event = defaultdict(list)
    for i, m in enumerate(metas):
        event_id = str(m.get("event") or "").strip()
        if not event_id:
            raise InsufficientIndependentLabels(
                "样本缺少非空 meta.event，无法按独立事件构造无泄漏切分。"
            )
        by_event[event_id].append(i)
    events_list = list(by_event.keys())
    rng = np.random.default_rng(config.SEED)
    rng.shuffle(events_list)
    n = len(events_list)
    if n < 2:
        raise InsufficientIndependentLabels(
            "至少需要 2 个具有不同 event ID 的独立事件，才能构造互不重叠的 "
            "train/test；单事件实验已 fail closed。"
        )

    n_tr = int(round(n * config.SPLIT["train"]))
    n_va = int(round(n * config.SPLIT["val"]))
    n_te = n - n_tr - n_va
    # 事件数充足时，保证 train/val/test 各至少 1 个事件；两个事件时 val 为空。
    if n >= 3:
        n_te = max(n_te, 1)
        n_va = max(n_va, 1)
        n_tr = n - n_va - n_te
        if n_tr < 1:
            n_tr = 1
            n_te = n - n_va - 1
    else:  # n == 2
        n_tr, n_va, n_te = 1, 0, 1

    tr_ev = events_list[:n_tr]
    va_ev = events_list[n_tr:n_tr + n_va]
    te_ev = events_list[n_tr + n_va:]
    if not tr_ev or not te_ev or set(tr_ev) & set(te_ev):
        raise InsufficientIndependentLabels(
            "无法构造非空且事件互斥的 train/test 切分；拒绝泄漏式评估。"
        )

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


def load(allow_proxy_labels=False):
    """完整入口；无独立标签时默认拒绝训练和评估。"""
    samples = build_samples(allow_proxy_labels=allow_proxy_labels)
    X, Y, metas = _to_windows(samples)
    return split(X, Y, metas)


if __name__ == "__main__":
    d = load(allow_proxy_labels="--allow-proxy-labels" in sys.argv)
    print("数据集：")
    for k in ["train", "val", "test"]:
        Xk, Yk = d[k]
        print(f"  {k:6s} 样本 {len(Xk):5d}  特征 {Xk.shape[1:]}  标签均值 {Yk.mean():.3f}")
    print("警告：标签为规则派生代理标签；该实验不得用于真实预测能力声明。")
