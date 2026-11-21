# 保存期间的输入与重复操作保护

日期：2026-11-14。当前候选为 **r18 / 未发行 dev44**；原 C 盘 dev43、配置和凭据继续保留。此批不修改 Python 运行代码、配置格式、合同、预算或媒体流程。

## 已复现并修复

[修复前六场景](../_local/web-browser-suite-20261114-save-lock-before-r2/save-lock/result.json)在真实本机预览/提交接口上延迟浏览器响应：上游名称、模型备注和默认策略在保存中仍可改，但提交成功后后来输入被清空；恢复期间备份选择仍可改；连续点击归档在第一份预览返回前发出两份预览。全部使用 F 盘合成配置，未调用上游。

现在从请求预览开始保留单一配置事务，直到提交和刷新完成。上游/模型用原生 disabled fieldset 锁定输入与内部编辑按钮；默认选择和恢复中的备份选择同时锁定。页面导航和新的配置操作在忙碌期间禁用，函数入口也检查状态，避免预览尚未返回时的重复操作。原有提交标识、服务端锁、来源指纹及重复提交对账继续生效。

上游/默认/备份的忙碌状态覆盖表单收尾；模型弹窗在清理前保持锁定。成功关闭上游弹窗时，先解除保存状态，再等待页面更新后归还键盘焦点。失败保留非秘密输入并恢复操作，Key 仍清空，不进入草稿。提交结果不明时仍须先核对，不自动新增。防抖/请求/磁盘确认之前强退可能丢失最近输入的原 W17 边界仍保留。

## 实际验证

| 范围 | 证据与结果 |
| --- | --- |
| 六项专项与焦点 | [最终源码套件](../_local/web-browser-suite-20261114-save-lock-full-r3/save-lock/result.json)和[已安装 r18](../_local/web-browser-suite-20261114-save-lock-installed-r1/save-lock/result.json)均通过；包括预览/提交响应延迟、原生输入不可编辑、保存后的值、失败重试、焦点归还、备份和导航、只发一份预览/提交 |
| Web 全专项 | [85 项](../_local/web-validation-20261114/save-lock-web-r1/result.json)通过，无错误/跳过/外部连接尝试；未新增或重计 Python 测试 |
| 完整浏览器 | [11 组](../_local/web-browser-suite-20261114-save-lock-full-r3/result.json)通过，含 URL/Key、HTTP 安全、报价、typed 参考、实际 100–200% 缩放、21 状态无障碍、读取上下文和新增保存组 |
| 服务与浏览器强退 | [8 次服务重启](../_local/web-recovery-20261114-save-lock-r1/result.json)、[实际 Chrome 崩溃](../_local/web-browser-crash-20261114-save-lock-r1/result.json)及草稿竞争/清理失败通过 |
| 目录失败后整理 | [已安装 r18](../_local/web-catalog-failure-20261114-save-lock-installed-r1/result.json)保留六类失败的文档整理路径；没有真实上游检查 |
| 候选构建 | [r18 构建](../_local/web-candidate-20261114-r18/candidate-build.json)从源码独立重建前端并核对静态资源，发布 Schema 一致；286 输入、260 技能文件；归档扫描通过 |
| 四入口与回滚 | [安装回执](../_local/web-candidate-install-20261114-save-lock-r1/result.json)：中文/空格/`&`、无 Node/npm、ZIP 无 wheel、43→44→43→44、Schema 与图片预算兼容检查通过 |
| 离线交付 | [r2 套件构建](../_local/web-acceptance-kit-20261114-r2/kit-build.json)及[独立解压验收](../_local/web-acceptance-kit-validation-20261114-r2/result.json)通过，内含 r18 wheel/ZIP 和 15 个依赖；仅 Windows x64 CPython 3.9 |
| 原数据保护 | [本批保护回执](../_local/web-validation-20261114/preservation-save-lock-final.json)：原配置/DPAPI、325 外部文件及 5466 项目文件不变；8765 仍为 PID 2176 |

Python 总数仍为 **1121 核心 + 85 Web = 1206**。技能包的 181 个 Python 文件（含 Web）均未变，沿用原完整核心回归；本批 Web 回归重跑。15 个逻辑浏览器组中，14 组在本批重新验证或新增；原 C 盘实际数据只读组保留 r16 的原范围，未重复全目录联调。原九阶段维护数据保留仍是 r14 证据，不借本批四入口回滚扩大其版本范围。

Codex 另查看了本批 200% 上游与模型弹窗截图，标题、字段正文和底部操作区无新增裁切；自动无障碍结果仍不能代替真人读屏或完整人工体验。

## 失败现场和候选替代

- 初始专项脚本的语法错误发生在浏览器启动前，保留 `save-lock-before-r1` 日志；修正后 `before-r2` 才是六项产品问题证据。
- 专项 `source-r1` 的五项通过，备份项在完成提示出现但附带清理未结束时过早检查解锁。改为等待真实可用状态，`source-r2` 通过；没有缩短产品的忙碌范围。
- 首次完整回归 `full-r1` 发现保存后聚焦仍被禁用的按钮；修正实际产品后，r17 由 r18 替代。r17 产物保留，不作为最终候选。
- `full-r2` 的 typed 参考脚本因新增外层 fieldset 匹配了两个组而失败；改用带精确 legend 名称的“执行条件 2”组，保留原删除和持久化断言，最终 `full-r3` 全部通过。

## 当前交付与剩余

最新 [离线 ZIP](../_local/web-acceptance-kit-20261114-r2/VideoCreate-dev44-offline-win-cp39.zip)为 5,033,895 字节，SHA-256：`4fbfe3516c79909870377c72f63ff094662994f1b3be27fe5126e230fc1c6db4`。原 r1/r16 套件及其历史说明保持不变；当前套件仍无 Python 运行时或真实用户材料。

新 Windows、真人读屏与完整操作验收、正式版本/采用仍待完成。额外精确合同、token/分钟等其他单位、170 条旧记录的原身份和实际在线恢复保持原缺口。没有收费生成、样片重生或生产素材切换。
