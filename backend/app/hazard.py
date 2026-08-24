# -*- coding: utf-8 -*-
"""
暴雨—产流—积水 物理代理层（理论 §3.3）
---------------------------------------------------------------
实现节点状态方程（部分可观测世界模型的 hazard 层）：

    h_i(t+Δt) = max[0, h_i(t) + α_i·R_i(t) + Σ_j w_ji·h_j(t) - β_i·h_i(t)]

- h_i : 第 i 区的“积水累积”代理状态（无量纲）
- R_i : 真实/降尺度的逐时降雨(mm/h)
- α_i : 降雨转积水的敏感度
- β_i : 抽排/下渗/退水综合衰减率
- w_ji: 上游/邻近低地向 i 的传播权重（由质心邻近度构造）

设计原则（对应理论 §3.3 / §17）：
- 物理守恒方程提供“边界”，α,β,w 由**数据校准**得到，而不是用端到端黑箱替代物理。
- 显式历史校准时才会惰性构造 `model.get_flood_risk_model()` 占位教师；
  一旦 `station_district_map.csv` 补齐且事件期真实水位到位，可无缝换成
  真实积涝点水位作为校准目标（见 calibrate_district 的 teacher 钩子）。
- 所有参数/输出均带 provenance 标签（observed/estimated/assumed/simulated）。
"""
import os
import json
import numpy as np

from . import shenzhen, model

# 代理水深 -> 风险概率 的映射（assumed 标定，可被校准间接调整）
H_HALF = 30.0
H_K = 10.0

# 校准目标的 provenance（目前是混合教师；换成真实水位后改为 observed）
CALIB_PROVENANCE = (
    "estimated (legacy calibration against a rule-derived teacher); "
    "swap to observed water level once station_district_map.csv + event water levels are ready"
)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", ".cache_hazard")
os.makedirs(CACHE_DIR, exist_ok=True)
PARAM_PATH = os.path.join(CACHE_DIR, "surrogate_params.json")


# ============ 物理默认参数（assumed，由可解释属性派生）============
def _default_params(d):
    C = d["drainage_design"]
    V, _ = model.district_vulnerability(d)
    low = d["low_lying_ratio"]
    # α：排水越弱、低洼越多 → 降雨转积水越敏感
    alpha = 0.004 + 0.010 * (1.0 - C / 40.0) + 0.006 * low
    # β：排水越强 → 退水/抽排衰减越快
    beta = 0.02 + 0.05 * (C / 40.0)
    return {"alpha": float(alpha), "beta": float(beta), "V": float(V), "C": float(C)}


# ============ 上游传播权重（assumed 邻接：质心邻近度）============
def _build_neighbors():
    centers = {d["id"]: tuple(d["center"]) for d in shenzhen.DISTRICTS}
    out = {}
    for di, ci in centers.items():
        ws = {}
        for dj, cj in centers.items():
            if dj == di:
                continue
            dist2 = (ci[0] - cj[0]) ** 2 + (ci[1] - cj[1]) ** 2
            w = float(np.exp(-dist2 / 0.02))
            if w > 0.05:
                ws[dj] = w
        s = sum(ws.values()) or 1.0
        out[di] = {k: v / s for k, v in ws.items()}
    return out


_NEIGH = _build_neighbors()
_PARAMS = None


def _risk_from_h(h):
    return float(1.0 / (1.0 + np.exp(-(h - H_HALF) / H_K)))


def _load_params():
    global _PARAMS
    if _PARAMS is not None:
        return _PARAMS
    if os.path.exists(PARAM_PATH):
        with open(PARAM_PATH, "r", encoding="utf-8") as f:
            _PARAMS = json.load(f)
    else:
        _PARAMS = {d["id"]: _default_params(d) for d in shenzhen.DISTRICTS}
    return _PARAMS


# ============ 批量时序推演（共享上游状态）============
def simulate_batch(rainfall_by_district, params=None, h0=None):
    """rainfall_by_district: {did: [R_t,...]}。返回 {did: [h_t,...]} 代理水深序列。"""
    params = params or _load_params()
    dids = list(rainfall_by_district.keys())
    T = max((len(v) for v in rainfall_by_district.values()), default=0)
    h = {d: float(h0 or 0.0) for d in dids}
    out = {d: [] for d in dids}
    for t in range(T):
        for d in dids:
            R = rainfall_by_district[d][t] if t < len(rainfall_by_district[d]) else 0.0
            C = params[d].get("C", 30.0)
            excess = max(0.0, R - C)
            up = sum(w * h.get(nb, 0.0) for nb, w in _NEIGH.get(d, {}).items())
            h[d] = max(0.0, h[d] + params[d]["alpha"] * excess + 0.30 * up - params[d]["beta"] * h[d])
            out[d].append(h[d])
    return out


