# CITY OS · 深圳城市内涝预测 v2

> 爱化身科技 **CITY OS 产品型 CEO 黑客松挑战赛** MVP Demo
> 命题：**基于城市数据 + 天气数据实现内涝预测（以深圳为例）**

本产品落在 CITY OS 框架 **SENSE → UNDERSTAND → PREDICT → SIMULATE → DECIDE → ACT** 全主线，
对应官网「预测未来 → 未来治理风险」一章。它回答：**一座城市，能不能提前知道哪里会内涝、什么时候涝、为什么涝，并据此调度处置？**

---

## 1. 当前能力

| 模块 | 实现 |
|------|------|
| 降雨感知 | **多点 Open-Meteo 网格 + 街道采样点空间降尺度** |
| 城市状态 | 深圳 10 区属性、高程缓存、历史易发指数、排水(OSM 道路网派生)与下垫面(WorldCover 真实) |
| 风险预测 | 混合物理模型 + LSTM 时序模型，输出逐区逐小时风险概率、等级和主因 |
| 物理代理 | 暴雨—产流—积水节点状态方程，显式输出参数与数据来源标签 |
| 研究验证 | 固定随机种子/数据切分、历史事件回放、AUC/Brier/命中率/漏报率/误报率 |
| 模型对比 | 在同一数据切分下比较 LSTM 与 Transformer |
| 数据实验室 | 查看当前降雨、手动输入降雨序列、按数据契约上传 CSV 并触发重训 |
| 情景推演 | 台风+大潮、泵站降效、极端暴雨及自定义 What-if 参数 |
| 海洋边界 | 72小时天文潮/风暴增水代理、潮位—排水非线性耦合、雨潮±6小时错位实验、基准面与质量护栏 |
| 真实GIS与积涝观测 | 项目内置480 DEM点、19,968不透水格网、28,625路段、5,965水系要素、206易涝点、148站空间特征及6,573条小时质控水位 |
| 决策支持 | 道路/设施可达性、封路与抽排反事实对比、观测数据同化 |
| 执行闭环 | 泵站调度建议、分级处置、预警日志与可选 Webhook |

---

## 2. 产品闭环

| 阶段 | 实现 |
|------|------|
| **SENSE 感知** | 多点 Open-Meteo 实时小时降雨（深圳，免费无需 Key）+ 深圳 10 区城市特征（真实 DEM 高程 + 真实历史事件指数 + 排水/下垫面真实数据(DEM/WorldCover/OSM)） |
| **UNDERSTAND 理解** | 「城市内涝世界行为模型 v2」：`风险 = f(降雨超额 × 城市脆弱性)`，可解释 + 可学习 |
| **PREDICT 预测** | 分区分时（未来 72h 逐小时）风险概率与等级（无/低/中/高/极高）+ 主因 |
| **SIMULATE 推演** | LSTM 时序模型对情景（降雨放大/额外暴雨峰值/泵站降效/潮位抬升）重算全城风险轨迹 |
| **DECIDE 决策** | 城市总览 + 分区预警 + 可达性评估 + 干预前后反事实比较 + 处置建议 |
| **ACT 执行** | 泵站调度建议 → 一键下发预警（写入日志，可接短信/APP/大屏 Webhook） |

前端按「总览 → 预测 → 研究验证 → 推演决策」组织页面，并使用 `observed / estimated / assumed / simulated` 标签区分观测、估计、假设与模拟结果。

---

## 3. 技术栈

- **前端**：React 18 + Vite + Leaflet（暗色地图，分区风险热力）+ Recharts（降雨图 / 推演轨迹）
- **后端**：Python FastAPI + NumPy（预测、物理代理、空间关系、同化和决策接口）
- **数据**：Open-Meteo 多点实时天气 + Open-Elevation 真实 DEM + 历史内涝事件库；深圳实测潮位仍待取得，当前海洋曲线明确标为物理代理
- **在线模型**：混合物理模型 + NumPy LSTM 时序推演（Adam/BPTT，权重缓存）
- **研究管线**：PyTorch LSTM/Transformer、固定切分训练、历史回放与概率校准

