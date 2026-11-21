# VideoCreate 最新完整开发清单 · 接手复核版 v2

日期：2026-11-13（Asia/Shanghai）。开发目录：`F:/VideoCreate`。

本文件接替原交接清单中的后续实施顺序，保留原 73 项工作包、W01–W22 子项及其未完成范围。原交接文档、保护基线、迁移记录和交接 ZIP 保留历史含义。本文第 1–9 节保留接手时的核查事实与原定验收要求；下方执行增量及链接反映本轮实际进度，不能将计划、原型或离线核心测试计作真实生成或正式发行。

最终产品流程：**本机 Web 填 URL/Key → 本机保存 → 用户明确触发只读目录检查 → Codex 结合已知合同整理接入 → Codex 选型与制作。** 名称、备注可选；model/binding/route、账户标识、协议和参数由工具与 Codex 维护。每个实体只有一个面向用户的保存动作，后端预览/提交可以分两步执行。

完整机器台账见 [v2 JSON](20261113-development-plan-v2.json)，本次检查证据见 [基线报告](20261113-web-baseline-verification.json)。原始要求及历史实现详见本文末尾的完整 73 项台账。

## 执行增量：本机 Web 候选已实现，目标继续进行

M1 安全只读页、M2 URL/Key 保存及 Codex/CLI 同文件闭环已实现并通过本机候选验证。M3 的筛选/比较、证据、诊断和四类非秘密草稿，以及 M4 的启动器、隔离素材进程、候选构建和安装回滚已有验证；其余未完成范围继续保留。当前源码/候选是未发行 dev44，已安装 dev43 不变。

- 核心全回归 1121 项沿用，Web 91 项已重跑，合计 **1212 项**。候选 r23、离线套件 r6 保持原包；本批补已安装 r23 原 C 配置只读联调，17 逻辑浏览器组中 14 个已验证 r23，三组保留 r22，维护仍为 r14。11 项生命周期补验不增加测试数；没有收费生成或样片重生。
- Windows venv 素材启动确认已修复；现有 8765 仍为 PID 2176。原配置/凭据、325 个外部基线文件、5466 个原项目文件校验不变；没有重生样片或收费生成。
- 截至 2026-11-14，本批新增能力/报价/档位和 typed 图片/视频/音频约束、七类组合、条件时长结构化编辑；四类持久草稿、8 个真实服务实例强退恢复，以及实际 Chrome 崩溃/标签页标识丢失后主动找回草稿。Chrome 100/125/150/175/200% 实际缩放通过并修复底部按钮裁切；损坏配置首页修复草稿恢复、同名/精确大小写/多菜单/多项目/旧平台别名歧义均补回归。草稿保存/接管/丢弃按版本检查，共享会话双窗口和真实多进程竞争通过；Tk `ThemeChanged` 警告已修复。保留未完成项：更多精确合同、token/分钟等其他核心计费语义及真实账单、未确认暂存前的极短强退窗口、更广历史项目/自然语言别名矩阵、真人读屏/新 Windows 及正式发行。本批又补统一计费说明、图片比较和旧结果失效/迟到响应保护，核心完整回归已通过；本批前端无障碍修复后 Web 回归及九组浏览器套件通过。真实历史只读核验见 [历史兼容说明](20261114-web-history-compatibility.zh-CN.md)：130 条 v3 快照解析稳定，170 条旧记录的原有平台别名歧义保持拦截，尚未在线恢复。自动化无障碍另见 [自动化核验](20261114-web-accessibility.zh-CN.md)：修复对比度、复选框目标与弹窗 Tab 边界；最新 21 状态和导航/收藏语义、逐目标符号对比度补验见下文，真人读屏仍待验收。r5 候选另补 [构建输入与静态一致性核验](20261114-web-build-provenance.zh-CN.md)，记录 284 个输入并拒绝真实过期静态副本；原前端字节不变，新增 5 项构建测试已计入 Web。本批 r6 又补 [Codex 精确名称查询](20261114-codex-name-lookup.zh-CN.md)，按保存名称、平台、精确型号/远端 ID 和家族返回规范身份，保留禁用/归档歧义，再进入原选择预检。任意别名及真人对话未宣称完成。完整核心与 Web 重新验证，285 个构建输入一致，同一 r6 包在 r7 隔离安装回滚通过。随后 r8 补齐 [启动入口特殊路径验证](20261114-web-launcher-paths.zh-CN.md)：独立 console 与 ZIP Python/PowerShell/CMD 四入口在中文、空格和 `&` 路径运行、同实例复用；ZIP 无 wheel、PATH 无 Node/npm。修复独立入口 traceback、依赖分类和 CMD `pause` 吞错误码，Web 76 项及 paths-r3 安装回滚通过。核心、前端和 HTTP 源码不变，沿用其已有验证。随后 r9 补齐 [导航与收藏符号语义](20261114-web-symbol-semantics.zh-CN.md)：21 状态、70 项语义检查及 51 次符号颜色观察通过，42 次 raw axe 未决观察全部保留并逐目标补验，最低 5.175:1。Web 76 项、九组浏览器及 symbols-r1 四入口安装回滚通过；核心 136 个 Python 文件未变，沿用 1107 项完整回归。真人读屏、完整任务可用性及新 Windows 仍待验收。随后 r10 修复 [缺少参数时的价格档位判断](20261114-budget-tier-context.zh-CN.md)：一般档已匹配仍不能排除未知条件档时金额未知；唯一排除/确认重叠和图片硬预算零创建通过。完整核心 1111、Web 77 及两组相关浏览器、四入口安装回滚再次通过。该 r10 批次没有增加计费单位。随后 r12 完成 [图片按张预算](20261114-image-budget-units.zh-CN.md)：只按适配器明确发送的 n 计数，不猜供应商默认值；Web/Tk、计划/执行预览和预算预留共用核心。首次核心回归发现发布 Schema 资产遗漏，修正后重跑完整回归并替代 r11。完整 1121 核心、79 Web、11 组浏览器含真实价格草稿强退恢复、四入口安装、安装 Schema 一致和 dev43 拒绝新字段均通过；真实账单仍未知。随后 r13 增加 [发布 Schema 构建检查](20261114-published-schema-build-gate.zh-CN.md)：四种故障副本的实际 CLI 均在前端/打包之前拒绝，正常候选与四入口安装回滚通过。产品运行文件未变，核心/浏览器结果沿用，Web 两项新增计入 81 项。W19 另补项目内结构化取证，80 JSON、20 日志/1097 行仍缺 170 条旧记录的原账户/地址/快照，歧义继续保留。随后 r14 完成 C07/W22 [维护说明和数据保留验收](20261114-web-maintenance-lifecycle.zh-CN.md)：文档同时入 wheel/ZIP，纠正旧安装器误导，九阶段各保留 13 个合成用户文件，四入口安装回滚再次通过；286 个输入一致，运行代码未变，1202 项测试沿用。随后 r15 修复 [目录失败后的文档整理](20261114-catalog-failure-documents.zh-CN.md)，六类失败仍保留精确地址合同，来源变化要求刷新；84 Web、源码/已安装包浏览器和四入口通过，合计 1205 Python 项及 12 个逻辑浏览器组；未新增型号合同。随后 r16 完成 [目录与证据读取上下文保护](20261114-web-read-context.zh-CN.md)：旧成功/错误/忙碌状态不串用，指纹绑定实际配置；85 Web、11 个专项源码/安装包、全部原浏览器及四入口通过，共 1206 Python 项和 13 个逻辑浏览器组；核心字节未变沿用。之后补 [已安装候选读取原 C 盘配置](20261114-web-original-data-readonly.zh-CN.md)：5 上游、25 接入详情、38 操作记录和五页只读联调通过；32,431 文件哈希与一个服务锁元数据不变，应用取钥/越界写入/外连尝试均为零，仍为 r16、共 14 个逻辑浏览器组。真人/干净机器未因此视为通过。W20 生产切换继续延后。

随后补 [Windows 离线验收套件](20261114-web-offline-acceptance-kit.zh-CN.md)：冻结 r16、15 个哈希依赖、四入口自动验收与人工回执模板，独立解压在本机通过；仅支持 Windows x64 CPython 3.9，不含 Python 运行时，未替代干净新主机或真人验收。

随后 r18 完成 [保存期间输入与重复操作保护](20261114-web-save-lock.zh-CN.md)：预览前保留事务、锁定输入/导航、失败保留非秘密字段并在解锁后归还焦点；完整回归修正后替代 r17，最新离线套件 r2 随同验证。

随后 r21 完成 [保存响应丢失后的表单收尾](20261114-web-commit-reconciliation.zh-CN.md)：核对接回原保存，四类表单与草稿正确收尾；重开不误删较新草稿，未知不自动重试。补键盘焦点与折叠高级区循环修复后替代中间 r19/r20，离线套件 r4 随同验证。

随后 r22 完成 [同端口配置上下文隔离](20261114-web-config-context.zh-CN.md)：认证路径身份绑定页面请求，草稿/pending 按配置保留，旧标识不静默删改。两份相同内容配置的五场景、88 Web、完整浏览器及安装回滚和 r5 离线套件通过。

随后 r23 完成 [草稿接入整理待办](20261114-web-setup-guidance.zh-CN.md)：未知合同显示具体缺少的协议、操作与参数；声明和适配器默认值不抵扣待补，精确文档仅整理匹配型号。91 Web、十二组浏览器、源码/安装新增区域及四入口回滚、r6 离线套件通过；169 个非 Web Python 文件不变，核心 1121 项沿用。

随后补 [r23 原数据与剩余发行条件复核](20261114-web-release-readiness-audit.zh-CN.md)：五页、25 接入详情和 38 操作记录通过，32,431 文件哈希及原服务锁元数据不变；取钥、外连、越界写入与子进程计数全零。286 构建输入、260 包文件、已安装 wheel 的 148 Python/3 静态资源和解压 ZIP 的 260 文件一致，未重建产品。17 逻辑浏览器组现有 14 个验证 r23、三个保留 r22；真人读屏、全新 Windows、精确新合同/计费语义及历史身份依据仍需分别补齐。

