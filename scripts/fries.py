#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fries.py — 麦门薯条推荐官 · 核心引擎

只回答一件事：**怎么把薯条吃明白、吃划算。**

它做三件别人没做的事：

1. **全图鉴（罗列）**：把菜单里所有「含薯条/能选薯条」的单品和套餐都挖出来。
   麦当劳的薯条家族很碎 —— 菜单只挂一个「薯条」（其实是中薯条），
   大薯条、扭扭薯、薯饼只在**套餐的小食选项**里出现，还带着相对默认项的差价。
   这套工具逐个套餐调 detail，把藏在小食轮次里的薯条规格全部翻出来。

2. **价格修正（关键）**：套餐里薯条各规格只有「相对默认项的差价」，绝对值要靠
   默认项（通常是中薯条）的真实菜单价反推。旧版错在「拿菜单里第一个薯条类商品
   当基准」，结果把鸡薯双全盒的 ¥15.9 当成了中薯条价。本版用**默认小食选项的
   商品码去菜单里查价**做基准，价格永远对。

3. **推荐（给理由）**：每元热量（kcal/¥）看绝对值划算不划算；升档边际效率
   （多花钱多得的每元热量）看「要不要加钱升大」。两个数字不一样，分开学才有用。
   再叠上券，告诉你哪张券用在哪个薯条上最省。

用法：
    # 全图鉴 + 推荐（读已落盘的 MCP 返回）
    python3 scripts/fries.py recommend \
        --meals /tmp/mcd_fries/meals.json \
        --nutrition /tmp/mcd_fries/nutrition.json \
        --details-dir /tmp/mcd_fries/details \
        --coupons /tmp/mcd_fries/coupons.json   # 可选

    # 只罗列，不要推荐结论
    python3 scripts/fries.py enumerate --meals ... --nutrition ... --details-dir ...

数据来源：scripts/mcp_client.py 调 query-meals / list-nutrition-foods / query-meal-detail
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from mcd_schema import parse_meals, parse_nutrition, parse_coupons  # noqa: E402


# 薯条家族的识别词。麦当劳的薯类商品名花样很多（扭扭薯、薯饼、脆脆薯条…）
FRIES_WORDS = ("薯条", "薯饼", "薯格", "扭扭薯", "薯")
# 这些带「薯/条」字但不是薯条本体，单独排除
NON_FRIES = ("玉米杯", "薯片", "芝士条", "油条")
# 套餐「小食轮次」的命名关键词
SNACK_ROUND_KEYWORDS = ("小食", "配餐")
# 这些词出现在套餐名里，基本可判定是「套餐/盒」而非单品
COMBO_NAME_HINTS = ("套餐", "三件套", "两件套", "桶", "盒", "餐", "随心配", "1+1", "分享", "拼盘")


def is_fries(name: str) -> bool:
    if not name:
        return False
    if any(k in name for k in NON_FRIES):
        return False
    return any(k in name for k in FRIES_WORDS)


def parse_diff(s) -> float:
    """diffPrice 长这样：'+ ¥1.5' / '- ¥1.5' / '+ ¥0'。`None` 当 0。"""
    if s is None:
        return 0.0
    t = str(s).replace("¥", "").replace("元", "").replace(" ", "")
    sign = -1 if t.startswith("-") else 1
    digits = "".join(ch for ch in t if ch.isdigit() or ch == ".")
    try:
        return sign * float(digits) if digits else 0.0
    except ValueError:
        return 0.0


def load_details(path: str) -> dict[str, dict]:
    """读套餐详情。支持一个目录（每码一个 JSON）或一个合并文件（list / dict）。"""
    if os.path.isdir(path):
        out: dict[str, dict] = {}
        for f in sorted(glob.glob(os.path.join(path, "*.json"))):
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            data = d.get("data", d) if isinstance(d, dict) else d
            code = str(data.get("code") or os.path.basename(f)[:-5])
            out[code] = data
        return out
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, list):
        out = {}
        for item in d:
            data = item.get("data", item) if isinstance(item, dict) else item
            code = str(data.get("code") or "")
            if code:
                out[code] = data
        return out
    if isinstance(d, dict):
        data = d.get("data", d)
        if "code" in data:
            return {str(data["code"]): data}
        # 已经是 code->detail 的字典
        return {str(k): (v.get("data", v) if isinstance(v, dict) else v)
                for k, v in data.items()}
    return {}


