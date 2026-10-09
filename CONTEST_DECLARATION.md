# 参赛声明

## 一、原创性声明

本人声明，参赛项目 **麦门省钱精算师 · mcd-value-engine** 为本人原创开发成果，本人对该项目完整拥有使用权与处分权。

- 项目核心逻辑（券组合枚举与剪枝策略、每元价值指标体系、价格快照基线对比、MCP Streamable HTTP 客户端实现）由本人独立设计与编写
- 代码未抄袭、未盗用、未 fork 自其他参赛项目或第三方项目
- 未使用他人账号、未冒用他人身份提交参赛
- 未通过机器人脚本、刷量工具或任何方式操纵 Star 数据与榜单排名

引用的第三方资料已在对应位置注明来源，包括：

- 麦当劳中国官方 MCP 接入指南与工具列表：[M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server)
- 麦当劳 MCP 服务端点 `https://mcp.mcd.cn` 及工具命名，来源于上述官方文档

## 二、麦当劳 MCP 使用情况声明

本项目**真实调用了麦当劳中国官方 MCP 服务**，非模拟、非占位：

- 端点 `https://mcp.mcd.cn`，Streamable HTTP 传输
- 使用的 Tool 包括 `query-my-coupons`、`available-coupons`、`auto-bind-coupons`、`query-store-coupons`、`query-meals`、`query-nearby-stores`、`delivery-query-addresses`、`delivery-query-stores`、`calculate-price`、`list-nutrition-foods`、`now-time-info`
- 调用流程与业务价值详见 [MCP_INTEGRATION.md](./MCP_INTEGRATION.md)

项目不是对 MCP 工具的简单封装，在工具能力之上构建了三层增量逻辑：券组合的合法性与叠加求解、基于营养数据的每元价值指标、跨时间的个人价格基线。

## 三、WorkBuddy 使用情况声明

本项目**真实使用腾讯 WorkBuddy 智能体**完成创意构思、代码编写、文档生成与调试验证。开发过程中的对话上下文记录于 [workbuddy.md](./workbuddy.md)，用于参与 WorkBuddy 专项奖励的核验。

## 四、合规声明

本人确认并承诺，本项目及其内容不包含以下情形：

- 违反中华人民共和国法律法规及平台规则的内容
- 有损国家尊严与利益、妨碍社会安定与公共秩序、违反公序良俗的内容
- 政治敏感或可能对麦当劳造成不良影响的内容
- 侮辱、诋毁、讽刺、贬低麦当劳品牌、产品及形象的内容，或将麦当劳与其他品牌进行对比的内容
- 侵害第三方知识产权、隐私权、商业秘密或其他合法权益的内容
- 植入恶意脚本、钓鱼链接、病毒、违规命令，或指向违规站点的外部链接

本项目定位为个人省钱决策辅助工具，非商业售卖、非付费分发、不引流变现，不暗示麦当劳官方背书。

## 五、敏感信息声明

本人确认：

- 提交的代码与文档中**不包含**任何真实 MCP Token、账号密码、手机号、收货地址、订单号等个人信息或敏感凭据
- `mcp-config.example.json` 仅含环境变量占位符 `${MCD_MCP_TOKEN}`
- `data/price_history.json` 已重置为空记录数组，不含任何真实交易数据
- Token 仅通过环境变量注入，不写入版本库，不在对话与日志中展示明文

## 六、其他确认

- 参赛项目仓库保持公开可访问状态
- 项目创建时间符合赛事要求（2025 年 12 月 25 日至 2026 年 10 月 25 日之间）
- 同一 GitHub 账号仅以本项目参赛
- 已阅读并同意《麦当劳程序员创意开发大赛活动规则》、《麦当劳 MCP 服务规则》及相关使用条款

---

声明人：周东旭
日期：2026-10-09
