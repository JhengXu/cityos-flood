# -*- coding: utf-8 -*-
"""CITY OS · 遗留代理标签时序实验复现工具。

默认拒绝运行。只有显式确认 ``--allow-proxy-labels`` 后才会复现旧实验；所得指标
不能作为真实事件预测能力证据，也不影响在线守恒状态空间模型。

用法：
    python -m ml.main train --allow-proxy-labels
    python -m ml.main evaluate --allow-proxy-labels
    python -m ml.main all --allow-proxy-labels
"""
import argparse

from . import config
from . import dataset as ds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cmd", nargs="?", choices=("train", "evaluate", "all"), default="all")
    parser.add_argument(
        "--allow-proxy-labels",
        action="store_true",
        help="仅复现历史代理标签实验；输出不可用于真实预测能力声明",
    )
    args = parser.parse_args()
    if not args.allow_proxy_labels:
        parser.error(
            "缺少独立积水深度标签，训练/评估默认关闭。仅复现历史实验时才可添加 "
            "--allow-proxy-labels。"
        )
    cmd = args.cmd
    print("警告：本次运行使用规则派生代理标签，所有指标均无效于真实预测能力声明。")
    if cmd in ("train", "all"):
        from . import train as tr

        print("=== 1. 构建历史代理标签数据集（固定种子/切分）===")
        d = ds.load(allow_proxy_labels=True)
        for k in ["train", "val", "test"]:
            Xk, Yk = d[k]
            print(f"  {k:6s} {len(Xk):5d} 样本  标签均值 {Yk.mean():.3f}")
        print("=== 2. 训练 LSTM ===")
        tr.train(d)
    if cmd in ("evaluate", "all"):
        from . import evaluate as ev

        print("=== 3. 评估 + 历史回放 ===")
        rep = ev.run(allow_proxy_labels=True)
        print(ev.fmt_report(rep))
        print(f"\n完整报告已写入: {config.REPORT_PATH}")


if __name__ == "__main__":
    main()
