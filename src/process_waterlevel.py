#!/usr/bin/env python3
"""清洗深圳内涝水情站水位数据, 与测站信息/坐标整合。"""
import csv, os
from collections import defaultdict

WL='data/raw/sz_waterlevel_points.csv'
STGEO='data/processed/shenzhen_stations_geo.csv'
OUT='data/processed/shenzhen_waterlevel_clean.csv'
OSM='data/osm/shenzhen_roads_raw.json'

def load_geo():
    geo={}
    for r in csv.DictReader(open(STGEO,encoding='utf-8-sig')):
        geo[r['station_code']]={'station_name':r['station_name'],'lat':r['lat'],'lon':r['lon'],'road':r['matched_road']}
    return geo

def main():
    geo=load_geo()
    rows=[]; n=0
    for r in csv.DictReader(open(WL,encoding='utf-8-sig')):
        code=r['测站编码'].strip()
        t=r['时间'].strip().strip('\t').replace('\t',' ').strip()
        try: lvl=float(r['水位（m）'].strip())
        except: lvl=None
        g=geo.get(code,{})
        rows.append({'station_code':code,'station_name':g.get('station_name',''),
                     'time':t,'level_m':lvl,'lat':g.get('lat',''),'lon':g.get('lon','')})
        n+=1
    os.makedirs('data/processed',exist_ok=True)
    with open(OUT,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['station_code','station_name','time','level_m','lat','lon'])
        w.writeheader(); w.writerows(rows)
    print(f'清洗后记录: {n} 条 -> {OUT}')
    # 统计
    from collections import Counter
    stations=Counter(r['station_code'] for r in rows)
    print('涉及测站数:', len(stations))
    # 每条记录的时间分布
    days=Counter(r['time'][:10] for r in rows)
    print('日期分布:', dict(sorted(days.items())))
    print('样例:', rows[0])

main()
