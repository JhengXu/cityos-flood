# CITY OS 深圳内涝 v3.2 · 技术说明

## 1. 生产计算路径

`backend/app/main.py` 的在线预测不导入 `backend/app/model.py`、`hazard.py`、`lstm.py` 或 `ml.realdata`。核心模块为：

- `weather.py`：带签发时间和 `forecast_run_id` 的小时降雨快照；
- `state_model.py`：守恒体积状态、两段蓄水曲线、分区路由、外排、参数集合和 EnSRF；
- `forecasting.py`：冻结规范初始分析/参数成员，统一序列化；
- `simulate.py`：在同一规范基线上改变显式控制量；
- `observations.py`：水位 QC、时效门控和站区映射；
- `gridrisk.py` / `streets.py`：有界 GIS 下尺度；
- `ocean.py`：未校准调和潮与参数化增水边界。
- `wam.py`：有限时域鲁棒 CEM 常值保持动作搜索、确定性安全盾与原型审计链。

## 2. 动力学

每区状态 `S[d]` 为 m³：

```text
runoff = rain_mm / 1000 × area_m² × runoff_coefficient

S[t+1] = S[t] + runoff + routed_in
         - routed_out - drainage - external_outflow
```

- 排水设计强度先经产流系数转换为有效排水体积；
- 重力排水受海面回水影响，泵排受 `pump_efficiency` 影响；
- `drainage_control` 是作用于组合排水能力的运行倍率；
- 区际路由只走行政相邻且 DEM 下坡的有向边；
- 超过浅层滞蓄阈值的可移动水量，在内部路由与外部边界排泄之间竞争；
- 所有通量使用更新前状态同步计算，避免行政区遍历顺序依赖。

深度采用连续两段式反演：

```text
S <= A_shallow × 0.15m:
    depth = S / A_shallow
else:
    depth = 0.15m + (S - A_shallow × 0.15m) / A_expanded
```

## 3. 集合与同化

规范集合为 64 成员，扰动：

1. 产流系数；
2. 有效排水能力；
3. 浅层洼地面积；
4. 扩展受淹面积；
5. 区际路由速度；
6. 外部边界排泄率。

输出 P10/P50/P90 和 50/150/300/500mm 超阈频率。当前仅表达参数不确定性；气象集合尚未接入。

新鲜观测通过确定性串行局地 EnSRF 更新体积集合。滤波在水深空间计算协方差，使用距离局地化，再转回每个成员自己的两段蓄水曲线。站点到行政区的代表性误差当前取 0.10m，并与传感器误差合成。

## 4. 身份与缓存

- `forecast_run_id`：包含本地签发时间和完整强迫指纹；
- 快照内规范集合缓存：冻结首次消费时的观测截止时间、初态和参数成员；
- `parameter_ensemble_id`：参数成员内容哈希；
- `model_run_id`：强迫、潮位、控制、初态、成员数和参数集合哈希；
- `simulation_run_id`：情景、基线/情景运行和成员数哈希。

天气档案、情景、网格 JSON 和 PNG 缓存均有容量上限。网格接口限制预报天数和分辨率，最近邻计算分块执行，避免构造数 GB 距离矩阵。

## 5. 空间产品语义

- 行政区主模型：真正参与状态转移；
- 街道采样点/约 2km JSON 网格：把区级成员深度乘以有界高程—不透水因子；
- 约 500m PNG：按当前 `hour_index` 展示 P50 水深分级，透明度联合连续 P50 水深与
  P(depth≥0.15m)，所以浅于 15cm 的非零中位水深仍可见；真正全干态才返回空图标记；
- PNG 行按 Leaflet 北向约定翻转；
- 矩形网格未裁剪到权威行政边界，响应保留质量标记。

这些产品用于风险排序，不是管网或二维浅水方程结果。

## 6. API 入口

当前接口不带 `/api/v1` 前缀。主要接口：

- `GET /api/predict?forecast_days=1..7`
- `GET /api/simulate?preset=...&forecast_run_id=...`
- `GET /api/risk/street`
- `GET /api/risk/grid`
- `GET /api/risk/grid/image?hour_index=...`
- `GET /api/assimilate` 与 `/api/assimilate/realtime`
- `GET /api/wam/architecture`、`POST /api/wam/optimize` 与 `GET /api/wam/audits/{id}`
- `GET /api/verify`、`/api/benchmark`
- `POST /api/data/upload`

详见 `docs/model_api_spec.md`。

## 7. 测试

```bash
backend/.venv/bin/python -m unittest discover -s tests -v
cd frontend && npm run build
```

测试覆盖质量守恒、非负/顺序无关、排水/潮位方向、两段蓄水连续性、六类集合参数、确定性 EnSRF、72h 极端情景、观测不重复使用、统一运行 ID、站点映射、栅格方向/分辨率和数据真实性门禁。

## 8. 自主动作优化边界

当前决策层复用同一预报快照、信念状态和守恒世界模型，用 4 个代表成员进行 CEM 搜索，再用
16 个成对成员验证十区 `drainage_control`。动作受设备上下界、首步变化率、风险区负荷下限、
应急增排总预算与 P90 无恶化护栏约束。它只输出 `advisory_only` 建议与唯一审计记录，不写
SCADA；当前并非已训练 RL，也不是一次调用内优化多时段动作序列的严格 MPC。

## 9. 限制

当前参数没有由独立湿事件校准；天气是确定性预报；潮位相位/基准未由深圳站校准；空间图是行政区代理；短时水位缺少站点零点和独立事件标签。任何业务部署都需要权威数据、滚动事件回放、可靠性校准和人工预警流程。
