# 深圳城市内涝预测系统 — 数据源清单（Data Sources Inventory）

> 项目：城市世界行为模型 —— 面向政府（ToG）的深圳内涝预测预警系统
> 阶段：v3.2 数据资产盘点；“已下载”只表示文件存在，不表示可用于训练或验证。
> 说明：本清单覆盖内涝预测所需的全部数据类别，标注访问方式、格式、覆盖范围、已验证状态与使用注意事项。凡标 ✅ 的为**本次已实际下载/提取**的数据；标 ⚠️ 的为需注册/授权或待补采的数据。

---

## 一、数据需求总览

一个可运行的城市内涝世界行为模型，需要四类数据：

| 类别 | 作用 | 时空粒度 | 关键性 |
|------|------|---------|--------|
| **降雨（驱动）** | 内涝发生的触发因子，预测输入 | 小时/日 × 站点/栅格 | ⭐ 核心 |
| **内涝点/水位（候选观测）** | 状态同化、参数校准与独立验证的候选来源 | 事件 × 点位 | ⭐ 核心 |
| **地形/汇流（静态特征）** | DEM、坡度、洼地，决定积水倾向 | 栅格/点 | 高 |
| **城市要素（静态特征）** | 路网密度、下垫面、排水管网、土地利用 | 矢量/栅格 | 高 |

---

## 二、数据源明细

### 2.1 降雨数据（动态驱动）

| 数据源 | 地址 | 格式 | 覆盖 | 状态 | 备注 |
|--------|------|------|------|------|------|
| **CHIRPS-2.0 全球逐日降雨** | `https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/{年}/chirps-v2.0.{年}.{月}.{日}.tif.gz` | GeoTIFF（7200×2000, float32, 0.05°≈5.5km） | 1981–今，全球，日尺度 | ✅ 已下载12个关键事件日 | 免账号。但为**日尺度、5.5km**，比城市尺度的暴雨时空分布偏粗；UTC 日界会导致跨午夜暴雨被拆分到两天。 |
| **中国气象数据网（CMA）逐小时站点** | `https://data.cma.cn/` | 站点 CSV | 全国站点，小时 | ⚠️ 需注册/审核 | 深圳站（Shenzhen 59493）逐小时降雨，粒度最佳，建议申请。 |
| **ERA5 再分析** | `https://cds.climate.copernicus.eu/` | NetCDF | 0.25°≈28km，逐小时 | ⚠️ 需 CDS 账号 | 时间分辨率好但空间过粗，适合做背景场。 |
| **深圳本地雨量站** | 深圳市气象局（`www.sz.gov.cn` 气象服务） | 站点 | 深圳，逐分钟 | ⚠️ 需申请 | 城市暴雨内涝建模的最优数据源。 |
| **高德/和风等天气 API** | `restapi.amap.com` 等 | JSON | 实时+预报 | ⚠️ 需 API Key | 适合做实时预警展示，不适合作历史建模。 |

> **已验证 CHIRPS 提取结果**（深圳区域，`data/processed/shenzhen_chirps_rainfall.csv`）：
> `2014-05-11: 169.0mm（5·11特大暴雨）`、`2018-08-29: 66.4mm`、`2020-05-11: 34.9mm`、`2023-09-07: 96.6mm（9·7极端特大暴雨）`、`2024-04-26: 30.7mm` —— 与历史暴雨事件吻合，可作为原型验证降雨输入。

### 2.2 内涝点/水位数据（候选观测源）

| 数据源 | 地址 | 格式 | 覆盖 | 状态 | 备注 |
|--------|------|------|------|------|------|
| **深圳市水务局·积涝点水位数据** | `https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_01403147` | 水位时序 | 深圳 | ✅ 已下载10万条短时切片 | 最重要的候选观测源；当前切片仅约44小时、最高0.10m、无独立事件，不能直接作为训练/验证标签。 |
| **深圳市水务局·测站基本信息表** | `https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_01400987` | 测站属性 | 深圳 | ✅ 已下载485个站 | 含测站编码/名称/站类，**148个内涝水情站**。站名即内涝点描述，需自行定位。 |

> **已下载候选观测切片**（登录+实名认证，详见 `docs/opendata_access_guide.md`）：
> - `data/raw/sz_waterlevel_points.csv`：**100,000 条**内涝水情站水位（148站，2026-08-19~20）
> - `data/raw/sz_station_info.csv`：**485 个**测站（内涝水情站148 / 水库204 / 河道133）
> - `data/processed/shenzhen_waterlevel_clean.csv`：清洗后水位时序（含站名/坐标）
> - `data/processed/shenzhen_stations_geo.csv`：148个内涝水情站（OSM定位81个）
| **深圳暴雨天易内涝路段名单（2019）** | `https://city.shenchuang.com/city/20190729/1498083.shtml` | 文本名单 | 深圳10区 | ✅ 已解析为CSV | 结构化出 **206 条**易涝点（区/街道/具体路段），来自官方口径汇总，可直接作为内涝风险点。 |
| **中国长序列县尺度城市洪涝事件时空数据集（2000-2022）** | `https://www.geodata.cn/main/face_science_detail?guid=96134580325160` | 时空数据集 | 全国县尺度 | ⚠️ 需注册 | 县级尺度，用于全国/区域对比，城市内部太粗。 |
| **新闻/政务报道内涝点** | 见 `data/floodpoints/` 归档 | 文本 | 事件级 | ✅ 已收集 | 用于补充特定暴雨事件（如2023.9.7）的内涝点。 |