随后 W19 补 [原配置备份只读身份核验](20261114-web-history-compatibility.zh-CN.md#原配置备份补充核验)：四份 C 盘 JSON 备份及当前配置均保留平台别名的多个候选；100 份项目结构化证据没有对应配置哈希/指纹的精确值关联。105 个输入字节不变、零取钥和在线请求；170 条旧记录仍需直接原身份，未作迁移。r23/r6 及测试范围不变。

当前目标状态为 **blocked，等待外部条件**，并非完成。官网文档正文的未认证读取返回 401；精确新合同/计费、170 条旧任务直接身份、真人读屏/完整体验和干净 Windows 条件仍需实际补齐。连续三个目标轮次的核对依据及可恢复工作条件见 [外部验收条件](20261114-web-external-acceptance-gates.zh-CN.md)。M1/M2 候选实现、全部未提交工作、原 73 项台账和 r23/r6 产物保留。

最新 2026-11-14 逐项 W01–W22 状态、候选哈希、失败处理及下一批完整顺序见 [开发验证进度](20261113-web-development-progress.zh-CN.md)，机器证据见 [开发验证回执](20261113-web-development-verification.json)。原 73 项历史状态和合计不变；下文“尚未开发”“两项失败”等属于接手基线时点，不能覆盖本节的后续执行结果。

## 1. 接手基线：开发前已经核实的事实

| 项目 | 本次结果 | 对后续工作的影响 |
| --- | --- | --- |
| 分支 / HEAD | `codex/provider-manager` / `aed9f160ed8d07007ab5b2ef3950706ce0d3a207` | 保留当前工作树及全部未提交内容 |
| 已安装 / F 盘源码 | `3.0.0.dev43` / 未完成的 `3.0.0.dev44` | 分别记录版本；新 Web 发行不得借用 dev43 验收 |
| 未提交文件保护 | 37 个既有文件测试前后字节不变；其中 11 个产品/测试文件与交接哈希一致 | 不 reset、不 clean、不覆盖 dev44 工作 |
| 权威配置 | Schema 4；5 上游、14 内部模型、25 接入、14 路由；19 启用、5 草稿；结构校验 0 错误 | 数量是配置登记，不是在线可用性 |
| 配置和凭据 | 配置与交接哈希一致；配置、`secrets.dpapi` 测试前后字节不变 | 继续使用 C 盘原配置及当前 Windows 账户凭据 |
| 路径解析 | 当前默认路径 resolve 后与交接中的权威路径相同 | 启动器仍须校验实际解析结果；不同启动环境不得初始化第二份配置 |
| Web 源码 | `config_web/`、`web/provider-config/` 均不存在 | HTML 是演示原型；正式 W01–W22 尚未交付 |
| 端口 | 本次前后均为 `127.0.0.1:8765`、PID 2176 监听；8787 未监听 | 仅确认本机监听；未重新验证公网素材访问 |
| 运行环境 | Python 3.9.12、Node 24.18.0；包声明 Python ≥3.9、核心依赖为空 | Web 依赖使用可选组；开发构建使用 Node，用户运行不依赖 Node |
| 历史总台账 | 73 项：11 离线实现、60 部分实现、2 待开发 | W 子项不额外计入 73 项，不计算虚假完成率 |

权威配置继续是：

```text
C:/Users/FBX/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/VideoCreate/videocreate.config.json
```

本次验证了 136 项专项测试，134 项通过、2 项失败、0 错误、0 跳过。共享配置/目录/修复/诊断/未知提交为 103 项通过，dev44 草稿与恢复为 23 项通过，manager 生命周期为 10 项中 2 项失败。全部使用隔离临时数据，主测试进程拒绝真实 socket 连接，连接尝试为 0；未请求上游或生成媒体。

两项失败仍为 `test_clip_import_close_removes_pending_poll_and_keeps_one_started_transaction`、`test_gif_window_close_removes_its_pending_poll_while_conversion_finishes`。失败断言把根窗口的所有 `after` 定时器都视为应随子窗关闭消失；与新增根级恢复定时器的作用域冲突需要修复验证。本次没有出现 `ttk::ThemeChanged`，不能据此认定历史警告已经解决。dev43 的 1063 项全通过是历史发行记录；本次没有执行产品全回归。

## 2. 本次梳理后的顺序调整

1. **M1 先交付能打开的安全只读页。** 首屏使用真实安全 DTO，显示实际配置路径和版本；原型截图不抵扣验收。
2. **M2 分为“保存成功”与“接入整理”两个可验收批次。** 将 W14 的最小目录读取、W19 的同文件联调提前到 M2，避免 URL/Key 保存后迟迟无法由 Codex 使用。
3. **基础未保存提醒与易用性从 M2 开始。** W17 的强退恢复、W21 的完整无障碍矩阵放 M3；保存错误定位、取消保护、单保存点从第一份可编辑表单就具备。
4. **保存、凭据轮换、备份恢复按同一事务边界设计。** 新密钥先加密形成新版本，再提交配置引用；冲突或断电保留原引用及旧版本，明确处理中间状态，禁止自动重复创建账户。
5. **dev44 仅做维护所需的缺陷处理。** 保留其 11 个文件；Web 不导入 Tk。`config/drafts.py` 目前仍绑定 manager 版本和表单，不能直接当通用 Web 草稿服务。发布前修复真实生命周期问题或做明确发行范围隔离，不能跳过失败冒充全绿。
6. **8765 的实际切换不作为配置 Web 首版前置条件。** 独立素材启动器可在隔离端口验证；当前约束下不切换、不停止现有 8765，不删除承载它的 EXE。实际迁移单独记录为未验收事项。

这些是实施次序调整，没有删掉原需求，也没有把收费实测、影片内容审核算作离线开发已完成。

## 3. M0：接手核查与开发准备

- [x] 完整阅读五份指定材料，确认 Web/Codex/素材服务边界。
- [x] 核对 F 盘工作树、已安装 dev43、未完成 dev44、11 个保护文件和配置哈希。
- [x] 核对权威配置路径、Schema 和登记数量；未解密真实凭据。
- [x] 检查 8765/8787 本机监听状态，保持已有服务。
- [x] 检查共享配置、凭据、目录、草稿服务与打包入口。
- [x] 执行 136 项离线专项并保存失败和保护记录。
- [ ] 修复两项生命周期回归：分清根级与子窗级定时器，验证子窗轮询取消、根级恢复继续、已启动事务仅执行一次；继续检查 Tk 警告。
- [ ] 确定候选发行记录和 dev44 保留方式；在候选功能通过前保持 C 盘 dev43 安装。

开发继续在当前 F 盘工作树内增量进行。测试夹具、临时目录和候选构建放 `F:/VideoCreate/_local/`；真实数据仅用于必要的只读核对。

## 4. M1：安全只读配置 Web

范围：W01–W06、W18a。每项完成后记录代码版本、测试、限制，不提前变更总台账的历史状态。

| 子项 | 具体交付 | 验收条件 |
| --- | --- | --- |
| W01 职责和界面合同 | 固定上游管理、模型目录、默认选择、检查与记录、设置五个入口；URL/Key 基础入口和可选高级维护 | 页面及 API 均无生成、任务执行、项目剪辑入口；内部 ID 不成为首次必填字段 |
| W02 工程与依赖 | Vue 3 + TypeScript + Vite；FastAPI + Uvicorn 薄服务；锁定依赖；静态资源同源托管 | 在 Python 3.9 干净环境验证兼容；CLI 不强装 Web；构建资源离线可用；运行无需 Node |
| W03 DTO 与错误 | 为摘要、上游、接入、默认、能力/价格定义白名单；统一字段错误及 409/422 语义 | 不返回 raw config、auth、secret_ref、密钥、加密字节；过滤校验异常中可能回显的请求输入 |
| W04 本机会话 | 仅 loopback；Host、Origin、CSRF、CORS、DNS rebinding、CSP、请求大小和超时；会话失效规则 | 会话秘密不进 URL、历史或公开 JS；跨站读写被拒；密钥哨兵不进响应、日志、缓存及浏览器持久存储 |
| W05 配置摘要 | 显示实际配置路径、运行版本、Schema、修订、结构计数；区分缺失/损坏/新版/只读 | 不静默新建、不降级未来 Schema、不泄露损坏原文；与 CLI 解析同一文件 |
| W06 只读主界面 | 真实上游/接入列表、搜索、类型/家族/收藏过滤、详情、空态、加载和失败反馈 | 5 家/25 接入仅从当前配置读取；目录、启用、合同、小样、内容审核分别显示 |
| W18a 开发启动 | CLI 启动、`--config`、`--port`、`--no-browser`；默认 8787；服务就绪再打开浏览器 | 校验端口和服务身份；端口冲突不打开陌生服务；启动/退出均不影响 8765 |

M1 出口：浏览器能打开真实只读目录；所有资源离线加载；首屏与 API 无秘密泄露；配置和凭据字节不变；安全测试通过。候选命令以实际实现为准，当前 `config-web` 尚不存在。

## 5. M2：URL/Key 保存与 Codex 接入闭环

**M2a：先把保存做好。** 实施顺序为 W07 → W09 的后端事务 → W08 完整表单，并在同批完成 W16、W17a、W21a。W08 的界面与验证可先开发，但在凭据事务完成前不宣称 URL/Key 保存闭环可用。

| 子项 | 具体交付 | 验收条件 |
| --- | --- | --- |
| W07 预览/提交 | 后端加载当前权威值、应用白名单 patch；来源 token、草稿指纹、预览有效期、一次提交标识；复用锁/校验/修订/备份 | 两窗口及 CLI 并发保存返回冲突；改草稿使旧预览失效；双击/重试不会重复新增；未展示字段原样保留 |
| W09 凭据事务 | DPAPI 只写录入、版本轮换、旧版本保留；配置与凭据写入之间的故障恢复 | 加密失败、配置冲突、磁盘失败、提交响应丢失均可解释恢复；旧引用不断；密钥不进草稿/日志/响应；不以遮蔽字符串覆盖旧值 |
| W08 两字段入口 | URL/Key 必填，名称取域名且可改，备注可选；自动生成稳定上游和账户 ID；增改、复制、归档 | 三家演示上游可只填 URL/Key 保存；无目录也保留已存配置；复制不复制秘密；改地址或不能确认同账户的换钥保留原实例并建新实例 |
| W16 备份与修复 | 受控备份 ID、恢复差异、来源绑定；损坏 JSON 检查、精确原文备份、有效配置恢复；未来版本只读 | 无任意路径访问；损坏原文及旧明文不能直接送到浏览器；恢复不丢后续任务身份；日志失败明确区分“保存成功、历史写入失败” |
| W17a / W21a 基础表单体验 | 字段错误、保存状态、取消保护、刷新/关闭提醒、失败保留非秘密输入、焦点定位 | 只有一个用户保存点；不承诺拦截强制退出；密钥持久恢复另行排除，需重新输入时说明原因 |

**M2b：再把接入整理和技能读取连起来。** W10a 先定义已有合同的来源与适用范围；W14a 依赖已保存的 W08/W09，**不依赖合同已经匹配**；W10b 消费已有文档和目录观察。没有 `/models` 时，W10b 可直接依据已有明确合同继续，目录不是必需条件。

| 子项 | 具体交付 | 验收条件 |
| --- | --- | --- |
| W14a 最小只读检查 | 明确点击后仅请求已选上游的目录；地址/账户绑定缓存；超时、鉴权失败、404 和不支持格式分别提示 | 不自动联网、不探测其他 URL、不发生成 POST；受控重定向不转发凭据；检查失败不回滚保存 |
| W10a/W10b 合同整理 | Codex 复用已给 XingAPI 文档及现有 adapter；维护精确远端 ID、操作、参数与来源；登记待补文档原因 | `seedance2.5-V` 大小写保留；不按家族、`/v1` 或目录名猜协议；已确认操作可候选，未确认部分仍未知；不要求先付费试错 |
| W10 高级维护 | 复用 models/upstreams/bindings/routes；基本、能力、价格、备注来源、高级协议可选维护 | 修改模型资料走同一核心校验；不丢未知扩展；声明/覆写/合同/实测分层；禁用草稿不能被选来执行 |
| W11 报价 | 展示价与预算价分开；币种、单位、组别、有效期、条件档位、最低计费/取整 | 未知不等于零；不同币种不混加；价格子表单由实体一次提交；不把报价标成实付 |
| W13 默认策略 | 图片/视频独立默认与 ask/use-default；仅使用符合条件的启用接入 | 不改已有项目或原 task；一次/项目选择不自动升为全局；空目录或无有效候选有明确提示 |
| W19a 同文件联调 | Web 保存后 CLI/Codex 立即读同一配置；Codex 整理后 Web 刷新同步；已知/未知协议均有状态 | URL/Key → 保存 → 合同整理 → 候选/未就绪原因；全部用离线夹具/假上游完成零收费闭环 |

M2 出口：三上游只填 URL/Key 可保存，已知合同能由 Codex 整理并进入候选；未知合同明确缺少什么；并发、换钥、归档、备份、修复、默认和 CLI 联调通过。接入就绪不等于授权生成或在线内容验收。

## 6. M3：管理体验、证据与恢复

| 子项 | 具体交付 | 验收条件 |
| --- | --- | --- |
| W12 筛选/比较 | 搜索、收藏、稳定排序、任务条件筛选、2–4 接入并排比较；复用 suitability/pricing | 零网络、零生成；未知条件有原因；不重排 Codex 已发出的选择菜单，不生成无样本质量排行 |
| W14b 目录导入 | 观察差异、精确 ID 多选、来源绑定、重复导入、过期观察、账户变更处理 | 只生成禁用草稿；不覆盖已有备注/协议，不删除目录中消失的型号，不自动认定型号等价 |
| W15 证据/诊断 | 逐操作展示目录/合同/小样/质量证据；匿名诊断预览后导出新文件 | 复用 allowlist；源变化需重预览；不输出账户、凭据、任务链接或原文；已有文件不覆盖 |
| W17b Web 草稿恢复 | 从服务层重新定义字段白名单、配置来源、表单版本、会话/标签页身份、过期/丢弃规则 | 不搬 Tk widget 状态；不存未提交密钥；强退后恢复非秘密草稿；配置变化禁止自动覆盖；恢复不自动提交 |
| W21 完整体验验收 | 长中文、键盘、焦点回收、读屏、100–200%缩放、窄屏、离线与错误重试 | 真实浏览器完成三上游配置任务；自动化结果与用户体验验收分别记录 |

## 7. M4：分发、兼容与发行

| 子项 | 具体交付 | 验收条件 |
| --- | --- | --- |
| W18b 正式启动与关闭 | 双击脚本、依赖诊断、重复实例识别；区分版本和规范化配置路径；浏览器关闭与服务生命周期清楚 | 只复用同产品/版本/配置的实例；退出配置服务不停止素材服务或 Codex 任务；启动日志无秘密 |
| W19b 完整兼容矩阵 | 四种选择输入、别名/同名、过期编号、多菜单/多项目、图片视频独立；改默认/显示名/归档/换钥后的原任务恢复 | 原快照 URL/账户/凭据版本/adapter/task ID 保持；已知任务只查/下载，未知提交不自动再创建；统计假服务器请求数 |
| W20 独立素材启动器 | 在隔离端口验证 Python 独立启动、实例识别、发布文件字节、重启恢复；记录退役条件 | 配置 Web 与素材服务独立；当前不停止/切换 8765；原 EXE 保留；实际生产切换继续标记待验收 |
| W22 构建与发行 | wheel/技能资源包含前端静态产物；可选 Web 依赖冻结；仓库外、干净环境、离线配置、升级回滚；同步版本/文档/模块目录 | 不含真实配置/凭据/项目；必要专项与完整回归通过；新产物独立记录版本/哈希/安装证据；旧 dev44 失败有真实处理结果 |

配置 Web 的首版验收覆盖 W01–W19、W21 和 W22 的实际范围；W20 可先完成独立启动器与互不干扰验证，**生产 8765 切换不计作已经完成，也不强行加入当前部署动作**。以后允许切换时，核对公网实例、已发布文件哈希、恢复和回滚，再退役旧启动方式。

## 8. M5：保留的完整产品后续工作

这些需求继续由 Codex + 技能 + CLI 与共享核心实现。原 73 项逐条需求、现有实现、剩余、验收和代码入口完整保留在下节；其中 H05、I05 仍待开发。

| 组 | 编号与数量 | 后续重点 |
| --- | --- | --- |
| A 配置与合同 | A01–A10，10 项 | 模块状态/证据同步、复杂 Schema 迁移、未知字段、真实边界、声明/合同/实测分离、报价及凭据恢复 |
| B 选型 | B01–B07，7 项 | 明确组合/只给上游/只给型号/均未给，稳定编号、作用范围、排除原因、全部创建入口一致门禁 |
| C 配置界面 | C01–C07，7 项 | 由 W01–W22 落地，保持轻量配置边界；Windows 分发与用户体验 |
| D 协议 | D01–D08，8 项 | Seedance V/S/933/C/Q、Wan、Grok 按精确 ID/操作核实；多媒体角色/顺序/组合；参数消费、查询/下载/幂等/取消按合同实现 |
| E 运行恢复费用 | E01–E06，6 项 | unknown 对账、多进程共享配额、退避、旧 task 恢复、退款/账单、可重建状态索引 |
| F 创作流程 | F01–F09，9 项 | 阶段/分支、主题大纲剧本、授权内推进、五层映射、局部失效、继续制作和交付清单 |
| G 资产系列 | G01–G06，6 项 | 跨项目版本化资产、角色对照、道具条件、主题/世界/风格包、互动库、连载与独立集 |
| H 声音剪辑审核 | H01–H08，8 项 | 声音路线、声线/口型、实际字幕、FFmpeg、可选速度曲线/补帧/跟踪、连续播放听审、局部修复与指标 |
| I 专项 | I01–I05，5 项 | 科普新闻、Muse 网页执行、ChatCut/剪映真实导入、图片/GIF 合同、可比基准数据集 |
| J 验证交付 | J01–J07，7 项 | 配置/选择/协议/故障/全流程矩阵、后续逐操作真实验收、发行与数据保护 |

当前开发不开展收费生成测试，不重新生成已有 30 秒样片。既有样片保持 `review_pending`；后续动作、对白、听审、口型和理解反馈可优先复用现有素材逐项补验，不改变未审核结论。真实新生成与实际账单核验仍列待办，不能用离线通过抵扣。

## 9. 下一批可直接执行的任务

1. 先修复两项生命周期回归所暴露的作用域问题，保留根级恢复机制与用户未提交代码。
2. 冻结 W03 字段白名单/错误合同和 W04 会话引导；建立 W02 前后端工程和兼容依赖锁。
3. 接上 W05/W06/W18a，交付可打开、真实只读、与 CLI 同路径的 M1 页面。
4. 以 W07/W09/W08 做第一个 URL/Key 保存闭环，同时接入备份、冲突和基本表单保护。
5. 提前接上 W14a/W10 的目录与合同整理，完成默认、价格、修复及 W19a 同配置读取验收。

每批报告实际修改、验收、失败及未覆盖范围；本地测试以模拟上游为主，记录实际请求计数。真实配置、历史路径、原 task、素材和用户凭据继续保护。所有新代码和开发产物只写 F 盘；C 盘稳定安装在候选验证前保持现状。

## 10. 原 73 项完整台账（原始需求保留）

以下保留交接时的原始要求、dev43 实现状态、剩余、验收条件与代码/测试索引。执行批次以上文 v2 为准；这些历史状态不因本次专项测试通过而自动升级。


## A — 配置、元数据、能力合同

### A01 · P0 · 部分实现

原始需求：建立机器可读模块目录和统一状态口径；每模块有真实入口、限制、实测范围、测试/文档证据和对应待办，旧清单逐项映射而不重复计数。

**已有实现：** 已有机器模块目录、modules list/roadmap 和真实入口/限制字段；dev43 保留 73 项状态。

**剩余工作：** 按本轮 Web 边界更新模块说明，关联可复验的离线/在线证据，持续同步发行状态。

**验收条件：** 每个模块可查入口、限制、版本及待办；未实施 Web 不计成已交付。

**入口归属：** Web 配置 + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/assets/module-catalog.json](../videocreate/assets/module-catalog.json)。

