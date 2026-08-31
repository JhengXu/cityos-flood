# CITY OS v5 · 快速启动

> 深圳全自然灾害指挥中心 · 世界模型 + 知识库 + 决策闭环
> 全部数据真实（IBTrACS/ERA5/CMEMS/HKO/规自局/深圳开放平台），研究演示口径

## 快速启动

### 1) 后端（Python 3.10+）
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
启动时自动预热实时数据缓存（Open-Meteo + 守恒模型 + 风暴潮谐波）。

### 2) 前端（Node 18+）
```bash
cd frontend
npm install        # 或直接用已含的 node_modules
npm run build
npm run preview -- --port 4173
```

### 3) 打开 http://localhost:4173

## 页面导览（7 大页面）

| 页面 | 内容 |
|------|------|
| **◎ 态势总览** | 今日态势简报（AI）+ 实时告警流（含声音）+ 四灾种卡（数值动画）+ 2D/3D 地图切换 + 风暴潮潮位曲线 + 台风 What-if 推演（含三情景对比）|
| **◈ 推演与反事实** | 世界模型：空间耦合 / 可达性 / 反事实 / 数据同化 |
| **⬢ 自主优化 WAM** | 决策工单闭环（建议→批准→执行→回评）+ 城市本体 + CEM 优化 |
| **▤ 沉淀知识库** | 6 真实案例 + 5 历史事件 + 城安助手 RAG（多轮对话+实时注入）+ 城市底座 + 模型档案 |
| **🌀 台风专页** | 42 个历史台风路径库 + 链式预测 + 3D 路径叠加 + What-if |
| **🌊 风暴潮专页** | 潮位站统计 + 四大事件波浪 + 海洋点位 |
| **⛰ 滑坡专页** | 300 在册隐患点 + 分区风险 |

## 核心能力

- **实时**：Open-Meteo 实况+预报（过去 6h + 未来 48h）、当前天气、D-1 提前预警
- **四灾种**：内涝（守恒模型+前期湿润度）、滑坡（ML AUC=0.821）、台风（IBTrACS+气象局）、风暴潮（8 分潮谐波+增水参数化）
- **AI**：城安助手（三段式 RAG：Qwen3-Embedding → bge-reranker → deepseek 生成）、多轮对话、实时数据注入、今日简报
- **决策闭环**：WAM 优化 → 提交决策建议 → 人工批准/驳回 → 执行 → 效果回评（SHA-256 审计链）
- **What-if**：台风路径平移/强度缩放 → 降雨/滑坡/内涝三链重算对比

## 数据真实性

- 全链路数据来源标注（态势总览「📋 数据来源与模型口径」可展开表格）
- 真实性检验脚本：`cd backend && python scripts/verify_truth.py`（18 项核对）
- 模型再训练：`python scripts/retrain.py`（滑坡 v2.1 + 潮汐谐波一键重训）

## 目录结构
```
cityos-flood-github/          主项目
├── backend/app/              FastAPI（41 模块：knowledge/surge/decision/live_ops/cascade…）
├── backend/scripts/          verify_truth.py / retrain.py
├── frontend/src/             React v5（双主题 + 侧栏导航 + 36 组件）
├── docs/                     KNOWLEDGE_BASE.md（全文档）/ TRAINING_REPORT.md
└── .env                      全部凭据（勿外传）
shenzhen-flood/               数据工作区（1.1G：unified/ml_models/raw/processed）
```
