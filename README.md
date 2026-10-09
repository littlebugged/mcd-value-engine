# 麦门省钱精算师 · mcd-value-engine

> 基于麦当劳中国官方 MCP（Model Context Protocol）的省钱决策引擎。
> 参赛作品：麦当劳程序员创意开发大赛（2026.10.09 — 10.25）

## 为什么还要再做一个麦当劳 Skill

卡包里有 12 张券，结账时你依然不知道该用哪几张。

现有的优惠券工具大多停在"你有这些券"这一步。但省钱真正的难点在后面：

1. **哪几张能一起用？** 满减、单品特价、折扣券的叠加规则各不相同，肉眼看不出来。
2. **叠加之后哪组最便宜？** 面额最大的那张，未必让实付最低。
3. **这一单算不算好价？** 今天省了 5 块，可上周同样配置只花了 24。

第三个问题没人回答过 —— 因为没有工具记得你上次花了多少。

这个项目的做法：**枚举所有合法的券组合，逐个送到官方 `calculate-price` 真机核价，用实付金额排序，再把结果存进你的历史账单。** 估算只用来剪枝，报价一律以服务端为准。

## 和已有方案的区别

| | 常见做法 | 这里 |
|---|---|---|
| 券 | 列一遍 | 枚举可叠加组合，逐个真机核价 |
| 单品券 | 一股脑推荐 | 校验适用范围，购物车没有该商品就直接排除 |
| 性价比 | 看价格 | 算每元热量与每元蛋白质，两个榜常常不是同一批餐品 |
| 时间维度 | 只看当次 | 存价格快照，对比你自己的历史成交价 |
| 依赖 | 一堆 pip 包 | 零依赖，只用 Python 标准库 |

## 快速开始

### 1. 拿 Token

打开 <https://open.mcd.cn/mcp>，手机号登录 → 控制台 → 激活 → 同意协议 → 复制 Token。

```bash
export MCD_MCP_TOKEN=你的token
```

### 2. 配 MCP

把 `mcp-config.example.json` 复制成你的客户端配置，Token 走环境变量，别写进文件。完整教程见官方仓库 [M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server)。

### 3. 验证连通性

```bash
python3 scripts/mcp_client.py ping          # 协议握手
python3 scripts/mcp_client.py list-tools    # 看你能用到哪些工具
```

不需要 `pip install`，两个脚本都只用标准库。

### 4. 装 Skill

把 `SKILL.md` 挂到你的 Agent 上（WorkBuddy / Claude Code / Cursor / Cherry Studio 等都行）。之后直接说人话：

> "帮我点个巨无霸加薯条，看看怎么用券最省"

Agent 会自己走完六步流程。

## 三个例子

### 例一：券怎么叠

```bash
python3 scripts/optimizer.py plan \
  --coupons /tmp/my_coupons.json \
  --menu /tmp/menu.json \
  --items 'M1:1' 'M3:1'
```

```jsonc
{
  "subtotal": 36.5,
  "candidate_plans": [
    { "coupons": ["满30减5"], "estimated_discount": 5.0, "estimated_pay": 31.5 }
  ],
  "rejected_coupons": [
    { "name": "麦香鱼特价9.9", "reason": "购物车里没有该券适用的商品" },
    { "name": "全场8折",       "reason": "未达使用门槛（需满 40.0 元，当前 36.5 元）" }
  ]
}
```

被排除的券**附理由**。知道"差 3.5 元到门槛"之后，你才能判断要不要凑单 —— 这才是决策依据。

### 例二：哪种才是真性价比

```bash
python3 scripts/optimizer.py value --menu /tmp/menu.json --nutrition /tmp/nutrition.json
```

```
热量榜（每元热量）      蛋白榜（每元蛋白）
1. 薯条大    42.5      1. 板烧鸡腿堡  1.27
2. 麦香鱼    26.0      2. 巨无霸      1.06
3. 板烧鸡腿堡 22.8     3. 麦香鱼      1.13
4. 巨无霸    22.4      4. 薯条大      0.50
```

薯条在热量榜第一，在蛋白榜垫底。**"性价比"从来不是一个指标**，取决于你要的是饱腹还是蛋白。

### 例三：现在是不是好价

```bash
python3 scripts/optimizer.py snap --key "巨无霸+薯条大" --pay 28.9 --discount 7.6
```

```jsonc
{
  "historical_low": 26.0,
  "historical_avg": 30.2,
  "verdict": "不是好价。历史最低是 26.0元，现在贵 2.9 元。"
}
```

历史存在本地 `data/price_history.json`，不上传。用得越久越准。

## 目标用户

- **麦当劳高频消费者**：每月吃十几次，券越攒越多却从没算清楚过
- **价格敏感型用户**：学生、刚工作的年轻人，想省但不想花时间研究规则
- **健身人群**：要在预算内兼顾热量和蛋白质，需要的是每元蛋白而不是最便宜
- **Agent 开发者**：想要一份能直接复用的、零依赖的 MCP Streamable HTTP 客户端与券组合求解逻辑

## 仓库结构

```
SKILL.md                     技能主体，Agent 运行时加载
scripts/
  mcp_client.py              MCP Streamable HTTP 客户端（零依赖，含 SSE 解析）
  optimizer.py               组合求解 / 核价排序 / 每元价值 / 价格快照
references/
  tools.md                   官方 MCP 工具索引
web/
  index.html                 零依赖单页工具，纯本地计算
data/
  price_history.json         你的历史成交价（本地，不上传）
README.md / CONTEST_DECLARATION.md / MCP_INTEGRATION.md /
mcp-config.example.json / workbuddy.md
```

## 设计上的几个坚持

**估算与实付严格分开。** 所有本地估算字段都叫 `estimated_*`，并在输出里注明以 `calculate-price` 为准。优惠金额差几块钱，用户的信任就没了。

**绝不擅自花钱。** `create-order` 会真实扣款，`auto-bind-coupons` 会改动卡包 —— 两者都必须用户明确同意。核价的 `calculate-price` 是安全的，可以放手跑。

**零依赖。** 只用 Python 标准库。`clone` 下来就能跑，不用管虚拟环境和版本冲突。

**数据不出本地。** 价格历史写在你自己的磁盘上，网页工具纯前端计算，没有后端。这与"本地优先、不上传"的隐私趋势一致。

## 已知边界

- 券的字段命名在不同版本接口里可能变化，`optimizer.py` 用启发式归一化（每个语义字段列了多个候选 key）来兼容。若遇到新字段，在 `normalize_coupon` 里补一个 key 即可。
- 券叠加规则以服务端为准。本地的互斥剪枝是保守策略（同品类不叠、单品券不重复作用于同一商品），宁可少推荐，不推荐用不了的。
- 服务仅覆盖中国大陆（不含港澳台）。
- 麦当劳 MCP 工具集会随版本迭代，`references/tools.md` 记录到 v1.0.9。请以 `list-tools` 的实际返回为准。

## 许可与声明

参赛作品，原创发布。使用麦当劳 MCP 服务须遵守《麦当劳 MCP 服务规则》与使用条款。本项目非麦当劳官方产品，不构成商标授权。麦当劳相关商标归其权利人所有。
