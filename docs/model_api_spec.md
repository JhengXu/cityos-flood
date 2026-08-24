# 深圳城市内涝 v3.2 · 当前 API 契约

> Base URL 为服务根路径，例如 `http://localhost:8000`。当前接口直接使用 `/api/*`，不使用旧 `/api/v1` 契约。

## 1. 时间与运行身份

- `forecast_run_id`：带本地签发时间的强迫快照 ID；
- `model_run_id`：包含强迫、潮位、控制量、初态和参数集合；
- `simulation_run_id`：包含情景、成员数及基线/情景运行；
- `forcing_selection_as_of`：供应方响应返回后，从时间轴选择滚动未来窗口的时刻；
- `issued_at` / `snapshot_created_at` / `available_at`：完整强迫处理、校验并冻结后在本系统实际可用的时刻；
- `hours[0]` / `series[0]`：首个未来小时有效时次，不是当前实况；
- 所有时间应为带时区 ISO-8601；上传数据缺时区会被拒绝。

## 2. 预测

### `GET /api/predict?forecast_days=3&forecast_run_id=<id>`

`forecast_days` 范围为 1–7；`forecast_run_id` 可省略以创建/取得当前快照，也可传入已有 ID 做精确重放。同一 ID 与时域重复读取时，`model_run_id` 和完整预测结果保持一致；时域冲突返回 409。核心响应：

```json
{
  "forecast_run_id": "...",
  "model_run_id": "...",
  "analysis_time": "2026-08-24T18:00:02+08:00",
  "forcing_issued_at": "2026-08-24T18:00:02+08:00",
  "forcing_selection_as_of": "2026-08-24T18:00:00+08:00",
  "forcing_issued_at_semantics": "service snapshot freeze/availability time after provider response; not provider model-cycle time",
  "provider_forecast_issued_at": null,
  "hours": ["2026-08-24T19:00:00+08:00"],
  "model": {
    "version": "3.2.0-antecedent-spinup-ensemble",
    "members": 64,
    "probability_definition": "empirical ensemble exceedance; not yet observation-calibrated"
  },
  "districts": [{
    "id": "futian",
    "series": [{
      "depth_p10_m": 0.01,
      "depth_p50_m": 0.03,
      "depth_p90_m": 0.08,
      "threshold_prob": {"gt_0_05m": 0.20, "gt_0_15m": 0.05, "gt_0_30m": 0.0, "gt_0_50m": 0.0}
    }]
  }],
  "quality_flags": ["uncalibrated_parameters"]
}
```

`observations.initial_analysis.antecedent_spinup` 记录前 24 个完整小时的地表存水
spin-up 来源、起止时刻和独立质量闭合审计；缺少连续/可审计时间轴时
`quality_flags` 含 `no_complete_antecedent_spinup`，初态保守回退为零水深。

有可用观测且 `observations.initial_analysis.applied=true` 时，初态水量账本还包含：

- `structural_prior_increment_mean_m3`：相对物理 spin-up 末态，加入结构性先验集合离差造成的平均蓄水增量；这是非物理模型不确定性。`structural_prior_increment_p10_m3` / `structural_prior_increment_p90_m3` 给出成员范围。
- `assimilation_increment_mean_m3`：EnSRF 后验相对“已加入结构离差的先验”的平均蓄水增量；这是观测信息修正，不是物理通量。
- `total_nonphysical_initial_state_increment_mean_m3`：逐成员合并上述两项后再取均值的非物理初态总增量。端到端核算应使用此字段，不应把两个已分别舍入的展示均值重新相加。

三者单位均为 m³，正值表示增加系统蓄水、负值表示减少。它们不得计作降雨、边界入流或排水；物理预报期的质量闭合从同化后的分析初态起算。若没有合格观测、`applied=false`，这些修正字段不生成。

当前 Open-Meteo 接入没有可审计的供应方模式起报版本，因此
`forcing_issued_at` 只是本系统冻结强迫快照的时间；它不能冒充
`provider_forecast_issued_at`，也不能直接用于历史 forecast-as-issued 技巧验证。
`forcing_selection_as_of` 是本次天气响应选择过去/未来小时窗时使用的参考时刻，
与响应完成后的冻结时刻不是同一语义。`issued_at`、`snapshot_created_at` 和
`available_at` 三者均取供应方响应完成后的实际冻结时刻，并且只有完整性检查
通过才会归档；它们不能倒签为请求开始时间。若处理期间跨过整点，导致首个有效
小时在发布时已不再属于
未来，服务端会重新请求并重选一次时窗；仍无法得到完整未来时域则拒绝归档。

`threshold_prob` 是成员超阈频率，不是已经校准的真实发生概率。

`GET /api/forecast?forecast_days=3&forecast_run_id=...` 返回同一冻结强迫快照的原始分区降雨，并回传 `forecast_run_id`、`forecast_days`、`issued_at` / `snapshot_created_at`、`available_at`、`forcing_selection_as_of`、`provider_forecast_issued_at` 与签发时间语义；用于检查或复现时不要另取最新天气。

