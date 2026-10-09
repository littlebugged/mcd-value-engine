#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_schema.py — 麦当劳 MCP 真实返回格式的适配层。

这个文件存在的理由：麦当劳 MCP 返回的字段结构，和任何人凭文档猜的都不一样。

三个反直觉的真实结构：

1. 券不是「满 X 减 Y」，而是「用券价」。
   `discountInfo.discountValue = "9.9"` 配 `discountDesc = "用券价格"`。
   意思是"花 9.9 买这个东西"，省多少 = 商品原价 - 9.9。
   券的价值必须结合菜单才算得出来，光看券本身没有意义。

2. 菜单不是数组，是「商品码 → 商品」的字典。
   `data.meals = {"9900005456": {"name": "麦辣鸡腿汉堡三件套",
                                 "currentPrice": "33.5", "originalPrice": "47"}}`
   分类里只放商品码，价格要去 meals 字典里查。

3. 营养数据根本不是 JSON，是自定义文本。
   `[160]{productName,nutritionDescription,energyKj,energyKcal,...}:` 后接 CSV 行。
   热量字段名是 energyKcal 不是 kcal，商品名是 productName 不是 foodName。

另外两个只有真实数据才暴露的坑：
- 券有 `enable` 字段，0 = 还没到可用日期，必须过滤，否则会推荐用不了的券
- 「任选」类券（麦旋风任选、薯薯任选）匹配到多个商品，
  选最贵的那款省得最多 —— 这是"任选"的真实含义
"""

from __future__ import annotations

import json
import re
import os
from typing import Any


def _f(v) -> float | None:
    """麦当劳的价格字段是字符串，'null' 和 '' 都当没有。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("null", "none", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ============ 券 ============

# 券名里的这些词不参与商品匹配：「麦旋风任选」要匹配的是「麦旋风」
COUPON_NOISE = ("任选", "套餐", "两件套", "三件套", "四件套", "单人餐", "双人餐", "超值", "特惠")


def parse_coupons(payload: Any) -> list[dict]:
    """解析 query-my-coupons / available-coupons / query-store-coupons 的返回。"""
    if isinstance(payload, str) and os.path.exists(payload):
        with open(payload, "r", encoding="utf-8") as f:
            payload = json.load(f)
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    if isinstance(payload, dict):
        raw = payload.get("coupons") or payload.get("list") or []
    elif isinstance(payload, list):
        raw = payload
    else:
        return []

    out = []
    for x in raw:
        if not isinstance(x, dict):
            continue
        di = x.get("discountInfo") or {}
        coupon_price = _f(di.get("discountValue")) or _f(x.get("reducePrice"))
        out.append({
            "id": x.get("id") or x.get("code"),
            "code": x.get("code"),
            "name": x.get("title") or x.get("couponName") or "",
            "coupon_price": coupon_price,          # 用券价：花这么多钱买
            "discount_desc": di.get("discountDesc"),
            "discount_type": di.get("discountTypeText"),
            "start_date": x.get("tradeStartDate"),
            "end_date": x.get("tradeEndDate"),
            "enabled": x.get("enable") == 1,       # 0 = 还没到可用日
            "order_types": x.get("orderTypes") or ([x["orderType"]] if x.get("orderType") else []),
            "tags": [t.get("label") for t in (x.get("tags") or []) if isinstance(t, dict)],
            "multiple_products": bool(x.get("multipleProducts")),
            "raw": x,
        })
    return out


def coupon_keywords(name: str) -> list[str]:
    """
    从券名里提取用于匹配商品的关键词，由精确向宽泛排列。

    「麦旋风任选」→ ['麦旋风']
    「薯薯任选」  → ['薯薯', '薯']        叠字要折叠，菜单里只有「薯条」「薯饼」
    「巧克力味厚松饼猪柳蛋套餐」→ ['巧克力味厚松饼猪柳蛋', '猪柳蛋', '巧克力']
    """
    s = name.strip()
    for n in COUPON_NOISE:
        s = s.replace(n, "")
    s = s.strip()
    if not s:
        return []

    keys = [s]
    if len(s) > 4:
        keys.append(s[-3:])   # 长名的尾部通常是主商品，如「…猪柳蛋」
    if len(s) > 6:
        keys.append(s[:3])    # 头部作备选，如「巧克力…」

    # 叠字折叠：「薯薯」→「薯」、「堡堡」→「堡」
    if len(s) >= 2 and len(set(s)) == 1:
        keys.append(s[0])
    elif len(s) >= 4 and s[:2] == s[2:4]:
        keys.append(s[:2])

    # 去重保序
    seen, out = set(), []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


# ============ 菜单 ============

def parse_meals(payload: Any) -> list[dict]:
    """解析 query-meals 的返回（data.meals 是 商品码 → 商品 的字典）。"""
    if isinstance(payload, str) and os.path.exists(payload):
        with open(payload, "r", encoding="utf-8") as f:
            payload = json.load(f)
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]

    out = []
    if isinstance(payload, dict):
        meals = payload.get("meals")
        if isinstance(meals, dict):
            for code, it in meals.items():
                if not isinstance(it, dict):
                    continue
                cur = _f(it.get("currentPrice"))
                org = _f(it.get("originalPrice"))
                out.append({
                    "code": str(code),
                    "name": it.get("name") or str(code),
                    "price": cur if cur is not None else org,
                    "list_price": org if org is not None else cur,
                    "raw": it,
                })
        # 分类信息：用于按品类展示，也用来标记商品属于哪个分类
        cats = payload.get("categories") or []
        cat_of = {}
        for c in cats:
            if not isinstance(c, dict):
                continue
            for m in (c.get("meals") or []):
                if isinstance(m, dict) and m.get("code"):
                    cat_of[str(m["code"])] = c.get("name", "")
        for m in out:
            m["category"] = cat_of.get(m["code"], "")
        return out

    if isinstance(payload, list):
        for it in payload:
            if not isinstance(it, dict):
                continue
            out.append({
                "code": str(it.get("code") or it.get("productCode") or ""),
                "name": it.get("name") or it.get("productName") or "",
                "price": _f(it.get("currentPrice")) or _f(it.get("price")),
                "list_price": _f(it.get("originalPrice")),
                "category": it.get("category", ""),
                "raw": it,
            })
    return out


