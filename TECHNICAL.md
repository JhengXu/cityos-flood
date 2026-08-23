# CITY OS · 深圳城市内涝预测 — 技术文档 v2

> 面向：团队内部 / 评委路演 / 后续开发
> 版本：v2（2026-08）

---

## 0. 一句话

一个以深圳为范例的**城市内涝预测与情景推演产品**：实时感知降雨与城市特征 → 用「物理+机器学习混合模型」预测分区分时内涝风险 → 用 **LSTM 时序模型**对「台风+大潮」等 What-if 情景做全城推演 → 给出**泵站调度与分级预警**，形成 SENSE → UNDERSTAND → PREDICT → SIMULATE → DECIDE → ACT 的完整闭环，对齐 CITY OS 的「世界行为模型」叙事。

---

## 1. 数据真实性说明（先回答"是不是真数据"）

| 数据项 | 状态 | 来源 | 说明 |
|--------|------|------|------|
| 小时降雨（分区） | ✅ **真实、实时** | Open-Meteo 多点预报 API（免费、无需 Key） | 30 个街道级采样点批量拉取，`data_source=open-meteo-multi-point` |
| 海拔 | ✅ **真实** | Open-Elevation DEM API | 10 个区中心点，首次联网批量获取并缓存到 `data/elevation_cache.json` |
| 历史内涝易发指数 | ✅ **真实** | 公开报道的历史内涝事件库（`events.py`，附出处） | 2018 山竹 / 2023"9·7"极端暴雨 / 2024 多场事件聚合 |
| 排水防涝设计标准 | ✅ 真实推导 | 真实 OSM 道路网密度 + WorldCover 不透水 + DEM 低洼 | 由 `gisreal.py` 派生；权威排水管网台账可精确覆盖 |
| 低洼比例 / 临海度 | ✅ 真实 | 真实 DEM(SRTM) | 低洼=elev<10m 占比；临海=低洼+不透水派生 |
| 不透水率(下垫面) | ✅ 真实 | ESA WorldCover 建成密度格网 | 19968 格点分区均值 |
| 泵站能力台账 | ⚠️ 代表性估算 | — | 应替换为水务局真实泵站数据 |
| LSTM 模型权重 | ✅ 真实训练产物 | 本地合成数据训练并缓存 | `data/lstm_weights.npz`（详见 §4） |

> 关键结论：**天气/高程/历史事件/排水/下垫面均为真实或真实推导**（DEM/WorldCover/OSM）；仅泵站能力台账为代表性估算，留有替换缝。当前深圳实时降雨很小（约 0~0.6 mm/h），所以仪表盘实时风险多为「低」——这是真实情况，不是假数据。要看模型能力，请用 SIMULATE 情景沙盘。

---

## 2. 系统架构

```
┌────────────────────────────────────────────────────────────┐
│  前端  React 18 + Vite (生产构建单文件 bundle)                │
│  Leaflet(地图) / Recharts(图表)                              │
│  http://localhost:4173  (vite preview, /api 代理到后端)      │
└───────────────┬────────────────────────────────────────────┘
                │ /api/*  (同源代理)
┌───────────────▼────────────────────────────────────────────┐
│  后端  FastAPI (Python)  http://localhost:8000               │
│                                                            │
│  数据层      天气(多点Open-Meteo) / 高程(Open-Elevation)      │
│              历史事件库 / 深圳10区+30街道采样点               │
│  模型层      v1 混合物理模型 (逐小时)                         │
│              v2 LSTM 时序推演模型 (NumPy自实现)              │
│  应用层      simulate引擎 / dispatch调度 / 预警推送           │
└───────────────┬────────────────────────────────────────────┘
                │ 外网 HTTPS
      ┌─────────┴──────────┬─────────────────┐
      ▼                    ▼                 ▼
 Open-Meteo          Open-Elevation     ALERT_WEBHOOK(可选)
 30点降雨网格          真实DEM高程         短信/APP/大屏
```

