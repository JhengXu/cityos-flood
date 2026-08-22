# -*- coding: utf-8 -*-
"""
CITY OS · 城市内涝真实数据监督训练 + 可复现验证（§3.1 + §3.2）
用法：
    python -m ml.main train        # 训练
    python -m ml.main evaluate     # 评估 + 历史回放 + 输出量化指标
    python -m ml.main all          # 训练 + 评估
"""
import sys

from . import config
from . import dataset as ds
from . import train as tr
from . import evaluate as ev


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("train", "all"):
        print("=== 1. 构建数据集（固定种子/切分）===")
        d = ds.load()
        for k in ["train", "val", "test"]:
            Xk, Yk = d[k]
            print(f"  {k:6s} {len(Xk):5d} 样本  标签均值 {Yk.mean():.3f}")
        print("=== 2. 训练 LSTM ===")
        tr.train(d)
    if cmd in ("evaluate", "all"):
        print("=== 3. 评估 + 历史回放 ===")
        rep = ev.run()
        print(ev.fmt_report(rep))
        print(f"\n完整报告已写入: {config.REPORT_PATH}")


if __name__ == "__main__":
    main()
