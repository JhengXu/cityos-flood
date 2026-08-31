# -*- coding: utf-8 -*-
"""ml_model_defs — 供 pickle 反序列化的模型类定义。

train_*_v2.py 训练的自定义估计器（EnsembleHistGB）必须在这里定义，
后端 ml_models.py 才能 pickle.load。类结构变更会破坏旧模型反序列化，
因此保持与训练脚本完全一致。
"""
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import f1_score


class EnsembleHistGB:
    """多 seed HistGB 平均 + F1 阈值优化（与 train_landslide_warning_v2.py 一致）。"""

    def __init__(self, seeds=(42, 7, 2024), threshold=None):
        self.seeds = seeds
        self.models = []
        self.threshold = threshold

    def fit(self, X, y):
        for s in self.seeds:
            m = HistGradientBoostingClassifier(
                max_iter=600, learning_rate=0.05, max_depth=6,
                min_samples_leaf=25, l2_regularization=1.0,
                random_state=s, class_weight='balanced',
                early_stopping=True, validation_fraction=0.15,
            )
            m.fit(X, y)
            self.models.append(m)
        if self.threshold is None:
            p = self.predict_proba(X)[:, 1]
            best_t, best_f1 = 0.5, 0
            for t in np.arange(0.25, 0.75, 0.025):
                f1 = f1_score(y, (p >= t).astype(int))
                if f1 > best_f1:
                    best_f1, best_t = f1, t
            self.threshold = float(best_t)
        return self

    def predict_proba(self, X):
        ps = np.mean([m.predict_proba(X) for m in self.models], axis=0)
        return ps

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= self.threshold).astype(int)
