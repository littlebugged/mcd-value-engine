# 麦当劳 MCP 工具索引

**实测数据**：2026-10-09 连 `https://mcp.mcd.cn` 用 `tools/list` 拉取，实际返回 **35 个工具**。
端点 Streamable HTTP，协议版本 `2025-06-18`，Bearer Token 鉴权，600 次/分钟（超限 429），Token 失效 401。

> 工具集会随版本迭代。以 `python3 scripts/mcp_client.py list-tools` 的实际返回为准。

## 与官方 README 的三处不一致

实测对照官方仓库 [M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server) 的「工具列表」章节：

| 项 | 官方文档 | 实测 |
|---|---|---|
| 工具数 | 31 | **35** |
| 派对日期工具 | `query-partystore-date` | **`query-party-store-date`**（连字符位置不同，照文档调会失败） |
| 派对场次工具 | `query-partystore-session` | **`query-party-store-session`** |
| 未见记载的工具 | — | **`query-promotions`**、**`query-survey-coupon`** |

`query-promotions`（门店促销活动，参数同 `query-meals`）对省钱场景有用，官方文档没列。

## 省钱精算师依赖的 8 个

| Tool | 必填参数 | 用途 |
|---|---|---|
| `query-my-coupons` | — | 卡包内已有的券（`page`/`pageSize` 选填） |
| `available-coupons` | — | 麦麦省当前可领的券 |
| `auto-bind-coupons` | — | 一键领取，**需用户同意** |
| `query-store-coupons` | `storeCode` `beType` `orderType` | 门店专属券，容易漏 |
| `query-nearby-stores` | `beType` `searchType` | 拿 storeCode（`city`/`keyword` 选填） |
| `query-meals` | `storeCode` `beType` `orderType` | 门店在售菜单 |
| `calculate-price` | `storeCode` `beType` `orderType` | **唯一可信金额来源** |
| `list-nutrition-foods` | — | 160 条营养数据，性价比分析的分母 |

## 定位、门店与菜单

| Tool | 必填 | 说明 |
|---|---|---|
| `delivery-query-addresses` | — | 我的配送地址（拿 addressId） |
| `delivery-create-address` | `address` `addressDetail` `city` `contactName` `phone` | 新增地址 |
| `delivery-query-stores` | `beType` `addressId` | 外送可配送门店，拿 beCode |
| `query-meal-detail` | `storeCode` `beType` `orderType` `code` | 套餐组成与可替换项 |
| `query-meal-assistance` | `storeCode` | 企业团餐助餐服务 |
| `query-promotions` | `storeCode` `beType` `orderType` | 门店促销活动（文档未记载） |
| `now-time-info` | — | 当前时间，判断早餐/正餐时段 |

## 下单与订单

| Tool | 必填 | 风险 |
|---|---|---|
| `create-order` | `storeCode` `beType` `orderType` | **真实扣款，必须用户明确同意** |
| `cancel-order` | `orderId` `cancelReasonCode` | 改动用户状态 |
| `query-order` | `orderId` | 只读 |
| `order-list` | — | 只读 |
| `query-survey-coupon` | `orderId` | 评价后得的券（文档未记载） |

## 积分、商城与抽奖

| Tool | 必填 |
|---|---|
| `query-my-account` | — |
| `mall-points-products` | —（`catRuleIds` 选填） |
| `mall-product-detail` | `spuId` |
| `mall-create-order` | `skuId` `spuCategory` |
| `mall-order-list` | —（`lastId`/`size` 选填） |
| `mall-order-detail` | `orderId` |
| `query-lottery-info` / `draw-lottery` / `query-my-prizes` | — |

## 活动与派对

| Tool | 必填 |
|---|---|
| `campaign-calendar` | —（`specifiedDate` 选填） |
| `query-party-city` | `spuId` |
| `query-party-store` | `code` |
| `query-party-store-date` | `spuId` `storeCode` |
| `query-party-store-session` | `spuId` `storeCode` `dateStr` |
| `party-order-create` | `partyType` |

## 实测出来的调用坑

官方文档没写，但照着猜会失败：

- **`query-nearby-stores` 的 `searchType` 必须传 `2`**。传 `1` 或不传 → 「收藏餐厅列表为空，请您提供城市+关键词进行搜索」。1 是查收藏门店，2 才是关键词搜索。
- **`beType=2` 会被拒绝**：「仅支持到店和得来速」。
- **外送（`orderType=2`）必须传 `beCode`**，否则报「外送场景下，beType=2/5/6 时必传 beCode」。到店（`beType=1` `orderType=1`）只给 `storeCode` 就行。
- **`list-nutrition-foods` 的 `data` 是字符串不是 JSON**：`[160]{productName,energyKcal,protein,fat,carbohydrate,sodium,calcium}:` 后接 CSV 行。热量字段叫 `energyKcal`，商品名叫 `productName`。
- **券的语义是「用券价」不是满减**：`discountInfo.discountValue="9.9"` 表示花 9.9 买它。省多少 = 商品原价 − 9.9，必须结合菜单才能算。
- **券有 `enable` 字段**，`0` = 还没到可用日期。麦当劳会把未来几天的早餐券一次性发进卡包。

真实返回结构的适配代码见 `scripts/mcd_schema.py`。

## 调用约定

- 鉴权：`Authorization: Bearer <MCD_MCP_TOKEN>`
- 传输：Streamable HTTP，协议版本 `2025-06-18`
- 复杂参数用 `--args @file.json` 传完整 JSON，尤其 `calculate-price` 的 `items`（对象数组）
- `scripts/mcp_client.py` 已封装 initialize / 会话维持 / SSE 解析，直接用它

## 版本轨迹

| 版本 | 日期 | 新增 |
|---|---|---|
| 1.0.0 | 2025-12-09 | 麦麦日历、麦麦省领券 |
| 1.0.1 | 2026-01-23 | 餐品营养信息 |
| 1.0.2 | 2026-02-13 | 麦乐送点餐、积分兑换券 |
| 1.0.3 | 2026-04-02 | 到店取餐、团餐 |
| 1.0.4 | 2026-05-21 | 积分兑换实物、商城订单、得来速、全场景预约 |
| 1.0.5 | 2026-06-16 | 更换套餐组合、部分餐品特制 |
| 1.0.6 | 2026-07-16 | 历史订单查询、优惠价展示、随单买麦金卡/早餐卡 |
| 1.0.7 | 2026-07-29 | 麦当劳派对、品鉴会 |
| 1.0.8 | 2026-08-27 | 积分抽奖 |
| 1.0.9 | 2026-09-10 | 取消订单、餐具选择、订单备注、取餐柜二维码 |