```
cityos-flood/
├── PROJECT_MASTER.md       # 项目总纲、能力边界与路线图
├── docs/
│   ├── model_data_contract.md # 真实监督数据字段与切分契约
│   └── ocean_data_contract.md # 潮位时区、基准面、质量控制、聚合与分解契约
├── backend/app/
│   ├── shenzhen.py   # 10区 + 30街道采样点；特征接入真实高程/历史指数
│   ├── geo.py        # Open-Elevation 真实 DEM（批量+文件缓存）
│   ├── weather.py    # 多点 Open-Meteo 降雨网格 + 空间降尺度
│   ├── events.py     # 真实历史内涝事件库（带出处）+ 真实标注CSV接入缝
│   ├── model.py      # v1 混合模型 + v2 LSTM 序列模型
│   ├── lstm.py       # NumPy LSTM（Adam/BPTT，权重缓存）
│   ├── hazard.py     # 暴雨—产流—积水物理代理
│   ├── spatial.py    # 区域、设施、道路和格点空间关系
│   ├── accessibility.py # 设施可达性与干预反事实评估
│   ├── assimilation.py  # 观测水深残差同化
│   ├── userdata.py   # 当前数据、手动预测与 CSV 上传
│   ├── simulate.py   # What-if 情景沙盘引擎 + 预设
│   ├── ocean.py      # 天文潮、增水、海洋特征与排水边界耦合
│   ├── ocean_data.py # 实测潮位读取、质量控制、小时聚合与调和分解
│   ├── data_paths.py # 项目内真实GIS数据统一路径
│   ├── dispatch.py   # 泵站调度 + 处置建议 + 预警推送（日志/Webhook）
│   └── main.py       # FastAPI 接口
├── frontend/src/     # React 主界面与可视化组件
├── backend/data/real_gis/ # 轻量可追溯GIS、易涝点、站点特征和小时水位产物
├── backend/scripts/process_waterlevel.py # 原始水位去重、北京时间和小时聚合
└── ml/               # PyTorch 训练、评估、回放和模型对比
```

---

## 4. 本地运行

> 需要 Python 3.10+ 与 Node 18+

```bash
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 &

cd frontend && npm install && npm run dev
```
打开 http://localhost:5173 。或直接 `bash run.sh` 一键启动。

设置环境变量 `ALERT_WEBHOOK=https://your-endpoint` 后，「一键下发预警」会 POST 到该地址（对接短信/APP/大屏）。

### 运行研究训练与验证

研究管线与在线后端使用独立依赖。首次运行：

```bash
python3 -m venv .venv-ml
source .venv-ml/bin/activate
pip install -r ml-requirements.txt
python -m ml.main all
```

评估报告写入 `ml/outputs/report.json`，模型对比结果写入 `ml/outputs/benchmark.json`。仓库内结果是已有实验产物，实际指标应以相同数据版本重新运行得到的报告为准。

### 主要 API

| 接口 | 用途 |
|------|------|
| `GET /api/predict` | 分区逐小时风险预测与数据来源标签 |
| `GET/POST /api/simulate` | 预设或自定义情景推演 |
| `GET /api/verify` | 可复现验证报告与配置 |
| `GET /api/benchmark` | LSTM/Transformer 对比结果 |
| `GET /api/ontology` | 深圳分区城市本体属性 |
| `GET /api/accessibility` | 灾情影响下的设施可达性 |
| `GET /api/counterfactual` | 封路/抽排干预前后比较 |
| `GET /api/assimilate` | 注入观测水深并修正预测状态 |
| `POST /api/data/upload` | 上传符合契约的 CSV 并触发重训 |
| `POST /api/dispatch` | 生成调度建议并记录/推送预警 |

---

## 5. 数据真实性说明（重要，诚实标注）

- **观测/公开来源**：Open-Meteo 降雨预报、Open-Elevation 高程，以及根据公开资料整理的历史内涝事件事实。外部服务不可用时会使用回退样例。
- **真实/真实推导**：低洼比例/临海度(真实 DEM)、下垫面可透水率(真实 WorldCover)、排水防涝设计标准(真实 OSM 道路网+WorldCover+DEM 派生)；泵站排涝能力为代表性估算，待水务局台账替换。
- **训练模式**：存在符合 `docs/model_data_contract.md` 的逐时积水数据时使用真实监督标签；缺失时使用锚定历史事件事实的演示序列。演示模式结果不能等同于生产环境实测能力。
- **潮位模式**：原始潮位必须符合 `docs/ocean_data_contract.md`；系统拒绝无时区时间戳和未统一基准面的跨站合并。当前尚未取得深圳历史逐时实测序列，面板显示的是预测/模拟代理。
- **替换缝**：可将权威排水管网、DEM、下垫面、积水点和泵站台账接入 `backend/data/`；模型数据契约保持不变。
- **部署边界**：本项目是研究与产品演示原型，不能直接替代气象、水务或应急部门的正式预警系统。

---

## 6. 晋级比赛可继续做的

1. 用权威逐时积水点台账完成**独立监督训练和测试**，替换演示序列，并叠加管网水力模型耦合。
2. 降雨做**街道级空间降尺度**到更细网格（结合雷达/数值预报）。
3. 推演加入**实时反馈闭环**（处置后风险回落），形成完整「感知→预测→推演→决策→执行→复盘」。
4. 多城市、多灾种（内涝/积水/地质灾害）扩展。
