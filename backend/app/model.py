# -*- coding: utf-8 -*-
"""遗留 v1/v2 代理模型，仅供显式历史实验复现。

在线预测与推演使用 ``state_model.py`` 的守恒图状态空间集合。本模块不得在导入时
训练模型；尤其是物理教师生成标签的 LSTM 不属于生产模型。
"""
import numpy as np

from .shenzhen import DISTRICTS, DRAINAGE_AVG
from . import lstm as _lstm

FEATURE_NAMES = ["excess_norm", "vuln_x_excess", "vuln", "cum24_norm"]
FEATURE_LABELS = {
    "excess_norm": "降雨超出排水能力",
    "vuln_x_excess": "高危本底叠加暴雨",
    "vuln": "区域本底脆弱性",
    "cum24_norm": "前期累计降雨饱和",
}
RISK_LEVELS = ["无", "低", "中", "高", "极高"]


def _elev_vuln(elev):
    return 1.0 / (1.0 + np.exp((elev - 40.0) / 25.0))


def district_vulnerability(d):
    v_low = d["low_lying_ratio"]
    v_imp = d["impervious_ratio"]
    v_elev = _elev_vuln(d["elevation_mean"])
    v_hist = d["historical_flood_index"]
    v_coast = d["coastal"]
    V = 0.30 * v_low + 0.20 * v_imp + 0.15 * v_elev + 0.20 * v_hist + 0.15 * v_coast
    breakdown = {
        "low_lying": round(v_low, 3),
        "impervious": round(v_imp, 3),
        "elevation": round(v_elev, 3),
        "historical": round(v_hist, 3),
        "coastal": round(v_coast, 3),
    }
    return round(float(V), 3), breakdown


def _build_features(rain_intensity, cum24, drainage, V):
    excess = max(0.0, rain_intensity - drainage)
    return np.array([
        excess / 50.0,
        V * (excess / 50.0),
        V,
        cum24 / 150.0,
    ], dtype=float)


class FloodRiskModel:
    def __init__(self):
        self.weights = np.array([1.5, 1.0, 0.5, 0.6], dtype=float)
        self.bias = -1.0
        self._train()

    def _teacher(self, x):
        score = 1.5 * x[0] + 1.0 * x[1] + 0.5 * x[2] + 0.6 * x[3]
        return 1.0 / (1.0 + np.exp(-4.0 * (score - 1.0)))

    def _synthesize(self, n=8000):
        rng = np.random.default_rng(42)
        Rs = rng.uniform(0, 120, n)
        cum = rng.uniform(0, 300, n)
        Vs = rng.uniform(0.20, 0.90, n)
        Cs = rng.uniform(20, 40, n)
        X = np.zeros((n, 4))
        X[:, 0] = np.clip(Rs - Cs, 0, None) / 50.0
        X[:, 1] = Vs * X[:, 0]
        X[:, 2] = Vs
        X[:, 3] = cum / 150.0
        y = np.array([self._teacher(x) for x in X])
        y = np.clip(y + rng.normal(0, 0.05, n), 0, 1)
        return X, y

    def _train(self, n=8000, lr=0.05, epochs=400, l2=1e-4):
        X, y = self._synthesize(n)
        w = self.weights.copy()
        b = self.bias
        for _ in range(epochs):
            z = X.dot(w) + b
            p = 1.0 / (1.0 + np.exp(-z))
            err = p - y
            gw = (X.T.dot(err)) / n + l2 * w
            gb = err.mean()
            w -= lr * gw
            b -= lr * gb
        self.weights = w
        self.bias = float(b)

    def _sigmoid(self, z):
        return 1.0 / (1.0 + np.exp(-z))

    def predict_one(self, rain_intensity, cum24, drainage, V):
        x = _build_features(rain_intensity, cum24, drainage, V)
        z = float(x.dot(self.weights) + self.bias)
        p = self._sigmoid(z)
        level = self._level(p)
        contrib = {FEATURE_NAMES[i]: float(self.weights[i] * x[i]) for i in range(4)}
        driver = max(contrib, key=contrib.get)
        return {
            "prob": round(p, 4),
            "level": level,
            "level_label": RISK_LEVELS[level],
            "driver": FEATURE_LABELS[driver],
            "contrib": {k: round(v, 4) for k, v in contrib.items()},
            "excess": round(max(0.0, rain_intensity - drainage), 2),
        }

    @staticmethod
    def _level(p):
        if p < 0.15:
            return 0
        if p < 0.40:
            return 1
        if p < 0.65:
            return 2
        if p < 0.85:
            return 3
        return 4

    def feature_importance(self):
        imp = {FEATURE_NAMES[i]: round(float(abs(self.weights[i])), 4) for i in range(4)}
        total = sum(imp.values()) or 1.0
        return {k: round(v / total, 4) for k, v in imp.items()}