> **已解析内涝点分布**（`data/floodpoints/sz_waterlogging_points_2019.csv`，共206条）：
> 龙岗区57 · 福田区32 · 坪山区29 · 罗湖区29 · 南山区19 · 宝安区12 · 光明区11 · 盐田区9 · 龙华区5 · 大鹏新区3。
> 内容示例：福田区福保街道「滨河新洲一号桥洞」、龙岗区布吉街道「湖南立交穿孔桥」等。

### 2.3 地形/汇流数据（静态特征）

| 数据源 | 地址 | 格式 | 覆盖 | 状态 | 备注 |
|--------|------|------|------|------|------|
| **SRTM 90m 高程** | `https://api.opentopodata.org/v1/srtm90m?locations={lat},{lon}` | 点值 API | 全球 90m | ✅ 已采样480点 | 免账号。API 单次上限100点，需分批。 |
| **ASTER GDEM 30m** | `https://api.opentopodata.org/v1/aster30m` | 点值 API | 全球 30m | ✅ 可用 | 更精细，建议用于坡度/洼地提取。 |
| **地形起伏（Slope/洼地）** | 由 DEM 计算 | 栅格 | 深圳 | 待计算 | 后续建模步骤用 ArcGIS/GDAL 提取洼地、坡度、流向。 |
| **NASA SRTM 原始栅格** | `https://earthexplorer.usgs.gov/` | GeoTIFF | 全球 | ⚠️ 需注册 | 若需完整栅格而非采样点。 |

> **已验证 DEM 范围**（`data/processed/shenzhen_dem.csv`，480点）：`min=-5m，max=506m，mean=59.3m`，符合深圳「沿海低地+丘陵山地」地形。

### 2.4 城市要素数据（静态特征）

| 数据源 | 地址 | 格式 | 覆盖 | 状态 | 备注 |
|--------|------|------|------|------|------|
| **OpenStreetMap 路网** | Overpass API `https://overpass-api.de/api/interpreter` | GeoJSON | 深圳全市 | ✅ 已下载28,625段 | 免账号，ODbL 许可。含道路名称、等级、几何。 |
| **OSM 水系（河流/水库）** | Overpass API | GeoJSON | 深圳 | ✅ 已下载5965要素 | 河流1229/水库270/湖泊75等，`data/processed/shenzhen_water.geojson`。 |
| **OSM 行政区划边界** | Overpass API | GeoJSON | 深圳9区 | ✅ 已下载 | `data/processed/shenzhen_districts.geojson`（大鹏新区OSM为admin_level=7未含）。 |
| **排水管网/泵站** | 深圳市水务局 / 智慧水务 | 矢量 | 深圳 | ⚠️ 需申请 | 内涝成因关键（管网过流能力），建议向水务局申请。 |
| **土地利用/不透水面** | 珞珈一号 / ESA WorldCover / 深圳国土 | 栅格 10m | 深圳 | ⚠️ 部分需注册 | 不透水率影响产流。OSM landuse 查询过重(504)，建议用WorldCover。 |

> **已下载路网等级分布**（`data/processed/shenzhen_roads_summary.csv`，28,625段）：
> `tertiary 9538 · primary 7120 · secondary 6992 · motorway 2583 · trunk 2392`，含中文路名26,553条。

---

## 三、下载/提取脚本（可复现）

| 脚本 | 作用 | 输出 |
|------|------|------|
| `src/download_chirps.py` | 批量下载关键暴雨事件日 CHIRPS 降雨 | `data/rainfall/raw/*.tif.gz` |
| `src/download_chirps_extended.py` | 扩充下载（暴雨前多日累积+负样本，29天） | `data/rainfall/raw/*.tif.gz` |
| `src/extract_shenzhen_rainfall.py` | 动态解析 TIFF，提取深圳区域逐日降雨 | `data/processed/shenzhen_chirps_rainfall.csv` |
| `src/geocode_floodpoints.py` | OSM路名匹配定位内涝点 | `data/processed/shenzhen_floodpoints_geo.csv` |
| `src/geocode_stations_tianditu.py` | 天地图定位内涝水情站 | `data/processed/shenzhen_stations_geo_final.csv` |
| `src/geocode_floodpoints_tianditu.py` | 天地图定位2019易涝点 | `data/processed/shenzhen_floodpoints_geo_v2.csv` |

---

## 四、已验证的关键结论

1. **降雨驱动可用**：CHIRPS 免账号可下载，深圳区域提取值与历史特大暴雨吻合（2014·5·11≈169mm，2023·9·7≈96mm）。
2. **候选观测源已定位**：深圳市水务局开放了积涝点水位与测站信息；只有补齐多年湿事件、站点基准/QC、`available_at` 并完成人工事件核验后，才能形成独立 ground truth。
3. **静态特征就绪**：OSM 路网（28,625段）+ SRTM 高程（480点）已落地，可进入特征工程。
4. **局限与对策**：CHIRPS 为日尺度·5.5km，需在建模中通过「降水-内涝」统计关系或融合高德/气象局小时数据弥补；跨日暴雨需按 UTC 日界校准。

## 五、下一步建议（数据补充）

- [ ] 持续回补**积涝点水位数据** + **测站基本信息**，形成带时效审计的多年事件观测，而不是只增加干态行数。
- [ ] 申请 CMA 深圳站逐小时降雨（提升时间精度）。
- [ ] 用 ASTER 30m DEM 计算坡度/洼地/流向，生成汇流特征栅格。
- [ ] 向水务局申请**排水管网/泵站**数据（内涝成因核心）。
- [ ] 地理编码 206 条易涝点 → 坐标，与路网/水位测站关联。
