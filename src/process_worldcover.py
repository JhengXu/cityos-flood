#!/usr/bin/env python3
"""从 ESA WorldCover COG 瓦片提取深圳不透水面(类50)与水体(类80)。"""
import tifffile, numpy as np, json, os, csv

DIR="data/raw/worldcover"
# 深圳 bbox
LONMIN,LONMAX,LATMIN,LATMAX=113.72,114.65,22.44,22.87

def crop_tile(path, lonmin,lonmax,latmin,latmax):
    with tifffile.TiffFile(path) as tif:
        page=tif.pages[0]
        # 从 tags 读取地理参考
        tags=page.tags
        w=tags['ImageWidth'].value; h=tags['ImageLength'].value
        # ModelPixelScale / ModelTiepoint
        scale=tags['ModelPixelScale'].value if 'ModelPixelScale' in tags else [0.0001,0.0001,0]
        tie=tags['ModelTiepoint'].value if 'ModelTiepoint' in tags else [0,0,0,-180,90,0]
        sx,sy=scale[0],scale[1]
        X0,Y0=tie[3],tie[4]
        # 像素列/行: col=(lon-X0)/sx ; row=(Y0-lat)/sy (北向上)
        c0=int((lonmin-X0)/sx); c1=int((lonmax-X0)/sx)
        r0=int((Y0-latmax)/sy); r1=int((Y0-latmin)/sy)
        c0,c1=max(0,c0),min(w-1,c1); r0,r1=max(0,r0),min(h-1,r1)
        data=page.asarray()[r0:r1+1, c0:c1+1]
        return data, (c0,r0,sx,sy,X0,Y0)

def main():
    tiles=[f for f in os.listdir(DIR) if f.endswith('.tif')]
    tiles.sort()
    print("处理瓦片:",tiles)
    allmask=[]
    for t in tiles:
        data,meta=crop_tile(os.path.join(DIR,t),LONMIN,LONMAX,LATMIN,LATMAX)
        # 类: 50=built-up(不透水), 80=水
        built=(data==50).astype(np.uint8)
        water=(data==80).astype(np.uint8)
        allmask.append((t,data,built,water,meta))
        print(f"  {t}: 尺寸{data.shape} builtup像素={int(built.sum())} 水体像素={int(water.sum())}")
    # 汇总
    c0,r0,sx,sy,X0,Y0=allmask[0][4]
    built_total=int(sum(m[2].sum() for m in allmask))
    water_total=int(sum(m[3].sum() for m in allmask))
    print(f"\n深圳区域: 不透水面像素={built_total} 水体像素={water_total}")
    print(f"像素尺度={sx:.6f}° (~{sx*111320:.1f}m)")
    # 保存 CSV 网格统计 (粗网格)
    json.dump({'tiles':tiles,'builtup_px':built_total,'water_px':water_total,
               'pixel_deg':sx},open('data/processed/worldcover_summary.json','w'))
    print("已保存 data/processed/worldcover_summary.json")

main()