_MODEL = None


def get_flood_risk_model():
    """Explicitly construct the old teacher-fitted baseline on first request."""
    global _MODEL
    if _MODEL is None:
        _MODEL = FloodRiskModel()
    return _MODEL


# Compatibility symbol only. Importing this legacy module must never train.
MODEL = None


# ============================================================
# v2：LSTM 时序推演模型
# ============================================================
def compute_cum_seq(rainfall_seq, window=24):
    out = []
    for t in range(len(rainfall_seq)):
        lo = max(0, t - window)
        out.append(sum(rainfall_seq[lo:t]))
    return out


def build_seq_features(rainfall_seq, cum_seq, V, C, tide_seq):
    T = len(rainfall_seq)
    X = np.zeros((T, 5))
    cseq = np.asarray(C if np.ndim(C) else [C] * T, dtype=float)
    for t in range(T):
        drainage = float(cseq[t])
        excess = max(0.0, rainfall_seq[t] - drainage)
        X[t] = [excess / 60.0, cum_seq[t] / 200.0, V, drainage / 40.0, tide_seq[t]]
    return X


def _storm_traj(T, peak):
    t = np.linspace(0, 1, T)
    return peak * np.exp(-((t - 0.55) ** 2) / 0.02)


def _make_training_sequences(n=600, T=30):
    rng = np.random.default_rng(11)
    Xs, Ys = [], []
    harmonics = [2, 3, 4, 5]
    for _ in range(n):
        d = DISTRICTS[rng.integers(0, len(DISTRICTS))]
        V, _ = district_vulnerability(d)
        C = d["drainage_design"]
        peak = rng.uniform(10, 110)
        rain = np.clip(_storm_traj(T, peak) + rng.normal(0, 2, T), 0, None)
        h = harmonics[rng.integers(0, len(harmonics))]
        surge = rng.uniform(0, 0.4) * (peak / 110.0)
        tide = np.clip(0.5 + 0.3 * np.sin(np.linspace(0, h, T) * np.pi) + surge, 0, 1)
        cum = compute_cum_seq(list(rain))
        X = build_seq_features(list(rain), cum, V, C, list(tide))
        teacher = get_flood_risk_model()
        Y = np.array([
            teacher.predict_one(rain[t], cum[t], C, V)["prob"] for t in range(T)
        ])
        Xs.append(X)
        Ys.append(Y)
    return Xs, Ys


class SequenceFloodModel:
    def __init__(self):
        self.net = _lstm.LSTM(input_dim=5, hidden=16, seed=7)
        if not self.net.load():
            print("[model] 首次训练 LSTM 时序推演模型…")
            Xs, Ys = _make_training_sequences()
            self.net.fit(Xs, Ys, epochs=35, lr=0.01)
            self.net.save()
            print("[model] LSTM 训练完成并缓存")

    def forecast_district(self, d, rainfall_seq, tide_seq):
        V, _ = district_vulnerability(d)
        C = d["drainage_design"]
        cum = compute_cum_seq(list(rainfall_seq))
        X = build_seq_features(list(rainfall_seq), cum, V, C, list(tide_seq))
        return self.net.predict_seq(X)


_SEQ_MODEL = None


def get_sequence_model():
    """显式、惰性加载旧 LSTM；调用方必须自行遵守代理标签可信边界。"""
    global _SEQ_MODEL
    if _SEQ_MODEL is None:
        _SEQ_MODEL = SequenceFloodModel()
    return _SEQ_MODEL


# 兼容旧导入符号，但不再因 ``import backend.app.model`` 触发训练。
SEQ_MODEL = None