def meals_by_code(meals: list[dict]) -> dict[str, dict]:
    return {str(m.get("code")): m for m in meals if m.get("code")}


def find_kcal(name: str, nutri: list[dict]) -> dict | None:
    """
    给餐品名找营养数据。菜单/套餐里的薯条名很碎（「薯条」「中薯条」「大薯条」
    「5块心形薯饼+韩式辣椒黄油风味酱」），营养表里的名字又不一样，所以按优先级：

    1. 精确匹配（先把 detail 里的真实规格名传进来，如「中薯条」）
    2. 提取薯条核心词（大薯条/中薯条/小薯条/迷你薯条/扭扭薯/薯饼/脆脆薯条）做包含匹配
    3. 都不中 → 返回 None，让上层标记为「营养库暂无」（通常是新品）
    """
    pool = [n for n in nutri if n.get("kcal")]

    for n in pool:
        if n["name"] == name:
            return n
    for n in pool:
        if name and (name in n["name"] or n["name"] in name):
            return n

    cores = ("大薯条", "中薯条", "小薯条", "迷你薯条", "脆脆薯条", "扭扭薯", "薯饼", "薯条")
    core = next((w for w in cores if w in name), None)
    if core:
        hits = [n for n in pool if core in n["name"]]
        if len(hits) == 1:
            return hits[0]
    return None


def margin(base: dict, bigger: dict) -> dict | None:
    """升一档的边际效率：多加多少钱、多得多少热量、合每元多少。"""
    if not base.get("kcal") or not bigger.get("kcal"):
        return None
    if not base.get("price") or not bigger.get("price"):
        return None
    d_price = round(bigger["price"] - base["price"], 2)
    d_kcal = round(bigger["kcal"] - base["kcal"], 1)
    if d_price <= 0 or d_kcal <= 0:
        return None
    return {
        "from": base["name"], "to": bigger["name"],
        "extra_price": d_price, "extra_kcal": d_kcal,
        "margin_kcal_per_yuan": round(d_kcal / d_price, 1),
    }


# ---------------------------------------------------------------------------
# 枚举：单品 + 套餐
# ---------------------------------------------------------------------------

def build_single(code: str, m: dict, nutri: list[dict]) -> dict:
    kcal = find_kcal(m["name"], nutri)
    row = {
        "code": code, "name": m["name"], "price": m.get("price"),
        "category": m.get("category", ""), "kind": "single",
        "kcal": kcal["kcal"] if kcal else None,
        "kcal_per_yuan": (round(kcal["kcal"] / m["price"], 1)
                          if kcal and m.get("price") else None),
    }
    return row


