# 数据字典（Data Dictionary）

> 对应本次已落地的各数据文件，描述字段含义、单位、取值范围与缺失处理。

---

## 1. `data/processed/shenzhen_chirps_rainfall.csv` —— 深圳逐日降雨量

| 字段 | 含义 | 单位 | 说明 |
|------|------|------|------|
| `date` | 日期（UTC 日） | — | 格式 `YYYY.MM.DD`，对应 CHIRPS 栅格日期 |
| `mean_mm` | 深圳区域平均降雨 | mm | 覆盖 `113.72–114.65°E, 22.44–22.87°N` 的栅格像元均值 |
| `max_mm` | 深圳区域最大降雨 | mm | 单像元最大，反映暴雨中心强度 |
| `min_mm` | 深圳区域最小降雨 | mm | |
| `n_pixels` | 参与统计的像元数 | 个 | 已剔除 NODATA(-9999)，深圳约 165 像元 |

**来源**：CHIRPS-2.0 全球逐日降雨（0.05°≈5.5km）。**提取脚本**：`src/extract_shenzhen_rainfall.py`。
**缺失值**：CHIRPS 陆地区域有效；海洋为 NODATA(-9999)。已剔除。
**注意**：日尺度、UTC 日界，跨午夜暴雨可能被拆分。

---

## 2. `data/processed/shenzhen_dem.csv` —— 深圳高程采样

| 字段 | 含义 | 单位 | 说明 |
|------|------|------|------|
| `lat` | 纬度 | 度 | WGS84 |
| `lon` | 经度 | 度 | WGS84 |
| `elevation_m` | 地面高程 | 米 | SRTM 90m |

**来源**：OpenTopoData `srtm90m`。**采样网格**：0.03°×0.03°（约3.3km），共480点。
**范围**：`-5m – 506m`。

---

## 3. `data/processed/shenzhen_roads_summary.csv` —— 深圳路网汇总

| 字段 | 含义 | 单位 | 说明 |
|------|------|------|------|
| `name` | 道路名称 | — | 中文路名，可能为空 |
| `highway` | 道路等级 | — | motorway/trunk/primary/secondary/tertiary |
| `lat` | 路段中心纬度 | 度 | WGS84 |
| `lon` | 路段中心经度 | 度 | WGS84 |
| `length_m` | 路段长度 | 米 | 由折线近似计算 |
| `n_nodes` | 折线节点数 | 个 | |

**来源**：OpenStreetMap Overpass API。**数量**：28,625 段。**原始几何**：`data/osm/shenzhen_roads_raw.json`（GeoJSON，29MB）。

---

## 4. `data/floodpoints/sz_waterlogging_points_2019.csv` —— 深圳易涝点名单

| 字段 | 含义 | 单位 | 说明 |
|------|------|------|------|
| `district` | 行政区 | — | 福田/罗湖/盐田/南山/宝安/龙岗/龙华/坪山/光明/大鹏新区 |
| `street` | 街道 | — | 如「福保街道」 |
| `location` | 具体易涝点 | — | 道路/桥洞/路口/小区名 |

**来源**：深圳官方口径汇总（2019，`sz_waterlogging_roads_2019.txt` 为原始文本）。
**数量**：206 条。**用途**：静态易涝暴露先验与巡查布点；不是逐时水深 ground truth。坐标化结果见项目内处理产物。

---

## 5. `data/raw/sz_waterlevel_points.csv` —— 积涝点水位原始数据

| 字段 | 含义 | 单位 | 说明 |
|------|------|------|------|
| `测站编码` | 内涝水情站编码 | — | 与测站表关联 |
| `时间` | 采集时间 | — | 格式 `2026-08-19 00:00:30` |
| `水位（m）` | 水位 | 米 | 多为0，非零值反映积水 |
| `水位id` | 记录id | — | |

**来源**：深圳市水务局开放平台（dataSetId=29200_01403147，无条件开放）。**规模**：100,000 条，148个内涝水情站，2026-08-19~08-20。

## 5b. `data/raw/sz_station_info.csv` —— 测站基本信息

| 字段 | 含义 | 单位 | 说明 |
|------|------|------|------|
| `测站编码` | 测站编码 | — | |
| `测站名称` | 测站名称 | — | **即内涝点描述**（如「滨河益田立交桥洞」） |
| `站类` | 测站类型 | — | 内涝水情站148 / 水库水位站204 / 河道水位站133 |

**来源**：dataSetId=29200_01400987。**规模**：485 个测站。**注意**：无经纬度字段。

## 5c. `data/processed/shenzhen_waterlevel_clean.csv` —— 清洗后水位时序

整合水位数据与测站信息/坐标，字段：`station_code, station_name, time, level_m, lat, lon`。100,000 条。用于监测分析。

## 5d. `data/processed/shenzhen_stations_geo.csv` —— 内涝水情站定位

