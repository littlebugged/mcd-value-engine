# MCP 集成说明

参赛要求项：说明实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。

## 一、使用的 MCP Server

| 项 | 值 |
|---|---|
| 提供方 | 麦当劳中国（金拱门（中国）有限公司） |
| 端点 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP（MCP 协议版本 `2025-06-18`） |
| 鉴权 | 请求头 `Authorization: Bearer <MCD_MCP_TOKEN>` |
| Token 申请 | <https://open.mcd.cn/mcp>，手机号登录后激活 |
| 限流 | 每 Token 600 次/分钟，超限返回 `429` |
| 覆盖范围 | 中国大陆（不含港澳台） |

官方接入指南：[M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server)

脱敏配置见 `mcp-config.example.json`，只允许环境变量占位符，不含任何真实凭据。

## 二、客户端实现方式

`scripts/mcp_client.py` 是零依赖实现（仅 Python 标准库），完整走完 MCP 生命周期：

```
initialize                    → 协议握手，声明 protocolVersion 2025-06-18
  ← 记录响应头 Mcp-Session-Id，后续请求回传维持会话
notifications/initialized     → 通知服务端初始化完成
tools/list                    → 拉取当前账号可用工具清单
tools/call                    → 调用具体工具
```

几个必须处理的细节：

- **会话维持**：服务端通过 `Mcp-Session-Id` 响应头下发会话标识，客户端要存起来并在后续请求回传，否则每次调用都被当成新会话。
- **双响应形态**：Streamable HTTP 允许服务端返回普通 JSON，也允许返回 SSE 流。客户端同时声明 `Accept: application/json, text/event-stream`，并按 `Content-Type` 分支解析；SSE 场景要逐行找 `data:` 块，取最后一个完整 JSON-RPC 响应。
- **错误分级**：`401` 提示 Token 失效并给出重新申请入口，`429` 提示限流并建议降频，其余按 JSON-RPC `error` 对象抛出 code 与 message。
- **结构化优先**：`tools/call` 成功时优先取 `structuredContent`；没有结构化内容时，把 `content[].text` 尝试解析为 JSON，解析失败才返回原文。这样上层拿到的始终是结构化数据。

## 三、实际使用的 Tool

### 核心链路（省钱决策主流程）

| Tool | 调用时机 | 拿什么 | 业务价值 |
|---|---|---|---|
| `query-my-coupons` | 第 1 步 | 卡包内已有券 | 主数据源。很多人从没领过券，卡包是空的 |
| `available-coupons` | 第 1 步 | 麦麦省可领券 | 补漏，避免漏掉还没领的券 |
| `auto-bind-coupons` | 第 1 步（需用户同意） | — | 一键领取，把可领券变成可用券 |
| `query-nearby-stores` / `delivery-query-stores` | 第 2 步 | storeCode、beCode | 门店维度定位，券和菜单都是门店相关的 |
| `delivery-query-addresses` | 第 2 步（外送） | addressId | 外送核价的必需参数 |
| `query-meals` | 第 2 步 | 门店在售菜单、编码、价格 | 算购物车小计，也是性价比分析的数据源 |
| `query-store-coupons` | 第 2 步 | 门店专属券 | 与全国券不是一回事，漏掉就少一种组合 |
| `calculate-price` | 第 4 步（每方案一次） | 商品金额、配送费、优惠、应付总价 | **唯一可信金额来源**，券叠加规则只有服务端算得准 |
| `list-nutrition-foods` | 性价比分析 | 能量、蛋白质、脂肪、碳水、钠、钙 | 每元热量 / 每元蛋白的分母来源 |
| `now-time-info` | 需要时 | 当前时间 | 判断早餐/正餐时段、券是否已过期 |

### 下单与领券（受控调用）

`create-order`、`auto-bind-coupons` 属于**改动用户状态**的操作，默认不调用。必须在用户明确表达"就这个，下单"或"帮我领"之后才执行，且执行前复述关键参数（门店、商品、金额）请用户确认。

### 未使用但有价值的

`campaign-calendar`（活动日历）、`query-my-account` + `mall-points-products`（积分兑换）、`order-list`（历史订单）可作为扩展方向。当前版本聚焦在"省钱决策"这条主线上，避免功能发散。

## 四、完整调用流程

```
用户："帮我点个巨无霸加薯条，怎么用券最省"
  │
  ├─ 1. query-my-coupons ─────────────► /tmp/my_coupons.json
  │     available-coupons ────────────► /tmp/available_coupons.json
  │     （用户同意后）auto-bind-coupons → 重新拉一次卡包
  │
  ├─ 2. delivery-query-addresses ─────► addressId
  │     delivery-query-stores ────────► storeCode / beCode
  │     query-meals ──────────────────► /tmp/menu.json
  │     query-store-coupons ──────────► /tmp/store_coupons.json
  │
  ├─ 3. optimizer.py plan ────────────► 候选券组合（本地枚举 + 剪枝）
  │     · 过滤不满足门槛的券
  │     · 过滤适用范围不匹配的单品券
  │     · 同品类互斥剪枝
  │     · 输出 ≤20 个候选，控制核价请求数
  │
  ├─ 4. calculate-price × N ──────────► /tmp/price_1..N.json   ← 真机核价
  │
  ├─ 5. optimizer.py rank ────────────► 按实付金额排序，输出最优解与差额
  │
  └─ 6. optimizer.py snap ────────────► 写入历史，对比历史最低价给结论
```

第 3 步的本地剪枝是**为限流服务的**：600 次/分钟的额度看着宽裕，但一次决策如果枚举 100 个组合就消耗掉了六分之一。先把不可能的组合剪掉，再核价，才能在配额内跑完。

## 五、MCP 带来的业务价值

没有 MCP 时，"怎么用券最省"只能靠人肉试错：在 App 里反复加购、切换券、看价格变没变。这个过程既慢，又因为无法穷举而拿不到最优解。

MCP 把三件事变成了可编程的：

1. **券数据可获取** —— `query-my-coupons` 一次性拿到全部券的门槛、面额、有效期、适用范围，人眼在 App 里是看不全的。
2. **价格可批量核** —— `calculate-price` 可以对任意组合反复试算而不产生真实订单。这是"枚举 + 求解"能成立的前提，也是整个项目的支点。
3. **营养数据可计算** —— `list-nutrition-foods` 提供了热量与蛋白质，让"性价比"从单一价格维度扩展到"每元能买到什么"。

三者叠加产生的增量，是单看任何一个工具都得不出的结论：**面额最大的券未必让实付最低，最便宜的餐品未必是性价比之王。** 这个反直觉的结论，正是本项目想交付的东西。

## 六、合规与约束

- Token 只通过环境变量 `MCD_MCP_TOKEN` 注入，不写入任何会被提交或分享的文件，不在对话与日志中展示明文。
- `mcp-config.example.json` 仅含环境变量占位符。
- 遵守《麦当劳 MCP 服务规则》（<https://cdn.mcd.cn/cms/pages/MCPServerRules.html>）与使用条款。
- 遵守限流：默认候选方案上限 20，超出先剪枝。
- 不缓存、不转发、不上传用户券数据与订单数据；价格历史只写本地磁盘。
- 本集成用于非商业性质的个人省钱决策，不用于商业售卖、付费分发或暗示官方背书。