# ============ 营养（自定义文本格式） ============

NUTRI_HEADER = re.compile(r"\[(\d+)\]\s*\{([^}]+)\}\s*:")


def parse_nutrition(payload: Any) -> list[dict]:
    """
    解析 list-nutrition-foods 的返回。data 是字符串，形如：

        [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,...}:
          猪柳麦满分,null,1288,308,16,16,24,781,213
          ...
    """
    if isinstance(payload, str) and os.path.exists(payload):
        with open(payload, "r", encoding="utf-8") as f:
            payload = json.load(f)
    if isinstance(payload, dict):
        text = payload.get("data")
        if not isinstance(text, str):
            return []
    elif isinstance(payload, str):
        text = payload
    else:
        return []

    m = NUTRI_HEADER.search(text)
    if not m:
        return []
    cols = [c.strip() for c in m.group(2).split(",")]
    body = text[m.end():]

    def idx(*names):
        for n in names:
            if n in cols:
                return cols.index(n)
        return None

    i_name = idx("productName", "foodName", "name")
    i_kcal = idx("energyKcal", "kcal", "energy")
    i_prot = idx("protein")
    i_fat = idx("fat")
    i_carb = idx("carbohydrate", "carb")
    i_sodium = idx("sodium")
    if i_name is None:
        return []

    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("[") or line.startswith("{"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or not parts[i_name]:
            continue
        def g(i):
            return _f(parts[i]) if i is not None and i < len(parts) else None
        out.append({
            "name": parts[i_name],
            "kcal": g(i_kcal) or 0.0,
            "protein": g(i_prot) or 0.0,
            "fat": g(i_fat) or 0.0,
            "carb": g(i_carb) or 0.0,
            "sodium": g(i_sodium),
        })
    return out


# ============ 券 × 菜单：算真实省额 ============

def match_meals(coupon: dict, meals: list[dict]) -> list[dict]:
    """
    把一张券匹配到菜单商品，返回按「用券能省多少」降序的候选。

    「任选」券会命中多个商品，第一个就是最划算的选择。
    """
    hits = []
    for kw in coupon_keywords(coupon["name"]):
        for m in meals:
            nm = m["name"]
            if not nm:
                continue
            if kw in nm or nm in kw:
                price = m.get("price")
                cp = coupon.get("coupon_price")
                save = round(price - cp, 2) if (price is not None and cp is not None) else None
                if save is not None and save <= 0:
                    continue  # 用券反而更贵，不划算
                hits.append({
                    "code": m["code"], "name": nm,
                    "price": price, "list_price": m.get("list_price"),
                    "coupon_price": cp, "save": save,
                    "keyword": kw,
                })
        if hits:
            break  # 用最长关键词的匹配结果，更精确
    # 去重 + 按省额降序
    seen, uniq = set(), []
    for h in sorted(hits, key=lambda x: -(x["save"] or 0)):
        if h["code"] in seen:
            continue
        seen.add(h["code"])
        uniq.append(h)
    return uniq


def evaluate_coupons(coupons: list[dict], meals: list[dict],
                     today: str | None = None) -> dict:
    """
    把手里的券对着菜单算一遍，回答三个问题：
    哪些券今天能用、每张券用在哪个商品上最省、总共能省多少。
    """
    usable, inactive, unmatched = [], [], []

    for c in coupons:
        if not c.get("enabled", True):
            inactive.append({
                "name": c["name"],
                "reason": f"未到可用日期（{c.get('start_date')} ~ {c.get('end_date')}）",
            })
            continue
        if today and c.get("end_date") and today > c["end_date"]:
            inactive.append({"name": c["name"], "reason": f"已过期（{c['end_date']}）"})
            continue
        if today and c.get("start_date") and today < c["start_date"]:
            inactive.append({"name": c["name"], "reason": f"还没生效（{c['start_date']} 起）"})
            continue

        hits = match_meals(c, meals)
        if not hits:
            unmatched.append({
                "name": c["name"],
                "coupon_price": c.get("coupon_price"),
                "reason": "当前菜单里没有对应商品（可能是早餐/限时商品，或该门店不售卖）",
            })
            continue

        best = hits[0]
        usable.append({
            "name": c["name"],
            "coupon_price": c["coupon_price"],
            "best_on": best["name"],
            "best_code": best["code"],
            "original_price": best["price"],
            "save": best["save"],
            "alternatives": [
                {"name": h["name"], "price": h["price"], "save": h["save"]}
                for h in hits[1:6]
            ],
            "end_date": c.get("end_date"),
            "tags": c.get("tags") or [],
        })

    usable.sort(key=lambda x: -(x["save"] or 0))
    return {
        "usable": usable,
        "inactive": inactive,
        "unmatched": unmatched,
        "total_potential_save": round(sum(u["save"] for u in usable if u["save"]), 2),
    }


def auto_detect(path: str) -> str:
    """判断一个 JSON 文件是券、菜单还是营养数据。"""
    with open(path, "r", encoding="utf-8") as f:
        try:
            d = json.load(f)
        except json.JSONDecodeError:
            return "unknown"
    if isinstance(d, dict):
        data = d.get("data")
        if isinstance(data, str) and NUTRI_HEADER.search(data):
            return "nutrition"
        if isinstance(data, dict):
            if "coupons" in data:
                return "coupon"
            if "meals" in data:
                return "meal"
        if "coupons" in d or "couponId" in d:
            return "coupon"
        if "meals" in d:
            return "meal"
    return "unknown"


# ============ CLI ============

def _report(coupons_path: str, meals_path: str, nutrition_path: str | None, today: str | None):
    coupons = parse_coupons(coupons_path)
    meals = parse_meals(meals_path)
    if not coupons:
        print("没解析出券。确认文件是 query-my-coupons / available-coupons 的原始返回。")
        return 1
    if not meals:
        print("没解析出菜单。确认文件是 query-meals 的原始返回。")
        return 1

    r = evaluate_coupons(coupons, meals, today=today)

    print("=" * 62)
    print(f"麦当劳券包体检   今天 {today or '未指定'}   券 {len(coupons)} 张 / 菜单 {len(meals)} 款")
    print("=" * 62)

    if r["usable"]:
        print("\n【今天能用】按省额排序\n")
        for u in r["usable"]:
            print(f"  {u['name']}   用券价 ¥{u['coupon_price']}")
            print(f"    最优选择 → {u['best_on']}（原价 ¥{u['original_price']}）省 ¥{u['save']}")
            if u["alternatives"]:
                alt = "、".join(f"{a['name']}(省{a['save']})" for a in u["alternatives"][:4])
                print(f"    同类可选 → {alt}")
            tail = f"到期 {u['end_date']}" if u["end_date"] else ""
            if u["tags"]:
                tail += "  " + "/".join(u["tags"])
            print(f"    {tail}\n")
        print(f"  合计潜在节省 ¥{r['total_potential_save']}")
        print("  ⚠ 以上按菜单原价估算，实付请以 calculate-price 核价为准。")
    else:
        print("\n今天没有能用的券。")

    if r["inactive"]:
        print(f"\n【还没生效 / 已过期】{len(r['inactive'])} 张")
        for x in r["inactive"][:12]:
            print(f"  · {x['name']} — {x['reason']}")
        if len(r["inactive"]) > 12:
            print(f"  … 还有 {len(r['inactive']) - 12} 张")

    if r["unmatched"]:
        print(f"\n【菜单里没找到对应商品】{len(r['unmatched'])} 张")
        for x in r["unmatched"][:8]:
            print(f"  · {x['name']}（用券价 {x['coupon_price']}）— {x['reason']}")

    if nutrition_path:
        nut = parse_nutrition(nutrition_path)
        if nut:
            print("\n" + "=" * 62)
            print("性价比榜单（每元能买到什么）")
            print("=" * 62)
            rows = []
            for m_ in meals:
                if not m_.get("price"):
                    continue
                hit = None
                for n_ in nut:
                    if n_["name"] in m_["name"] or m_["name"] in n_["name"]:
                        hit = n_
                        break
                if not hit:
                    continue
                rows.append({
                    "name": m_["name"], "price": m_["price"],
                    "kcal": hit["kcal"], "protein": hit["protein"],
                    "kpy": round(hit["kcal"] / m_["price"], 1),
                    "ppy": round(hit["protein"] / m_["price"], 2),
                })
            by_k = sorted(rows, key=lambda x: -x["kpy"])
            by_p = sorted(rows, key=lambda x: -x["ppy"])
            print(f"\n  匹配到营养数据的餐品 {len(rows)} 款\n")
            print("  每元热量榜（扛饿）              每元蛋白榜（健身）")
            for i in range(min(8, len(by_k), len(by_p))):
                a, b = by_k[i], by_p[i]
                print(f"  {i+1}. {a['name'][:14]:<16}{a['kpy']:>6} kcal/元   "
                      f"{i+1}. {b['name'][:14]:<14}{b['ppy']:>5} g/元")
            if by_k and by_p and by_k[0]["name"] != by_p[0]["name"]:
                print(f"\n  注意：热量榜第一是「{by_k[0]['name']}」，蛋白榜第一却是「{by_p[0]['name']}」。")
                print("  扛饿和高蛋白从来不是同一件事，先想清楚要哪个。")
    return 0


def main() -> int:
    import argparse
    from datetime import datetime

    p = argparse.ArgumentParser(
        description="麦当劳券包体检：把手里的券对着菜单算一遍，看今天能省多少",
        epilog="数据来源：mcp_client.py call query-my-coupons / query-meals / list-nutrition-foods",
    )
    p.add_argument("--coupons", required=True, help="query-my-coupons 返回的 JSON 文件")
    p.add_argument("--meals", required=True, help="query-meals 返回的 JSON 文件")
    p.add_argument("--nutrition", help="list-nutrition-foods 返回的 JSON 文件（可选，出性价比榜）")
    p.add_argument("--today", default=datetime.now().strftime("%Y-%m-%d"),
                   help="当作今天的日期，默认取系统日期")
    p.add_argument("--json", action="store_true", help="输出 JSON 而非报告")
    a = p.parse_args()

    if a.json:
        c = parse_coupons(a.coupons)
        m = parse_meals(a.meals)
        print(json.dumps(evaluate_coupons(c, m, today=a.today), ensure_ascii=False, indent=2))
        return 0
    return _report(a.coupons, a.meals, a.nutrition, a.today)


if __name__ == "__main__":
    raise SystemExit(main())
