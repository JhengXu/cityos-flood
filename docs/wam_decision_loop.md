# 自主优化行动 WAM：安全决策闭环

## 当前实现边界

当前线上新增的是**有限时域、参数集合鲁棒的 CEM 常值保持控制基线**，不是已经训练或部署的强化学习策略，也不是一次调用内同时优化多时段动作序列的严格 MPC。优化器在 6–72 小时时域内为深圳十区各搜索一个保持不变的 `drainage_control`，每当新观测、新天气或设备状态形成新的信念状态时，可再次调用接口进行滚动重算。所有输出均为 `advisory_only`，不会写入 SCADA 或设备。

该决策层复用 `/api/predict` 和 `/api/simulate` 的 NumPy 守恒图状态模型、起报状态集合、参数集合与潮位边界。规划阶段选取 4 个代表成员控制计算时延，最终用同一预报快照下的 16 个成对成员重新验证候选动作，保留每个成员的水量守恒审计。

## W–S–A–R 契约

- **World**：十区降雨产流、排水、区际汇流、河道/城市边界外排和潮位顶托，状态转移满足 `S[t+1]=S[t]+runoff+routed_in-routed_out-drainage-external_outflow`。
- **State**：各区初始积水深度集合、均值/方差、未来逐区降雨、潮位、设备泵效、设计排水能力和应急增排预算。起报状态沿用前期降雨 spin-up 与局地 EnSRF。
- **Action**：当前仅优化十区连续排水控制倍率。`pump_efficiency` 是设备健康/环境状态，不是智能体动作；降雨、潮位、风暴增水也不是动作。
- **Reward / cost**：所有正水深均进入连续积水成本，避免优化器把水蓄到 15 cm 阈值以下而不受惩罚；30 cm 以上另加严重积水成本，同时计入集合不确定性、能耗与动作调度成本。API 的 `delta` 正值表示相对标称控制降低了成本。

## 安全盾

原始候选动作依次通过以下确定性硬约束：

1. 设备最小/最大控制倍率；
2. 相对当前标称负荷的首步变化率；
3. 已达到可行动水深或降雨超过设计排水能力的区域不得降到标称负荷以下；
4. 十区应急增排能力总预算；
5. 16 成员成对集合无恶化护栏：任一区 P90 水深相对标称控制增加超过容差时，整组动作回退为 `1.0`。

高负荷动作或 P90 严重积水动作标记为 `approval_required`。即使全部约束满足，也只产生建议，不自动执行。

## API

### `GET /api/wam/architecture`

返回 WAM 状态、环境、动作、奖励、硬约束、当前已实现技术以及尚未安装的生产演进技术栈。响应明确包含：

- `policy_type=model_based_robust_cem_constant_hold_baseline`
- `execution_mode=advisory_only`
- `rl_status=not_trained_not_deployed`

### `POST /api/wam/optimize`

严格请求示例：

```json
{
  "forecast_run_id": "pinned-forecast-run-id",
  "forecast_days": 3,
  "horizon_hours": 24,
  "pump_efficiency": 1.0,
  "planner": {
    "method": "robust_cem_constant_hold",
    "population": 32,
    "iterations": 3,
    "elite_fraction": 0.2,
    "seed": 42
  },
  "objective_weights": {
    "flood": 8.0,
    "severe": 18.0,
    "uncertainty": 2.0,
    "energy": 0.25,
    "mobilization": 0.2
  },
  "constraints": {
    "min_control": 0.75,
    "max_control": 1.25,
    "max_first_step_change": 0.25,
    "emergency_budget_mm_h": 45.0,
    "no_regret_max_depth_increase_mm": 5.0
  }
}
```

`planner.method` 的正式值是 `robust_cem_constant_hold`；`cem_mpc` 只作为已弃用兼容别名。响应中的精确算法名为 `finite_horizon_robust_cem_constant_hold`，并显式返回 `within_call_action_sequence_optimized=false`。当预报快照剩余时效短于请求时域时，响应同时返回 `requested_horizon_hours`、实际 `horizon_hours` 与 `horizon_truncated_to_snapshot=true`，不静默伪装为完整时域。

主要响应字段：

- `belief_state`：起报分析、观测与十区状态摘要；
- `baseline` / `optimized`：城市与各区 P10/P50/P90、超 15 cm 概率、目标成本和水量审计；
- `reward_breakdown.components`：五项成本和总成本的基线、优化后与成本下降量；
- `action_plan`：每区原始动作、安全动作、等效能力、原因与人工审批标志；
- `safety_projection`：被修正动作、预算、约束结果、违例数与无恶化回退；
- `planner`：种子、候选数、迭代收敛轨迹和集合成员数；
- `audit`：决策 ID、预报/模型版本、SHA-256 链式摘要与回放地址；
- `technology_stack`：已实现栈和生产演进栈的明确分区。

### `GET /api/wam/audits/{decision_run_id}`

读取保留期内的完整决策审计。每次调用都有唯一 `decision_run_id`，相同输入和动作另以稳定的
`decision_fingerprint` 关联；进程重启时会从当前日志恢复上一条摘要并续接链。当前原型使用本地
append-only JSONL 与 SHA-256 前后摘要链，可发现简单篡改，但不是经过认证的 WORM 存储。

## 强化学习演进路线

完整技术演进按以下七步推进：

1. 用 Gymnasium 封装 `reset/step/action` 与暴雨、潮位、故障、缺测的 domain randomization；
2. 冻结奖励、硬约束和评估协议；
3. 先建立 CEM/MPC/规则控制器可解释基线；
4. 用历史暴雨、人工调度、MPC 专家轨迹与随机模拟训练离线或残差 SAC/PPO；
5. 影子运行，不影响真实动作；
6. 建议模式，由人工审批；
7. 仅对低风险动作开放有限闭环，高风险长期保留人工审批。

生产目标栈包括 MQTT、Kafka/Redpanda、Debezium、Flink、TimescaleDB、PostGIS、MinIO、Redis、PyTorch/JAX 残差世界模型、Numba/Ray、CasADi/CVXPY/OSQP、Stable-Baselines3/RLlib/TorchRL、GNN+CTDE、OR-Tools/MILP、Kubernetes/gRPC、MLflow/BentoML/KServe、Prometheus/Grafana/OpenTelemetry 与认证 WORM 审计库。它们是演进目标，不应被描述为当前仓库已部署能力。