已有测试索引：[test_catalog_observations.py](../tests/test_catalog_observations.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### A02 · P0 · 离线实现已落地

原始需求：设计配置 Schema v4、草稿/启用语义及扩展策略；模型、上游、binding、route 继续分层；不完整草稿可保存但不可执行。

**已有实现：** Schema 4 和 v3 兼容已落地；model/upstream/binding/route 分层，草稿禁用。

**剩余工作：** 保持核心实现，设计浏览器 DTO 映射及未来字段兼容，不再另起配置格式。

**验收条件：** 不完整草稿可保存且不会进入创建候选；CLI/Web 对同一输入给出一致错误。

**入口归属：** Web 配置 + 共享核心。Web 子项：W05。

代码/证据：[videocreate/src/videocreate/config/schema_v4.py](../videocreate/src/videocreate/config/schema_v4.py)。

已有测试索引：[test_catalog_observations.py](../tests/test_catalog_observations.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### A03 · P0 · 部分实现

原始需求：model/upstream/binding 增加中文展示名、notes、tags、文档链接、收藏/排序和来源时间；备注不改变任务输入哈希，不升级能力。

**已有实现：** 展示名、备注、标签、收藏、排序和声明已有核心及旧管理器入口。

**剩余工作：** 补 Web 普通/高级表单、来源日期、长文本体验；审核展示变更不影响生成内容哈希。

**验收条件：** 修改备注/价格说明不重生视频；刷新后字段保持，供应商文字仅作为文本。

**入口归属：** Web 配置 + 共享核心。Web 子项：W03, W10。

代码/证据：[videocreate/src/videocreate/catalog/presentation.py](../videocreate/src/videocreate/catalog/presentation.py)。

已有测试索引：[test_catalog_observations.py](../tests/test_catalog_observations.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### A04 · P0 · 部分实现

原始需求：以操作为单位定义提示词计数、时长、分辨率、画幅、多媒体数量/大小/时长与组合限制；未知不是无限，空枚举不是“全支持”。

**已有实现：** 字符计数、时长/画幅/分辨率及分类型参考数量、字节、时长、角色/组合检查已有实现。

**剩余工作：** 补模型真实边界、通用条件规则及 Web 结构化编辑；未知值表达一致。

**验收条件：** 边界前后和混合输入整批预检；空枚举/未知不能误当全部支持。

**入口归属：** Web 配置 + 共享核心。Web 子项：W10。

代码/证据：[videocreate/src/videocreate/catalog/media_constraints.py](../videocreate/src/videocreate/catalog/media_constraints.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_provider_management.py](../tests/test_provider_management.py)；[test_v3_config.py](../tests/test_v3_config.py)。

### A05 · P0 · 部分实现

原始需求：分离供应商声明、执行合同、用户覆写、逐能力证据；拆分协议/能力、价格、展示与请求指纹，修改标价不误使内容审核过期。

**已有实现：** 声明、执行范围、覆写与逐操作证据已有分层；存在分用途指纹。

**剩余工作：** 审计所有入口和模型变更的证据范围；Web 分层呈现，限制失效只影响相关证据。

**验收条件：** 文生视频通过不推导参考通过；备注/标价变化不使无关内容审核过期。

**入口归属：** Web 配置 + 共享核心。Web 子项：W03, W10, W15。

代码/证据：[videocreate/src/videocreate/catalog/evidence.py](../videocreate/src/videocreate/catalog/evidence.py)。

已有测试索引：[test_catalog_observations.py](../tests/test_catalog_observations.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### A06 · P0 · 部分实现

原始需求：版本化计价：按次/秒/张、条件档位、组别、币种、取整/最低计费和有效期；估算与实付分开，未知报价不可满足硬金额上限。

**已有实现：** 按次/秒/张、币种、报价状态及条件档位已有预算/比较核心。

**剩余工作：** 核实组别、最低计费、取整、有效期和退款的真实合同；完善 Web 价格编辑。

**验收条件：** 未知报价不满足硬金额限额；币种不混加；页面标价与实付分别展示。

**入口归属：** Web 配置 + 共享核心。Web 子项：W11。

代码/证据：[videocreate/src/videocreate/catalog/pricing.py](../videocreate/src/videocreate/catalog/pricing.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_provider_management.py](../tests/test_provider_management.py)；[test_v3_config.py](../tests/test_v3_config.py)。

### A07 · P0 · 离线实现已落地

原始需求：增加非秘密账户身份、凭据版本与凭据录入服务；同账户轮换、切账户、改 URL 区分处理；活动任务可找到原账户和允许使用凭据的地址。

**已有实现：** 版本化 DPAPI 凭据和非秘密账户 ID 已实现；旧版本保留供恢复。

**剩余工作：** 新增只写 HTTP 凭据边界和跨文件失败处理，复用既有加密服务。

**验收条件：** 换钥后旧任务可恢复；响应/草稿/日志无密钥；换账户/域名须保留原实例。

**入口归属：** Web 配置 + 共享核心。Web 子项：W04, W08, W09。

代码/证据：[videocreate/src/videocreate/config/secrets.py](../videocreate/src/videocreate/config/secrets.py)。

已有测试索引：[test_catalog_observations.py](../tests/test_catalog_observations.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### A08 · P0 · 离线实现已落地

原始需求：配置读改写事务、修订号、并发冲突、备份恢复、引用检查、归档；不允许删除仍被未完成任务引用的上游或破坏其凭据恢复。

**已有实现：** 核心有修订/token、锁、校验、备份、原子替换、历史、归档与恢复身份保护。

**剩余工作：** 接入 Web 预览/提交与并发冲突；验证多文件中断和历史写失败提示。

**验收条件：** 两窗口不会静默覆盖；原实例和旧凭据可恢复；错误时文件保持可读。

**入口归属：** Web 配置 + 共享核心。Web 子项：W07, W08, W16。

代码/证据：[videocreate/src/videocreate/config/management.py](../videocreate/src/videocreate/config/management.py)。

已有测试索引：[test_catalog_observations.py](../tests/test_catalog_observations.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### A09 · P0 · 部分实现

原始需求：v3→v4 dry-run、变更差异、应用及回滚；旧默认/自定义字段按明确策略保留，未知新版只读而不覆盖；回滚不丢新任务快照。

**已有实现：** v3→v4 预演/应用和保留后续身份的恢复已有；新版配置只读。

**剩余工作：** 补复杂自定义字段迁移矩阵、Web 差异与回滚呈现；不按旧草图新造 Schema。

**验收条件：** 升级/恢复保留旧默认、用户扩展和新任务身份；未知新版禁止写回。

**入口归属：** Web 配置 + 共享核心。Web 子项：W05, W16。

代码/证据：[videocreate/src/videocreate/config/management.py](../videocreate/src/videocreate/config/management.py)。

已有测试索引：[test_catalog_observations.py](../tests/test_catalog_observations.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### A10 · P1 · 部分实现

原始需求：导入 /models、手工录入与来源备注；目录新增/移除仅提示差异，不自动启用、删本地备注或认定能力；同名远端别名不自动合并。

**已有实现：** 按地址/账户保存目录观察，新增/消失提示和来源绑定禁用草稿导入已实现。

**剩余工作：** 迁移到 Web，补来源过期/身份变化/重复导入交互和受控只读网络检查。

**验收条件：** 导入不覆盖备注、不启用、不删除旧接入；目录名不能自动证明合同。

**入口归属：** Web 配置 + 共享核心。Web 子项：W14。

代码/证据：[videocreate/src/videocreate/catalog/observations.py](../videocreate/src/videocreate/catalog/observations.py)。

已有测试索引：[test_catalog_observations.py](../tests/test_catalog_observations.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；[test_provider_management.py](../tests/test_provider_management.py)。

## B — 明确选型与编号交互

### B01 · P0 · 部分实现

原始需求：双向目录：上游→型号、家族→型号→上游；可按任务、操作、时长、画幅、参考数量筛选，输出人读表格及机器结果。

**已有实现：** 双向目录、媒体/家族/收藏及任务参数/参考数量过滤、排除原因已有。

**剩余工作：** 补 Web 目录/筛选/排序和缺失条件提示；完整预检保持在 Codex。

**验收条件：** 按上游或家族都能定位 binding；筛选匹配不标成可立即生成。

**入口归属：** Codex 选择；Web 目录/全局默认。Web 子项：W06, W12。

代码/证据：[videocreate/src/videocreate/catalog/suitability.py](../videocreate/src/videocreate/catalog/suitability.py)。

已有测试索引：[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### B02 · P0 · 部分实现

原始需求：解析明确组合、只给上游、只给型号、均未给四类输入；唯一路线直接使用，歧义时只询问缺失选择；保留本会话已有选择。

**已有实现：** 核心能按模型/上游约束提供选择，技能规定唯一组合使用、歧义先询问。

**剩余工作：** 审计全部自然语言别名和四种输入；在 Codex 合并缺失的图片/视频选择。

**验收条件：** 明确组合不重复问；缺项只问必要项；不偷偷选择相似型号。

**入口归属：** Codex 选择；Web 目录/全局默认。Web 子项：W19。

代码/证据：[videocreate/src/videocreate/selection.py](../videocreate/src/videocreate/selection.py)。

已有测试索引：[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### B03 · P0 · 离线实现已落地

原始需求：菜单序号绑定 selection_id、配置修订、候选稳定 ID 和任务参数；处理过期、重排、非法序号、跨项目回复与并发菜单。

**已有实现：** selection_id、配置/候选绑定及序号校验已有离线实现。

**剩余工作：** 补多菜单、跨项目和配置并发的端到端回归；Web 不取代对话选择。

**验收条件：** 回复序号落到原菜单稳定 ID；过期/非法/跨项目回复零创建。

**入口归属：** Codex 选择；Web 目录/全局默认。Web 子项：W13, W19。

代码/证据：[videocreate/src/videocreate/selection.py](../videocreate/src/videocreate/selection.py)。

已有测试索引：[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### B04 · P0 · 离线实现已落地

原始需求：本次/项目/全局选择范围和来源；恢复旧任务优先原快照；仅用户明确要求才把一次选择保存为以后默认。

**已有实现：** 一次/项目/全局范围和已有任务快照优先已有实现。

**剩余工作：** 接入 Web 全局默认设置；审计一次选择从不自动写成全局。

**验收条件：** 图片/视频独立；已有项目/任务不被 Web 全局更改迁移。

**入口归属：** Codex 选择；Web 目录/全局默认。Web 子项：W13, W19。

代码/证据：[videocreate/src/videocreate/selection.py](../videocreate/src/videocreate/selection.py)。

已有测试索引：[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### B05 · P0 · 部分实现

原始需求：统一 route explain 与费用预演：列最终选择、参数消费、排除理由、来源、报价状态；选定路线就绪检查不被无关坏上游阻断。

**已有实现：** route 解释、参数/报价预演、选中范围就绪与对比已有。

**剩余工作：** 补每 adapter 消费报告及未知条件说明；Web 展示本地比较，完整预检留在 CLI。

**验收条件：** 无关坏上游不阻断选定路线；排除原因和报价单位可追溯。

**入口归属：** Codex 选择；Web 目录/全局默认。Web 子项：W12。

代码/证据：[videocreate/src/videocreate/catalog/bindings.py](../videocreate/src/videocreate/catalog/bindings.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_provider_management.py](../tests/test_provider_management.py)；[test_v3_config.py](../tests/test_v3_config.py)。

### B06 · P0 · 部分实现

原始需求：切换前显示已提交、未知、已完成、未提交镜头；只调整指定的新任务；默认固定，备用需明确策略且只在确认未受理时执行。

**已有实现：** 切换影响预演、固定任务和明确备用策略已有基础。

**剩余工作：** 补全状态组合及多项目影响回归；Codex 解释切换范围。

**验收条件：** 仅指定未提交任务更改；已提交/未知始终使用原快照。

**入口归属：** Codex 选择；Web 目录/全局默认。Web 子项：W19。

代码/证据：[videocreate/src/videocreate/selection.py](../videocreate/src/videocreate/selection.py)。

已有测试索引：[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_provider_management.py](../tests/test_provider_management.py)。

### B07 · P0 · 部分实现

原始需求：在图片/视频所有创建入口统一检查选择；非交互缺项返回 selection_required 且零创建，离线策划不被该选择挡住。

**已有实现：** 主 v3 图片/视频执行入口有选择门禁，离线策划可独立进行。

**剩余工作：** 审计保留的 legacy/动画/批量入口，确保所有创建路径同一门禁。

**验收条件：** 无头缺项返回 selection_required 且零 POST；不因无关图片配置阻断本地剪辑。

**入口归属：** Codex 选择；Web 目录/全局默认。Web 子项：W13, W19。

代码/证据：[videocreate/src/videocreate/runtime/jobs.py](../videocreate/src/videocreate/runtime/jobs.py)。

已有测试索引：[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_provider_management.py](../tests/test_provider_management.py)。

## C — 本机 Web 配置界面（替代旧 EXE 主界面目标）

### C01 · P0 · 离线实现已落地

原始需求：将配置/选型服务与 CLI 展示分离，供界面直接调用；确定轻量桌面技术方案，不从界面拼接任意 shell 命令或复制执行逻辑。

**已有实现：** 核心服务与 CLI 已分离；旧 Tk 直接复用核心，离线实现状态保留。

**剩余工作：** 将主界面改为本机 Web 薄 API/DTO/前端；停扩 Tk，不把旧 C01 通过等同 Web 完成。

**验收条件：** HTTP 直接调用核心；无 shell 拼接、无第二套预算/路由逻辑。

**入口归属：** Web 配置 + 共享核心。Web 子项：W01, W02, W03, W04。

代码/证据：[videocreate/src/videocreate/config/management.py](../videocreate/src/videocreate/config/management.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_config_repair.py](../tests/test_config_repair.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；其余见机器清单。

### C02 · P0 · 部分实现

原始需求：上游增改/复制/归档、凭据遮蔽录入、型号增改与启用；3 个不同上游、多个家族可以纯表单配置。

**已有实现：** 旧表单可管理上游/型号/密钥/启用，核心增改归档已在用。

**剩余工作：** 实现 URL/Key 两字段 Web 入口，内部 ID 自动生成，名称/备注可选；受控复制、归档、只写密钥和模型高级维护。

**验收条件：** 三家上游仅 URL/Key 即可保存，不要求用户写内部型号/binding/route；复制不泄露/复用不该复用的凭据。

**入口归属：** Web 配置 + 共享核心。Web 子项：W01, W06, W08, W09, W21。

代码/证据：[videocreate/src/videocreate/config/management.py](../videocreate/src/videocreate/config/management.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_config_repair.py](../tests/test_config_repair.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；其余见机器清单。

### C03 · P0 · 部分实现

原始需求：能力与备注表单、价格页、状态徽标；展示“声明支持但 adapter 未实现”，动态约束与核心校验一致。

**已有实现：** 旧能力/价格/备注表单及徽标已有，校验走共享核心。

**剩余工作：** 落实原型五页签、声明/执行/实测分层，基本与高级字段分离。

**验收条件：** 字段错误定位清楚；供应商声明不能绕过 adapter；取消保留原文件。

**入口归属：** Web 配置 + 共享核心。Web 子项：W01, W10, W11, W21。

代码/证据：[videocreate/src/videocreate/catalog/presentation.py](../videocreate/src/videocreate/catalog/presentation.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_config_repair.py](../tests/test_config_repair.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；其余见机器清单。

### C04 · P1 · 部分实现

原始需求：搜索、收藏、排序、并排比较和适用场景；单独设置图片/视频默认，显示费用单位与是否已确认。

**已有实现：** 旧目录搜索、收藏、比较、默认及任务筛选有实现。

**剩余工作：** 在 Web 重做易用的表格/详情、比较和图片/视频默认策略；补键盘与缩放。

**验收条件：** 2–4 接入比较不联网/不生成；跨币种和未知价清楚；默认独立保存。

**入口归属：** Web 配置 + 共享核心。Web 子项：W01, W06, W11, W12, W13, W21。

代码/证据：[videocreate/src/videocreate/catalog/pricing.py](../videocreate/src/videocreate/catalog/pricing.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_config_repair.py](../tests/test_config_repair.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；其余见机器清单。

### C05 · P0 · 部分实现

原始需求：保存前校验、差异预览、未保存提醒、冲突处理、修复无效 JSON 和恢复备份；显示实际读取路径与配置版本。

**已有实现：** 旧 UI 有未保存提醒、冲突、JSON 修复、备份；dev44 强退恢复尚未完成。

**剩余工作：** Web 使用单一保存、来源 token、差异/冲突/修复；重新设计安全草稿，不延续 Tk widget 状态。

**验收条件：** 关闭/刷新/强退均无静默覆盖；未提交密钥不进草稿；损坏/新版配置受控。

**入口归属：** Web 配置 + 共享核心。Web 子项：W05, W07, W16, W17, W21。

代码/证据：[videocreate/src/videocreate/config/repair.py](../videocreate/src/videocreate/config/repair.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_config_repair.py](../tests/test_config_repair.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；其余见机器清单。

### C06 · P1 · 部分实现

原始需求：只读连接/目录检查、证据详情、脱敏诊断导出；检查按钮不会生成媒体；生成试测有独立入口与范围。

**已有实现：** 目录观察、逐操作证据、离线 allowlist 诊断预览/导出已有。

**剩余工作：** 增加 Web 安全检查/记录页及受控导出；生成试测统一由 Codex 执行。

**验收条件：** 所有 Web 按钮零媒体创建；默认诊断匿名，源变化重新预览，文件不覆盖。

**入口归属：** Web 配置 + 共享核心。Web 子项：W14, W15。

代码/证据：[videocreate/src/videocreate/diagnostics.py](../videocreate/src/videocreate/diagnostics.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_config_repair.py](../tests/test_config_repair.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；其余见机器清单。

### C07 · P1 · 部分实现

原始需求：Windows 分发、干净机器启动、离线配置、升级与卸载；保留用户数据；明确依赖、签名/校验和及真实包体，不承诺未经测量的“小体积”。

**已有实现：** 历史 wheel/便携 EXE 已在本机验收安装，干净机器未验收。

**剩余工作：** 改为 Python+本机 Web 启动脚本和静态资源分发；迁移独立素材服务启动；补卸载/升级文档。

**验收条件：** 无需 Node 或 EXE UI 即可离线配置；依赖/端口明确，升级保留配置/凭据/8765。

**入口归属：** Web 配置 + 共享核心。Web 子项：W02, W18, W20, W22。

代码/证据：[install.ps1](../install.ps1)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)；[test_config_repair.py](../tests/test_config_repair.py)；[test_manager_catalog_observations.py](../tests/test_manager_catalog_observations.py)；其余见机器清单。

## D — 星光、Seedance、Wan 与多媒体协议

### D01 · P0 · 部分实现

原始需求：取得星光实际 API 文档/脱敏合同样例，核对 create/query/download/upload、ID、错误语义和账户报价；页面 OPENAI 标签不作为协议证据。

**已有实现：** 已取得用户提供的统一视频 create/query/content/HTTPS 参考文档并实现版本化合同。

**剩余工作：** 继续核对各型号操作范围、报价、错误、上传差异；不再把已提供基础文档列为缺失。

**验收条件：** 每型号精确 ID 和各操作合同有来源；标价/账单差异有记录。

**入口归属：** Codex / CLI + 共享核心。Web 子项：W10, W14。

代码/证据：[videocreate/references/xingapi-contract.md](../videocreate/references/xingapi-contract.md)。

已有测试索引：[test_pricing_discovery.py](../tests/test_pricing_discovery.py)；[test_typed_media_generation.py](../tests/test_typed_media_generation.py)；[test_xingapi.py](../tests/test_xingapi.py)。

### D02 · P0 · 部分实现

原始需求：将 Seedance2.5-V 做成独立 binding；协议一致则复用 adapter，不一致则新增版本；5–30 秒、实际 ID、720P、音频与按次报价各自验收。

**已有实现：** seedance2.5-V 独立接入已有真实 30 秒有声文生视频样片，保留原任务。

**剩余工作：** 补参考输入、原生音频开关、边界及实付核对；实际听审/动作/口型尚未全过。

**验收条件：** 分别记录文生/图参/视参/音参结果；不重生现有样片以充当 UI 测试。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/adapters/xingapi.py](../videocreate/src/videocreate/adapters/xingapi.py)。

已有测试索引：[test_pricing_discovery.py](../tests/test_pricing_discovery.py)；[test_typed_media_generation.py](../tests/test_typed_media_generation.py)；[test_xingapi.py](../tests/test_xingapi.py)。

### D03 · P1 · 部分实现

原始需求：分别登记并验证 Seedance2.5-S 与 933/C/Q；不继承 V 的计价或参数；仅开放已核对的操作组合。

**已有实现：** S/933/C/Q 等型号可独立登记，统一 adapter 有离线夹具。

**剩余工作：** 逐精确 ID/账户核实合同和价格，再按授权做各操作小样，不继承 V 的通过记录。

**验收条件：** 每型号仅开放已核实组合；超时/失败恢复不重复 POST。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/adapters/xingapi.py](../videocreate/src/videocreate/adapters/xingapi.py)。

已有测试索引：[test_pricing_discovery.py](../tests/test_pricing_discovery.py)；[test_typed_media_generation.py](../tests/test_typed_media_generation.py)；[test_xingapi.py](../tests/test_xingapi.py)。

### D04 · P1 · 部分实现

原始需求：Wan 独立家族/型号/绑定，核验 Wan3.0-Prime-720P 合同；同协议复用，新协议单独 adapter；与其他上游 Wan 的等价性另记。

**已有实现：** Wan 家族和独立 binding 的配置/统一协议基础已有。

**剩余工作：** 逐 Wan 型号核实参数、参考语义、报价与跨站等价性，完成授权小样。

**验收条件：** Wan 证据与 Seedance/Grok 独立，不因同 /v1 推断兼容。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/adapters/xingapi.py](../videocreate/src/videocreate/adapters/xingapi.py)。

已有测试索引：[test_pricing_discovery.py](../tests/test_pricing_discovery.py)；[test_typed_media_generation.py](../tests/test_typed_media_generation.py)；[test_xingapi.py](../tests/test_xingapi.py)。

### D05 · P0 · 部分实现

原始需求：参考输入统一类型、角色和时间区间；扩展项目校验、编译、快照与审核；旧 opening-frame 图片行为保持兼容。

**已有实现：** 参考按图片/视频/音频、角色与顺序贯穿校验/编译/快照；可派生时间切片。

**剩余工作：** 补广泛真实语义、last-frame/特定模型角色合同；切片不是原生时间/末帧字段。

**验收条件：** MP4/WAV 不塞图片字段；同类顺序和哈希保持，旧首帧行为可恢复。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/media_references.py](../videocreate/src/videocreate/media_references.py)。

已有测试索引：[test_media_hosting.py](../tests/test_media_hosting.py)；[test_reference_analysis.py](../tests/test_reference_analysis.py)；[test_reference_slices.py](../tests/test_reference_slices.py)；[test_typed_media_generation.py](../tests/test_typed_media_generation.py)。

### D06 · P0 · 部分实现

原始需求：按实需实现文件/URL/asset_id 上传、失效重传、来源哈希、过期和恢复；禁止静默丢视频/音频或把参考视频降为首帧。

**已有实现：** 已有 8765 本机素材服务、HTTPS 隧道、发布/校验/撤销与账户范围传输记录。

**剩余工作：** 补运行生命周期、过期/失效恢复与服务独立启动；S3/COS/OSS 暂非当前依赖，asset_id 上传按实际合同另做。

**验收条件：** 公网文件字节一致且整个生成期间可读；只发布明确文件，下载失效不重生视频。

**入口归属：** Codex / CLI + 共享核心。Web 子项：W20。

代码/证据：[videocreate/src/videocreate/media_server.py](../videocreate/src/videocreate/media_server.py)。

已有测试索引：[test_media_hosting.py](../tests/test_media_hosting.py)；[test_pricing_discovery.py](../tests/test_pricing_discovery.py)；[test_reference_analysis.py](../tests/test_reference_analysis.py)；[test_reference_slices.py](../tests/test_reference_slices.py)；其余见机器清单。

### D07 · P0 · 部分实现

原始需求：适配字符/字节计数、混合参考和条件参数，实际 payload 字段有消费报告；整批错误在任何创建/预算预留之前发现。

**已有实现：** 按字符/字节与 typed HTTPS 数组、数量/大小/时长/组合的批量预检已有。

**剩余工作：** 补所有 adapter 的参数消费证明及各模型边界；不得仅登记能力就声称 payload 可发送。

**验收条件：** 整批参数错误在任何创建/预留前发现；无静默丢参考或互相冲突字段。

**入口归属：** Codex / CLI + 共享核心。Web 子项：W10。

代码/证据：[videocreate/src/videocreate/adapters/xingapi_references.py](../videocreate/src/videocreate/adapters/xingapi_references.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_media_hosting.py](../tests/test_media_hosting.py)；[test_provider_management.py](../tests/test_provider_management.py)；[test_reference_analysis.py](../tests/test_reference_analysis.py)；其余见机器清单。

### D08 · P1 · 部分实现

原始需求：按合同补查询、下载、异步/SSE 及可选 cancel/idempotency；幂等和取消必须由真实服务支持，不能本地假实现；型号硬编码迁入版本化限制。

**已有实现：** 异步创建一次、保留完整 ID、同账户轮询、下载及跨域认证保护已有。

**剩余工作：** 按真实服务补 SSE、asset_id、原生 cancel/idempotency，完善 Retry-After/下载有效性。

**验收条件：** 502/空响应只重查原任务；下载非媒体不落为 MP4；无文档不伪造取消/幂等。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/adapters/video.py](../videocreate/src/videocreate/adapters/video.py)。

已有测试索引：[test_pricing_discovery.py](../tests/test_pricing_discovery.py)；[test_typed_media_generation.py](../tests/test_typed_media_generation.py)；[test_xingapi.py](../tests/test_xingapi.py)。

## E — 运行、恢复与费用

### E01 · P0 · 离线实现已落地

原始需求：保留现有 unknown 保护并统一失败分类；超时/5xx/仅 trace ID 不自动重发；内容失败不得触发无痕换站。

**已有实现：** unknown 分类和冻结、已知任务恢复、明确拒绝才可备用等已有离线验证。

**剩余工作：** 审计每创建入口和崩溃窗口；继续保留对账证据要求。

**验收条件：** 超时/5xx/只有 trace ID 零自动重建；内容失败不偷偷换上游。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/runtime/failures.py](../videocreate/src/videocreate/runtime/failures.py)。

已有测试索引：[test_generation_actions.py](../tests/test_generation_actions.py)；[test_manager_task_execution.py](../tests/test_manager_task_execution.py)；[test_provider_management.py](../tests/test_provider_management.py)；[test_runtime_quotas.py](../tests/test_runtime_quotas.py)；其余见机器清单。

### E02 · P1 · 部分实现

原始需求：区分共享账户/容量组的提交并发、远端在途、RPM、轮询与下载配额；进程重启和多个 binding 不能绕过限制。

**已有实现：** 本机注册 v3 项目的远端在途及 create/poll/download RPM 已持久化，共享组取最严限制。

**剩余工作：** 补并发进程/重启压力及旧项目注册体验；明确不覆盖其他机器/外部客户端。

**验收条件：** 多个 binding 共用额度不能绕过；未知提交占位不自动过期。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/runtime/quotas.py](../videocreate/src/videocreate/runtime/quotas.py)。

已有测试索引：[test_generation_actions.py](../tests/test_generation_actions.py)；[test_manager_task_execution.py](../tests/test_manager_task_execution.py)；[test_provider_management.py](../tests/test_provider_management.py)；[test_runtime_quotas.py](../tests/test_runtime_quotas.py)；其余见机器清单。

### E03 · P1 · 部分实现

原始需求：按故障范围的冷却、Retry-After、退避/抖动和进度；不把一个型号失败等同全站失败，不通过付费探针自动恢复健康。

**已有实现：** 已有局部健康/冷却和故障范围处理。

**剩余工作：** 完善退避、抖动、Retry-After、缺省响应与可读进度，按具体上游合同验收。

**验收条件：** 一个型号失败不冻结全站；不以付费探针自动恢复健康。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/runtime/health.py](../videocreate/src/videocreate/runtime/health.py)。

已有测试索引：[test_generation_actions.py](../tests/test_generation_actions.py)；[test_manager_task_execution.py](../tests/test_manager_task_execution.py)；[test_provider_management.py](../tests/test_provider_management.py)；[test_runtime_quotas.py](../tests/test_runtime_quotas.py)；其余见机器清单。

### E04 · P0 · 离线实现已落地

原始需求：验证改默认、改显示名、凭据同账户轮换、旧上游归档后仍恢复原任务；切账户/改域名需要保留原实例，不能误用新凭据。

**已有实现：** 快照固定 URL/账户/adapter 与凭据版本，改默认/归档后恢复已有离线覆盖。

**剩余工作：** Web 保存/轮换/归档回归沿用这些不变量，审计原账户密钥轮换。

**验收条件：** 原 task 只 GET/下载，禁止被新默认或新账户改写。

**入口归属：** Codex / CLI + 共享核心。Web 子项：W08, W09, W19, W20。

代码/证据：[videocreate/src/videocreate/runtime/state.py](../videocreate/src/videocreate/runtime/state.py)。

已有测试索引：[test_generation_actions.py](../tests/test_generation_actions.py)；[test_manager_task_execution.py](../tests/test_manager_task_execution.py)；[test_provider_management.py](../tests/test_provider_management.py)；[test_runtime_quotas.py](../tests/test_runtime_quotas.py)；其余见机器清单。

### E05 · P0 · 部分实现

原始需求：新价格结构接入原预留/结算账本；失败收费、退款、未知、跨币种分别显示；生成秒数、保留秒数、已审核可用秒数分开。

**已有实现：** 预算预留/结算、未知与多币种以及生成/保留秒数指标已有。

**剩余工作：** 真实失败收费/退款/结算核对，补复杂计费规则和账单导入范围。

**验收条件：** 候选/重做分别记账，未知实付不当零，保留 8 秒不按 8 秒估算 30 秒生成费。

**入口归属：** Codex / CLI + 共享核心。Web 子项：W11。

代码/证据：[videocreate/src/videocreate/runtime/budget.py](../videocreate/src/videocreate/runtime/budget.py)。

已有测试索引：[test_catalog_presentation.py](../tests/test_catalog_presentation.py)；[test_generation_actions.py](../tests/test_generation_actions.py)；[test_manager_task_execution.py](../tests/test_manager_task_execution.py)；[test_provider_management.py](../tests/test_provider_management.py)；其余见机器清单。

### E06 · P1 · 部分实现

原始需求：可重建的项目/任务索引与只读任务面板；显示队列、未知提交、候选、审核和费用；不复制一份会与 state.json 漂移的运行状态。

**已有实现：** 状态从 state/jobs/review 派生，已有本机项目注册和旧任务面板。

**剩余工作：** 完善可重建索引与跨项目状态查询，入口留 Codex/CLI；不开发新的 Web 任务中心。

**验收条件：** 删缓存可重建且账本不漂移；显示原任务/候选/未知与成本来源。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/production.py](../videocreate/src/videocreate/production.py)。

已有测试索引：[test_generation_actions.py](../tests/test_generation_actions.py)；[test_manager_task_execution.py](../tests/test_manager_task_execution.py)；[test_provider_management.py](../tests/test_provider_management.py)；[test_runtime_quotas.py](../tests/test_runtime_quotas.py)；其余见机器清单。

## F — 制作步骤与创作产物

### F01 · P0 · 部分实现

原始需求：统一阶段索引、状态、输入输出版本、阻塞原因和下一步；阶段文件引用现有 job/review，不平行维护任务真相。

**已有实现：** production status/next、阶段输入输出/阻塞与检查点已有。

**剩余工作：** 补所有分支和依赖的统一解释、缺失工具提示，留 Codex 工作流。

**验收条件：** 继续同项目定位当前阶段，不从头重生；状态以现有计划/任务/审核为准。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/production.py](../videocreate/src/videocreate/production.py)。

已有测试索引：[test_authoring.py](../tests/test_authoring.py)；[test_edit_only_production.py](../tests/test_edit_only_production.py)；[test_generation_authoring.py](../tests/test_generation_authoring.py)；[test_image_production.py](../tests/test_image_production.py)；其余见机器清单。

### F02 · P1 · 离线实现已落地

原始需求：主题/受众/目标/规格的引导采集与大纲阅读稿；足够信息可继续，缺失偏好只询问影响创作的部分。

**已有实现：** brief 引导、主题/受众/目标/规格、outline 阅读稿已有离线实现。

**剩余工作：** 完善技能引导质量和实际用户体验，不再扩展创作 Web 表单。

**验收条件：** 足够信息即可推进；偏好缺失只问影响创作的部分。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/authoring.py](../videocreate/src/videocreate/authoring.py)。

已有测试索引：[test_authoring.py](../tests/test_authoring.py)；[test_edit_only_production.py](../tests/test_edit_only_production.py)；[test_generation_authoring.py](../tests/test_generation_authoring.py)；[test_image_production.py](../tests/test_image_production.py)；其余见机器清单。

### F03 · P0 · 离线实现已落地

原始需求：定义通用剧本创作/投射层：场景、动作、台词、情绪与 beat/shot 映射；阅读稿与结构化源有明确单向导出或版本化导入。

**已有实现：** director 结构化剧本、阅读稿导出和来源版本绑定导入已有离线实现。

**剩余工作：** 审计长对白/多场景/动画 sidecar 的一致性和实际创作质量。

**验收条件：** 可读稿与结构源单向导出/受控导入明确，镜头 ID 不因改稿漂移。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/authoring.py](../videocreate/src/videocreate/authoring.py)。

已有测试索引：[test_authoring.py](../tests/test_authoring.py)；[test_edit_only_production.py](../tests/test_edit_only_production.py)；[test_generation_authoring.py](../tests/test_generation_authoring.py)；[test_image_production.py](../tests/test_image_production.py)；其余见机器清单。

### F04 · P0 · 部分实现

原始需求：流程分支覆盖单镜、图生视频、原创/改编动画、科普、连载、独立系列、仅剪辑、纯图/GIF；无关阶段可跳过并记录原因。

**已有实现：** video/edit-only/mixed-video/image-only/gif-only/gif-local 及动画/系列分支有基础。

**剩余工作：** 补科普/新闻/网页等分支整合及跳步原因，完成真实工作流覆盖。

**验收条件：** 纯剪辑不要求上游，纯图无视频时间线，分支共享执行底座但不混淆产物。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/planning/profiles.py](../videocreate/src/videocreate/planning/profiles.py)。

已有测试索引：[test_authoring.py](../tests/test_authoring.py)；[test_edit_only_production.py](../tests/test_edit_only_production.py)；[test_generation_authoring.py](../tests/test_generation_authoring.py)；[test_image_production.py](../tests/test_image_production.py)；其余见机器清单。

### F05 · P0 · 部分实现

原始需求：逐步审阅/按授权自动推进策略；不每镜重新选上游，不每阶段机械求确认；付费前仍校验既有授权范围和预算。

**已有实现：** 逐步/自动策略、选定检查点与来源预览已有；不是无人值守执行循环。

**剩余工作：** 由 Codex 连续推进已授权步骤，明确授权/预算边界，不再造 Web 自动工作台。

**验收条件：** 既有授权内不机械逐镜确认；策略保存既不授权收费也不批准媒体。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/production_policy.py](../videocreate/src/videocreate/production_policy.py)。

已有测试索引：[test_authoring.py](../tests/test_authoring.py)；[test_edit_only_production.py](../tests/test_edit_only_production.py)；[test_generation_authoring.py](../tests/test_generation_authoring.py)；[test_image_production.py](../tests/test_image_production.py)；其余见机器清单。

### F06 · P1 · 部分实现

原始需求：主题、剧本、分镜、参考、声音与模型参数的逐层映射；早期能力预演、最终请求预检；可解释一个镜头为何如此生成。

**已有实现：** 五层映射、creative audit、编译与局部预检已有。

**剩余工作：** 补主题/剧本/分镜/声音到实际请求的可读解释和早期能力反馈。

**验收条件：** 能解释单镜输入来源、最终参数及未消费项，不把计划验证当艺术验收。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/planning/creative_audit.py](../videocreate/src/videocreate/planning/creative_audit.py)。

已有测试索引：[test_authoring.py](../tests/test_authoring.py)；[test_edit_only_production.py](../tests/test_edit_only_production.py)；[test_generation_authoring.py](../tests/test_generation_authoring.py)；[test_image_production.py](../tests/test_image_production.py)；其余见机器清单。

### F07 · P1 · 部分实现

原始需求：可视化修改影响分析与局部失效；改字幕/备注不重生视频，改动作只使相关镜和实际依赖待更新，旧候选保留。

**已有实现：** 输入影响、候选保留、来源局部审核与最终编辑失效已有。

**剩余工作：** 覆盖复杂依赖、引用/声音/时间线变更的影响；在 Codex 输出局部影响清单。

**验收条件：** 改字幕/备注零生成，改动作只影响相关镜和实际依赖。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/authoring.py](../videocreate/src/videocreate/authoring.py)。

已有测试索引：[test_authoring.py](../tests/test_authoring.py)；[test_edit_only_production.py](../tests/test_edit_only_production.py)；[test_generation_authoring.py](../tests/test_generation_authoring.py)；[test_image_production.py](../tests/test_image_production.py)；其余见机器清单。

### F08 · P1 · 部分实现

原始需求：项目 status/next 的统一查询入口与步骤面板；“继续制作”能定位当前阶段和可复用产物，而不是从头开始。

**已有实现：** status/next 和 token 绑定 continue-local 能定位计划、导入、渲染、审片页、交付。

**剩余工作：** 完善 Codex 的继续制作指引和失败恢复；保留生成显式入口，不迁入配置 Web。

**验收条件：** 继续复用当前产物；过期 token 重新预览；本地动作无上游创建。

**入口归属：** Codex / CLI + 共享核心。Web 子项：W01。

代码/证据：[videocreate/src/videocreate/production_continue.py](../videocreate/src/videocreate/production_continue.py)。

已有测试索引：[test_authoring.py](../tests/test_authoring.py)；[test_edit_only_production.py](../tests/test_edit_only_production.py)；[test_generation_authoring.py](../tests/test_generation_authoring.py)；[test_image_production.py](../tests/test_image_production.py)；其余见机器清单。

### F09 · P1 · 部分实现

原始需求：标准交付清单：成片/小样、字幕、分镜阅读稿、来源和素材映射、路线与成本、未核实项；草稿与正式验收明确区分。

**已有实现：** 不同产物类型的交付清单、映射、审核状态与集合交付已有。

**剩余工作：** 补可读说明和所有分支的一致性，成本未知/审片未完成完整呈现。

**验收条件：** 清单哈希绑定实际文件；review_pending 不伪装正式验收成片。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/production.py](../videocreate/src/videocreate/production.py)。

