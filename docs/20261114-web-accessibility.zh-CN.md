# 本机 Web 自动化无障碍核验

日期：2026-11-14。适用范围为 F 盘未发行 dev44 候选，C 盘已安装 dev43 保持原样。本次只在隔离配置上运行，没有修改真实配置、解密真实凭据或调用生成接口。

下表保留首次 18 状态修复批次的证据。最新 r9 已完成 21 状态、70 项导航/收藏语义检查及 51 次实际符号颜色观察；42 次 raw axe 未决观察完整保留，并逐个精确 DOM 目标补充核验通过，最低 5.175:1。最新回执为 `_local/web-symbol-semantics-20261114-coverage-r1/accessibility/result.json`，完整范围、旧报告与新报告的关系见 [符号语义补验](20261114-web-symbol-semantics.zh-CN.md)。这项补验不等于 axe 自行解决 incomplete，也不替代真人读屏或完整 WCAG 审计。

新增核验复现三类问题：辅助文字、远端型号及状态标签的小字对比度不足；任务比较列表中复选框目标过小且过密；模型弹窗从末尾按 Tab 后焦点会离开弹窗。调整了文字颜色、24px 复选框和可见焦点轮廓；两个编辑弹窗共用 Tab/Shift+Tab 边界处理，按当时可见、可用的控件计算，展开高级字段后仍可循环。Escape、未保存确认和返回原按钮保持原流程。

| 核验 | 实际证据 | 结论边界 |
| --- | --- | --- |
| 修复前 | `_local/web-accessibility-20261114-before-r1/accessibility/result.json` | 16 个状态出现 17 组规则违规（重复页面各计一组）、1 个焦点边界失败；不是 17 个独立缺陷 |
| 修复后完整套件 | `_local/web-browser-suite-20261114-a11y-r2/result.json` | 9 个浏览器组全部通过，包含原保存、草稿、计费、typed 媒体和真实 Chrome 缩放验证 |
| 自动化无障碍 | 上述目录的 `accessibility/result.json` | 18 个状态、5 个焦点边界通过，自动化违规为 0；原配置夹具字节不变，无外部请求或收费创建 |
| 工具无法判定 | 同一回执各状态的 `incomplete` | 当时 27 次重复符号观察待复核；后续扩大到 21 状态的逐目标补验已完成，原报告不删除或改写 |
| Web 专项 | `_local/web-validation-20261114/accessibility-web/result.json` | 68 项通过；本批未改 Python 运行逻辑，核心 1098 项沿用上一批已通过完整回归，7 项产品质量合同测试另行重查且不重复计数（原记录误称文档同步，现更正；它不验证文档/模块同步） |
| 新候选安装回滚 | `_local/web-candidate-install-20261114-r4/result.json` | 仓库外运行、离线安装和 43→44→43→44 通过；不是全新 Windows 主机验收，也未覆盖稳定安装 |

扫描工具为锁定的开发依赖 axe-core 4.14.0，规则采用 WCAG 2 A/AA、2.1 A/AA 与 2.2 AA 标签。工具通过浏览器调试接口注入隔离页面，不放宽服务 CSP；不会打进前端运行产物或技能包。全部前端依赖的 npm audit 本次报告 0 漏洞，见 `_local/web-validation-20261114/accessibility-npm-audit-all.json`。

桌面高级表单及 390px 上游表单截图已由 Codex 复核。截图及自动化结果不能替代真人读屏、实际用户完成配置任务和完整 WCAG 审计。这些人工验收及全新 Windows 环境验证继续列为未完成。

复跑入口为 [浏览器套件](../tools/verify_config_web_browser_suite.py) 的 `--scripts verify_config_web_accessibility.cjs`。该入口要求指定新的 F 盘 `_local` 输出目录，使用合成配置及独立端口；8765 不参与测试。