### 目录结构
```
cityos-flood/
├── README.md                     # 快速上手
├── TECHNICAL.md                  # 本文档
├── run.sh                        # 一键启动
├── backend/
│   ├── requirements.txt
│   ├── data/                     # 运行期生成：高程缓存 + LSTM权重
│   └── app/
│       ├── main.py               # FastAPI 路由（全部接口）
│       ├── shenzhen.py           # 10区特征 + 30街道采样点
│       ├── weather.py            # 多点降雨网格 + 空间降尺度
│       ├── geo.py                # 真实高程（缓存）
│       ├── events.py             # 历史内涝事件库 + 标注CSV接入缝
│       ├── model.py              # v1混合模型 + v2 LSTM序列模型
│       ├── lstm.py               # NumPy LSTM（Adam/BPTT，权重缓存）
│       ├── simulate.py           # What-if 情景引擎 + 预设
│       └── dispatch.py           # 泵站调度 + 预警推送
└── frontend/
    ├── index.html / vite.config.js / package.json
    └── src/
        ├── main.jsx              # 入口 + 全局错误兜底
        ├── api.js                # 所有接口封装
        ├── App.jsx               # 页面组装
        ├── styles.css
        └── components/           # Header/CityOverview/RiskMap/
                                   # RainfallChart/DistrictPanel/ModelInfo/
                                   # ScenarioPanel/SimulateChart/
                                   # DispatchPanel/EventsPanel/ErrorBoundary
```

---

## 3. 数据管线

### 3.1 多点降雨网格 + 街道级空间降尺度（`weather.py`）
- `shenzhen.py` 定义了 **30 个街道级采样点**（每区 3 个，如福田=市民中心/华强北/车公庙）。
- `weather.fetch_grid()` 用 Open-Meteo 的**多坐标一次请求**（`latitude`/`longitude` 逗号分隔）拉取全部采样点的小时降雨（含过去 24h 实况 + 未来 72h 预报）。
- `downscaled_forecast()` 按区聚合（区内 3 点均值）得到**分区分时降雨**，并对每区计算**前 24h 累计降雨** `cum24`（管网/土壤饱和度代理）。
- 离线降级：外网不可用时生成带空间差异的合成台风暴雨（沿海略强），保证路演断网也能跑。

### 3.2 真实高程（`geo.py`）
- Open-Elevation 批量查询 10 个区中心海拔，结果缓存到 `backend/data/elevation_cache.json`（只首次联网）。
- 已缓存真实值示例：福田 7m、罗湖 19m、南山 9m、宝安 -2m（填海低地）。

### 3.3 历史事件库（`events.py`）
- 5 个真实事件（2018 山竹、2023"9·7"、2024-04、2024-08、2014"3·30"），每条含日期、影响区、强度、出处。
- `historical_index()` 按影响频次聚合出每区历史易发指数（0-1），覆盖到模型特征。
- `load_real_labels(path)` 预留：放入真实积水点台账 CSV（`date,district_id,rainfall_mm_h,flooded`）即可切换为真实监督训练。

---

## 4. 预测模型原理（核心）

### 4.1 v1 混合物理模型（逐小时、可解释）

对每个区 d、每小时 t：

```
excess   = max(0, R_t − C_d)          # R: 降雨强度(mm/h)  C: 该区排水设计标准(mm/h)
V_d      = Σ w·f(低洼, 不透水, 地势, 历史, 临海)   # 城市本底脆弱性 (0-1)
x        = [ excess/50,  V·excess/50,  V,  cum24/150 ]
p        = sigmoid( w·x + b )          # 内涝风险概率
```

- **物理含义**：降雨只有超过排水能力（超额）才产生内涝；超额叠加在本底脆弱性越高的区越危险；前期累计降雨降低管网余量。
- **训练方式**：由一个"物理教师"函数生成大量合成样本（暴雨强度、脆弱性、排水标准、累计量全空间采样 + 标签噪声），用**梯度下降（sigmoid 回归）**在线拟合权重，使模型既符合物理又可解释。
- **可解释性**：每条预测给出四个特征的贡献 `contrib` 与主因 `driver`（降雨超排 / 高危叠加 / 本底脆弱 / 前期饱和）。

### 4.2 v2 LSTM 时序推演模型（SIMULATE 引擎核心）

- **输入**：每个时刻 t 的 5 维特征 `[excess/60, cum/200, V, C/40, tide]`，按时间顺序输入。
- **结构**：单层 LSTM，隐层 16（纯 NumPy 实现，Adam 优化 + BPTT，见 `lstm.py`），输出逐小时风险 logit → sigmoid → 概率。
- **训练**：物理教师模型（v1）对合成暴雨序列逐小时标注 → 600 条序列 × 30 步 × 35 epoch 训练；权重保存 `data/lstm_weights.npz`，**启动即加载，不重复训练**。
- **为什么用 LSTM**：它能学到**时间动力学**——管网饱和的累积效应、降雨峰值的滞后响应、前期降雨对后期风险的放大。这比逐小时独立预测更接近"城市行为"。

### 4.3 潮位模型（台风+大潮的关键）
- 基线潮位：半日潮近似 `tide = 0.5 + 0.2·sin(2π·t/12.4)`（深圳为半日潮港）。
- 情景可叠加潮位抬升 `tide_raise`，临海区（coastal 高）风险放大更明显。

