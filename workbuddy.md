# WorkBuddy 开发上下文

> 本文件用于参与麦当劳程序员创意开发大赛的 WorkBuddy 专项奖励核验，
> 记录项目「麦门省钱精算师 · mcd-value-engine」在 WorkBuddy 中的真实开发过程。

## 一、项目概况

| 项 | 值 |
|---|---|
| 项目名称 | 麦门省钱精算师 · mcd-value-engine |
| 一句话定位 | 基于麦当劳官方 MCP 的省钱决策引擎：枚举券组合、真机核价、算每元价值、对比历史价 |
| 开发时间 | 2026-10-09 |
| 使用工具 | 腾讯 WorkBuddy（Agent 模式） |
| 技术栈 | Python 3（仅标准库，零第三方依赖）+ 原生 HTML/CSS/JS |

## 二、需求来源与构思过程

**起因**：查询麦当劳 GitHub 官方账号时，发现 `M-China/mcd-developer-innovation-challenge`（麦当劳程序员创意开发大赛）于当日开赛，WorkBuddy 为官方合作伙伴。

**方向选择**：WorkBuddy 给出四个候选方向（减脂吃麦当劳、省钱精算师、办公室团餐计算器、活动日历），并说明各自的 Star 天花板与竞争情况。用户选择「麦门省钱精算师」。

**差异化论证**：WorkBuddy 检索发现已有参赛者提交了同名方向 `mcd-saver-strategist`，因此明确指出「不能只做券列表，要做别人没有的三层增量」：

1. 券组合的**合法叠加枚举 + 逐个真机核价**（不是估算，是拿实付金额排序）
2. 结合营养数据的**每元热量 / 每元蛋白质**双榜（两个榜第一名常常不是同一个商品）
3. **个人历史价格基线**（回答"现在是不是好价"，越用越准）

## 三、信息获取

WorkBuddy 通过 GitHub API 与 raw 内容接口检索并读取了以下资料，用于确定 MCP 协议细节与工具清单：

- `M-China/mcd-mcp-server` 官方接入指南与完整工具列表（README）
- `M-China/mcd-developer-innovation-challenge` 活动规则 `activityGuidelines.md`
- 第三方实现参考：`cwyhkyochen-a11y/mcdonalds-mcp`、`ArisuMika520/mcd-skill`

据此确认：端点 `https://mcp.mcd.cn`、Streamable HTTP、协议版本 `2025-06-18`、Bearer Token 鉴权、600 次/分钟限流、31 个工具的清单与用途。

## 四、WorkBuddy 参与的具体环节

### 1. 方案设计与文件规划

规划了满足赛事硬性要求的仓库结构，明确五个必交文件：`README.md`、`CONTEST_DECLARATION.md`、`MCP_INTEGRATION.md`、`mcp-config.example.json`、`workbuddy.md`，外加 `SKILL.md` 与两个可执行脚本。

### 2. 代码编写

- **`scripts/mcp_client.py`** —— 零依赖 MCP Streamable HTTP 客户端。实现了完整生命周期：initialize 握手、从响应头提取并回传 `Mcp-Session-Id`、`notifications/initialized` 通知、`tools/list`、`tools/call`；同时支持 JSON 与 SSE 两种响应形态（`Accept` 双声明 + SSE `data:` 块解析）；对 `401` / `429` 做了分级提示；`tools/call` 优先取 `structuredContent`，退化时尝试把 `content[].text` 解析为 JSON。
- **`scripts/optimizer.py`** —— 计算引擎，四个子命令。券、餐品、营养数据的字段命名在不同版本接口中可能变化，因此写了启发式归一化：每个语义字段列多个候选 key，按优先级取第一个命中的，并递归遍历任意嵌套结构捞取 dict，避免漏掉藏在 list 里的数据。
- **`web/index.html`** —— 零依赖单页可视化工具，纯前端本地计算。

### 3. 缺陷发现与修复

WorkBuddy 用构造数据实跑验证，发现并修复了一个会导致错误推荐的缺陷：

**问题**：初版 `plan` 把单品券「麦香鱼特价 9.9」推荐给了购物车里只有巨无霸和薯条的用户。因为初版只看券面额和整单门槛，没有判断券的适用范围。

**影响**：这类错误会让用户按推荐下单后发现券用不了，是优惠券工具最常见的翻车点。

**修复**：在 `normalize_coupon` 中新增 `scope` 判定 —— 券里带商品码/商品名，或"有原价现价且无满减门槛"，即判定为单品券；单品券的优惠改为 `(商品原价 - 券价) × 数量` 计算，且只在购物车命中匹配商品时生效。同时在输出中增加 `rejected_coupons`，逐条说明每张券用不了的原因（"购物车里没有该券适用的商品" / "未达使用门槛，需满 40 元，当前 36.5 元"）。

**验证**：修复后，无麦香鱼的购物车正确排除该券并给出理由；购物车含麦香鱼时该券正确生效，优惠 5.1 元。

### 4. 测试验证

构造了券 / 菜单 / 营养三组模拟数据，实跑四个子命令：

- `plan`：小计 36.5 元场景，正确识别 1 张可用券、排除 3 张并附理由
- `value`：4 款餐品，输出热量榜（薯条大 42.5 kcal/元居首）与蛋白榜（板烧鸡腿堡 1.27 g/元居首），验证了"两个榜第一名不是同一个商品"这一核心洞察
- `rank`：3 个核价结果正确排序，输出最优解 28.9 元与相对最差方案节省 5.1 元
- `snap`：连续三次记录，正确给出"首次记录"、"不是好价，贵 2.6 元"、"历史最低，便宜 2.9 元"三种判断

测试后清除了产生的模拟数据，`data/price_history.json` 重置为空记录。

### 5. 文档撰写

撰写 `README.md`、`MCP_INTEGRATION.md`、`CONTEST_DECLARATION.md`、`SKILL.md`、`references/tools.md` 及本文件。

## 五、WorkBuddy 带来的效率提升

按实际产出估算，本次开发约为：代码约 700 行、文档约 900 行，从构思到可提交状态在一次连续会话内完成。其中效率提升最明显的三处：

1. **协议细节不用试错**：直接从官方文档与第三方实现中提取出 Streamable HTTP 的会话维持、SSE 响应、错误码等关键细节，避免了连不通时的盲目调试。
2. **缺陷在交付前暴露**：构造数据实跑这一步抓出了单品券适用范围的缺陷 —— 这个问题如果带到线上，用户第一次用就会发现推荐不准。
3. **竞争情报影响决策**：开工前检索发现已有同名参赛项目，直接改变了功能设计，从"做券列表"升级为"做组合求解 + 每元价值 + 历史基线"。

## 六、后续计划

- 待用户提供 GitHub PAT 后创建公开仓库并推送代码
- 在 `M-China/mcd-developer-innovation-challenge` 用指定 Issue 模板提交参赛申请
- 申请真实 MCP Token 后跑通端到端流程，并按真实接口字段校准 `normalize_coupon` / `normalize_meal` 的 key 列表
- `web/index.html` 部署到 GitHub Pages

---

开发者：周东旭
开发工具：腾讯 WorkBuddy
日期：2026-10-09
