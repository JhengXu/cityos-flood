#!/usr/bin/env python3
"""Extract Shenzhen-region daily rainfall from CHIRPS-2.0 global daily tiffs.
Reads TIFF tags dynamically (strip offsets, georeferencing) instead of hardcoding."""
import gzip, struct, os, csv, glob

RAW = "data/rainfall/raw"
LON_MIN, LON_MAX = 113.72, 114.65
LAT_MIN, LAT_MAX = 22.44, 22.87
NODATA = -9999.0

def parse_tiff(raw):
    endian = '<' if raw[:2]==b'II' else '>'
    ifd = struct.unpack(endian+'I', raw[4:8])[0]
    n = struct.unpack(endian+'H', raw[ifd:ifd+2])[0]
    tags = {}
    for i in range(n):
        e = ifd+2+i*12
        tag, typ, cnt, val = struct.unpack(endian+'HHII', raw[e:e+12])
        tags[tag] = (typ, cnt, val)
    return endian, tags

def get_val(raw, endian, tag, count):
    typ, cnt, val = tag
    nbytes = {1:1,2:1,3:2,4:4,5:8,11:4,12:8}[typ]*count
    if nbytes <= 4:
        # value inline
        fmt = {1:'B',3:'H',4:'I'}.get(typ)
        if fmt and count==1:
            return struct.unpack(endian+fmt, struct.pack('<I',val)[:nbytes])[0]
        return val
    else:
        off = val
        if typ==4:  # LONG array
            return list(struct.unpack(endian+f'{count}I', raw[off:off+4*count]))
        if typ==3:  # SHORT array
            return list(struct.unpack(endian+f'{count}H', raw[off:off+2*count]))
        if typ==12:  # DOUBLE array
            return list(struct.unpack(endian+f'{count}d', raw[off:off+8*count]))
        return val

def load_reader(fname):
    raw = gzip.open(fname,'rb').read()
    endian, tags = parse_tiff(raw)
    W = get_val(raw,endian,tags[256],tags[256][1]) if 256 in tags else 7200
    H = get_val(raw,endian,tags[257],tags[257][1]) if 257 in tags else 2000
    strip_offsets = get_val(raw,endian,tags[273],tags[273][1])
    if isinstance(strip_offsets, int):
        strip_offsets = [strip_offsets]
    # 地理参考
    scale = get_val(raw,endian,tags[33550],tags[33550][1]) if 33550 in tags else [0.05,0.05,0]
    tie = get_val(raw,endian,tags[33922],tags[33922][1]) if 33922 in tags else [0,0,0,-180,50,0]
    sx,sy = scale[0], scale[1]
    i0,j0,X0,Y0 = tie[0],tie[1],tie[3],tie[4]
    rowbytes = W*4
    def pixel(col,row):
        off = strip_offsets[row] + col*4
        return struct.unpack(endian+'f', raw[off:off+4])[0]
    return pixel, W, H, sx, sy, X0, Y0

def col_of(lon, X0, sx):  return (lon - X0)/sx
def row_of(lat, Y0, sy):
    # 北向上: 行随纬度降低而增加
    return (Y0 - lat)/sy

rows = []
for gz in sorted(glob.glob(os.path.join(RAW,'*.tif.gz'))):
    d = os.path.basename(gz).replace('chirps-v2.0.','').replace('.tif.gz','')
    try:
        pixel, W, H, sx, sy, X0, Y0 = load_reader(gz)
    except Exception as e:
        print(d, 'PARSE_FAIL', e); continue
    c0,c1 = int(col_of(LON_MIN,X0,sx)), int(col_of(LON_MAX,X0,sx))
    r0,r1 = int(row_of(LAT_MAX,Y0,sy)), int(row_of(LAT_MIN,Y0,sy))
    c0,c1 = max(0,c0), min(W-1,c1)
    r0,r1 = max(0,r0), min(H-1,r1)
    vals=[]
    for r in range(r0,r1+1):
        for c in range(c0,c1+1):
            v = pixel(c,r)
            if v != NODATA:
                vals.append(v)
    if vals:
        rows.append({'date':d,'mean_mm':round(sum(vals)/len(vals),2),
                     'max_mm':round(max(vals),2),'min_mm':round(min(vals),2),
                     'n_pixels':len(vals)})
    else:
        rows.append({'date':d,'mean_mm':0,'max_mm':0,'min_mm':0,'n_pixels':0})

os.makedirs('data/processed', exist_ok=True)
out='data/processed/shenzhen_chirps_rainfall.csv'
with open(out,'w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=['date','mean_mm','max_mm','min_mm','n_pixels'])
    w.writeheader(); w.writerows(rows)
print("深圳区域每日降雨量 (CHIRPS-2.0, 动态解析):")
for r in sorted(rows,key=lambda x:x['date']):
    print(f"  {r['date']}: mean={r['mean_mm']:>7}mm max={r['max_mm']:>7}mm px={r['n_pixels']}")
print(f"\n已保存 {out}")