已有测试索引：[test_authoring.py](../tests/test_authoring.py)；[test_edit_only_production.py](../tests/test_edit_only_production.py)；[test_generation_authoring.py](../tests/test_generation_authoring.py)；[test_image_production.py](../tests/test_image_production.py)；其余见机器清单。

## G — 角色、主题、资产与系列复用

### G01 · P1 · 离线实现已落地

原始需求：建立跨项目角色/场景/道具/声音索引及素材浏览；引用时复制或快照哈希，来源修改不悄悄改变已建立项目。

**已有实现：** 跨项目角色/场景/道具/声音不可变版本及项目拷贝/哈希已有离线实现。

**剩余工作：** 补批量检索、跨版本对照、来源追溯及实际复用体验，入口留 Codex/CLI。

**验收条件：** 修改原库文件不会静默改变旧项目；导入不继承媒体审批。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/asset_library.py](../videocreate/src/videocreate/asset_library.py)。

已有测试索引：[test_animation.py](../tests/test_animation.py)；[test_animation_reuse.py](../tests/test_animation_reuse.py)；[test_asset_library.py](../tests/test_asset_library.py)；[test_project_asset_authoring.py](../tests/test_project_asset_authoring.py)。

### G02 · P1 · 部分实现

原始需求：身份、服装、表情、美术与镜头构图分开；提供原图/首帧/视频对照板和角色版本更新影响清单。

