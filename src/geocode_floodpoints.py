#!/usr/bin/env python3
"""将深圳易涝点地名地理编码为坐标。

优先用已下载的 OSM 路网做"路名匹配"（对中文路名最稳），
对无法匹配的条目，可选回退到 Nominatim（需网络且会被限流）。
输出: data/processed/shenzhen_floodpoints_geo.csv
"""
import json, csv, re, os, sys

OSM = 'data/osm/shenzhen_roads_raw.json'
FLOOD = 'data/floodpoints/sz_waterlogging_points_2019.csv'
OUT = 'data/processed/shenzhen_floodpoints_geo.csv'

def load_osm_index():
    """建立 路名 -> [(lat,lon)...] 的索引（道路中心点）。"""
    d = json.load(open(OSM))
    idx = {}
    for w in d.get('elements', []):
        if w.get('type') != 'way':
            continue
        name = (w.get('tags') or {}).get('name')
        geom = w.get('geometry')
        if not name or not geom:
            continue
        lat = sum(g['lat'] for g in geom)/len(geom)
        lon = sum(g['lon'] for g in geom)/len(geom)
        idx.setdefault(name, []).append((lat, lon))
    return idx

def match_location(loc, idx):
    """在位置字符串中找出现在 OSM 路网里的路名，返回其中心。"""
    # 尝试整串匹配 / 子串包含匹配
    for name, pts in idx.items():
        if name and name in loc:   # 路名出现在地点描述中
            lat = sum(p[0] for p in pts)/len(pts)
            lon = sum(p[1] for p in pts)/len(pts)
            return name, round(lat,5), round(lon,5)
    return None, None, None

def main():
    if not os.path.exists(OSM):
        print('未找到 OSM 路网文件，请先运行路网下载。'); return
    print('加载 OSM 路网索引...')
    idx = load_osm_index()
    print('路名数:', len(idx))
    # 用出现频率高的路名优先（减少误匹配）
    idx = {k:v for k,v in sorted(idx.items(), key=lambda x:-len(x[1]))}

    rows=[]; matched=0
    with open(FLOOD, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            loc = r['location']
            name, lat, lon = match_location(loc, idx)
            rows.append({'district':r['district'],'street':r['street'],
                         'location':loc,'matched_road':name or '',
                         'lat':lat if lat is not None else '',
                         'lon':lon if lon is not None else ''})
            if lat is not None:
                matched+=1
    os.makedirs('data/processed', exist_ok=True)
    with open(OUT,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['district','street','location','matched_road','lat','lon'])
        w.writeheader(); w.writerows(rows)
    print(f'匹配成功: {matched}/{len(rows)} 条')
    print('已保存', OUT)

if __name__=='__main__':
    main()
