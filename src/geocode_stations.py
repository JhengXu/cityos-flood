#!/usr/bin/env python3
"""用 OSM 路网名匹配给深圳内涝水情站定位 (近似坐标)。"""
import json, csv, re, os

OSM='data/osm/shenzhen_roads_raw.json'
ST='data/raw/sz_station_info.csv'
OUT='data/processed/shenzhen_stations_geo.csv'

def load_osm():
    d=json.load(open(OSM))
    idx={}
    for w in d.get('elements',[]):
        if w.get('type')!='way': continue
        name=(w.get('tags') or {}).get('name')
        geom=w.get('geometry')
        if not name or not geom: continue
        lat=sum(g['lat'] for g in geom)/len(geom)
        lon=sum(g['lon'] for g in geom)/len(geom)
        idx.setdefault(name, []).append((lat,lon))
    return idx

def find_road(loc, idx):
    """在站名里找 OSM 路名 (长度>=2), 返回 (路名, 中心点)。"""
    for name,pts in idx.items():
        if name and len(name)>=2 and name in loc:
            lat=sum(p[0] for p in pts)/len(pts)
            lon=sum(p[1] for p in pts)/len(pts)
            return name,lat,lon
    return None,None,None

def main():
    idx=load_osm()
    idx={k:v for k,v in sorted(idx.items(), key=lambda x:-len(x[1]))}  # 高频路优先
    rows=[]
    for r in csv.DictReader(open(ST,encoding='utf-8-sig')):
        if r['站类'].strip()!='内涝水情站': continue
        name=r['测站名称'].strip()
        rn,lat,lon=find_road(name, idx)
        rows.append({'station_code':r['测站编码'].strip(),'station_name':name,
                     'matched_road':rn or '','lat':lat if lat is not None else '',
                     'lon':lon if lon is not None else ''})
    os.makedirs('data/processed',exist_ok=True)
    with open(OUT,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['station_code','station_name','matched_road','lat','lon'])
        w.writeheader(); w.writerows(rows)
    matched=sum(1 for r in rows if r['lat']!='')
    print(f'内涝水情站: {len(rows)} 个, 匹配到坐标: {matched} ({100*matched//len(rows)}%)')
    for r in rows[:15]: print('  ', r['station_name'], '->', r['matched_road'], (r['lat'],r['lon']))

main()