**已有实现：** 身份/服装/表情/风格分层卡片、本地对照板和引用快照已有。

**剩余工作：** 补自动抽帧/跨版本比较、真实身份稳定验收和局部变更影响。

**验收条件：** 原图/首帧/候选可对照；对照板不等于通过身份或动作质量。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/project_assets.py](../videocreate/src/videocreate/project_assets.py)。

已有测试索引：[test_animation.py](../tests/test_animation.py)；[test_animation_reuse.py](../tests/test_animation_reuse.py)；[test_asset_library.py](../tests/test_asset_library.py)；[test_project_asset_authoring.py](../tests/test_project_asset_authoring.py)。

### G03 · P1 · 部分实现

原始需求：道具可达性、尺度、状态与场景布局的共享卡片；图像资产和动作条件共同进入分镜，防止道具凭空出现。

**已有实现：** 道具状态/物理条件与场景资产已有共享卡片。

**剩余工作：** 补复杂尺度/可达性/布局约束和实际接触/遮挡验收。

**验收条件：** 道具来源与动作条件进入分镜；计划声明不能代替实际接触检验。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/project_assets.py](../videocreate/src/videocreate/project_assets.py)。

已有测试索引：[test_animation.py](../tests/test_animation.py)；[test_animation_reuse.py](../tests/test_animation_reuse.py)；[test_asset_library.py](../tests/test_asset_library.py)；[test_project_asset_authoring.py](../tests/test_project_asset_authoring.py)。

