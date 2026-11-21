# 保存响应丢失后的表单收尾

日期：2026-11-14。本批候选为 **r21 / 未发行 dev44**，仍保留 C 盘已安装 dev43。本批只修改前端保存流程、随包说明和验证工具；181 个技能包 Python 文件不变。

## 问题与修复

[修复前九场景](../_local/web-browser-suite-20261114-reconcile-before-r1/reconcile/result.json)使用真实本机接口：服务端提交成功后丢弃浏览器响应，或在发送前断开。8 项失败、1 项未提交后手动重试通过。上游核对成功后弹窗未关闭；模型弹窗没有核对入口；默认选择仍脏、备份选择未清空；已提交草稿未清理；结果未知时输入过早解锁。原 M3 脚本核对成功后手动取消，未检查实际收尾，现已改为等待弹窗自动关闭。

现在提交响应不确定时，原保存调用保持等待，输入和取消继续锁定。待核对及核对失败后焦点落在当前核对按钮；折叠区的隐藏子控件不参与键盘循环。上游、模型弹窗均提供可用的“核对保存结果”；默认和备份使用页面入口。核对不重复提交，也不自动重试创建，连续点击只发一次状态读取。

- 确认已提交：继续原成功流程，关闭对应弹窗、选中保存的上游、重置默认基线或备份选择，并按原草稿版本清理；上游关闭后恢复键盘焦点。
- 确认未提交：继续原失败流程，解锁并保留非秘密输入及草稿；Key 保持清空，仅由用户明确重填重试。
- 未知或状态读取失败：保持原保存等待和输入锁定，显示提示并允许再次核对；可以重新打开页面查看本机配置，不会自动写入。
- 页面重开：浏览器仅保留原提交的不透明标识。核对刷新当前配置，明确提示旧非秘密草稿继续保留，须核对后再恢复或丢弃。没有持久化表单或 Key，也不使用重开后加载的草稿版本删除旧提交的草稿。

同页成功清理沿用精确版本检查。验证中另一个共享会话先改写草稿，核对成功后较新草稿继续存在；配置成功不被清理冲突误报为失败。防抖、请求或磁盘确认前强退仍可能丢失最近输入，此原 W17 边界未扩大。

## 验证范围

| 范围 | 证据与结论 |
| --- | --- |
| 新增九场景 | [完整源码](../_local/web-browser-suite-20261114-reconcile-final-full-r1/reconcile/result.json)与[已安装 r21 最终专项](../_local/web-browser-suite-20261114-reconcile-final-installed-r1/reconcile/result.json)通过；涵盖四表单、未提交手动重试、未知/失败、重复核对、重开页面和竞争草稿；最终专项补键盘遍历和截图 |
| Web | [85 项](../_local/web-validation-20261114/reconcile-final-web-r1/result.json)通过，0 失败/错误/跳过/外部连接；15.015 秒；未新增 Python 计数 |
| 完整浏览器 | [12 组](../_local/web-browser-suite-20261114-reconcile-final-full-r1/result.json)通过；原六项输入锁定、缩放、21 状态自动无障碍及读上下文均重跑 |
| 强退与竞争 | [8 次服务重启](../_local/web-recovery-20261114-reconcile-final-r1/result.json)、[真实 Chrome 强退](../_local/web-browser-crash-20261114-reconcile-final-r1/result.json)通过 |
| 目录失败后整理 | [已安装 r21](../_local/web-catalog-failure-20261114-reconcile-final-installed-r1/result.json)通过，未访问真实上游 |
| 构建与安装 | [r21 构建](../_local/web-candidate-20261114-r21/candidate-build.json)286 输入、260 技能文件，独立前端重建与静态/Schema 匹配；[四入口及安装回滚](../_local/web-candidate-install-20261114-reconcile-final-r1/result.json)通过，支持中文、空格和 `&` 路径，运行无需 Node |
| 离线套件 | [r4 构建](../_local/web-acceptance-kit-20261114-r4/kit-build.json)包含 r21 和 15 个哈希依赖；[独立解压验收](../_local/web-acceptance-kit-validation-20261114-r4/result.json)通过；仅 Windows x64 CPython 3.9，不含 Python 运行时 |
| 保护与清理 | [数据保护](../_local/web-validation-20261114/preservation-reconcile-final-r2.json)与[测试进程清理](../_local/web-validation-20261114/reconcile-cleanup.json)：原配置/DPAPI、325 外部文件、5466 项目文件保留，8765 仍为 PID 2176 |

总数仍为 **1121 核心沿用 + 85 Web 重跑 = 1206 项唯一 Python 测试**。16 个逻辑浏览器组中，15 个在 r21 验证；原 C 盘配置只读组仍为 r16 范围。九阶段维护仍是 r14 范围，未借四入口回滚宣称重跑。

保留首轮专项错误：`source-r1` 有 8 项通过，未知场景仍按普通按钮文案定位“保存上游”，但原保存现保持等待、按钮显示“正在保存…”，改为断言实际忙碌按钮。`installed-r2/r3` 新增键盘检查发现实际产品问题：禁用提交按钮的顺序起点使 Tab 到弹窗外。r20 补待核对焦点后，上游通过、模型仍失败；`focus-debug-r1` 的实际 DOM 显示关闭高级区的隐藏 summary 仍返回矩形，原循环误计为可用控件。修正产品的关闭详情区过滤后 r21 替代 r19/r20。最终断言核对按钮先获得焦点、Tab 全程留在弹窗并循环返回；原持久化/写入次数断言全部保留。

## 当前交付与剩余

[r4 离线 ZIP](../_local/web-acceptance-kit-20261114-r4/VideoCreate-dev44-offline-win-cp39.zip)：5,035,769 字节，SHA-256 `8af2c3535680a88a8622c32fb4e3cc43d85f109bdbd2c0fcf02d61644a284a5b`。r18、r2，以及中间 r19/r3 套件与 r20 候选均原样保留。

更多精确合同、token/分钟等单位及真实账单、170 条旧记录原身份与在线恢复、真人读屏/完整操作、新 Windows 和正式采用仍待完成。没有收费生成、样片重生、C 盘稳定安装替换或 8765 切换。目标保持进行中。
