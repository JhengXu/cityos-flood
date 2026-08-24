# -*- coding: utf-8 -*-
"""旧代理标签网络训练器，仅供显式历史复现。"""
import os
import numpy as np
import torch
import torch.nn as nn

from . import config
from .model import build_model


def set_seed(seed=config.SEED):
    torch.manual_seed(seed)
    np.random.seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def train(split, cfg=None, verbose=True, save_path=None):
    cfg = cfg or config.MODEL
    set_seed(config.SEED)
    Xtr, Ytr = split["train"]
    Xva, Yva = split["val"]

    model = build_model(cfg)
    opt = torch.optim.Adam(model.parameters(), lr=cfg["lr"])
    lossfn = nn.BCELoss()
    torch.set_grad_enabled(True)

    n = len(Xtr)
    for ep in range(cfg["epochs"]):
        model.train()
        perm = torch.randperm(n)
        tot = 0.0
        for i in range(0, n, cfg["batch_size"]):
            idx = perm[i:i + cfg["batch_size"]]
            Xb = torch.tensor(Xtr[idx]); yb = torch.tensor(Ytr[idx])   # (B, horizon)
            opt.zero_grad()
            p = model(Xb)                       # (B, horizon)
            loss = lossfn(p, yb)
            loss.backward()
            if cfg.get("clip_grad"):
                nn.utils.clip_grad_norm_(model.parameters(), cfg["clip_grad"])
            opt.step()
            tot += loss.item() * len(idx)
        # 验证（事件数少时 val 可能为空，需防止对空张量计算损失）
        if len(Xva):
            model.eval()
            with torch.no_grad():
                pv = model(torch.tensor(Xva))
                val_bce = lossfn(pv, torch.tensor(Yva)).item()
            vb_str = f"{val_bce:.4f}"
        else:
            vb_str = "n/a(empty val)"
        if verbose and (ep % 10 == 0 or ep == cfg["epochs"] - 1):
            print(f"  epoch {ep:3d}  train_bce {tot/n:.4f}  val_bce {vb_str}")

    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        torch.save(model.state_dict(), save_path)
        if verbose:
            print(f"  ✓ 模型已保存: {save_path}")
    return model


def load_model(cfg=None):
    cfg = cfg or config.MODEL
    model = build_model(cfg)
    model.load_state_dict(torch.load(config.CKPT_PATH, map_location="cpu"))
    model.eval()
    return model
