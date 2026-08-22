# -*- coding: utf-8 -*-
"""轻量时序模型（LSTM / Transformer 可切换，§3.1）。
输出：对未来 HORIZON 小时的内涝风险轨迹（多步），可据此算预警提前量。"""
import torch
import torch.nn as nn


class LSTMSeq(nn.Module):
    def __init__(self, input_dim, hidden=32, layers=1, dropout=0.0, horizon=24):
        super().__init__()
        self.horizon = horizon
        self.lstm = nn.LSTM(input_dim, hidden, num_layers=layers,
                            batch_first=True, dropout=dropout)
        self.head = nn.Linear(hidden, horizon)     # 输出 horizon 个未来风险

    def forward(self, x):
        out, _ = self.lstm(x)          # (B, T, H)
        h = out[:, -1]                  # 取最后时刻状态
        return torch.sigmoid(self.head(h))   # (B, horizon)


class TransformerSeq(nn.Module):
    def __init__(self, input_dim, hidden=32, layers=1, dropout=0.0, nhead=4, horizon=24):
        super().__init__()
        self.horizon = horizon
        self.embed = nn.Linear(input_dim, hidden)
        enc = nn.TransformerEncoderLayer(d_model=hidden, nhead=nhead,
                                         dim_feedforward=hidden * 4,
                                         dropout=dropout, batch_first=True)
        self.enc = nn.TransformerEncoder(enc, num_layers=layers)
        self.head = nn.Linear(hidden, horizon)

    def forward(self, x):
        x = self.embed(x)
        x = self.enc(x)
        h = x[:, -1]
        return torch.sigmoid(self.head(h))   # (B, horizon)


def build_model(cfg):
    kw = dict(input_dim=cfg["input_dim"], hidden=cfg["hidden"], layers=cfg["layers"],
              dropout=cfg["dropout"], horizon=cfg.get("horizon", 24))
    if cfg["type"] == "transformer":
        return TransformerSeq(**kw)
    return LSTMSeq(**kw)
