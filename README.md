# CITY OS v5.1 · 深圳全自然灾害指挥中心

世界模型 + 知识库 + 决策闭环的**城市安全指挥中心**（研究演示原型）。
数据全部真实（IBTrACS/ERA5/CMEMS/HKO/规自局/深圳开放平台），非演示数字。

## 核心能力

### 四灾种实时监测
- **内涝**：守恒状态空间模型（真实 GIS 参数，质量守恒可审计）+ 集合模拟 P10/P50/P90 概率桶
- **滑坡**：监督模型 **AUC 0.821**（905 条官方预警训练，时间外验证）
- **台风**：IBTrACS 路径库（42 事件）+ 气象局实时预报
- **风暴潮**：12 分潮谐波推算（RMSE 0.126m）+ 台风增水参数化

### AI 城安助手（三段式 RAG）
Qwen3-Embedding-8B 语义召回 → bge-reranker-v2-m3 精排 → deepseek-v4-flash-vision-exp 生成。多轮对话、实时数据注入、今日态势简报、历史事件检索。

### 决策闭环
WAM 优化 → 提交决策建议 → 人工批准/驳回 → 执行 → 效果回评（SHA-256 审计链）。

### What-if 推演
台风路径平移/增强 → 降雨/滑坡/内涝/增水四链对比 + 三情景对比表。

### 页面（7）
态势总览（简报+告警+内涝概率桶+2D/3D地图+风暴潮+What-if）· 世界模型 · 自主优化（决策闭环）· 知识库 · 台风 · 风暴潮 · 滑坡

## 快速启动

```bash
# 后端 (Python 3.10+)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端 (Node 18+)
cd frontend && npm run build && npm run preview -- --port 4173
# 打开 http://localhost:4173
```

## 质量保障

| 项 | 状态 |
|----|------|
| 单元测试 | **128 通过**（`python -m unittest discover -s tests`）|
| 真实性检验 | **20/20**（`backend/scripts/verify_truth.py`）|
| E2E 用户旅程 | **10/10**（`backend/scripts/e2e_journey.py`）|
| OpenAPI 文档 | 71 端点 |
| 模型再训练 | `backend/scripts/retrain.py` |

## 目录结构
```
cityos-flood-github/    主项目（FastAPI 42 模块 + React v5 42 组件）
├── backend/app/        knowledge(知识库) / surge(风暴潮) / decision(决策) / live_ops(实时) / cascade(链式)
├── backend/scripts/    verify_truth.py / e2e_journey.py / retrain.py / health_monitor.sh
├── frontend/src/       7 页面 + 42 组件
├── docs/               KNOWLEDGE_BASE.md / TRAINING_REPORT.md
└── tests/              128 单元测试
shenzhen-flood/         数据工作区（unified/ml_models/raw/processed）
```

⚠️ `.env` 含全部 API 凭据，已 gitignore，勿上传公开渠道。
