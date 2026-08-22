# -*- coding: utf-8 -*-
"""
轻量 LSTM（纯 NumPy 实现，Adam 优化 + BPTT）
---------------------------------------------------------------
用于城市内涝风险的「时序推演(SIMULATE)」：输入降雨/累计/脆弱性/排水/潮位的
时序特征，逐小时输出内涝风险 logit。
权重缓存到 data/lstm_weights.npz，首次训练后复用，避免每次启动重训。
"""
import os
import numpy as np

WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "lstm_weights.npz")


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _outer(a, b):
    return np.outer(a, b)


class LSTM:
    def __init__(self, input_dim, hidden=16, seed=7):
        self.n_in = input_dim
        self.H = hidden
        rng = np.random.default_rng(seed)
        s = 0.1
        self.Wf = rng.normal(0, s, (input_dim, hidden))
        self.Wi = rng.normal(0, s, (input_dim, hidden))
        self.Wg = rng.normal(0, s, (input_dim, hidden))
        self.Wo = rng.normal(0, s, (input_dim, hidden))
        self.Uf = rng.normal(0, s, (hidden, hidden))
        self.Ui = rng.normal(0, s, (hidden, hidden))
        self.Ug = rng.normal(0, s, (hidden, hidden))
        self.Uo = rng.normal(0, s, (hidden, hidden))
        self.bf = np.zeros(hidden)
        self.bi = np.zeros(hidden)
        self.bg = np.zeros(hidden)
        self.bo = np.zeros(hidden)
        self.Wy = rng.normal(0, s, (hidden,))
        self.by = 0.0

    # ---- forward ----
    def forward(self, X):
        T = X.shape[0]
        H = self.H
        h = np.zeros(H)
        c = np.zeros(H)
        cache = []
        ys = np.zeros(T)
        for t in range(T):
            x = X[t]
            f = _sigmoid(x @ self.Wf + h @ self.Uf + self.bf)
            i = _sigmoid(x @ self.Wi + h @ self.Ui + self.bi)
            g = np.tanh(x @ self.Wg + h @ self.Ug + self.bg)
            o = _sigmoid(x @ self.Wo + h @ self.Uo + self.bo)
            c_new = f * c + i * g
            h_new = o * np.tanh(c_new)
            y = h_new @ self.Wy + self.by
            cache.append((x, h.copy(), c.copy(), c_new.copy(), f, i, g, o, h_new.copy()))
            ys[t] = y
            h, c = h_new, c_new
        return ys, cache

    # ---- backward (BPTT) ----
    def backward(self, X, ys, cache, targets):
        T = X.shape[0]
        H = self.H
        p = _sigmoid(ys)
        dy = (p - targets) / T  # (T,)
        # grads
        gWf = np.zeros_like(self.Wf); gWi = np.zeros_like(self.Wi)
        gWg = np.zeros_like(self.Wg); gWo = np.zeros_like(self.Wo)
        gUf = np.zeros_like(self.Uf); gUi = np.zeros_like(self.Ui)
        gUg = np.zeros_like(self.Ug); gUo = np.zeros_like(self.Uo)
        gbf = np.zeros_like(self.bf); gbi = np.zeros_like(self.bi)
        gbg = np.zeros_like(self.bg); gbo = np.zeros_like(self.bo)
        gWy = np.zeros_like(self.Wy); gby = 0.0

        dh = np.zeros(H)
        dc = np.zeros(H)
        for t in range(T - 1, -1, -1):
            x, h_prev, c_prev, c_new, f, i, g, o, h_new = cache[t]
            # output path
            dh += dy[t] * self.Wy
            gWy += dy[t] * h_new
            gby += dy[t]
            # through h = o * tanh(c)
            do = dh * np.tanh(c_new)
            dc += dh * o * (1 - np.tanh(c_new) ** 2)
            # c = f*c_prev + i*g
            df = dc * c_prev
            di = dc * g
            dg = dc * i
            if t > 0:
                dc = dc * f  # carry to previous timestep
            do_pre = do * o * (1 - o)
            df_pre = df * f * (1 - f)
            di_pre = di * i * (1 - i)
            dg_pre = dg * (1 - g ** 2)
            gWf += _outer(x, df_pre); gUf += _outer(h_prev, df_pre); gbf += df_pre
            gWi += _outer(x, di_pre); gUi += _outer(h_prev, di_pre); gbi += di_pre
            gWg += _outer(x, dg_pre); gUg += _outer(h_prev, dg_pre); gbg += dg_pre
            gWo += _outer(x, do_pre); gUo += _outer(h_prev, do_pre); gbo += do_pre
            dh = df_pre @ self.Uf + di_pre @ self.Ui + dg_pre @ self.Ug + do_pre @ self.Uo
        return {
            "Wf": gWf, "Wi": gWi, "Wg": gWg, "Wo": gWo,
            "Uf": gUf, "Ui": gUi, "Ug": gUg, "Uo": gUo,
            "bf": gbf, "bi": gbi, "bg": gbg, "bo": gbo,
            "Wy": gWy, "by": gby,
        }

    def _params(self):
        return ["Wf", "Wi", "Wg", "Wo", "Uf", "Ui", "Ug", "Uo",
                "bf", "bi", "bg", "bo", "Wy", "by"]

    def fit(self, Xs, Ys, epochs=40, lr=0.01, l2=1e-5):
        m = len(Xs)
        for ep in range(epochs):
            # Adam state
            if ep == 0:
                self._m = {k: np.zeros_like(getattr(self, k)) for k in self._params()}
                self._v = {k: np.zeros_like(getattr(self, k)) for k in self._params()}
            for b in range(m):
                ys, cache = self.forward(Xs[b])
                grads = self.backward(Xs[b], ys, cache, Ys[b])
                for k in self._params():
                    g = grads[k] + l2 * getattr(self, k)
                    self._m[k] = 0.9 * self._m[k] + 0.1 * g
                    self._v[k] = 0.999 * self._v[k] + 0.001 * (g ** 2)
                    mhat = self._m[k] / (1 - 0.9 ** (ep + 1))
                    vhat = self._v[k] / (1 - 0.999 ** (ep + 1))
                    setattr(self, k, getattr(self, k) - lr * mhat / (np.sqrt(vhat) + 1e-8))

    def predict_seq(self, X):
        ys, _ = self.forward(np.asarray(X, dtype=float))
        return _sigmoid(ys)

    def save(self, path=WEIGHTS_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez(path, **{k: getattr(self, k) for k in self._params()})

    def load(self, path=WEIGHTS_PATH):
        if not os.path.exists(path):
            return False
        d = np.load(path)
        for k in self._params():
            setattr(self, k, d[k])
        return True