| 字段 | 含义 | 说明 |
|------|------|------|
| `station_code` / `station_name` | 测站编码/名称 | |
| `matched_road` | 匹配到的OSM路名 | 用于定位 |
| `lat` / `lon` | 坐标 | 用OSM路名匹配，81/148站有值 |

**方法**：站名含路名（如「沿河南路」「东湖路」），在OSM路网中匹配名称取中心点。其余站名为学校/政府/地铁等地标，需高德/百度地理编码。

## 5e. `data/processed/shenzhen_station_locations.csv` —— 内涝水情站坐标（全部定位）

| 字段 | 含义 | 说明 |
|------|------|------|
| `station_code` / `station_name` | 测站编码/名称 | |
| `lat` / `lon` | 坐标 | **148/148 全部定位** |
| `method` | 定位方法 | `osm_road`(81) / `tianditu`(66+1) |

**来源**：OSM 路网匹配 + **天地图地理编码**（浏览器端key）。全部在深圳bbox内。

## 5f. `data/processed/shenzhen_floodpoints_geo_v2.csv` —— 2019易涝点坐标（全部定位）

| 字段 | 含义 | 说明 |
|------|------|------|
| `district` / `street` / `location` | 区/街道/易涝点 | |
| `lat` / `lon` | 坐标 | **206/206 全部定位** |
| `method` | 定位方法 | 天地图地理编码 |

**来源**：天地图地理编码 API，全部在深圳bbox内（lat 22.50~22.81, lon 113.79~114.53）。

---

## 6. `data/osm/shenzhen_roads_raw.json` —— OSM 路网原始 GeoJSON

Overpass 导出，每条 `way` 含 `tags`（名称/等级）与 `geometry`（经纬度折线）。ODbL 许可。用于后续构建路网图、缓冲/密度分析。

---

## 6. `data/rainfall/raw/*.tif.gz` —— CHIRPS 原始栅格

全球 7200×2000 float32 GeoTIFF（gzip），覆盖 `-180–180°E, 50–50°N`（北向上，0.05°）。共12个关键事件日。NODATA=-9999。

## 10. `data/processed/shenzhen_water.geojson` —— 深圳水系

OSM水系，5965要素。GeoJSON FeatureCollection，`properties.kind`（river/pond/reservoir/lake等）+ `geometry`。用于汇流/水网背景。

## 11. `data/processed/shenzhen_districts.geojson` —— 深圳行政区划边界

OSM 9区边界（坪山/盐田/宝安/龙岗/福田/光明/龙华/罗湖/南山），GeoJSON FeatureCollection，`properties.name`。用于分区统计/风险地图底图。大鹏新区OSM为admin_level=7未含。

## 12. `data/processed/shenzhen_recession_time.csv` —— 内涝消退时间

| 字段 | 含义 | 说明 |
|------|------|------|
| `station_code` | 测站编码 | |
| `peak_m` | 峰值水位(米) | 观测时段最大水位 |
| `max_recess_h` | 最长消退时间(小时) | 峰值到水位降至阈值(0.02m)下的时间 |
| `avg_recess_h` | 平均消退时间 | |
| `events` | 积水事件数 | |

148 个内涝水情站；旧 0.02m 阈值算法在 31 站识别出非零片段，但这些片段没有独立事件标注，且最高水位仅 0.10m。该表只用于管线回放，不能作为已核验积水事件或模型技巧验证真值。

## 13. `outputs/shenzhen_flood_heatmap.html` —— 内涝热力图

Leaflet交互式热力图（`station_heatmap_data.json`）。148站彩色圆点，可切换 **消退时间/峰值水位/积水事件数** 三种指标，含图例与OSM底图。用浏览器打开即可查看。

## 14. `data/processed/shenzhen_builtup_density.csv` —— 深圳不透水面密度

| 字段 | 含义 | 说明 |
|------|------|------|
| `lat` / `lon` | 格网中心 | 500m格网 |
| `builtup_pct` | 不透水占比(%) | ESA WorldCover 类50(不透水) 占比 |
| `n_px` | 格网内像素数 | |

19,968 个格网。来源：ESA WorldCover 10m 2021 v200（`data/raw/worldcover/*.tif`，N21E111/N21E114 两瓦片裁剪深圳）。不透水面平均23.6%、最大99.9%。

## 15. `outputs/shenzhen_impervious_map.html` —— 深圳不透水面分布图

Leaflet交互图，500m格网按不透水密度着色（橙红=不透水）。底图OSM。`worldcover_summary.json` 为统计汇总。

## 16. `data/raw/worldcover/` —— ESA WorldCover 原始瓦片

`ESA_WorldCover_10m_2021_v200_N21E111/N21E114_Map.tif`，36000×36000 uint8 COG，10m分辨率，EPSG:4326。类值：10林地/50不透水/80水体等。来源 AWS `esa-worldcover` 公开桶 `v200/2021/map/`。
