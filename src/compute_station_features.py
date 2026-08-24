#!/usr/bin/env python3
"""计算 148 个内涝水情站的静态特征矩阵 (模型输入)。
elevation_m / road_density / impervious_pct / dist_to_water_km
"""
import csv, json, math, os
import numpy as np

def haversine(lat1,lon1,lat2,lon2):
    R=6371.0
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(a))

def main():
    # 站点
    stations=list(csv.DictReader(open('data/processed/shenzhen_station_locations.csv',encoding='utf-8-sig')))
    # DEM
    dem=list(csv.DictReader(open('data/processed/shenzhen_dem.csv',encoding='utf-8-sig')))
    dem=[(float(r['lat']),float(r['lon']),float(r['elevation_m'])) for r in dem]
    # 路网
    roads=list(csv.DictReader(open('data/processed/shenzhen_roads_summary.csv',encoding='utf-8-sig')))
    roads=[(float(r['lat']),float(r['lon']),float(r['length_m'])) for r in roads if r['lat']]
    # 不透水密度
    imp=list(csv.DictReader(open('data/processed/shenzhen_builtup_density.csv',encoding='utf-8-sig')))
    imp=[(float(r['lat']),float(r['lon']),float(r['builtup_pct'])) for r in imp]
    # 水系 (取折线点)
    water=json.load(open('data/processed/shenzhen_water.geojson'))
    wpts=[]
    for f in water['features']:
        for c in f['geometry']['coordinates']:
            wpts.append((c[1],c[0]))  # lat,lon
    print('水系点数:',len(wpts))

    rows=[]
    for s in stations:
        lat,lon=float(s['lat']),float(s['lon'])
        # 最近DEM
        e=min(dem,key=lambda x:haversine(lat,lon,x[0],x[1]))
        elev=e[2]
        # 不透水: 最近格网
        i=min(imp,key=lambda x:haversine(lat,lon,x[0],x[1]))
        imp_pct=i[2]
        # 路网密度: 500m内路长(km)/面积(km²)
        rd=sum(r[2] for r in roads if haversine(lat,lon,r[0],r[1])<=0.5)/1000
        rd=rd/(math.pi*0.5**2)
        # 到最近水系距离
        dw=min(haversine(lat,lon,w[0],w[1]) for w in wpts) if wpts else 0
        rows.append({'station_code':s['station_code'],'station_name':s['station_name'],
                     'lat':lat,'lon':lon,'elevation_m':round(elev,1),
                     'road_density':round(rd,2),'impervious_pct':round(imp_pct,1),
                     'dist_to_water_km':round(dw,2)})
    os.makedirs('data/processed',exist_ok=True)
    with open('data/processed/shenzhen_station_features.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['station_code','station_name','lat','lon','elevation_m','road_density','impervious_pct','dist_to_water_km'])
        w.writeheader(); w.writerows(rows)
    print('特征矩阵已生成:',len(rows),'站')
    print('示例:')
    for r in rows[:4]: print('  ',r)

main()
