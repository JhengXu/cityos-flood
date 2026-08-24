#!/usr/bin/env python3
"""用 OSM Overpass POI 查询给深圳内涝水情站定位 (免费, 免key)。
对每个未定位站做多种名称匹配, 取最优结果。剩余的标记为"待定位"。
"""
import json, csv, os, time, urllib.request, urllib.parse, re, subprocess

OVER = "https://overpass-api.de/api/interpreter"
BBOX = "22.4,113.7,22.9,114.7"
GEO = "data/processed/shenzhen_stations_geo.csv"
OUT = "data/processed/shenzhen_stations_geo_v2.csv"

def overpass(q, timeout=40):
    data = f"[out:json][timeout:30];{q};out center 1;"
    req = urllib.request.Request(OVER, data=urllib.parse.urlencode({'data': data}).encode(),
                                 headers={'User-Agent': 'shenzhen-flood/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def query_name(name):
    """对名称做多策略 Overpass 查询, 返回 (lat, lon, matched_name) 或 None。"""
    name = name.strip()
    candidates = [name]
    # 去掉 (市) 前缀
    m = re.match(r'^\(市\)(.*)$', name)
    if m and m.group(1):
        candidates.append(m.group(1))
    # 去掉 "地铁站 X 出入口"/"地铁站" 冗余后缀 及 括号内容
    for c in list(candidates):
        candidates.append(re.sub(r'(地铁站.*|站.*出入口|（.*?）|\(.*?\))', '', c).strip())
    candidates = [c for c in candidates if c][:4]
    candidates = list(dict.fromkeys(candidates))  # 去重保序

    for c in candidates:
        if len(c) < 2:
            continue
        for pat in [rf"^{re.escape(c)}$", re.escape(c)]:
            q = f'nwr["name"~"{pat}"]({BBOX})'
            try:
                d = overpass(q)
                els = d.get('elements', [])
                if els:
                    e = els[0]
                    ctr = e.get('center') or e
                    return (ctr.get('lat'), ctr.get('lon'), e.get('tags', {}).get('name', c), c)
            except Exception:
                time.sleep(3)
            time.sleep(1.0)  # 限流
    return None

def main():
    rows = list(csv.DictReader(open(GEO, encoding='utf-8-sig')))
    results = []
    n_osmos = 0
    for i, r in enumerate(rows):
        if r['lat'] != '':
            results.append(r)  # 保留已定位的
            continue
        name = r['station_name'].strip()
        hit = query_name(name)
        if hit:
            lat, lon, mname, used = hit
            results.append({**r, 'lat': round(lat, 5), 'lon': round(lon, 5),
                            'matched_road': r['matched_road'] or ('OSM:' + mname), 'method': 'osm_poi'})
            n_osmos += 1
        else:
            results.append({**r, 'method': 'unresolved'})
        # 进度
        if (i + 1) % 10 == 0:
            print(f'... 处理 {i+1}/{len(rows)} 已定位OSM {n_osmos}', flush=True)

    with open(OUT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['station_code', 'station_name', 'matched_road', 'lat', 'lon', 'method'])
        w.writeheader(); w.writerows(results)
    total = sum(1 for r in results if r['lat'] != '')
    print(f'完成: 已定位 {total}/{len(results)} (其中OSM POI新增 {n_osmos})')

main()