def build_combo(code: str, m: dict, detail: dict, mbc: dict[str, dict],
                nutri: list[dict]) -> dict | None:
    """
    把一个套餐拆成「小食轮次里的薯条选项」。返回 None 表示这个套餐不含/不能选薯条。

    价格基准：取小食轮次里 isDefault==1 的那一项，用它的**商品码**去菜单查价，
    而不是拿菜单里第一个薯条类商品当基准（旧版 bug 的根源）。
    """
    rounds = detail.get("rounds") or []
    snack_round = None
    for r in rounds:
        if not isinstance(r, dict):
            continue
        rname = r.get("name") or ""
        if any(k in rname for k in SNACK_ROUND_KEYWORDS):
            snack_round = r
            break
    if not snack_round:
        return None

    choices = snack_round.get("choices") or []
    fries_choices = [c for c in choices if isinstance(c, dict) and is_fries(c.get("name") or "")]
    if not fries_choices:
        return None

    # 基准价：默认项的商品码 → 菜单价
    default = next((c for c in choices if c.get("isDefault") == 1), None)
    base_price = None
    if default:
        base_item = mbc.get(str(default.get("code")))
        if base_item and base_item.get("price") is not None:
            base_price = base_item["price"]
    # 兜底：若默认项查不到，退回「默认项差价 + 套餐价差」不可靠，直接用菜单查默认项名
    if base_price is None and default:
        dn = default.get("name") or ""
        for it in mbc.values():
            if it["name"] == dn:
                base_price = it.get("price")
                break

    opts = []
    for c in fries_choices:
        diff = parse_diff(c.get("diffPrice"))
        price = round(base_price + diff, 2) if base_price is not None else None
        kcal = find_kcal(c.get("name") or "", nutri)
        opts.append({
            "code": str(c.get("code") or ""),
            "name": c.get("name"),
            "diff": diff,
            "is_default": c.get("isDefault") == 1,
            "price": price,
            "kcal": kcal["kcal"] if kcal else None,
            "kcal_per_yuan": (round(kcal["kcal"] / price, 1)
                              if kcal and price else None),
        })

    return {
        "code": code, "name": m["name"], "combo_price": m.get("price"),
        "category": m.get("category", ""), "kind": "combo",
        "base_price": base_price,
        "options": opts,
    }


def enumerate_all(meals: list[dict], details: dict[str, dict],
                  nutri: list[dict]) -> dict:
    mbc = meals_by_code(meals)
    singles, combos = [], []

    for m in meals:
        code = str(m.get("code"))
        detail = details.get(code)
        rounds = (detail.get("rounds") or []) if detail else []

        # 1) 可选套餐：存在「小食/配餐」轮次且选项 >1
        is_combo = any(
            (any(k in (r.get("name") or "") for k in SNACK_ROUND_KEYWORDS)
             and len([c for c in (r.get("choices") or []) if isinstance(c, dict)]) > 1)
            for r in rounds if isinstance(r, dict)
        )
        if is_combo:
            rec = build_combo(code, m, detail, mbc, nutri)
            if rec:
                combos.append(rec)
            continue

        # 2) 盒装/套餐类绑定（名字带盒/套餐/随心配/四件套…，且固定含薯类）
        fixed_fries = []
        for r in rounds:
            if not isinstance(r, dict):
                continue
            for c in (r.get("choices") or []):
                if isinstance(c, dict) and is_fries(c.get("name") or ""):
                    fixed_fries.append(c.get("name"))
        is_box = any(h in (m["name"] or "") for h in COMBO_NAME_HINTS) and bool(fixed_fries)
        if is_box:
            row = build_single(code, m, nutri)
            row["kind"] = "box"
            row["contains"] = fixed_fries
            kcal = find_kcal(fixed_fries[0], nutri)
            if kcal:
                row["included_kcal"] = kcal["kcal"]
                row["included_name"] = fixed_fries[0]
            row["kcal_per_yuan"] = None  # 盒装价含别的东西，不参与单买性价比排名
            singles.append(row)
            continue

        # 3) 纯单品（薯条 / 扭扭薯 / 心形薯饼5块 …）
        if is_fries(m["name"] or ""):
            singles.append(build_single(code, m, nutri))

    return {"singles": singles, "combos": combos}


# ---------------------------------------------------------------------------
# 推荐
# ---------------------------------------------------------------------------