### G04 · P1 · 部分实现

原始需求：角色主题、世界与风格包分别版本化；噜噜、狐狸兔子与自定义角色复用执行底座，不复制生成程序。

**已有实现：** 动画主题与角色版本化和共享执行底座已有。

**剩余工作：** 完善主题/世界/风格包独立版本与迁移，不为每套角色复制执行器。

**验收条件：** 同底座可切主题，旧项目引用版本不变。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/animation](../videocreate/src/videocreate/animation)。

已有测试索引：[test_animation.py](../tests/test_animation.py)；[test_animation_reuse.py](../tests/test_animation_reuse.py)；[test_asset_library.py](../tests/test_asset_library.py)；[test_project_asset_authoring.py](../tests/test_project_asset_authoring.py)。

### G05 · P1 · 部分实现

原始需求：展示已审核互动库与 description-only 动作建议；关联开场条件、实际区间、失败撤销与主题适配，不能把描述当实测动作。

**已有实现：** 有哈希/区间/开场条件的互动库和描述性动作建议已有。

**剩余工作：** 补失败撤销、适配展示与更广实际审阅样例；描述保持 description-only。

**验收条件：** 未播放观察不进已审核动作库；换主题不假定动作已适用。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/animation](../videocreate/src/videocreate/animation)。