## 3. 情景推演

### `GET /api/scenarios`

返回预设。当前主要预设：

- `baseline`
- `pump_failure`：只把泵站剩余效能改为 35%
- `extreme`：只改变降雨
- `typhoon_tide`：降雨、排水和增水复合情景
- `rain_6h_before_tide` / `rain_with_tide` / `rain_6h_after_tide`

### `GET /api/simulate`

推荐传入预测响应的 `forecast_run_id`：

```text
/api/simulate?preset=typhoon_tide&forecast_run_id=<id>&forecast_days=3
```

自定义参数包括：

- `rainfall_multiplier`, `add_peak_mm`, `peak_offset_h`
- `drainage_factor`：组合排水能力倍率
- `pump_efficiency`：0–1 泵站剩余效能
- `mean_sea_level_m`, `tide_amplitude_m`, `tide_phase_h`
- `surge_peak_m`, `surge_peak_offset_h`, `surge_duration_h`

未知 `preset` 返回 HTTP 422。`preset` 与任一情景覆盖参数不可混用：调用方必须二选一，仅提交预设，或移除 `preset` 后提交自定义参数；混用返回 422，不会静默忽略覆盖值。GET 请求中的未知或重复查询参数同样返回 422，以避免参数拼写错误被静默忽略。弃用的 `tide_raise` 只作为 `mean_sea_level_m` 兼容别名，二者同时传入会返回 422。

响应同时包含 `baseline_model_run_id`、`scenario_model_run_id`、`parameter_ensemble_id`、质量账本和成对差值。

海洋边界预览 `/api/ocean/boundary` 与潮雨错峰实验 `/api/ocean/offset-experiment` 同样接受 `forecast_run_id`。错峰实验只解析一次快照，三组时间偏移共享完全相同的降雨强迫与初始分析；时域与锁定快照冲突时返回 409。

### `GET /api/ocean/boundary`

海洋边界预览与情景请求使用相同的物理范围：`tide_amplitude_m` 为 0–3 m，`tide_phase_h` 为 -48–48 h，`surge_peak_m` 为 0–5 m，`surge_peak_offset_h` 为 0–167 h，`surge_duration_h` 为大于 0 且不超过 168 h。查询参数越界或边界构造失败均返回 422，不返回内部错误。

## 4. 观测同化

### `GET /api/assimilate`

```text
/api/assimilate?district=baoan&observed_h=0.30&at_hour=6&forecast_days=3&forecast_run_id=<id>
```

`observed_h` 单位为米。应复用 `/api/predict` 返回的 `forecast_run_id` 和 `forecast_days`；返回同化前后集合均值/标准差、创新量、增益、修正轨迹与 `mass_accounting_note`。此处是指定未来时次的手工 EnSRF 实验，不等同于 `/api/predict` 的冻结初始分析；上面的三个初态账本字段属于 `observations.initial_analysis`。

### `GET /api/assimilate/realtime`

```text
/api/assimilate/realtime?district=baoan&forecast_days=3&forecast_run_id=<id>
```

实时同化也必须复用主预测的 `forecast_run_id` 与 `forecast_days`；成功和 `unavailable` 响应都会在外层回传解析后的同一运行 ID，客户端应丢弃与当前页面运行不一致的迟到响应。未传 `observed_h` 时只使用新鲜、质控通过、已映射且满足 `available_at <= forecast_issued_at` 的水位。过期、缺少 `available_at` 或未进入该快照冻结初始分析的观测均 fail closed，返回 `unavailable`，不会以空分析结果触发服务端错误。当前时刻观测只进入初始分析，不会在任何未来时次重复注入。未知行政区，或显式提交 `observed_h` 却未同时提交 `at_hour`，返回 422。

若冻结快照缺少带审计意义的 `issued_at`，初始分析返回 `applied: false`，且不会退回服务器 wall clock 读取观测。

## 5. 空间风险

- `GET /api/risk/street?forecast_days=3&forecast_run_id=...`
- `GET /api/risk/grid?forecast_days=3&res=0.018&forecast_run_id=...`
- `GET /api/risk/grid/image?forecast_days=3&res=0.0045&hour_index=0&forecast_run_id=...`

街道、网格和 PNG 的缺省时域统一为 3 天。传入 `forecast_run_id` 时，`forecast_days` 必须与被锁定快照的时域一致；三者复用同一快照、初始分析和规范参数集合。`grid` 的 `res` 范围 0.009–0.1°；PNG 为 0.0045–0.05°。`hour_index` 省略时 PNG 表示全预报期成员峰值，提供时表示该小时。两者都是 GIS 约束的区级下尺度，不是二维水动力。