---

## 5. SIMULATE 推演引擎（`simulate.py`）

### 5.1 情景参数
| 参数 | 含义 | 默认/示例 |
|------|------|-----------|
| `rainfall_multiplier` | 实时降雨整体放大倍数 | 1.3（台风） |
| `add_peak_mm` | 在 `peak_offset_h` 处叠加的高斯暴雨峰值(mm/h) | 22 |
| `peak_offset_h` | 峰值出现的时刻偏移 | 20 |
| `drainage_factor` | 泵站/排水效能（<1 表示降效，有效排水 = C×factor） | 0.85 |
| `tide_raise` | 潮位抬升（叠加到半日潮） | 0.35 |

### 5.2 推演流程（对每个区）
1. 取该区真实降尺度降雨为**基线** → LSTM 前向 → 基线风险轨迹。
2. 应用情景：`scenario_rain[t] = rain[t]×mult + 空间权重×add_peak×高斯(t)`；其中**空间权重 = 0.5 + 0.9×coastal**（沿海受台风雨更重，更真实且增强区分度）。
3. 有效排水 = `C × drainage_factor`；潮位 = 基线 + `tide_raise`。
4. 用修改后的特征重跑 LSTM → **情景风险轨迹**。
5. 输出：基线 vs 情景逐小时概率、各自峰值（等级/时刻/概率）、风险增量 `delta_prob`、全城最危险区。

### 5.3 预设情景
| preset | 说明 |
|--------|------|
| `baseline` | 现状预报（基线） |
| `typhoon_tide` | 台风 + 天文大潮（mult 1.3 / +22mm / 泵效85% / 潮位+0.35）→ 沿海区高、内陆中 |
| `pump_failure` | 泵站降效 65%（排水×0.65）→ 全市整体抬升 |
| `extreme` | 极端特大暴雨（mult 2.2 / +70mm）→ 全市极高 |

---

## 6. ACT 闭环（`dispatch.py`）

- **泵站台账**：每区泵站等级(1-5)、等效排涝能力(m³/s)、泵站/前置点清单（代表性估算）。
- **分级处置建议**（随风险等级递增）：
  - ≥低：排涝单元待命
  - ≥中：预置移动泵车
  - ≥高：泵站开至 60%+ 负荷、低洼路段交通管制、加密巡查
  - ≥极高：启动应急排涝预案、跨区泵车支援、开放避险场所、停课停工指引
  - 潮位高：关闭沿河/沿海闸门防潮水顶托倒灌
- **预警下发**：生成分级预警（APP/短信/应急大屏/网格员四通道）→ `push_alert()` 写入 `/tmp/cityos_alerts.log`；若设置环境变量 `ALERT_WEBHOOK` 则同时 POST 到真实通道。

---

## 7. API 接口文档

| 接口 | 方法 | 参数 | 返回要点 |
|------|------|------|----------|
| `/api/health` | GET | — | 服务状态 |
| `/api/districts` | GET | — | 10 区：中心点/排水/真实高程/历史指数/脆弱性 |
| `/api/forecast` | GET | `forecast_days`(1-7) | 降尺度后分区分时降雨 + cum24 |
| `/api/predict` | GET | `forecast_days` | 完整预测：小时轴、城市降雨、分区系列（概率/等级/主因/超额）、总览、模型信息 |
| `/api/events` | GET | — | 真实历史内涝事件 + 历史指数 |
| `/api/scenarios` | GET | — | 预设情景列表 |
| `/api/simulate` | GET | `preset` 或 5 个情景参数 | 基线 vs 情景推演、预警 |
| `/api/simulate` | POST | JSON 情景体 | 同上（自定义） |
| `/api/dispatch` | POST | `{preset\|scenario}` | 执行推演 + 下发预警，返回推送状态 |
| `/api/alerts` | GET | `limit` | 已下发预警记录 |

### `/api/predict` 返回结构（节选）
```jsonc
{
  "data_source": "open-meteo-multi-point | fallback-sample",
  "hours": ["2026-08-21T17:00", ...],        // 未来逐小时
  "rainfall": [0.02, 0.0, ...],              // 城市级降雨
  "districts": [{
    "id": "baoan", "name": "宝安区", "center": [22.555, 113.88],
    "drainage": 25.0, "elevation": -2.0, "historical_index": 0.95,
    "vulnerability": 0.757,
    "rainfall": [...], "cum24": [...],        // 该区降尺度降雨
    "series": [{ "prob": 0.36, "level": 1, "level_label": "低",
                 "driver": "区域本底脆弱性", "excess": 0, "time": "..." }, ...],
    "current": {...}, "peak": { "time": "...", "level_label": "...", ... }
  }],
  "overview": { "current_risk_level": 1, "high_risk_now": [], "peak_time": "...",
                "alert_count": 0, "alerts": [...] },
  "model": { "hybrid_weights": {...}, "hybrid_feature_importance": {...},
             "hybrid_feature_labels": {...}, "lstm": {...}, "levels": [...], "notes": "..." }
}
```

