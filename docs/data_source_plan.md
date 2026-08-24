# 深圳内涝预测数据源与接入计划

> 目标不是“数据越多越好”，而是补齐能够改变预测状态、校准参数或独立验证结果的数据，并保存其发布时点、质量和许可。
>
> 官方链接核对日期：2026-08-24。外部页面、接口和许可可能变化，正式部署前需再次确认。

## 1. 接入优先级

### P0：形成可独立验证的事件闭环

1. **全量积涝点水位历史与测站元数据**
   - 官方目录：[深圳市水务局积涝点水位数据](https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_01403147)
   - 官方目录：[深圳市水务局测站基本信息表](https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_01400987)
   - 用途：连续水深标签、起涨/峰值/消退、实时同化。
   - 当前缺口：仓库只有 148 站约 44 小时切片，且没有 ≥0.15m 记录；必须按时间分批回补多年湿事件，而不是继续扩充干态样本。
   - 已核实接口形态：`https://opendata.sz.gov.cn/api/2920001403147/1/service.xhtml?page=1&rows=100&appKey=<APP_KEY>`。需要注册、订阅和应用 Key；站点记录频率并不恒定，原始记录必须保留，不能先强制插成“固定5分钟真值”。
   - 必存字段：原始站码、原始时间、统一时区时间、接收时间、原始值、单位、质量码、修订版本、站点坐标和高程基准。

