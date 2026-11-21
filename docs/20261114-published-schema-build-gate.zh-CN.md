# 候选构建前检查发布 Schema

日期：2026-11-14。此批只扩展开发构建检查和测试，产品源码、前端静态资源及运行行为与 r12 相同；候选仍为未发行 dev44。

上批图片按张计价实现曾漏同步随包发布的 `videocreate.config.schema.json`，由完整核心回归发现后修复。这说明安全扫描和构建输入哈希只能证明“打包的是这些字节”，不能单独证明发布 Schema 与当前运行时一致。

`tools/build_web_candidate.py` 现在先读取当前源码的运行时 Schema，再检查随包 JSON。缺失、编码/JSON 损坏、内容过期或 JSON 字段类型不同均拒绝；JSON 空白和缩进差异可接受。检查不改写资产，也不从当前用户配置推导 Schema。成功回执记录被核验的资产路径、SHA-256、与运行时一致，以及检查发生在前端构建和打包之前。原有构建前后输入一致性检查继续生效。

| 验证 | 结果与边界 |
| --- | --- |
| 实现前定向用例 | 缺少检查函数，五种无效资产仍进入前端步骤；失败日志保留在 `schema-gate-before.log` |
| 构建专项 | 原五项加新增两项共七项通过；覆盖缺失、无效 JSON、非 UTF-8、过期、非对象和数字被布尔替换；测试不重复计入总数 |
| 真实构建入口拒绝 | 复制 285 个构建输入到新的 F 盘目录，分别去掉 `per_image`、损坏 JSON、删除资产和将数字改为布尔，四次实际 CLI 均在前端步骤前拒绝；无包、无成功回执 |
| 正常候选 | r13 独立前端重建及输入/打包哈希校验；仓库外四入口、新旧版回滚和安装 Schema 一致性验收见最新开发回执 |
| 测试适用范围 | r12→r13 产品源码与静态资源未变，1121 核心及 11 组浏览器结果继续适用；Web 测试加入两项后完整重跑 |

主要证据位于 `F:/VideoCreate/_local/`：`web-validation-20261114/schema-gate-before.log`、`schema-gate-after-r2.log`、`schema-gate-web-r1/result.json`；实际拒绝记录为 `web-schema-build-rejection-20261114-r1/result.json`；候选为 `web-candidate-20261114-r13/candidate-build.json`，安装记录为 `web-candidate-install-20261114-schema-gate-r1/result.json`。最新数量和保护核验见 [开发验证进度](20261113-web-development-progress.zh-CN.md) 与 [开发验证回执](20261113-web-development-verification.json)。

该检查不验证所有 Schema 的语义约束、所有模型合同或新主机兼容性，也不替代完整回归。发布资产与运行时一致不代表真实价格、账单或内容质量已验收。原配置、凭据、项目和 8765 服务继续保留；没有收费生成或样片重生。