PNG 同时支持 `HEAD` 预检。客户端应校验 `X-Forecast-Run-Id`、`X-Temporal-Slice` 与
`X-BBox-*`，并用 `X-Raster-Empty`、`X-Visible-Cell-Count`、`X-Max-Depth-Mm` 和
`X-Max-Probability` 区分“真实干态空图”和接口/图片故障。浅于 15 cm 但 P50 大于零的像元仍会
以连续透明度显示；只有所有像元的 P50 与超阈概率都为零时才标记为空图。

`/api/risk/grid` 的逐时风险与 P50 水深采用 cell-major 紧凑编码，不再在每个
`cells[i]` 内重复 JSON 浮点数组。`timeseries_encoding.shape` 为
`[n_cells, n_times]`；给定 `cell_index=i`、`time_index=t`，扁平索引为
`i * n_times + t`：

- `risk_u8_b64`：Base64 解码后为连续 `uint8`；风险值为 `byte / 255`，最大绝对量化误差不超过 `0.5 / 255`。
- `depth_mm_u16le_b64`：Base64 解码后为连续小端 `uint16` 毫米值；米制水深为 `value / 1000`，最大绝对量化误差不超过 0.5 mm。

`timeseries_encoding` 同时返回布局、形状、dtype、解码公式和误差上限；`cells`
只保留经纬度、行政区、下尺度因子和峰值摘要等单元元数据。客户端必须按返回的
`times` 与上述形状解码，不能再读取旧的 per-cell `risk` / `depth` 数组。

### 自主动作优化 WAM

- `GET /api/wam/architecture`
- `POST /api/wam/optimize`
- `GET /api/wam/audits/{decision_run_id}`

优化接口必须使用与页面一致的 `forecast_run_id`，正式规划方法为
`robust_cem_constant_hold`。响应显式区分请求时域与快照内实际时域，返回基线/优化对比、五项
目标成本、十区请求动作与安全动作、硬约束、候选搜索信息以及审计证据。当前
`policy_type=model_based_robust_cem_constant_hold_baseline`、`execution_mode=advisory_only`、
`rl_status=not_trained_not_deployed`；`within_call_action_sequence_optimized=false`，不得称为严格
动作序列 MPC 或已训练 RL。每次调用返回唯一 `decision_run_id`，等价决策用稳定
`decision_fingerprint` 关联。详细契约见 `docs/wam_decision_loop.md`。

### 影响与反事实接口

- `GET /api/accessibility?forecast_days=3&forecast_run_id=...`
- `GET /api/counterfactual?forecast_days=3&forecast_run_id=...&close=luohu&pump=futian:0.5`

这两个接口也应复用主预测的运行 ID。响应回传 `forecast_run_id` 与 `forecast_days`，客户端应拒绝展示与当前主预测 ID 不一致的迟到响应。

`/api/accessibility` 的 `depth_mm` 与旧兼容参数 `damage` 互斥，同时提交返回 422。水深必须是有限非负毫米值，旧损伤比例必须在 0–0.95。`/api/counterfactual` 的 `close` 只接受已知行政区 ID，并把关闭区从可达性图中移除（不可进入、离开或穿越），而不是仅降低车速；`pump` 使用 `district:fraction` 格式且 fraction 必须在 0–1。未知行政区、重复区、空项、非法格式或非有限数值均返回 422。

## 6. 数据与验证

- `GET /api/platform/realtime`：水位快照，显式返回 `observed_at`、`age_hours`、`freshness` 和缓存状态；
- `GET /api/geo/realtime`：易涝点、历史 CHIRPS、站点/水位资产与数据就绪度；
- `GET /api/verify`：独立事件不足时返回 `insufficient_data`；
- `GET /api/benchmark`：返回候选模型和验证协议，不在 GET 请求中训练；
- `POST /api/data/upload`：必须使用 `multipart/form-data` 的 `file` 字段；服务端分块读取且最多读取 20MB+1 字节，超过 20MB 返回 413，缺文件、表单解析或 CSV Schema/QC 失败返回 422。通过后只做内容寻址落盘，不自动训练。
- `POST /api/forecast/manual`：严格 JSON 请求体仅接受 `district_id`、1–240 个 `rainfall`（每项 0–500 mm/h）和可选 `tide_raise`（0–5m）；缺字段、未知区、越界值或额外字段返回 422。
- `GET /api/alerts?limit=50`：`limit` 范围 1–200；日志采用有界流式读取并在达到大小上限后轮转。

## 7. 错误语义

- 422：参数单位、范围、行政区、预设或时间索引非法；
- 413：上传文件超过 20MB；
- 409：请求的 `forecast_run_id` 已不在有界快照档案中，或所传 `forecast_days` 与锁定快照时域冲突；
- 200 + `data_source=fallback-sample` / `synthetic_rainfall_fallback`：上游天气不可用时仍返回可运行的显式降级结果。

所有调用方都应展示 `quality_flags`、`provenance` 和 `probability_definition`，不得只取一个数值后丢弃其可信边界。
