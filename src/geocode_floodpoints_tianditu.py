#!/usr/bin/env python3
"""用天地图地理编码给 2019 深圳易涝点名单定位。"""
import json, csv, os, re, time, urllib.request, urllib.parse

TK = "8e275d45d3d21a78bf1c097e9639655c"
FLOOD = "data/floodpoints/sz_waterlogging_points_2019.csv"
OUT = "data/processed/shenzhen_floodpoints_geo_v2.csv"

def geocode(kw):
    ds = {"keyWord": kw, "level": "12", "city": "深圳", "mapBound": "113.7,22.4,114.7,22.9"}
    url = f"https://api.tianditu.gov.cn/geocoder?ds={urllib.parse.quote(json.dumps(ds,ensure_ascii=False))}&tk={TK}"
    req = urllib.request.Request(url, headers={'Referer':'https://lbs.tianditu.gov.cn/','User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def in_sz(lat, lon): return 22.3 <= lat <= 23.0 and 113.6 <= lon <= 114.8

def resolve(location, district):
    # 候选查询
    loc = location.strip()
    cands = [loc, district + loc, "深圳" + loc, district + loc.replace("路口","").replace("交汇处",""),
             "深圳市" + district + loc]
    seen=set(); c=[]
    for x in cands:
        x=x.strip()
        if x and x not in seen: seen.add(x); c.append(x)
    for kw in c:
        try:
            d = geocode(kw)
            loc2 = d.get('location', {})
            try: lat, lon = float(loc2.get('lat')), float(loc2.get('lon'))
            except: continue
            score = loc2.get('score') or 0
            if in_sz(lat, lon) and score >= 30:
                return round(lat,6), round(lon,6), loc2.get('keyWord', kw), kw
        except Exception:
            time.sleep(2)
        time.sleep(0.5)
    return None

def main():
    rows = list(csv.DictReader(open(FLOOD, encoding='utf-8-sig')))
    out=[]
    n=0
    for i,r in enumerate(rows):
        hit = resolve(r['location'], r['district'])
        if hit:
            lat,lon,kw,used = hit
            out.append({**r,'lat':lat,'lon':lon,'method':'tianditu'}); n+=1
        else:
            out.append({**r,'lat':'','lon':'','method':'unresolved'})
        if (i+1)%30==0: print(f'... {i+1}/{len(rows)} 已定位 {n}', flush=True)
    with open(OUT,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['district','street','location','lat','lon','method'])
        w.writeheader(); w.writerows(out)
    print(f'完成: 内涝点 {len(out)} 条, 已定位 {n} ({100*n//len(out)}%)')

main()
