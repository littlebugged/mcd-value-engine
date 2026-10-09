# 麦当劳 MCP 工具索引

来源：麦当劳中国官方仓库 [M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server) 的「3. 工具列表」章节。
端点 `https://mcp.mcd.cn`，Streamable HTTP，限流 600 次/分钟（超限 429），Token 失效返回 401。

> 工具集会随版本迭代增减。用 `python3 scripts/mcp_client.py list-tools` 拿你自己账号当前的真实清单，以那个为准。

## 省钱精算师重点依赖的 7 个

| Tool | 用途 | 在流程中的位置 |
|---|---|---|
| `query-my-coupons` | 我卡包里可用的券 | 第 1 步，主数据源 |
| `available-coupons` | 麦麦省当前可领的券 | 第 1 步，补漏 |
| `auto-bind-coupons` | 一键领取所有可领券 | 第 1 步，**需用户同意** |
| `query-store-coupons` | 当前门店专属券 | 第 2 步，容易漏 |
| `query-meals` | 门店在售菜单 | 第 2 步，算小计与性价比 |
| `calculate-price` | 算商品金额/配送费/优惠/应付 | 第 4 步，**唯一可信金额来源** |
| `list-nutrition-foods` | 餐品营养成分 | `value` 子命令的营养源 |

## 定位与门店

| Tool | 说明 |
|---|---|
| `delivery-query-addresses` | 我创建的配送地址列表（外送要拿 addressId） |
| `delivery-create-address` | 新增配送地址 |
| `delivery-query-stores` | 外送场景下收货地址附近的可配送门店 |
| `query-nearby-stores` | 附近可用门店 |
| `query-meal-detail` | 按餐品编码查套餐组成与可替换项 |

## 下单与订单

| Tool | 说明 | 风险 |
|---|---|---|
| `create-order` | 创建订单，返回订单详情与支付链接 | **真实扣款，必须用户明确同意** |
| `cancel-order` | 取消订单 | 改动用户状态 |
| `query-order` | 查询订单详情 | 只读 |
| `order-list` | 近期到店/外送历史订单 | 只读 |

## 积分与商城

| Tool | 说明 |
|---|---|
| `query-my-account` | 积分账户（可用/累计/冻结/即将过期） |
| `mall-points-products` | 麦麦商城可兑换/可购买商品 |
| `mall-product-detail` | 商城商品详情 |
| `mall-create-order` | 积分兑换下单 |
| `mall-order-list` | 商城近一年订单 |
| `mall-order-detail` | 商城订单详情 |

## 活动、抽奖与派对

| Tool | 说明 |
|---|---|
| `campaign-calendar` | 当月营销活动日历（进行中/往期/未来） |
| `query-lottery-info` | 积分抽奖活动信息与奖品池 |
| `draw-lottery` | 执行一次积分抽奖 |
| `query-my-prizes` | 我的奖品记录 |
| `query-party-city` | 主题活动可参与城市 |
| `query-party-store` | 指定城市下可参与门店 |
| `query-partystore-date` | 可预约日期 |
| `query-partystore-session` | 可预约场次 |
| `party-order-create` | 创建主题活动订单 |

## 其他

| Tool | 说明 |
|---|---|
| `now-time-info` | 当前时间信息，判断早餐/正餐时段、券是否过期时有用 |
| `query-meal-assistance` | 仅企业团餐场景，查询门店助餐服务 |

## 调用约定

- 鉴权：`Authorization: Bearer <MCD_MCP_TOKEN>`
- 传输：Streamable HTTP，支持的最高协议版本 `2025-06-18`
- 复杂参数用 `--args @file.json` 传完整 JSON，尤其是 `calculate-price` 的 `items`（对象数组）
- `scripts/mcp_client.py` 已封装 initialize / session 维持 / SSE 解析，直接用它，不要自己拼 JSON-RPC

## 版本轨迹（判断哪些能力较新）

| 版本 | 日期 | 新增 |
|---|---|---|
| 1.0.0 | 2025-12-09 | 麦麦日历、麦麦省领券 |
| 1.0.1 | 2026-01-23 | 餐品营养信息 |
| 1.0.2 | 2026-02-13 | 麦乐送点餐、积分兑换券 |
| 1.0.3 | 2026-04-02 | 到店取餐、团餐 |
| 1.0.4 | 2026-05-21 | 积分兑换实物、商城订单、得来速、全场景预约 |
| 1.0.5 | 2026-06-16 | 更换套餐组合、部分餐品特制 |
| 1.0.6 | 2026-07-16 | 历史订单查询、优惠价展示、随单买麦金卡/早餐卡 |
| 1.0.7 | 2026-07-29 | 麦当劳派对、品鉴会查询预约下单 |
| 1.0.8 | 2026-08-27 | 积分抽奖 |
| 1.0.9 | 2026-09-10 | 取消订单、餐具选择、订单备注、取餐柜二维码 |