2. **同事件自动站/雷达降雨与当时发布的预报**
   - 深圳气象局：[自动站查询](https://weather.sz.gov.cn/qixiangfuwu/qixiangjiance/zidongzhanchaxun/)可查看 00/05/10…/55 分钟时次及 30分钟、1/3/6/12/24/48/72小时滑动雨量，但公开页面只支持近一年且无稳定 SLA API，不应抓网页作为生产依赖。
   - 开放平台：[深圳范围自动站实况格点数据表](https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_00903509)为 1km×1km 产品；[水库站点降雨量实时信息](https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_01403150)可补充水务雨量站；两者都需申请后审计真实时距、缺测和累计量重置。
   - 雷达：[CMA 全国基本反射率拼图](https://k.data.cma.cn/mekb/?dataCode=J.0017.0010.S001&r=data%2Fdetail)约 0.01°、6分钟，但公开窗口主要是近24小时，适合从现在开始持续归档；[深圳本地雷达图](https://weather.sz.gov.cn/qixiangfuwu/qixiangjiance/leidatuxiang/index.html)没有核实到匿名历史批量接口。
   - 用途：地面真值、雷达分钟级暴雨结构、历史 forecast-as-issued 回放。
   - 关键要求：实况与预报不能混用。保存 `valid_at`、`forecast_issued_at`、`available_at`、模式名/版本/成员号；验证时不得用事后拼接或重分析替代当时预报。

3. **事件与影响台账**
   - 申请单位：深圳市水务局、应急管理、交警、交通运输及各区三防部门。
   - 目标数据：道路积水/封闭的起止时间和深度、隧道/地铁影响、报警工单、现场巡查、泵站启停、闸门状态、应急处置。
   - 用途：独立事件边界、影响等级、消退时间和干预效果验证。
   - 注意：新闻报道和“某区受影响”只能用于事件检索，不能扩展成逐时逐区监督标签。

### P1：把灰盒参数替换成城市水力状态

4. **排水管网、检查井、雨水口、箱涵、泵站、闸门和调蓄设施**
   - 官方信息入口：[深圳市水务局数据发布](https://swj.sz.gov.cn/sjfb/index.html)。
   - 公开统计参考：[2024 年水务基础统计数据](https://swj.sz.gov.cn/gkmlpt/content/12/12568/mpost_12568123.html)。该页面说明深圳具有大规模排涝泵站与水闸资产，但公开统计量不能替代设施级拓扑和运行时序。
   - 申请字段：节点/管段拓扑、管径、底高程、坡度、糙率、设计流量、泵曲线、闸门规则、维护/堵塞、实时启停与故障、数据版本。
   - 用途：将“行政区质心图”替换为子汇水区—管网图，离线构建 SWMM/1D-2D 高保真模型，并校准在线灰盒参数。

5. **高分辨率地形与城市表面**
   - 优先申请：深圳测绘/LiDAR 裸地 DEM、建筑物、道路缘石、下穿隧道、河道断面和海堤。
   - 全球回退：[NASA Earthdata SRTM/NASADEM](https://www.earthdata.nasa.gov/centers/lp-daac)（30m 产品可作区域地形底板）。
   - 下垫面：[ESA WorldCover](https://esa-worldcover.org/en/data-access)（2020/2021 全球 10m，CC BY 4.0；两个年份算法版本不同，不能直接把差值都解释为真实变化）。
   - 用途：汇流方向、洼地容积、不透水产流、站点高程核验。
   - 限制：30m/10m 全球产品仍无法可靠表示路缘、地下通道和微地形。

6. **潮位、风暴增水、河道水位与统一高程基准**
   - 优先申请：深圳/广东海洋、港口、水务部门的赤湾、盐田、大鹏湾等逐时/分钟潮位和河口水位；同时取得站点基准、零点、基准转换和质量码。
   - 用途：排口顶托、重力排水折减、雨潮复合事件与沿海区状态同化。
   - 硬约束：没有统一基准面就不能跨站合并，也不能直接与 DEM 或排口底高程比较。
   - 可立即归档的邻近公开源：香港天文台[最新潮位数据集](https://data.gov.hk/en-data/dataset/hk-hko-rss-latest-tidal-info)，CSV 为 `https://data.weather.gov.hk/weatherAPI/hko_data/tide/ALL_en.csv`，约每5分钟更新；[逐时天文潮预报](https://data.gov.hk/en-data/dataset/hk-hko-rss-hourly-heights-of-tides)可按站点/年份下载。尖鼻咀可作深圳湾外部参考，但不能未经转换直接作为深圳排口边界。
   - [HKO 潮位格式/基准说明](https://data.weather.gov.hk/weatherAPI/hko_data/tide/File_layout_for_latest_tides_en.pdf)指出其单位相对香港海图基准面；深圳本地页面采用另一高程基准。采集表必须保存 `vertical_datum`，转换参数不明时只展示单站异常/残差，不做绝对水位合并。

### P2：扩展覆盖和不确定性

7. **气象集合预报**
   - 优先：气象部门业务集合或 [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data)。
   - 开发期聚合入口：[Open-Meteo Ensemble API](https://open-meteo.com/en/docs/ensemble-api)。
   - 用途：把降雨落区、峰值和时序不确定性传播到积水深度集合。
   - 归档要求：必须保存每个成员的模式起报时间；不能只保留集合均值。

8. **历史 forecast-as-issued 档案**
   - [ECMWF TIGGE](https://www.ecmwf.int/en/research/projects/tigge)保存多个中心自 2006 年以来的集合预报与总降水，适合保存 `issue_time/valid_time/lead_time/member` 后做无泄漏回放；城市尺度较粗，只作大尺度环境场。
   - [NOAA/NCEI GFS 档案](https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast)提供长期历史模式版本；0.25°产品自 2021 年起较完整，同样不能替代深圳雷达/自动站。
   - [深圳分区逐时预报](https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_00900269)适合在线特征，但未核实平台会永久保留每次签发版本；系统应从接入当天起自行做只追加快照。

9. **卫星降雨与淹水影像**
   - [NASA GPM IMERG](https://gpm.nasa.gov/data/imerg)：0.1°、半小时产品，适合补齐区域事件过程和跨源检查；约 10km 网格不足以单独驱动深圳街道级暴洪。
   - [Copernicus Sentinel-1](https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-1)：全天时 C 波段 SAR，可用于事件后淹水范围佐证；过境时间、城市叠掩和积水尺度限制其作为连续小时标签。
   - 用途：缺站区域补充、事件空间范围和大范围异常检测，不替代地面水深站。

10. **再分析与长期背景**
   - [ERA5 小时单层数据](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=overview)：1940 年至今、0.25°、小时级。
   - 用途：长期气候态、前期土壤湿度背景和缺测检查。
   - 限制：空间尺度远粗于深圳内涝，且再分析属于事后产品，不能混入实时 forecast-as-issued 技巧验证。

11. **可立即补齐的粗 DEM**
   - [Copernicus DEM GLO-30](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM)与 [NASA SRTM/NASADEM](https://www.earthdata.nasa.gov/centers/lp-daac)可作30m区域汇流/坡度底板和交叉检查。
   - 深圳官方测绘目录包含 DEM/DSM/点云，但不是匿名下载；应正式申请亚米级裸地 DEM/LiDAR。30m DSM 无法表达路缘、下穿通道和道路横坡，不能把格网下尺度结果称为街道水动力精度。

## 2. 当前项目资产的正确用途

| 资产 | 当前覆盖 | 可以做 | 不能做 |
|---|---:|---|---|
| 质控小时水位 | 6,573 行、148 站、44h；旧缓存无 `available_at` | ingestion/QC、站区映射、干态先验、同化管线单测 | 无泄漏历史同化、独立事件训练、AUC/命中率证明、当前实时同化 |
| 2019 易涝点 | 206 个静态点 | 空间暴露先验、采样/巡查布点 | 逐时积水深度标签 |
| CHIRPS | 少量事件日、日尺度、约 0.05° | 事件检索、日累计交叉检查 | 小时暴雨峰值、城市临近预报 |
| DEM/WorldCover/OSM | 项目内轻量派生特征 | 灰盒参数先验、静态空间特征 | 权威管网能力、街道微地形、水力拓扑 |
| Open-Meteo 最新预报 | 小时确定性快照 | 开发期在线强迫、接口演示 | 不保存起报版本的历史技巧验证 |

当前 Open-Meteo 小时 `precipitation` 按[官方变量说明](https://open-meteo.com/en/docs#hourly=precipitation)
解释为“时间戳之前一小时的累计量”。状态 spin-up 只使用已经完整结束的连续 24 个小时，
并把这一 interval semantics 写入强迫快照；它仍是模式估计，不是深圳自动站实况。

## 3. 统一落地契约

所有原始数据采用 append-only 分区存储，不覆盖旧版本：

```text
data_lake/
  source=<provider>/dataset=<dataset_id>/
    ingest_date=YYYY-MM-DD/part-*.parquet
  manifests/<content_sha256>.json
```

每条动态记录至少包含：

- `source`, `dataset_id`, `source_record_id`, `source_version`；
- `observed_at` 或 `valid_at`（物理时间）；
- `available_at`（系统真正可见时间）；
- 预报另含 `forecast_issued_at`, `model_run_id`, `lead_time_h`, `member_id`；
- `lat`, `lon`, `station_id`, `district_id` 及空间映射版本；
- 原始值、标准化值、单位、时区、垂直基准、质量码；
- `ingested_at`, 原始文件哈希、处理代码版本、许可/署名要求。

上传接口的推荐最小 CSV：

```text
timestamp,event_id,district_id,rainfall_mm,water_depth_m,available_at
2023-09-07T22:00:00+08:00,2023-09-07-rain,futian,68.2,0.31,2023-09-07T22:05:00+08:00
```

`timestamp` 等价于 `observed_at`。可以兼容 `flooded` 二分类列，但缺少 `water_depth_m` 时不能训练或校准连续深度；缺少 `available_at` 时不能用于无泄漏历史回放。上传只执行 schema/QC 和内容寻址落盘，不自动启动训练。

## 4. 质量门禁

进入同化前：

- 站码与空间位置可追溯，数值和单位合法；
- 时间带时区，延迟小于业务新鲜度窗口；
- 水位基准已确认，无跳变/卡死/重复；
- 不同传感器不得在未知定义下直接聚合为“水深”。

进入训练/校准前：

- 事件 ID 经人工去重，存在足够湿事件与干对照；
- 雨量、水深和控制状态时间对齐，缺测掩码显式保留；
- 标签来自独立观测，不由候选模型或同源规则生成；
- 许可允许模型研发、发布派生指标和保存必要期限。

进入最终测试前：

- 测试事件按时间锁定，训练人员不可反复调参查看；
- forecast-as-issued 输入快照完整；
- 指标脚本、阈值、行政区映射和版本在评估前冻结。

## 5. 90 天执行顺序

1. **第 1–2 周**：建立只追加采集器和 manifest；分批回补积涝水位、站点元数据、自动站雨量，完成时区/单位/站码字典。
2. **第 3–4 周**：按降雨和水位共同识别候选事件，人工核验 `event_id`；保存 `observed_at`/`available_at`，冻结首个事件外测试集。
3. **第 5–6 周**：用事件校准灰盒参数，与零积水、持续性、简单消退基线做 rolling-origin 回放。
4. **第 7–9 周**：接入气象集合与实时新鲜度监控；验证 EnSRF 在观测到达/缺失/延迟情况下的增益。
5. **第 10–12 周**：取得管网/泵闸运行数据后构建子汇水区图；只在事件覆盖足够时加入残差学习器并做锁定测试。

## 6. 安全、许可与凭据

- 密钥、Cookie、手机号和实名信息不得写入仓库文档；只在未提交的 `.env` 或秘密管理服务中保存，并定期轮换。
- 深圳开放平台要求在成果中注明数据来源，且服务条款可能调整；每个数据快照应保存当时许可文本/版本。
- 对含报警、车辆轨迹或人员信息的数据先做最小化、脱敏、访问控制和留存期限评估。
- 对外发布只输出必要的聚合风险和来源说明，不公开受限设施细节或原始敏感记录。
