# -*- coding: utf-8 -*-
"""test_night_upgrades.py — 深夜新增模块单元测试

覆盖：surge 风暴潮谐波/增水、knowledge 知识库、decision 决策工单。
"""
import os
import sys
import unittest

# 使 backend.app 可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class SurgeModuleTest(unittest.TestCase):
    def test_harmonics_fit_and_predict(self):
        """潮汐谐波拟合可用 + 任意日期可推算。"""
        from backend.app import surge
        h = surge.fit_harmonics()
        self.assertIn("hko_cheungchau", h)
        # 推算一段
        from datetime import datetime
        pts = surge.predict_tide("hko_cheungchau", datetime(2026, 9, 1), hours=24)
        self.assertEqual(len(pts), 24)
        # 潮位应在合理范围（-1 ~ 4m CD 基准）
        for _, t in pts:
            self.assertTrue(-1.0 <= t <= 4.0, f"潮位越界: {t}")

    def test_harmonic_rmse_bound(self):
        """谐波拟合 RMSE 上界（精度门槛）。"""
        from backend.app import surge
        h = surge.fit_harmonics()
        for sid, meta in h.items():
            self.assertLess(meta["rmse"], 0.15, f"{sid} 拟合 RMSE 过高")

    def test_surge_estimate_physical(self):
        """增水参数化：气压越低、风越强 → 增水越大。"""
        from backend.app import surge
        s1, _ = surge.surge_estimate(30, 100, 980)
        s2, _ = surge.surge_estimate(40, 100, 950)
        self.assertGreater(s2, s1)
        # 距离越远 → 增水越小（风堆积项衰减）
        s_far, _ = surge.surge_estimate(40, 300, 950)
        self.assertLess(s_far, s2)


class KnowledgeModuleTest(unittest.TestCase):
    def test_cases_and_events_exist(self):
        """案例 + 历史事件库非空且结构完整。"""
        from backend.app import knowledge
        self.assertGreaterEqual(len(knowledge.CASES), 6)
        self.assertGreaterEqual(len(knowledge.HISTORICAL_FLOOD_EVENTS), 3)
        for ev in knowledge.HISTORICAL_FLOOD_EVENTS:
            self.assertIn("date", ev)
            self.assertIn("name", ev)

    def test_city_base_real_numbers(self):
        """城市底座真实统计（非演示）。"""
        from backend.app import knowledge
        base = knowledge.city_base()
        self.assertGreater(base["population"]["total_1km"], 1_000_000)
        self.assertGreater(base["buildings"]["total"], 50_000)
        self.assertEqual(base["exposure"]["flood_2019_points"], 206)

    def test_suggested_questions(self):
        """建议问题生成。"""
        from backend.app import knowledge
        qs = knowledge.suggested_questions()
        self.assertGreater(len(qs), 3)
        self.assertTrue(isinstance(qs[0], str))


class DecisionModuleTest(unittest.TestCase):
    def setUp(self):
        """隔离测试存储。"""
        from backend.app import decision
        self.decision = decision
        self._orig_store = decision._STORE
        decision._STORE = os.path.join(os.path.dirname(__file__), "..", "data", "_test_decisions.json")
        self.decision._save({"decisions": []})

    def tearDown(self):
        from backend.app import decision
        decision._STORE = self._orig_store
        if os.path.exists(decision._STORE.replace("_test_decisions", "_test_decisions")):
            pass
        # 清理测试文件
        tf = self._orig_store.replace("decisions.json", "_test_decisions.json")
        if os.path.exists(tf):
            os.remove(tf)

    def test_full_workflow(self):
        """提交 → 批准 → 执行 → 回评 全链路。"""
        d = self.decision.submit_suggestion(
            optimizer_run={"method": "test"},
            plan_summary="测试工单",
            control_actions=[{"district": "futian", "action": "pump", "value": 1.2}],
        )
        self.assertEqual(d["status"], "pending")
        sid = d["id"]
        # 批准
        appr = self.decision.approve(sid, "测试指挥")
        self.assertEqual(appr["status"], "executing")
        # 完成回评
        comp = self.decision.complete(sid, {"flood_peak_mm_actual": 30.0})
        self.assertEqual(comp["status"], "done")
        self.assertEqual(comp["review"]["actual_peak_mm"], 30.0)
        # 审计链
        self.assertGreaterEqual(len(comp["timeline"]), 3)

    def test_reject(self):
        """驳回流程。"""
        d = self.decision.submit_suggestion({}, "驳回测试", [])
        r = self.decision.reject(d["id"], "指挥", "方案不可行")
        self.assertEqual(r["status"], "rejected")
        self.assertEqual(r["reject_reason"], "方案不可行")

    def test_list_counts(self):
        """列表统计。"""
        self.decision.submit_suggestion({}, "待决1", [])
        self.decision.submit_suggestion({}, "待决2", [])
        lst = self.decision.list_decisions()
        self.assertEqual(lst["counts"]["pending"], 2)


if __name__ == "__main__":
    unittest.main()
