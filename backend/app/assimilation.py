# -*- coding: utf-8 -*-
"""
数据同化钩子（理论 #6）
----------------------------------------------------------------
新观测（真实水位/风险）抵达时，用残差修正物理代理的隐状态 h：
    h_corrected(t*) = max[0, h(t*) + K·(obs − h_predicted(t*))]
随后从 t* 重新推演（状态被钉到观测）。

K 为卡尔曼式增益（assumed）。这是把“真实观测”喂回世界模型的入口：
- 观测来自真实积涝点/水位站（station_district_map.csv 就位后）。
- 修正的是 #2 的物理代理隐状态，而非端到端黑箱。
"""
from . import hazard

DEFAULT_K = 0.3  # 增益（assumed；可用 EnKF/历史残差标定）


def assimilate_at(district_id, rseq, observed_value, at_hour, K=DEFAULT_K, C=None):
    """在 at_hour 处注入观测，残差修正隐状态并从该时刻重推。

    返回 {raw_h, corrected_h, raw_risk, corrected_risk, residual, gain, provenance}。
    observed_value 为真实水深代理（与 h 同量纲）。
    """
    params = hazard._load_params().get(district_id)
    if params is None or "alpha" not in params:
        from . import shenzhen
        d = next(x for x in shenzhen.DISTRICTS if x["id"] == district_id)
        params = hazard._default_params(d)
    C = C if C is not None else params.get("C", 30.0)

    h = 0.0
    hs = []
    for R in rseq:
        excess = max(0.0, R - C)
        h = max(0.0, h + params["alpha"] * excess - params["beta"] * h)
        hs.append(h)

    if at_hour < 0 or at_hour >= len(hs):
        at_hour = len(hs) - 1
    predicted = hs[at_hour]
    residual = observed_value - predicted

    # 修正并重新推演 at_hour 之后
    hc = max(0.0, predicted + K * residual)
    hs_corr = hs[:at_hour] + [hc]
    for t in range(at_hour + 1, len(rseq)):
        excess = max(0.0, rseq[t] - C)
        hc = max(0.0, hc + params["alpha"] * excess - params["beta"] * hc)
        hs_corr.append(hc)

    raw_risk = [hazard._risk_from_h(x) for x in hs]
    corr_risk = [hazard._risk_from_h(x) for x in hs_corr]
    return {
        "district_id": district_id,
        "at_hour": at_hour,
        "raw_h": [round(x, 4) for x in hs],
        "corrected_h": [round(x, 4) for x in hs_corr],
        "raw_risk": [round(x, 4) for x in raw_risk],
        "corrected_risk": [round(x, 4) for x in corr_risk],
        "residual": round(residual, 4),
        "gain": K,
        "provenance": "estimated(残差修正隐状态；增益 K=0.3 assumed，待 EnKF 标定)",
        "note": "观测注入后，物理代理状态被钉到观测并从该时刻重推；观测应来自真实积涝点/水位站。",
    }