def risk_batch(rainfall_by_district, params=None):
    """返回 {did: [risk_t,...]}（代理水深经 assumed 映射转风险概率）。"""
    hs = simulate_batch(rainfall_by_district, params=params)
    return {d: [_risk_from_h(h) for h in seq] for d, seq in hs.items()}


# ============ 校准：用教师风险序列拟合 α,β（estimated）============
def _teacher_risk_seq(did, R_seq):
    """旧规则教师，仅供显式历史实验；不可替代独立水深观测。"""
    d = next(x for x in shenzhen.DISTRICTS if x["id"] == did)
    V, _ = model.district_vulnerability(d)
    C = d["drainage_design"]
    cum = 0.0
    out = []
    for R in R_seq:
        cum = min(cum + R, 300.0)
        out.append(model.get_flood_risk_model().predict_one(R, cum, C, V)["prob"])
    return np.array(out, dtype=float)


def calibrate_district(did, epochs_search=14, teacher_fn=None):
    d = next(x for x in shenzhen.DISTRICTS if x["id"] == did)
    V, _ = model.district_vulnerability(d)
    C = d["drainage_design"]
    rng = np.random.default_rng(abs(hash(did)) % (2 ** 32))
    teacher_fn = teacher_fn or _teacher_risk_seq
    # 生成若干合成降雨序列 + 教师风险目标
    seqs = []
    for _ in range(40):
        T = 30
        peak = rng.uniform(10, 110)
        R = np.clip(peak * np.exp(-((np.linspace(0, 1, T) - 0.55) ** 2) / 0.15)
                    + rng.normal(0, 3, T), 0, None)
        cum = 0.0
        Rc = []
        for r in R:
            cum = min(cum + r, 300.0)
            Rc.append(r)
        seqs.append((np.array(Rc, dtype=float), teacher_fn(did, Rc)))

    base = _default_params(d)
    alphas = np.linspace(0.005, 0.15, epochs_search)
    betas = np.linspace(0.02, 0.25, epochs_search)
    best = None
    denom = max(1, len(seqs) * len(seqs[0][1]))
    for a in alphas:
        for b in betas:
            mse = 0.0
            for R, teacher in seqs:
                h = 0.0
                for t in range(len(R)):
                    excess = max(0.0, R[t] - C)
                    h = max(0.0, h + a * excess - b * h)
                    mse += (_risk_from_h(h) - teacher[t]) ** 2
            mse /= denom
            if best is None or mse < best[0]:
                best = (mse, a, b)
    return {"alpha": float(best[1]), "beta": float(best[2]),
            "mse": float(best[0]), "V": float(V), "C": float(C),
            "provenance": CALIB_PROVENANCE}


def calibrate_all(teacher_fn=None):
    """校准全部行政区的 α,β 并落盘缓存（estimated）。"""
    global _PARAMS
    params = {}
    for d in shenzhen.DISTRICTS:
        params[d["id"]] = calibrate_district(d["id"], teacher_fn=teacher_fn)
    with open(PARAM_PATH, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)
    _PARAMS = params
    return params


# ============ 与现有 PREDICT 兼容的逐时接口 ============
def predict_one_surrogate(did, rainfall_seq, cum_seq, V, C):
    """给定某区完整降雨序列，返回代理风险序列与参数 provenance。"""
    params = _load_params().get(did)
    if params is None or "alpha" not in params:
        params = _default_params(next(x for x in shenzhen.DISTRICTS if x["id"] == did))
        prov = "assumed"
    else:
        prov = params.get("provenance", "estimated")
    h = 0.0
    risks = []
    for R in rainfall_seq:
        excess = max(0.0, R - C)
        h = max(0.0, h + params["alpha"] * excess - params["beta"] * h)
        risks.append(_risk_from_h(h))
    return {
        "risk_seq": [round(float(r), 4) for r in risks],
        "alpha": round(params["alpha"], 5),
        "beta": round(params["beta"], 5),
        "provenance": prov,
    }
