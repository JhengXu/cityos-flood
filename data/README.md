# P0 真实监督标签数据

本目录只保存数据契约、来源清单和空模板；受许可限制或体积较大的原始数据不直接提交 Git。

## 获取优先级

1. **积水真值**：逐时/逐点积水深度、开始与结束时间、坐标、街道、行政区。
2. **水位观测**：测站编码、坐标、时间、水位、基准面和质量标记。
3. **灾情佐证**：道路封闭、交通中断、设施影响、处置时间和位置。
4. **驱动数据**：逐时降雨、潮位、台风和事件前 72 小时累计降雨。

降雨是输入，不是内涝监督标签。只有能回答“何时、何地、积水多深”的记录才能作为核心真值。

## 目录约定

```text
data/
├── manifests/sources.json       数据来源、许可、时间范围和状态
├── templates/                   可复制的数据空模板
├── raw/                         原始下载文件（Git 忽略）
└── processed/events/<event_id>/ 清洗后的事件数据（Git 忽略）
```

每个事件目录至少包含：

```text
meta.json
rainfall_hourly.csv
waterlogging.csv
```

推荐同时包含 `waterlevel.csv` 与 `disaster.csv`。所有时间统一为带 `+08:00` 时区的 ISO 8601；坐标统一为 WGS84。

## 数据验收

```bash
python scripts/validate_supervision_data.py data/processed/events
```

校验失败的数据不能进入训练集。训练报告必须记录数据集版本、事件清单、标签来源和校验结果，并明确区分 `observed` 与 `proxy` 标签。
