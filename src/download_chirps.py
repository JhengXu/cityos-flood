#!/usr/bin/env python3
"""Download CHIRPS-2.0 daily global rainfall tiffs for key Shenzhen flood events."""
import os, sys, time, urllib.request, concurrent.futures

BASE = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/{y}/chirps-v2.0.{d}.tif.gz"
OUT = "/Users/imac/shs/shenzhen-flood/data/rainfall/raw"
os.makedirs(OUT, exist_ok=True)

# Key historical extreme-rainfall / flood days for Shenzhen
EVENTS = [
    "2014.05.11", "2014.05.12",
    "2016.05.20",
    "2017.08.29", "2017.08.30",
    "2018.08.29",
    "2020.05.11",
    "2023.05.11",
    "2023.09.07", "2023.09.08",
    "2024.04.26",
    "2024.05.11",
]

def fetch(d):
    y = d.split(".")[0]
    url = BASE.format(y=y, d=d)
    fn = os.path.join(OUT, f"chirps-v2.0.{d}.tif.gz")
    if os.path.exists(fn) and os.path.getsize(fn) > 0:
        return (d, "exists")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hackathon/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            open(fn, "wb").write(data)
            return (d, f"ok {len(data)}B")
        except Exception as e:
            if attempt == 2:
                return (d, f"FAIL {e}")
            time.sleep(2)

with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    for d, res in ex.map(fetch, EVENTS):
        print(d, res, flush=True)
print("DONE")
