#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_fries_data.py — 一键拉取「麦门薯条推荐官」需要的全部 MCP 数据。

把三样东西落盘，供 scripts/fries.py 离线分析：
    <out>/meals.json        query-meals
    <out>/nutrition.json    list-nutrition-foods
    <out>/details/<code>.json  每个餐品的 query-meal-detail（薯条规格藏在这里）

用法：
    export MCD_MCP_TOKEN=你的token
    python3 scripts/fetch_fries_data.py --store 1950264 --out /tmp/mcd_fries

说明：query-meal-detail 会对每个餐品调一次。麦当劳一个门店约 120 个餐品，
实测 120 次调用很快，远低于 600 次/分钟的限流。如果你只关心套餐里的薯条，
加 --combos-only 只会抓名字带「套餐/三件套/盒/随心配/四件套」的餐品，调用量更小。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from mcp_client import McpClient  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="拉取麦门薯条推荐官所需的 MCP 数据")
    p.add_argument("--store", default="1950264", help="门店 storeCode，默认北京双桥路")
    p.add_argument("--out", required=True, help="输出目录")
    p.add_argument("--token", default=os.environ.get("MCD_MCP_TOKEN", ""))
    p.add_argument("--combos-only", action="store_true",
                   help="只抓套餐类餐品（调用量更小）")
    a = p.parse_args()

    if not a.token:
        print("错误：缺少 MCP Token。export MCD_MCP_TOKEN=你的token", file=sys.stderr)
        return 1

    os.makedirs(a.out, exist_ok=True)
    os.makedirs(f"{a.out}/details", exist_ok=True)
    client = McpClient(a.token)

    print("[1/3] query-meals ...")
    meals = client.call_tool("query-meals",
                             {"storeCode": a.store, "beType": 1, "orderType": 1})
    json.dump(meals, open(f"{a.out}/meals.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    print("[2/3] list-nutrition-foods ...")
    nutri = client.call_tool("list-nutrition-foods", {})
    json.dump(nutri, open(f"{a.out}/nutrition.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    data = meals.get("data", meals) if isinstance(meals, dict) else meals
    codes = list(data.get("meals", {}).keys())
    if a.combos_only:
        hints = ("套餐", "三件套", "两件套", "桶", "盒", "随心配", "1+1",
                 "分享", "拼盘", "四件套", "双全")
        mdict = data.get("meals", {})
        codes = [c for c in codes
                 if any(h in str(mdict[c].get("name", "")) for h in hints)]
    print(f"[3/3] query-meal-detail × {len(codes)} ...")
    ok = err = 0
    for i, code in enumerate(codes, 1):
        try:
            det = client.call_tool("query-meal-detail",
                                   {"storeCode": a.store, "beType": 1,
                                    "orderType": 1, "code": code})
            json.dump(det, open(f"{a.out}/details/{code}.json", "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            ok += 1
        except Exception as e:
            err += 1
            if err <= 3:
                print(f"  ERR {code}: {e}")
        if i % 30 == 0:
            print(f"  progress {i}/{len(codes)}")
    print(f"DONE meals={len(codes)} detail_ok={ok} err={err}")
    print(f"下一步：")
    print(f"  python3 scripts/fries.py recommend \\")
    print(f"    --meals {a.out}/meals.json \\")
    print(f"    --nutrition {a.out}/nutrition.json \\")
    print(f"    --details-dir {a.out}/details")
    return 0


if __name__ == "__main__":
    sys.exit(main())
