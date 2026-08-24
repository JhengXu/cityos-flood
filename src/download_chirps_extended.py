#!/usr/bin/env python3
"""扩展下载 CHIRPS: 关键暴雨事件窗口(前3天+事件日+后1天) + 部分正常天气(负样本)。"""
import os, time, urllib.request, concurrent.futures
BASE="https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/{y}/chirps-v2.0.{d}.tif.gz"
OUT="data/rainfall/raw"
os.makedirs(OUT,exist_ok=True)

def expand(start):
    y,m,d=start.split('-')
    import datetime
    base=datetime.date(int(y),int(m),int(d))
    days=[]
    for off in range(-3,2):  # 前3天..后1天
        days.append((base+datetime.timedelta(days=off)).strftime('%Y.%m.%d'))
    return days

# 关键事件 + 负样本(正常天气)
EVENTS=["2014-05-11","2017-08-29","2018-08-29","2023-09-07","2024-04-26"]
DRY=["2019-11-10","2020-12-05","2021-10-20","2022-11-15"]  # 正常/干旱日 负样本
dates=[]
for e in EVENTS: dates+=expand(e)
for d in DRY: dates.append(d)
dates=sorted(set(dates))

def fetch(d):
    y=d.split('.')[0]
    url=BASE.format(y=y,d=d)
    fn=os.path.join(OUT,f"chirps-v2.0.{d}.tif.gz")
    if os.path.exists(fn) and os.path.getsize(fn)>0: return (d,'exists')
    for _ in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'hackathon/1.0'})
            with urllib.request.urlopen(req,timeout=90) as r: data=r.read()
            open(fn,'wb').write(data); return (d,f'ok {len(data)}B')
        except Exception as e:
            if _==2: return (d,f'FAIL {e}')
            time.sleep(2)

with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    for d,res in ex.map(fetch,dates):
        print(d,res,flush=True)
print("EXTENDED_DONE",len(dates))
