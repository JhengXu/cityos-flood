#!/usr/bin/env python3
"""用天地图地理编码 API 精确定位深圳内涝水情站 (浏览器端key, 需Referer)。
对未定位站生成多种候选查询, 只接受落在深圳bbox内的结果。
"""
import json, csv, os, re, time, urllib.request, urllib.parse

TK = "8e275d45d3d21a78bf1c097e9639655c"
GEO = "data/processed/shenzhen_stations_geo.csv"
OUT = "data/processed/shenzhen_stations_geo_final.csv"
BBOX = (22.3, 23.0, 113.6, 114.8)  # latmin,latmax,lonmin,lonmax

def geocode(keyword):
    ds = {"keyWord": keyword, "level": "12", "city": "深圳", "mapBound": "113.7,22.4,114.7,22.9"}
    url = f"https://api.tianditu.gov.cn/geocoder?ds={urllib.parse.quote(json.dumps(ds,ensure_ascii=False))}&tk={TK}"
    req = urllib.request.Request(url, headers={'Referer': 'https://lbs.tianditu.gov.cn/', 'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def in_sz(lat, lon):
    latmin, latmax, lonmin, lonmax = BBOX
    return latmin <= lat <= latmax and lonmin <= lon <= lonmax

def candidates(name):
    name = name.strip()
    base = re.sub(r'^\(市\)', '', name)
    cands = [name, base, "深圳" + name, "深圳市" + name, "深圳" + base, "深圳市" + base]
    # 去除冗余后缀: 地铁站X出入口, (X)等内容
    stripped = re.sub(r'地铁站.*|站[ABCDF]\s*出入口|（.*?）|\(.*?\)', '', base).strip()
    if stripped and stripped != base:
        cands += ["深圳" + stripped, "深圳市" + stripped, stripped]
    # 去重保序
    seen = set(); out = []
    for c in cands:
        if c and c not in seen:
            seen.add(c); out.append(c)
    return out

def resolve(name):
    for c in candidates(name):
        try:
            d = geocode(c)
            loc = d.get('location', {})
            try:
                lat, lon = float(loc.get('lat')), float(loc.get('lon'))
            except (TypeError, ValueError):
                continue
            score = loc.get('score') or 0
            if in_sz(lat, lon) and score >= 30:
                return round(lat, 6), round(lon, 6), loc.get('keyWord', c), c
        except Exception:
            time.sleep(2)
        time.sleep(0.5)
    return None

def main():
    rows = list(csv.DictReader(open(GEO, encoding='utf-8-sig')))
    results = []
    n_new = 0
    for i, r in enumerate(rows):
        if r['lat'] != '':
            results.append({**r, 'method': 'osm_road'})
            continue
        hit = resolve(r['station_name'])
        if hit:
            lat, lon, kw, used = hit
            results.append({**r, 'lat': lat, 'lon': lon,
                            'matched_road': r['matched_road'] or ('Tianditu:' + kw), 'method': 'tianditu'})
            n_new += 1
        else:
            results.append({**r, 'method': 'unresolved'})
        if (i + 1) % 10 == 0:
            print(f'... {i+1}/{len(rows)} 新增 {n_new}', flush=True)

    with open(OUT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['station_code','station_name','matched_road','lat','lon','method'])
        w.writeheader(); w.writerows(results)
    total = sum(1 for r in results if r['lat'] != '')
    print(f'完成: 已定位 {total}/{len(results)} (天地图新增 {n_new})')

main()