def recommend(enum: dict, coupons: list[dict] | None = None) -> dict:
    singles = enum["singles"]
    combos = enum["combos"]

    # 1) 单买每元热量榜
    single_rank = sorted(
        [s for s in singles if s.get("kcal_per_yuan")],
        key=lambda x: -x["kcal_per_yuan"],
    )

    # 2) 升档边际效率：在「同一套餐内」比中→大
    margins = []
    for cb in combos:
        opts = [o for o in cb["options"] if o.get("kcal") and o.get("price")]
        for a in opts:
            for b in opts:
                if a is b:
                    continue
                if "薯条" in a["name"] and "薯条" in b["name"]:
                    mg = margin(a, b)
                    if mg:
                        mg["combo"] = cb["name"]
                        margins.append(mg)
    seen, uniq_m = set(), []
    for mg in sorted(margins, key=lambda x: -x["margin_kcal_per_yuan"]):
        key = (mg["from"], mg["to"], mg["combo"])
        if key in seen:
            continue
        seen.add(key)
        uniq_m.append(mg)

    # 3) 大薯条怎么买最便宜（很可能只能靠套餐升档）
    big_fries_ways = []
    for cb in combos:
        for o in cb["options"]:
            if "大薯条" in o["name"] and o.get("price"):
                big_fries_ways.append({
                    "combo": cb["name"], "price": o["price"],
                    "diff": o["diff"], "kcal": o.get("kcal"),
                })
    big_fries_ways.sort(key=lambda x: x["price"])

    # 4) 券：薯类券用在最贵的薯条上最省
    coupon_tips = []
    if coupons:
        all_fries = []
        for s in singles:
            if s.get("price") and (s.get("kcal_per_yuan") or s.get("contains_fries_fixed")):
                all_fries.append({"name": s["name"], "price": s["price"],
                                  "kcal": s.get("kcal") or s.get("included_kcal")})
        for cb in combos:
            for o in cb["options"]:
                if o.get("price"):
                    all_fries.append({"name": f"{cb['name']}→{o['name']}",
                                      "price": o["price"], "kcal": o.get("kcal")})
        for c in coupons:
            if not c.get("enabled", True):
                continue
            if not any(k in (c["name"] or "") for k in ("薯", "条")):
                continue
            cp = c.get("coupon_price")
            if cp is None:
                continue
            best = None
            for f in all_fries:
                if not f.get("price") or not f.get("kcal"):
                    continue
                save = round(f["price"] - cp, 2)
                if save <= 0:
                    continue
                v = round(f["kcal"] / cp, 1)
                if best is None or v > best["kcal_per_yuan"]:
                    best = {"name": f["name"], "orig": f["price"],
                            "save": save, "kcal_per_yuan": v}
            if best:
                coupon_tips.append({"coupon": c["name"], "coupon_price": cp,
                                    "best": best})

    return {
        "single_rank": single_rank,
        "margins": uniq_m,
        "big_fries_ways": big_fries_ways,
        "coupon_tips": coupon_tips,
    }


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def print_report(enum: dict, rec: dict, store: str = "") -> None:
    singles = enum["singles"]
    combos = enum["combos"]
    print("=" * 64)
    print("麦门薯条推荐官 · 薯条全图鉴")
    if store:
        print(f"门店：{store}")
    print(f"单品 {len(singles)} 款 · 可选薯条套餐 {len(combos)} 个")
    print("=" * 64)

    print("\n【一、单买薯条类单品】")
    for s in singles:
        kcal = s.get("kcal")
        kpy = s.get("kcal_per_yuan")
        if s.get("kind") == "box":
            incl = s.get("included_name") or "、".join(s.get("contains") or [])
            kcal_s = f"含{incl} {s.get('included_kcal', '?')} kcal" if s.get("included_kcal") else f"含{incl}"
            tag = "（盒装，价含其他）"
            kpy_s = "      —"
        else:
            kcal_s = f"{kcal:.0f} kcal" if kcal else "营养暂无"
            tag = "（可单买）"
            kpy_s = f"{kpy:>5} kcal/¥" if kpy else "      —"
        name = s["name"]
        print(f"  · {name:<22} ¥{s['price']:<5} {kcal_s:<16} {kpy_s} {tag}")

    print(f"\n【二、可选薯条的套餐】共 {len(combos)} 个")
    for cb in combos:
        print(f"\n  {cb['name']}（套餐价 ¥{cb['combo_price']}）小食可换：")
        for o in cb["options"]:
            mark = " ←默认" if o["is_default"] else ""
            diff_s = f"{o['diff']:+.1f}" if o["diff"] else " 0.0"
            kcal = o.get("kcal")
            kcal_s = f"{kcal:.0f} kcal" if kcal else "营养暂无"
            kpy = o.get("kcal_per_yuan")
            kpy_s = f"{kpy:>5} kcal/¥" if kpy else "      —"
            print(f"      {o['name']:<20} 差价{diff_s:>5} → ¥{o['price']:<5} "
                  f"{kcal_s:<9} {kpy_s}{mark}")

    print("\n" + "=" * 64)
    print("【三、推荐结论】")
    print("=" * 64)

    if rec["single_rank"]:
        top = rec["single_rank"][0]
        print(f"\n  1) 单买最划算：{top['name']}（{top['kcal_per_yuan']} kcal/¥）。")
        # 找大薯条
        big = next((s for s in rec["single_rank"] if "大薯条" in s["name"]), None)
        if big:
            print(f"     大薯条直接单买 {big['kcal_per_yuan']} kcal/¥，是热量性价比之王，"
                  f"但注意它常不在单买菜单里。")

    if rec["margins"]:
        print("\n  2) 升档边际效率（加钱升大到底值不值）：")
        for mg in rec["margins"][:3]:
            base_kpy = next((o["kcal_per_yuan"] for cb in combos
                             for o in cb["options"]
                             if o["name"] == mg["from"]), None)
            ratio = f"，是原单价 {base_kpy} 的 {mg['margin_kcal_per_yuan']/base_kpy:.1f} 倍" if base_kpy else ""
            print(f"     · {mg['combo']}：{mg['from']}→{mg['to']} 加 ¥{mg['extra_price']}"
                  f" 多得 {mg['extra_kcal']:.0f} kcal，边际 {mg['margin_kcal_per_yuan']} kcal/¥{ratio}")

    if rec["big_fries_ways"]:
        print("\n  3) 大薯条怎么买最便宜：")
        bw = rec["big_fries_ways"][0]
        print(f"     · 大薯条只能靠套餐升档拿到（门店单买菜单通常没有它）。")
        print(f"     · 最便宜路径：{bw['combo']} 里把默认中薯条升大薯条，"
              f"大薯条到手价 ¥{bw['price']}（边际 +¥{bw['diff']}）。")

    if rec["coupon_tips"]:
        print("\n  4) 用券：")
        for t in rec["coupon_tips"]:
            b = t["best"]
            print(f"     · 「{t['coupon']}」用券价 ¥{t['coupon_price']} → "
                  f"用在 {b['name']}（原价 ¥{b['orig']}）省 ¥{b['save']}"
                  f"，{b['kcal_per_yuan']} kcal/¥")

    print("\n" + "-" * 64)
    print("热量代理份量：麦当劳不公布薯条重量，热量与份量强相关，")
    print("是目前能拿到的最靠谱口径。实付请以 calculate-price 为准。")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load(path):
    return path


