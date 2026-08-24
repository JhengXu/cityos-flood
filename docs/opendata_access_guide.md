# 深圳开放平台数据获取指南（注册/登录/取Cookie/下载）

> 本项目已通过本流程成功下载 **深圳市水务局「积涝点水位数据」+「测站基本信息」**。
> 本指南记录完整可复现的步骤，供团队复现或补采。

---

## 1. 前置：两个核心数据集

| 数据集 | dataSetId | 文件格式 | 说明 |
|--------|-----------|---------|------|
| **市水务局积涝点水位数据** | `29200_01403147` | csv/xlsx/json/xml | 积涝点水位时序，**开放方式：无条件开放**，数据量约3505万条 |
| **市水务局测站基本信息表** | `29200_01400987` | csv/xlsx/json/xml/rdf | 测站编码/名称/站类（含**148个内涝水情站**） |

- 数据集详情页：`https://opendata.sz.gov.cn/data/dataSet/toDataDetails/{dataSetId}`
- **关键约束**：下载需**登录 + 实名认证**（`userLevel=2`）。

## 2. 登录/取 Cookie

平台 `opendata.sz.gov.cn` 的下载接口全部需登录会话（匿名调用返回 502/JSON 空）。有两种方式：

### 方式A：直接用已登录的 Chrome 下载（最省事）
您自己在 Chrome 里登录后，直接打开数据集页 → 点「文件」标签 → 点对应格式的「下载」即可。无需取 Cookie。

### 方式B：取 Cookie 后用脚本下载（本项目采用）
1. 在已登录的 Chrome 中按 F12 → **Application（应用）→ Storage（存储）→ Cookies → https://opendata.sz.gov.cn**
2. 复制 **JSESSIONID** 的 Value（形如 `b969663f-c6df-48ca-be9c-8f2477ad0ab6`）及其他登录 Cookie。
3. 用 curl 携带该 Cookie 调用下载接口（见下）。

> 注意：注册时需**手机号+短信验证码**；登录页的「手机验证码登录」对已注册账号可直接发短信，但若该号未注册会提示「手机号没有注册」。建议直接使用已有账号登录。

## 3. 获取文件下载链接（核心）

`singleFileDownload` 函数会 POST 到 `/data/dataSet/singleFileDownload`，成功后返回 JSON，其中 `message` 字段就是**带 filekey 的下载 URL**：

```bash
curl -s -X POST "https://opendata.sz.gov.cn/data/dataSet/singleFileDownload" \
  -H "Cookie: JSESSIONID=<你的JSESSIONID>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "fileId=<文件ID>&resId=29200/01403147&isShowOriginalFileName=true"
# 返回 {"result":"true","message":"https://opendata.sz.gov.cn/downloadFiles/temp/zip/<文件名>?filekey=..."}
```

⚠️ **`resId` 必须用斜杠格式 `29200/01403147`**（下划线 `_` 会 502）。

## 4. 下载文件

用拿到的下载 URL（含 filekey）+ Cookie 直接下载：

```bash
curl -s -H "Cookie: JSESSIONID=<JSESSIONID>" \
  -o data/raw/sz_waterlevel_points.csv \
  "https://opendata.sz.gov.cn/downloadFiles/temp/zip/...csv?filekey=..."
```

**关键文件ID（本项目用到的）**：

| 数据集 | 格式 | fileId |
|--------|------|--------|
| 积涝点水位数据 | CSV | `1818478466449911808` |
| 积涝点水位数据 | XLSX | `1818478466487660544` |
| 积涝点水位数据 | JSON | `1818478466307305472` |
| 积涝点水位数据 | XML | `1818478466407968768` |
| 测站基本信息表 | CSV | `2008721463098224640` |
| 测站基本信息表 | XLSX | `2008721463106613248` |

## 5. 已下载结果

| 文件 | 内容 | 规模 |
|------|------|------|
| `data/raw/sz_waterlevel_points.csv` | 内涝水情站水位时序 | **100,000 条**（148个内涝水情站，2026-08-19~08-20） |
| `data/raw/sz_station_info.csv` | 测站信息 | **485 个站**（内涝水情站148 / 水库204 / 河道133） |
| `data/processed/shenzhen_waterlevel_clean.csv` | 清洗后水位时序 | 100,000 条，含站名/坐标 |
| `data/processed/shenzhen_stations_geo.csv` | 148个内涝水情站（OSM定位81个） | 148 条 |

## 6. 局限与对策

- **单次下载上限约 10 万条**（当前为最近2天数据）。要全量3505万条，需按时间分批下载或联系水务局。
- 当前下载只是近期运行切片，不含可独立验证的历史暴雨事件。2019 易涝点名单与 CHIRPS 日雨只能用于事件检索、空间先验和交叉核验，不能拼接扩展成逐时水深训练标签。
- **站名无坐标**：站名本身即内涝点描述（如「滨河益田立交桥洞」），已用 OSM 路网匹配定位 81/148。
- 后续可用高德/百度地理编码 key 精确定位全部站名。

## 7. 天地图地理编码（补全坐标）

用**天地图浏览器端key**（需带 Referer `https://lbs.tianditu.gov.cn/`）可精确地理编码。

```bash
# 地理编码: 结果在 location.{lat,lon}, 需限定深圳bbox过滤误匹配
curl "https://api.tianditu.gov.cn/geocoder?ds={\"keyWord\":\"深圳市龙岗区政府\",\"level\":\"12\",\"city\":\"深圳\",\"mapBound\":\"113.7,22.4,114.7,22.9\"}&tk=<KEY>" \
  -H "Referer: https://lbs.tianditu.gov.cn/"
```

- ✅ 已用其把 **148个内涝水情站**、**206条2019易涝点** 全部定位到坐标（见 `data/processed/shenzhen_station_locations.csv`、`shenzhen_floodpoints_geo_v2.csv`）。
- ⚠️ **需过滤**：不加「深圳」前缀会误匹配外省市（如「万达广场」→昆明、「市民中心」→杭州）；已用 bbox+前缀+评分(≥30) 三重过滤。
- ⚠️ **行政区划接口被 WAF 拦截(418)**，该key无法下载行政边界；如需区/街道边界可用 OSM（Overpass）获取。