已有测试索引：[test_animation.py](../tests/test_animation.py)；[test_animation_reuse.py](../tests/test_animation_reuse.py)；[test_asset_library.py](../tests/test_asset_library.py)；[test_project_asset_authoring.py](../tests/test_project_asset_authoring.py)。

### G06 · P1 · 部分实现

原始需求：连载结尾与独立集初态的不同规则在界面可见；角色、声音、道具和场景引用快照完整，乱序建独立集与重选声线互不污染。

**已有实现：** 连载/独立集及声线快照已有基础。

**剩余工作：** 补乱序创建、重选声音和角色/道具/场景状态不污染的真实验收。

**验收条件：** 独立集不继承上集结尾，连载才按明确连续性；源快照完整。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/series.py](../videocreate/src/videocreate/series.py)。

已有测试索引：[test_animation.py](../tests/test_animation.py)；[test_animation_reuse.py](../tests/test_animation_reuse.py)；[test_asset_library.py](../tests/test_asset_library.py)；[test_project_asset_authoring.py](../tests/test_project_asset_authoring.py)。

## H — 声音、剪辑、审核与修复

### H01 · P1 · 部分实现

原始需求：原生对白、独立配音、保留环境音、静音的明确选择与消费报告；尊重已选路线，不因对白出现而自动安装 TTS。

**已有实现：** 原生视频声、独立音轨、静音/保留源声已有。

**剩余工作：** 补声音路线消费报告和实际听审，严格尊重用户选择。

**验收条件：** 出现对白不自动安装 TTS；计划台词不自动当实听字幕。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/timeline/render.py](../videocreate/src/videocreate/timeline/render.py)。

已有测试索引：[test_v3_production.py](../tests/test_v3_production.py)。

### H02 · P1 · 部分实现

原始需求：固定声线、试听、局部换声与系列快照走统一界面；非人脸口型与逐字对白实测独立，不把服务健康当声音合格。

**已有实现：** 固定声线/系列快照与既有配音入口保留。

**剩余工作：** 在 Codex 完善试听、局部换声及可选语音/口型服务真实验证；不做新声音 Web。

**验收条件：** 逐字对白、说话者、非人脸口型分开观察；健康检查不代表声音合格。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/animation/voice_cast.py](../videocreate/src/videocreate/animation/voice_cast.py)。

已有测试索引：[test_v3_production.py](../tests/test_v3_production.py)。

### H03 · P1 · 部分实现

原始需求：可选 ASR/对齐辅助实际字幕与切点；原生对白按实听结果，核对说话者、额外台词和半句截断；ASR 不自动批准音质。

**已有实现：** 旧 ASR/字幕相关入口和时间线字幕已保留。

**剩余工作：** 按需要接入可选 ASR/对齐到 v3，检查额外台词/截半句和说话者。

**验收条件：** 字幕依据实际听到的内容；ASR 文本不自动批准音质。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/timeline/model.py](../videocreate/src/videocreate/timeline/model.py)。

已有测试索引：[test_v3_production.py](../tests/test_v3_production.py)。

### H04 · P1 · 部分实现

原始需求：整理旧 FFmpeg 编辑器转场、滤镜、响度、字幕烧录的可复用部分，形成 v3 明确入口；不把两套命令误当完全互通。

**已有实现：** v3 转场、滤镜、响度、烧录、格式 4 及旧 edit-plan v1/v2 的新项目迁移已有。

**剩余工作：** 补编码/字体/字幕/声音差异的真实比较和更多受控编辑效果；留 CLI/Codex。

**验收条件：** 实际像素/音频及完整解码通过，源不变；迁移不带旧媒体审批。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/timeline/finishing.py](../videocreate/src/videocreate/timeline/finishing.py)。

已有测试索引：[test_editing_workflow.py](../tests/test_editing_workflow.py)；[test_legacy_edit_import.py](../tests/test_legacy_edit_import.py)；[test_manager_project_actions.py](../tests/test_manager_project_actions.py)；[test_manager_static_images.py](../tests/test_manager_static_images.py)；其余见机器清单。

### H05 · P2 · 待开发

原始需求：可选速度曲线、补帧、动态遮罩/跟踪和屏幕合成；保存源片、映射与伪影预览，实际派生片重新审核。

**已有实现：** 未实现速度曲线、补帧、动态遮罩/跟踪和屏幕合成完整能力。

**剩余工作：** 按实际项目需求选做，定义派生映射/伪影预览/可选依赖；优先级 P2。

**验收条件：** 保存原片与实际派生链，补帧不冒充原生高帧，修改后重新审片。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/timeline](../videocreate/src/videocreate/timeline)。

已有测试索引：[test_editing_workflow.py](../tests/test_editing_workflow.py)；[test_legacy_edit_import.py](../tests/test_legacy_edit_import.py)；[test_manager_project_actions.py](../tests/test_manager_project_actions.py)；[test_manager_static_images.py](../tests/test_manager_static_images.py)；其余见机器清单。

### H06 · P1 · 部分实现

原始需求：集成可播放/可听的审片页、区间定位、前后镜对照与逐层记录；缺失播放/音频工具时保留未核实，静帧不能自动通过动作。

**已有实现：** 可播放/听的本地 review page、前后片对照和观察导出已有。

