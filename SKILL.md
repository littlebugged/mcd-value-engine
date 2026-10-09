---
name: mcd-value-engine
description: 麦门省钱精算师。用麦当劳中国官方 MCP 帮用户把一单吃明白：枚举券的真实可叠加组合、逐个核价找出真正最优解、算每元热量与每元蛋白判断哪款才是性价比之王、对比历史成交价告诉你现在是不是好价。当用户要点麦当劳、问哪张券划算、问怎么点最省、问哪款性价比高、问现在是不是好价时使用。
---

# 麦门省钱精算师

不是把券列一遍就完事。绝大部分"优惠券助手"停在"你有这些券"，而真正省钱要回答三个更难的问题：**哪几张能叠加、叠加后到底哪组最便宜、这个价格历史上算不算低。**

## 它与别的麦当劳 Skill 有什么不同

| 别家做到 | 这里多做一层 |
|---|---|
| 列出你有哪些券 | 枚举券的**合法叠加组合**，逐个用 `calculate-price` 真机核价，用实付金额排序 |
| 告诉你打折了 | 算**每元热量 / 每元蛋白质**，两个榜常常不是同一批餐品 —— 这才是"性价比"的真实含义 |
| 当次便宜多少 | 存价格快照，对比**你自己**的历史成交价，回答"现在是不是好价" |
| 推荐单品券 | 校验券的适用范围，**购物车里没这个商品就不推荐**（最常见的翻车点） |

## 前置条件

- 麦当劳 MCP Token：到 <https://open.mcd.cn/mcp> 手机号登录后激活获取
- 环境变量：`export MCD_MCP_TOKEN=你的token`
- 已配置 MCP Server：见 `mcp-config.example.json`，端点 `https://mcp.mcd.cn`，Streamable HTTP

如果没配 MCP，也可以用纯本地模式（`optimizer.py value` / `snap`，见文末）。

## 主流程：帮用户下最省的一单

### 第 1 步：把可用券全部拿到手

```
query-my-coupons              -> 我卡包里已有的券
available-coupons             -> 麦麦省现在能领的券
```

**先问用户要不要一键领。** 用户同意后用 `auto-bind-coupons` 领全，再重新 `query-my-coupons` 拉一次。很多人卡包里是空的，因为从没领过。

把两次结果分别存成 `/tmp/my_coupons.json` 和 `/tmp/available_coupons.json`。

### 第 2 步：定位门店与菜单

```
delivery-query-addresses      -> 拿 addressId（外送）
query-nearby-stores           -> 拿 storeCode / beCode（自取、到店）
delivery-query-stores         -> 外送场景下的可配送门店
query-meals                   -> 该门店实际售卖的菜单
query-store-coupons           -> 该门店专属券（和全国券不是一回事，别漏）
```

菜单存成 `/tmp/menu.json`，门店券存成 `/tmp/store_coupons.json`。

### 第 3 步：枚举合法组合

```bash
python3 scripts/optimizer.py plan \
  --coupons /tmp/my_coupons.json \
  --menu /tmp/menu.json \
  --items '巨无霸代码:1' '薯条大代码:1'
```

也可以 `--cart /tmp/cart.json` 传完整购物车，或 `--subtotal 45` 只给金额。

输出里 `candidate_plans` 是按估算优惠排序的候选项，`rejected_coupons` 说明每张券为什么用不了 —— **把 rejected 的理由复述给用户听**，这比报个数字更让人信服。

### 第 4 步：逐个真机核价（关键，别省）

估算不等于实付。**每个候选方案都要真的调一次 `calculate-price`**，把结果分别存文件：

```
calculate-price  →  /tmp/price_1.json, /tmp/price_2.json, ...
```

券叠加规则、配送费、打包费只有服务端算得准。跳这一步，前面全白做。

### 第 5 步：排序出最优解

```bash
python3 scripts/optimizer.py rank \
  --results /tmp/price_1.json /tmp/price_2.json /tmp/price_3.json \
  --labels "只叠加满减" "满减+单品" "不用券"
```

### 第 6 步：记一笔，回答"现在是不是好价"

```bash
python3 scripts/optimizer.py snap \
  --key "巨无霸+薯条大" --pay 28.9 --discount 7.6 --store "门店名"
```

历史存在 `data/price_history.json`。第一次只有基线，用久了才有意义 —— 这是越用越值钱的功能。

## 第二个用法：哪款才是性价比之王

```bash
python3 scripts/optimizer.py value \
  --menu /tmp/menu.json \
  --nutrition /tmp/nutrition.json
```

营养数据来自 `list-nutrition-foods`。

- `kcal_per_yuan` 高 = 同样的钱买到更多热量，**饱腹导向**
- `protein_per_yuan` 高 = 同样的钱买到更多蛋白质，**健身导向**
- 两个榜第一名经常不是同一个东西。薯条在热量榜常常碾压，在蛋白榜垫底。把这个反差讲给用户听，是这个工具最出彩的地方。

## 汇报给用户时怎么说

不要甩 JSON。按这个顺序讲：

1. **结论先给**："这样点最省，实付 X 元，比直接点省了 Y 元"
2. **方案对比**：最优方案和次优差多少，值不值得为那几块钱多领一张券
3. **为什么别的券用不了**：直接说"你卡包里那张满 60 减 12 差 23 元到门槛，加一份薯条就能用，多花 12 实付反而降 5"
4. **历史判断**："这是你这单的历史最低价" 或 "比你上次贵 2.6 元，不急可以等"

第 3 条尤其重要 —— 差多少到门槛、凑单是否划算，这才是"精算"该干的事。

## 边界与红线

- **绝不擅自下单。** `create-order` 会真实扣款，任何下单动作必须用户明确说"就这个，下单"。核价阶段的 `calculate-price` 是安全的。
- **不擅自领券。** `auto-bind-coupons` 会改动用户卡包，先问。
- **Token 不外泄。** 不写进任何会被提交的文件，不在对话里展示明文，`mcp-config.example.json` 只允许环境变量占位符。
- **限流 600 次/分钟。** 候选方案控制在 20 个以内（默认 `--max-combos 20`），超了先剪枝再核价。
- **估算不是实付。** 任何 `estimated_*` 字段都必须说明以 `calculate-price` 为准，绝不能拿来当报价。
- 数据只覆盖中国大陆（不含港澳台）。

## 纯本地模式（没有 MCP 时）

两个子命令完全离线，不需要 Token：

- `optimizer.py value --menu 菜单.json --nutrition 营养.json` —— 性价比排行
- `optimizer.py snap --show` —— 查看历史价格基线

配合 `web/index.html`，把菜单 JSON 粘进去就能可视化看性价比榜单。

## 工具索引

`scripts/mcp_client.py` —— 零依赖 MCP 客户端，也是排查连通性的第一站：

```bash
python3 scripts/mcp_client.py ping          # 验证 Token 与协议握手
python3 scripts/mcp_client.py list-tools    # 看当前账号实际能用到哪些工具
python3 scripts/mcp_client.py call query-my-coupons
python3 scripts/mcp_client.py call calculate-price --args @payload.json
```

常见报错：`401` Token 失效，去 <https://open.mcd.cn/mcp> 重新拿；`429` 触发限流，降频重试。

完整工具清单见 `references/tools.md`。
