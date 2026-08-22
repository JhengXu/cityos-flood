# -*- coding: utf-8 -*-
"""全局配置：固定随机种子 + 数据切分 + 模型超参（可复现，对应方案 §3.2）"""
import os

# ============ 可复现性（§3.2：固定随机种子 / 固定数据切分）============
SEED = 42
SPLIT = {"train": 0.6, "val": 0.2, "test": 0.2}   # 按事件/时间切分，避免泄漏
DISTRICT_SPLIT_MODE = "by_event"                   # by_event | by_time

# ============ 数据（§3.1 真实数据接入缝）============
REAL_LABELS_CSV = os.path.join(
    os.path.dirname(__file__), "..", "backend", "data", "flood_labels.csv"
)   # 真实积水点台账: date,district_id,rainfall_mm_h,flooded  (接入即替换合成标签)
USE_REAL_LABELS_IF_AVAILABLE = True
SEQ_LEN = 24          # 时序窗口
HORIZON = 24          # 未来小时
FEATURES = ["excess", "cum24", "vuln", "drainage", "tide"]   # 5 维特征

# ============ 模型（§3.1 LSTM/Transformer 时序）============
MODEL = {
    "type": "lstm",          # lstm | transformer
    "input_dim": len(FEATURES),
    "hidden": 32,
    "layers": 1,
    "dropout": 0.0,
    "lr": 1e-3,
    "epochs": 40,
    "batch_size": 64,
    "clip_grad": 1.0,
    "horizon": HORIZON,      # 多步输出（未来 HOURS 小时），可算提前量
}

# ============ 评估 / 阈值（§3.2 量化指标）============
RISK_THRESHOLD = 0.40        # 判定"发生内涝"的概率阈值（对应等级中+）
LEAD_TIME = {"min": 1, "max": 24}

# ============ 路径 ============
CACHE_DIR = os.path.join(os.path.dirname(__file__), "outputs")
CKPT_PATH = os.path.join(CACHE_DIR, "model.pt")
REPORT_PATH = os.path.join(CACHE_DIR, "report.json")