def main() -> int:
    p = argparse.ArgumentParser(description="麦门薯条推荐官 · 薯条全图鉴与推荐")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("recommend", "enumerate"):
        sp = sub.add_parser(name)
        sp.add_argument("--meals", required=True, help="query-meals 返回")
        sp.add_argument("--nutrition", required=True, help="list-nutrition-foods 返回")
        sp.add_argument("--details-dir", required=True,
                        help="query-meal-detail 落盘目录（每码一个 JSON），或合并文件")
        sp.add_argument("--coupons", help="query-my-coupons 返回（可选）")
        sp.add_argument("--store", default="", help="门店名/码，仅用于报告展示")
        sp.add_argument("--json", action="store_true", help="输出 JSON")

    a = p.parse_args()

    meals = parse_meals(a.meals)
    nutri = parse_nutrition(a.nutrition)
    details = load_details(a.details_dir)
    coupons = parse_coupons(a.coupons) if a.coupons else None

    enum = enumerate_all(meals, details, nutri)
    rec = recommend(enum, coupons)

    if a.json:
        print(json.dumps({"enumeration": enum, "recommendation": rec},
                         ensure_ascii=False, indent=2))
        return 0

    if a.cmd == "enumerate":
        print(json.dumps(enum, ensure_ascii=False, indent=2))
        return 0

    print_report(enum, rec, store=a.store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