---

## 8. 前端界面详解（每个模块在做什么）

| 组件 | 数据来源 | 功能 |
|------|----------|------|
| `Header` | `/api/predict` | 品牌 + 数据源徽章（●实时天气 / ○样例）+ 刷新 |
| `CityOverview` | `overview` | 4 张卡：当前城市风险、当前高风险区、风险峰值时刻、预警条数；+ 最高优先级预警条 |
| `Timebar` | `hours` | 时间滑块 + 「自动推演」逐小时播放（演示用） |
| `RiskMap` | `districts[].series` | Leaflet 暗色地图；每区 CircleMarker：颜色=风险等级、半径=概率；Popup 显示该区排水/脆弱性/超额/主因/峰值；底部图例 |
| `RainfallChart` | `rainfall` | 城市小时降雨曲线 + 全市排水均值参考线（橙虚线）；点击曲线可跳转时间轴 |
| `DistrictPanel` | `series` | 按当前时刻风险概率排序的 10 区榜单：等级徽章/概率/主因/峰值 |
| `ModelInfo` | `model` | 模型名、混合模型特征权重、特征重要性条形图、风险分级色板、LSTM 配置、数据说明 |
| `ScenarioPanel` | `/api/scenarios` | 预设按钮（台风+大潮/泵站降效/极端暴雨/基线）+ 自定义滑块（降雨放大/额外峰值/泵站效能/潮位）+ 运行推演 |
| `SimulateChart` | `/api/simulate` | 选定某区，绘制**基线 vs 情景**两条风险概率轨迹曲线，底部给出峰值对比 |
| `DispatchPanel` | `simulate.alerts` | 预警列表（等级/区/时刻/消息/通道/处置建议）+ 「一键下发预警」按钮 + 已下发记录 |
| `EventsPanel` | `/api/events` | 真实历史内涝事件时间线（含出处），佐证模型标定依据 |
| `ErrorBoundary`(全局+局部) | — | 任何渲染错误显示为红色文字而非白屏；地图单独容错，瓦片不可用不影响其余功能 |

**页面信息流**：`App` 挂载时并行拉取 `/api/predict`（仪表盘）与 `/api/simulate?preset=typhoon_tide`（沙盘首屏）→ 数据下发给各组件；时间轴/情景变化时仅局部更新。

---

## 9. 运行与部署

```bash
# 一键
bash run.sh
# 或分开
cd backend  && python3 -m venv .venv && source .venv/bin/activate \
           && pip install -r requirements.txt \
           && uvicorn app.main:app --port 8000
cd frontend && npm install && npm run build && npm run preview   # :4173
```
- 前端生产构建为**单文件 bundle**，适合代理/iframe 环境（dev server 的 ESM 多请求在受限环境会黑屏，故推荐 preview）。
- 页面：`http://localhost:4173`；API 由 preview 代理到 `:8000`。
- 预警推送：`ALERT_WEBHOOK=https://... npm run preview` 后，一键下发会 POST 预警 JSON。

---

## 10. 已知限制（诚实清单）

1. 泵站能力台账为代表性估算（排水/下垫面已换真实数据；泵站待水务局台账替换）。
2. LSTM 训练数据为**物理教师合成的样本**，不是真实内涝过程监督（真实台账接入后应重训）。
3. 降雨降尺度为**街道采样点均值**，未耦合雷达外推/数值预报高分辨率格点。
4. 潮位为简化半日潮模型，未接入天文潮汐表与风暴潮数值预报。
5. 风险分级阈值为工程标定，未经历史事件 AUC 校准。

## 11. Roadmap（晋级比赛方向）

1. 接入真实排水管网/DEM/下垫面/积水点台账 → 监督重训 LSTM（`events.load_real_labels` 已留口）。
2. 降雨格点化（雷达 + 数值预报 + IDW/Kriging）做真正街道级。
3. 潮位接天文潮汐表 + 风暴潮耦合；引入管网水力模型（SWMM 类）。
4. 处置后反馈闭环（泵站开启→风险回落推演），形成「感知-预测-推演-决策-执行-复盘」完整循环。
5. 多城市、多灾种扩展。
