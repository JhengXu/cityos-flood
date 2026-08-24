# 深圳城市内涝预测与情景推演 v3.2

当前在线核心已经从“物理代理生成标签 → LSTM 拟合”改为可审计的守恒图状态空间模型：

- 以行政区地表存水体积（m³）为状态，显式计算降雨产流、排水、区际路由和城市边界外排；
- 用起报前 24 个已完整结束小时的分区降雨做地表存水 spin-up，再进行一次观测更新；
- 用连续两段式蓄水曲线把体积转换为代表性水深；
- 64 成员规范参数集合输出 P10/P50/P90 和 5/15/30/50cm 超阈频率；
- 新鲜、质控且完成空间映射的水深代理通过确定性局地 EnSRF 更新初态；
- 预测、情景推演、街道和网格产品共享同一预报快照、初始分析和参数成员；
- 旧 LSTM/Transformer 只保留为隔离的历史实验，不参与在线接口。

旧实验默认拒绝训练和评估；只有显式使用
`python -m ml.main all --allow-proxy-labels` 才能复现，且输出会标为
`invalid_for_skill_claim`，不得解释为真实预测准确率。该隔离复现还需单独安装
`ml-requirements.txt`，生产后端不需要 PyTorch。

## 运行

需要 Python 3.10+ 与 Node 18+：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

另开终端：

```bash
cd frontend
npm install
npm run dev
```

也可运行 `bash run.sh`。默认前端地址为 <http://localhost:5173>。

## 验证

```bash
backend/.venv/bin/python -m unittest discover -s tests -v
cd frontend && npm run build
```

当前项目内只有 148 站、6,573 条、约 44 小时的质控水位切片，最高 0.10m；这些旧缓存行没有 `available_at`，也没有独立标注洪涝事件。因此系统会返回 `insufficient_data`，并拒绝把它们注入历史起报快照或用合成标签冒充真实预测准确率。

## 关键文档

- [完整产品说明](README-cityos.md)
- [项目总纲与路线图](PROJECT_MASTER.md)
- [v3.2 模型架构](docs/model_v3_architecture.md)
- [优先数据源与接入计划](docs/data_source_plan.md)
- [当前 API 契约](docs/model_api_spec.md)
- [自主优化行动 WAM 安全闭环](docs/wam_decision_loop.md)
- [真实监督数据与无泄漏验证契约](docs/model_data_contract.md)

本项目是研究与产品演示原型，不能替代气象、水务或应急部门的正式预警。
