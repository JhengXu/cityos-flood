#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
e2e_journey.py — 端到端用户旅程模拟（10 步指挥中心操作流）
用法：cd backend && python scripts/e2e_journey.py
"""
import json
import sys
import time
import urllib.request

BASE = "http://localhost:8000"


def get(url, timeout=90):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post(url, body, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main():
    print("═" * 60)
    print(" 端到端用户旅程（指挥中心完整操作流）")
    print("═" * 60)
    steps = []

    t0 = time.time()
    bf = get(f"{BASE}/api/knowledge/briefing")
    steps.append(("① 看今日简报", bf.get("mode") in ("llm", "local") and len(bf.get("briefing", "")) > 50, f"{time.time()-t0:.1f}s"))

    live = get(f"{BASE}/api/live")
    steps.append(("② 检查告警流", isinstance(live.get("alerts"), list), f"{len(live.get('alerts', []))} 条"))

    t0 = time.time()
    ans = post(f"{BASE}/api/knowledge/ask", {"question": "现在有什么风险？"})
    steps.append(("③ 问助手", len(ans.get("answer", "")) > 30, f"{time.time()-t0:.1f}s"))

    steps.append(("④ D-1 提前预警", len(live.get("advance_warnings", [])) >= 1, ""))

    t0 = time.time()
    wi = get(f"{BASE}/api/cascade/whatif?dist_shift_km=-100")
    steps.append(("⑤ What-if 推演", "delta" in wi, f"{time.time()-t0:.1f}s"))

    t0 = time.time()
    sub = post(f"{BASE}/api/decisions/submit", {
        "plan_summary": "E2E：沿海区预置排水", "control_actions": [],
        "expected_flood_peak_mm": 20.0})
    steps.append(("⑥ 提交决策建议", "id" in sub, f"{time.time()-t0:.1f}s"))

    appr = post(f"{BASE}/api/decisions/approve", {"decision_id": sub["id"], "by": "E2E"})
    steps.append(("⑦ 人工批准", appr.get("status") == "executing", ""))

    comp = post(f"{BASE}/api/decisions/complete", {
        "decision_id": sub["id"], "flood_peak_mm_actual": 18.0})
    steps.append(("⑧ 效果回评", "review" in comp, ""))

    ev = get(f"{BASE}/api/knowledge/events")
    steps.append(("⑨ 历史事件库", ev.get("n") == 5, ""))

    t0 = time.time()
    ans2 = post(f"{BASE}/api/knowledge/ask", {
        "question": "那场增水多少？",
        "history": [{"role": "user", "content": "苏拉台风风暴潮"},
                    {"role": "assistant", "content": "苏拉：潮位 2.63m，增水 1.13m。"}]})
    steps.append(("⑩ 多轮指代追问", len(ans2.get("answer", "")) > 30, f"{time.time()-t0:.1f}s"))

    n = 0
    for name, ok, detail in steps:
        print(f"  {'✓' if ok else '✗'} {name} {detail}")
        n += ok
    print(f"\n旅程完成度: {n}/{len(steps)}")
    return n == len(steps)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
