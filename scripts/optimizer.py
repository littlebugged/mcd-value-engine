#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
optimizer.py — 麦门省钱精算师的核心计算引擎。

设计原则：**凡是不确定的字段，都靠启发式归一化；凡是需要花钱核价的，都交给 MCP。**
这个脚本本身不发网络请求，只读本地 JSON、做纯计算。这样它既能在 Skill 流程里被
Agent 驱动，也能被任何人离线验证。

四个子命令：

1) plan     读菜单 + 券，枚举「合法券组合」，输出候选方案清单
            实际核价交给 Agent 用 calculate-price 逐个跑

2) rank     把多个核价结果汇总排序，输出真正的最优解 + 省了多少钱

3) value    纯本地：结合营养数据算「每元热量 / 每元蛋白质」，找出性价比之王
            同时算「券后每元价值」，回答"这张券到底值不值"

4) snap     价格快照：把当次核价存进 data/price_history.json，对比历史最低价
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from datetime import datetime
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(ROOT, "data", "price_history.json")


# ============ 启发式归一化 ============
# 麦当劳 MCP 返回的字段命名我们无法百分百确定，所以这里对每个语义字段
# 列出若干候选 key，按优先级取第一个命中的。取不到就返回 None，由上层容错。

def pick(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


def to_float(v) -> float | None:
    """把 '¥12.5' / '12.5元' / 12.5 / '12.5' 都转成 12.5。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    for ch in ("¥", "￥", "元", ",", " "):
        s = s.replace(ch, "")
    try:
        return float(s)
    except ValueError:
        return None


def normalize_coupon(raw: dict) -> dict | None:
    """把一张券的各种可能格式压成统一结构。"""
    if not isinstance(raw, dict):
        return None
    cid = pick(raw, "couponId", "id", "couponCode", "code", "activityId")
    name = pick(raw, "couponName", "name", "title", "couponTitle", "activityName")
    if cid is None and name is None:
        return None

    # 优惠力度：优先取"折扣后价/减免额"，其次取原价-现价
    face = to_float(pick(raw, "faceValue", "discountAmount", "amount", "reduceAmount",
                         "couponValue", "value", "discount"))
    price = to_float(pick(raw, "price", "salePrice", "payAmount"))
    origin = to_float(pick(raw, "originPrice", "originalPrice", "marketPrice"))
    if face is None and price is not None and origin is not None:
        face = round(origin - price, 2)

    threshold = to_float(pick(raw, "threshold", "minAmount", "useThreshold",
                              "minSpend", "condition", "limitAmount"))
    discount_rate = to_float(pick(raw, "discountRate", "rate", "discount"))
    if discount_rate is not None and discount_rate > 1:
        # 有些接口把 8.5 折写成 85
        discount_rate = discount_rate / 100.0 if discount_rate > 10 else discount_rate

    expire = pick(raw, "expireTime", "endTime", "validEndTime", "expireDate", "validity")
    category = pick(raw, "category", "type", "couponType", "bizType", "scene")

    # 适用范围：单品券只能用在指定商品上，通用券（满减/折扣）作用于整单。
    # 这一步不做对，就会推荐出"购物车里根本没这个商品"的券，是最常见的坑。
    scope_codes = pick(raw, "productCodes", "skuCodes", "mealCodes", "itemCodes",
                       "applicableCodes", "productCode", "skuCode", "mealCode")
    scope_names = pick(raw, "productNames", "mealNames", "applicableNames",
                       "productName", "mealName")
    codes = [str(c) for c in scope_codes] if isinstance(scope_codes, list) else (
        [str(scope_codes)] if scope_codes else [])
    names = [str(n) for n in scope_names] if isinstance(scope_names, list) else (
        [str(scope_names)] if scope_names else [])

    is_item_scope = bool(codes or names)
    if not is_item_scope and price is not None and origin is not None and not threshold:
        # 有原价/现价、又没有满减门槛 —— 基本可以判定是单品特价券
        is_item_scope = True
    if is_item_scope and not names and name:
        # 没给商品清单时，拿券名当线索（"麦香鱼特价9.9" 里含商品名）
        names = [str(name)]

    return {
        "id": cid,
        "name": name or str(cid),
        "face": face,                  # 直接减免的钱（元）
        "threshold": threshold or 0.0,  # 使用门槛（元），0 表示无门槛
        "rate": discount_rate,         # 折扣率（0.85 = 八五折），无则 None
        "expire": str(expire) if expire else None,
        "category": str(category) if category else None,
        "scope": "item" if is_item_scope else "order",
        "codes": codes,
        "names": names,
        "raw": raw,
    }


def normalize_meal(raw: dict) -> dict | None:
    code = pick(raw, "productCode", "code", "mealCode", "skuCode", "id")
    name = pick(raw, "productName", "name", "mealName", "title")
    if code is None and name is None:
        return None
    price = to_float(pick(raw, "price", "salePrice", "sellPrice", "amount",
                          "originPrice", "originalPrice", "marketPrice"))
    promo = to_float(pick(raw, "promoPrice", "discountPrice", "activityPrice"))
    return {
        "code": code,
        "name": name or str(code),
        "price": promo if promo is not None else price,
        "list_price": price,
        "category": str(pick(raw, "category", "categoryName", "type", "tag", default="") or ""),
        "raw": raw,
    }


def normalize_nutrition(raw: dict) -> dict | None:
    name = pick(raw, "foodName", "name", "productName", "mealName")
    if not name:
        return None
    return {
        "name": str(name),
        "kcal": to_float(pick(raw, "energy", "kcal", "calories", "热量", "能量")) or 0.0,
        "protein": to_float(pick(raw, "protein", "蛋白质")) or 0.0,
        "fat": to_float(pick(raw, "fat", "脂肪")) or 0.0,
        "carb": to_float(pick(raw, "carbohydrate", "carb", "碳水化合物")) or 0.0,
        "sodium": to_float(pick(raw, "sodium", "钠")),
        "raw": raw,
    }


def deep_collect(obj, out: list):
    """从任意嵌套的 MCP 返回里把所有 dict 捞出来，避免漏掉藏在 list 里的券/餐品。"""
    if isinstance(obj, dict):
        out.append(obj)
        for v in obj.values():
            deep_collect(v, out)
    elif isinstance(obj, list):
        for v in obj:
            deep_collect(v, out)


def load_items(path: str, kind: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    buckets: list[dict] = []
    deep_collect(data, buckets)
    fn = {"coupon": normalize_coupon, "meal": normalize_meal,
          "nutrition": normalize_nutrition}[kind]
    seen, out = set(), []
    for b in buckets:
        n = fn(b)
        if not n:
            continue
        key = json.dumps({k: v for k, v in n.items() if k != "raw"},
                         ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    # 只有 normalize 真的识别出关键字段才保留，避免把外层包装对象也算进来
    return out


# ============ 1) plan：枚举合法券组合 ============

def item_discount(coupon: dict, cart: list[dict]) -> float:
    """
    单品券能省多少：只有购物车里真有匹配商品时才生效，
    省的钱 = (商品原价 - 券价) × 数量，而不是整单减免。
    """
    hit = 0.0
    for it in cart:
        matched = False
        if coupon["codes"] and str(it.get("productCode")) in coupon["codes"]:
            matched = True
        elif coupon["names"]:
            it_name = str(it.get("name") or "")
            matched = any(n and (n in it_name or it_name in n) for n in coupon["names"])
        if not matched:
            continue
        unit = to_float(it.get("unit_price"))
        coupon_price = to_float(pick(coupon["raw"], "price", "salePrice", "payAmount"))
        if unit is None or coupon_price is None:
            # 只知道面额不知道券价，就按面额算一次
            hit += (coupon["face"] or 0.0)
        else:
            hit += max(0.0, unit - coupon_price) * it.get("quantity", 1)
    return round(hit, 2)


def estimate_discount(coupon: dict, subtotal: float, cart: list[dict] | None = None) -> float:
    """估算这张券能省多少。用于排序与剪枝，不用于最终核价。"""
    if coupon["scope"] == "item":
        return item_discount(coupon, cart or [])
    if subtotal + 1e-9 < coupon["threshold"]:
        return 0.0
    if coupon["face"] is not None:
        return min(coupon["face"], subtotal)
    if coupon["rate"] is not None:
        return round(subtotal * (1 - coupon["rate"]), 2)
    return 0.0


def cmd_plan(args):
    coupons = load_items(args.coupons, "coupon")
    meals = load_items(args.menu, "meal") if args.menu else []

    cart: list[dict] = []
    if args.cart:
        with open(args.cart, "r", encoding="utf-8") as f:
            cart = json.load(f)
    elif args.items:
        for spec in args.items:
            # 支持 "code:数量" 或 "code"
            code, _, qty = spec.partition(":")
            meal = next((m for m in meals if str(m["code"]) == code), None)
            cart.append({
                "productCode": code,
                "name": meal["name"] if meal else code,
                "quantity": int(qty) if qty.strip().isdigit() else 1,
                "unit_price": meal["price"] if meal else None,
            })

    subtotal = sum(
        (it.get("unit_price") or 0) * it.get("quantity", 1) for it in cart
    )
    if subtotal <= 0 and args.subtotal:
        subtotal = args.subtotal
    if subtotal <= 0:
        print("错误：算不出购物车小计。用 --cart 提供商品，或用 --subtotal 直接给金额。",
              file=sys.stderr)
        return 1

    usable, rejected = [], []
    for c in coupons:
        gain = estimate_discount(c, subtotal, cart)
        if gain > 0:
            usable.append((c, gain))
        else:
            reason = ("购物车里没有该券适用的商品"
                      if c["scope"] == "item"
                      else f"未达使用门槛（需满 {c['threshold']} 元，当前 {round(subtotal,2)} 元）")
            rejected.append({"id": c["id"], "name": c["name"], "reason": reason})
    usable.sort(key=lambda t: -t[1])

    # 组合规模控制：默认最多叠 2 张、最多产出 20 个候选，避免核价请求爆炸
    coupon_list = [c for c, _ in usable]
    max_stack = min(args.max_stack, len(coupon_list))
    combos: list[list[dict]] = []
    for size in range(1, max_stack + 1):
        for combo in itertools.combinations(coupon_list, size):
            # 互斥剪枝 1：同一 category 的券默认不可叠加
            cats = [c["category"] for c in combo if c["category"]]
            if len(cats) != len(set(cats)):
                continue
            # 互斥剪枝 2：两张单品券不能作用在同一个商品上
            targets = []
            for c in combo:
                if c["scope"] == "item":
                    targets.append(tuple(sorted(c["codes"])) or tuple(sorted(c["names"])))
            if len(targets) != len(set(targets)):
                continue
            combos.append(list(combo))
            if len(combos) >= args.max_combos:
                break
        if len(combos) >= args.max_combos:
            break

    plans = []
    for combo in combos:
        est = round(sum(estimate_discount(c, subtotal, cart) for c in combo), 2)
        plans.append({
            "coupons": [
                {"id": c["id"], "name": c["name"], "face": c["face"],
                 "rate": c["rate"], "threshold": c["threshold"], "scope": c["scope"]}
                for c in combo
            ],
            "estimated_discount": est,
            "estimated_pay": round(subtotal - est, 2),
        })
    plans.sort(key=lambda p: -p["estimated_discount"])

    print(json.dumps({
        "subtotal": round(subtotal, 2),
        "cart": cart,
        "usable_coupon_count": len(usable),
        "candidate_plans": plans,
        "rejected_coupons": rejected[:20],
        "note": "estimated_* 为本地估算，且未计入配送费与打包费。"
                "真实金额请以 calculate-price 核价结果为准。",
    }, ensure_ascii=False, indent=2))
    return 0


# ============ 2) rank：汇总核价结果 ============

def cmd_rank(args):
    results = []
    for path in args.results:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pay = to_float(pick(data, "payAmount", "actualAmount", "totalAmount",
                            "payPrice", "amount", "total"))
        discount = to_float(pick(data, "discountAmount", "promoAmount",
                                 "couponAmount", "discount", "savedAmount"))
        origin = to_float(pick(data, "originAmount", "originalAmount", "totalPrice"))
        if pay is None:
            print(f"跳过 {path}：找不到支付金额字段", file=sys.stderr)
            continue
        if discount is None and origin is not None:
            discount = round(origin - pay, 2)
        results.append({
            "label": args.labels[len(results)] if args.labels and len(args.labels) > len(results)
                     else os.path.basename(path),
            "pay": pay,
            "discount": discount or 0.0,
            "origin": origin,
            "raw": data,
        })

    if not results:
        print("错误：没有可比较的核价结果。", file=sys.stderr)
        return 1

    results.sort(key=lambda r: r["pay"])
    best = results[0]
    worst = results[-1]
    print(json.dumps({
        "best": {"label": best["label"], "pay": best["pay"],
                 "discount": best["discount"],
                 "save_vs_worst": round(worst["pay"] - best["pay"], 2)},
        "ranking": [
            {"rank": i + 1, "label": r["label"], "pay": r["pay"],
             "discount": r["discount"],
             "gap_to_best": round(r["pay"] - best["pay"], 2)}
            for i, r in enumerate(results)
        ],
    }, ensure_ascii=False, indent=2))
    return 0


# ============ 3) value：每元价值指标 ============

def cmd_value(args):
    meals = load_items(args.menu, "meal")
    nutrition = load_items(args.nutrition, "nutrition") if args.nutrition else []
    if not meals:
        print("错误：菜单里没解析出餐品。", file=sys.stderr)
        return 1

    # 营养数据按名字模糊关联（两边命名不统一，只能做包含匹配）
    def find_nutri(name: str):
        for n in nutrition:
            if n["name"] in name or name in n["name"]:
                return n
        return None

    rows = []
    for m in meals:
        price = m["price"]
        if not price or price <= 0:
            continue
        n = find_nutri(m["name"])
        row = {
            "name": m["name"],
            "code": m["code"],
            "price": price,
            "list_price": m["list_price"],
            "kcal": n["kcal"] if n else None,
            "protein": n["protein"] if n else None,
        }
        if n:
            row["kcal_per_yuan"] = round(n["kcal"] / price, 1)
            row["protein_per_yuan"] = round(n["protein"] / price, 2)
        rows.append(row)

    by_kcal = sorted([r for r in rows if r.get("kcal_per_yuan")],
                     key=lambda r: -r["kcal_per_yuan"])
    by_protein = sorted([r for r in rows if r.get("protein_per_yuan")],
                        key=lambda r: -r["protein_per_yuan"])
    priced = sorted([r for r in rows if r["price"]], key=lambda r: r["price"])

    print(json.dumps({
        "count": len(rows),
        "best_calorie_value": by_kcal[:10],
        "best_protein_value": by_protein[:10],
        "cheapest": priced[:10],
        "hint": "kcal_per_yuan 越高＝同样钱买到的热量越多（饱腹导向）；"
                "protein_per_yuan 越高＝同样钱买到的蛋白质越多（健身导向）。"
                "两个榜常常不是同一批餐品，这正是这个工具的价值。",
    }, ensure_ascii=False, indent=2))
    return 0


# ============ 4) snap：价格快照与历史基线 ============

def cmd_snap(args):
    history = {"records": []}
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = {"records": []}

    if args.show:
        print(json.dumps(history, ensure_ascii=False, indent=2))
        return 0

    if not args.key:
        print("错误：--key 必填（比如 '巨无霸套餐'）。", file=sys.stderr)
        return 1

    records = [r for r in history["records"] if r.get("key") == args.key]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = {
        "key": args.key,
        "pay": args.pay,
        "discount": args.discount,
        "store": args.store,
        "at": now,
    }
    history["records"].append(entry)
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    past = [r for r in records if r.get("pay") is not None]
    best = min(past, key=lambda r: r["pay"]) if past else None
    avg = round(sum(r["pay"] for r in past) / len(past), 2) if past else None

    verdict = "首次记录，还没有基线可比。"
    if best and args.pay is not None:
        if args.pay < best["pay"] - 0.01:
            verdict = f"历史最低！比此前最低（{best['pay']}元 @ {best['at']}）还便宜 {round(best['pay']-args.pay,2)} 元。"
        elif args.pay > best["pay"] + 0.01:
            verdict = f"不是好价。历史最低是 {best['pay']}元 @ {best['at']}，现在贵 {round(args.pay-best['pay'],2)} 元。"
        else:
            verdict = f"持平历史最低（{best['pay']}元）。"

    print(json.dumps({
        "saved": entry,
        "history_count": len(past) + 1,
        "historical_low": best["pay"] if best else None,
        "historical_avg": avg,
        "verdict": verdict,
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="麦门省钱精算师 · 计算引擎")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", help="枚举合法券组合")
    sp.add_argument("--coupons", required=True, help="券列表 JSON（MCP 原始返回即可）")
    sp.add_argument("--menu", help="菜单 JSON（可选，用来补全商品名与单价）")
    sp.add_argument("--cart", help="购物车 JSON 文件")
    sp.add_argument("--items", nargs="*", help="简写：'商品码:数量'")
    sp.add_argument("--subtotal", type=float, help="直接给小计金额")
    sp.add_argument("--max-stack", type=int, default=2, help="最多叠加几张券（默认 2）")
    sp.add_argument("--max-combos", type=int, default=20, help="最多产出几个候选（默认 20）")
    sp.set_defaults(fn=cmd_plan)

    sp = sub.add_parser("rank", help="汇总多个核价结果")
    sp.add_argument("--results", nargs="+", required=True, help="多个 calculate-price 结果 JSON")
    sp.add_argument("--labels", nargs="*", help="每个结果的别名")
    sp.set_defaults(fn=cmd_rank)

    sp = sub.add_parser("value", help="每元价值指标")
    sp.add_argument("--menu", required=True)
    sp.add_argument("--nutrition", help="营养数据 JSON")
    sp.set_defaults(fn=cmd_value)

    sp = sub.add_parser("snap", help="价格快照与历史基线")
    sp.add_argument("--key", help="这次记录的标识，如 '巨无霸套餐'")
    sp.add_argument("--pay", type=float, help="实付金额")
    sp.add_argument("--discount", type=float, help="优惠金额")
    sp.add_argument("--store", help="门店名/编码")
    sp.add_argument("--show", action="store_true", help="只看历史，不写入")
    sp.set_defaults(fn=cmd_snap)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