**剩余工作：** 完成用户实际播放/听审体验、区间定位和工具可用性；它是项目审片页，不是配置 Web 扩张。

**验收条件：** 连续动作需视频证据、声音需听审；开页面/抽帧不自动通过。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/review/page.py](../videocreate/src/videocreate/review/page.py)。

已有测试索引：[test_content_reviews.py](../tests/test_content_reviews.py)；[test_mixed_video_production.py](../tests/test_mixed_video_production.py)；[test_production_metrics.py](../tests/test_production_metrics.py)；[test_static_image_timeline.py](../tests/test_static_image_timeline.py)；其余见机器清单。

### H07 · P1 · 部分实现

原始需求：缺陷→局部剪辑/换声/重画首帧/重生指定镜→复验；重做前显示影响与预算，旧失败和候选保留。

**已有实现：** 指定任务新候选/replan、局部剪辑/声轨和影响预览已有。

**剩余工作：** 完善缺陷定位→局部修复→复验的实际路径与预算解释。

**验收条件：** 旧失败/候选保留；只重做明确选中任务；不弱化验收条件掩盖缺陷。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/runtime/candidates.py](../videocreate/src/videocreate/runtime/candidates.py)。

已有测试索引：[test_content_reviews.py](../tests/test_content_reviews.py)；[test_editing_workflow.py](../tests/test_editing_workflow.py)；[test_legacy_edit_import.py](../tests/test_legacy_edit_import.py)；[test_manager_project_actions.py](../tests/test_manager_project_actions.py)；其余见机器清单。

### H08 · P1 · 部分实现

原始需求：有效镜头率、可用秒数、合格镜头成本、重做率和理解反馈；说明样本范围，不以单一艺术总分代替真实判断。

**已有实现：** 按审核来源统计有效镜头、已知生成/保留秒、重做和分币种费用已有。

**剩余工作：** 补理解反馈、合格成本解释及代表性样本，真实费用未知继续未知。

**验收条件：** 说明分母与样本范围；不以单一艺术分或旧过期审核代替判断。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/production_metrics.py](../videocreate/src/videocreate/production_metrics.py)。

已有测试索引：[test_content_reviews.py](../tests/test_content_reviews.py)；[test_mixed_video_production.py](../tests/test_mixed_video_production.py)；[test_production_metrics.py](../tests/test_production_metrics.py)；[test_static_image_timeline.py](../tests/test_static_image_timeline.py)；其余见机器清单。

## I — 专项模块

### I01 · P1 · 部分实现

原始需求：科普、地理、历史和新闻的来源/主张/旁白流程进入阶段体系；旧新闻功能按需迁入 v3；AI 示意与真实证据区分。

**已有实现：** 科普 research/claim/narration、历史/新闻保留工具已有。

**剩余工作：** 将需要的旧流程接入 v3 阶段，完善来源、主张与 AI 示意标记。

**验收条件：** 来源可核对；生成示意不冒充事实证据；阶段可恢复。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/education.py](../videocreate/src/videocreate/education.py)。

已有测试索引：[test_v3_production.py](../tests/test_v3_production.py)。

### I02 · P2 · 部分实现

原始需求：Muse 网页运行器在实际工具允许时完成提交/恢复/下载/对账；API Muse 独立保留；在此之前交接包明确 prepared_only。

**已有实现：** Muse 工作流准备/交接包已有，网页执行仍 prepared_only。

**剩余工作：** 在新会话确认可调用工具后实现真实提交/恢复/下载/对账，不以工具目录存在宣称已接通。

**验收条件：** 实际网页任务和文件回执可核对；失败回原任务，不自动重复提交。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/workflows.py](../videocreate/src/videocreate/workflows.py)。

已有测试索引：[test_v3_workflows.py](../tests/test_v3_workflows.py)。

### I03 · P2 · 部分实现

原始需求：ChatCut 实际任务工具对接、剪映指定版本草稿验证；失败可回到原生 MP4；不把导出素材包当编辑器已导入。

**已有实现：** ChatCut/剪映等素材或草稿导出桥保留。

**剩余工作：** 验证实际安装版本/任务工具导入与还原效果，失败仍可交付原生 MP4。

**验收条件：** 导出成功与编辑器实际导入分开；需要真实打开/渲染证据。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/references/legacy-v2-workflow.md](../videocreate/references/legacy-v2-workflow.md)。

已有测试索引：[test_chatcut_adapter.py](../tests/test_chatcut_adapter.py)。

### I04 · P1 · 部分实现

原始需求：保留 GPT/Grok 图片与 GIF 现有能力，补每 binding 的生成/编辑/动画合同和循环/体积/透明度检查；异步/SSE 按实需开发。

**已有实现：** GPT/Grok 图片、纯图/GIF 与本地视频/序列帧转 GIF、审核和集合交付已有。

**剩余工作：** 逐 binding 的生成/编辑/GIF 合同小样，循环/体积/透明检查和真实异步/SSE按需补齐。

**验收条件：** 动画帧数与连续播放验证；本地转换不依赖视频上游，不能当模型 GIF 已验证。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/src/videocreate/image_production.py](../videocreate/src/videocreate/image_production.py)。

已有测试索引：[test_gif_media.py](../tests/test_gif_media.py)；[test_image_model_routing.py](../tests/test_image_model_routing.py)；[test_image_production.py](../tests/test_image_production.py)；[test_local_gif_production.py](../tests/test_local_gif_production.py)。

### I05 · P2 · 待开发

原始需求：模型专属提示词、场景基准、延迟分布、成本和质量比较；只有可比样本才给用途推荐，跨型号替代单独可选。

**已有实现：** 未建立可比的多模型场景/质量/延迟/成本基准数据集。

**剩余工作：** 定义同条件样本、模型专属提示与统计口径，再在授权预算内采样。

**验收条件：** 无可比样本不做质量排行/用途推荐；不同模型替代需明确选择。

**入口归属：** Codex / CLI + 共享核心。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/assets/module-catalog.json](../videocreate/assets/module-catalog.json)。

## J — 验证与交付

### J01 · P0 · 部分实现

原始需求：Schema/迁移/凭据引用/未知字段/并发保存/断电原子性/撤销与旧版只读；真实用户配置不进入发行包。

**已有实现：** Schema/配置/加密/冲突/修复已有大量离线及发行验证。

**剩余工作：** 增加 HTTP DTO、CSRF/Host、Web 双窗口、密钥跨文件中断和干净用户数据保护。

**验收条件：** 真实配置不进包，原始备份可核对，未来版本只读，故障不丢恢复身份。

**入口归属：** 测试 / 发行 / 文档。Web 子项：W04, W07, W16, W17, W22。

代码/证据：[tests/test_provider_management.py](../tests/test_provider_management.py)。

### J02 · P0 · 部分实现

原始需求：四种选择输入、重复名、过期序号、配置变更、同项目续作、无头缺项零创建、图片视频独立选择。

**已有实现：** 稳定编号、任务筛选与范围已有离线覆盖。

**剩余工作：** 新增 Web 默认与技能协同，补四种输入、别名、跨项目/多菜单和全部创建入口矩阵。

**验收条件：** 菜单过期零创建，已选项目不重复问，图片视频独立。

**入口归属：** 测试 / 发行 / 文档。Web 子项：W13, W19, W22。

代码/证据：[tests/test_catalog_task_filter.py](../tests/test_catalog_task_filter.py)。

### J03 · P0 · 部分实现

原始需求：每 adapter × operation 的 create/query/download/upload fixture，大小写精确 ID、字符/字节、多参考边界、价格单位和跨账户隔离。

**已有实现：** 统一协议、typed 参考、精确 ID、诊断隐私有 fixture 和测试。

**剩余工作：** 补 HTTP/浏览器合同与各 adapter×operation 边界矩阵，以及未核实真实合同。

**验收条件：** 假服务器断言 payload/认证/请求数；测试密钥哨兵不进入响应/日志。

**入口归属：** 测试 / 发行 / 文档。Web 子项：W03, W04, W14, W15, W22。

代码/证据：[tests/test_xingapi.py](../tests/test_xingapi.py)。

已有测试索引：[test_manager_diagnostics.py](../tests/test_manager_diagnostics.py)；[test_provider_diagnostics.py](../tests/test_provider_diagnostics.py)。

### J04 · P0 · 部分实现

原始需求：提交后崩溃、未知提交、已知任务恢复、下载失败、凭据轮换、路由变化、并发预算；检查实际请求次数和账本，不仅检查返回值。

**已有实现：** unknown、恢复、配额及并发预算有离线故障覆盖。

**剩余工作：** 补 Web 换钥/归档与真实多进程/断电窗口，审计下载和旧任务回归。

**验收条件：** 以实际 POST 数量和账本核对，无重复创建，无未知占位泄漏。

**入口归属：** 测试 / 发行 / 文档。Web 子项：W09, W19, W22。

代码/证据：[tests/test_submission_unknown.py](../tests/test_submission_unknown.py)。

### J05 · P0 · 部分实现

原始需求：全流程分支、跳步、阶段恢复、局部失效、小样与全片区别、系列快照、审核过期；不允许字幕修改触发视频重生。

**已有实现：** 多 profile、政策/继续、迁移、时间线和局部审核有离线与仓库外夹具。

**剩余工作：** 补真实创作分支、复杂依赖和已有 30 秒样片连续动作/听审。

**验收条件：** 小样与全片分开，改字幕不重生，源通过不自动批准最终剪辑。

**入口归属：** 测试 / 发行 / 文档。Web 子项：W22。

代码/证据：[tests/test_production_continue.py](../tests/test_production_continue.py)。

### J06 · P1 · 部分实现

原始需求：在后续明确生成授权和预算内做逐 binding/操作的小样，记录真实 ID、时长、尺寸、参考语义、声音和费用；选择界面不能把离线测试标为在线通过。

**已有实现：** 已有 XingAPI 文生视频样片和目录观察；不等于各 binding/参考/声音通过。

**剩余工作：** 按后续明确生成授权/预算开展逐操作小样及账单核对；优先复用已有产物。

**验收条件：** 记录完整本地回执，公开报告脱敏；离线夹具从不标为在线通过。

**入口归属：** 测试 / 发行 / 文档。Web 子项：无；保留为核心/制作工作。

代码/证据：[videocreate/references/runtime-and-review.md](../videocreate/references/runtime-and-review.md)。

### J07 · P1 · 部分实现

原始需求：全回归、离仓库 wheel/ZIP/EXE、升级/回滚、可选依赖、文档/Schema/模块目录同步；提供可复现验收记录和已知限制。

**已有实现：** dev43 1063 全回归、wheel/技能/便携 EXE 的仓库外和本机安装验收已完成。

**剩余工作：** 新 Web 全链路、静态资源入包、离线/干净机器、升级/回滚/独立素材服务及文档同步。

**验收条件：** 版本/源码/安装字节一致、零秘密包；发布记录明确在线/人工未核实范围。

**入口归属：** 测试 / 发行 / 文档。Web 子项：W02, W15, W18, W20, W21, W22。

代码/证据：[docs/20261113-dev43-acceptance.zh-CN.md](../docs/20261113-dev43-acceptance.zh-CN.md)。

已有测试索引：[test_manager_diagnostics.py](../tests/test_manager_diagnostics.py)；[test_provider_diagnostics.py](../tests/test_provider_diagnostics.py)。
