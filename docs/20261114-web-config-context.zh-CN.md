# 同端口切换配置时的上下文隔离

日期：2026-11-14。当前候选 **r22 / 未发行 dev44**，离线套件 **r5**。C 盘已安装 dev43、原配置和凭据保持原样。

## 问题与实现

后端原本按配置路径隔离提交记录和草稿，但浏览器 sessionStorage 只使用固定键。同一端口先打开配置 A、后来打开 B 时，会显示 A 的待核对提交；在 B 查不到的旧草稿标识被清除；原页面自动重新取得 B 的会话后，内容指纹相同的 A/B 不能仅凭内容区分。

[修复前五场景](../_local/web-config-context-20261114-before-r1/result.json)全部失败，使用 F 盘两份初始字节完全相同的合成配置、同一个临时端口、实际退出和重启服务。没有使用原配置或访问上游。

现在认证会话返回规范化配置路径的不透明身份。页面首次连接后固定该身份，后续 API 请求携带 `X-VC-Config`；服务端先检查会话，再拒绝不匹配的上下文，返回脱敏 409 和重新打开提示，不执行目标读取、预览、核对或写入。会话引导也不允许静默切换配置。原页面非秘密输入继续保留，可重新打开正确配置；设置页仍显示实际配置路径。

草稿与待核对标识按配置身份分别存放。同端口打开另一份配置时，不读取、覆盖或删除前一份配置的标识；返回 A 可继续核对 A，B 的标识也继续存在。同一配置重启身份稳定；不同路径即使内容指纹完全相同也有不同身份。浏览器只存不透明身份与标识，不增加表单、配置路径或 Key 存储。

旧候选没有配置身份的草稿标识，只有当前服务实际加载成功后才迁到对应命名空间；另一份配置返回缺失时保留旧标识。旧版待核对标识仍保留，点击核对前须确认显示路径就是原配置；取消不读取状态，也不删除记录。既有明确选择配置的 API 客户端可继续原请求格式；这个可选请求头用于绑定页面上下文，不替代会话、同源、CSRF、配置指纹或用户核对。

## 验证

| 范围 | 证据与结论 |
| --- | --- |
| 新增五场景 | [最终源码](../_local/web-config-context-20261114-source-r2/result.json)及[已安装 r22](../_local/web-config-context-20261114-installed-r1/result.json)通过，各启动并退出 15 个不同实例；A/B 各自提交和草稿往返、相同指纹下阻止原页面写 B、旧标识迁移和旧提交路径确认均验证 |
| HTTP 回归 | [88 项 Web](../_local/web-validation-20261114/config-context-web-r2/result.json)通过，0 失败/错误/跳过/外连；新增 3 项覆盖路径身份稳定、错误上下文不进处理器、正确身份仍受 CSRF/Origin/只读约束 |
| 完整浏览器 | [12 组](../_local/web-browser-suite-20261114-config-context-full-r1/result.json)通过；原提交响应丢失九场景继续通过，存储断言改为精确配置命名空间，原字段保留/提交次数断言不变 |
| 强退恢复 | [8 次服务重启](../_local/web-recovery-20261114-config-context-r1/result.json)及[实际 Chrome 强退](../_local/web-browser-crash-20261114-config-context-r1/result.json)通过，四类草稿、版本竞争和清理失败保留行为继续有效 |
| 目录失败后整理 | [已安装 r22](../_local/web-catalog-failure-20261114-config-context-installed-r1/result.json)通过，没有真实上游读取 |
| 候选与安装 | [r22 构建](../_local/web-candidate-20261114-r22/candidate-build.json)独立重建前端并核对静态/Schema；286 输入、260 技能文件；[四入口/安装回滚](../_local/web-candidate-install-20261114-config-context-r1/result.json)通过 |
| 离线交付 | [r5 构建](../_local/web-acceptance-kit-20261114-r5/kit-build.json)内含 r22、15 个哈希依赖；[独立解压验收](../_local/web-acceptance-kit-validation-20261114-r5/result.json)通过；仅 Windows x64 CPython 3.9，不含 Python 运行时 |
| 保护与清理 | [原数据保护](../_local/web-validation-20261114/preservation-config-context-final.json)和[测试进程清理](../_local/web-validation-20261114/config-context-cleanup.json)：原配置/DPAPI、325 个外部文件、5466 个项目文件不变；8765 仍是 PID 2176 |

总数为 **1121 核心沿用 + 88 Web 重跑 = 1209 项唯一 Python 测试**。181 个打包 Python 文件中仅 Web 的 `app.py`、`security.py` 改变；169 个非 Web 文件全部未变，因此核心结果沿用，不宣称重跑。17 个逻辑浏览器组中，16 个在 r22 验证，原数据只读组保留 r16；九阶段维护仍保留 r14。

首次新增 Web 用例以空预览请求测试只读拒绝，实际先触发必填字段校验，422 与预期 403 不符。改为有效的归档预览，明确验证只读 403 及错误码；没有放宽产品校验。失败回执保留在 `config-context-web-r1`。源码第一轮功能专项通过后，验证工具另将 Playwright 临时目录显式固定到该批 F 盘 tmp；最终源码和已安装专项均使用此版本。

## 当前交付与边界

[r5 离线 ZIP](../_local/web-acceptance-kit-20261114-r5/VideoCreate-dev44-offline-win-cp39.zip)：5,037,862 字节，SHA-256 `85a4569b7edcaabfc813ea4a206479e48abdef0f4d4f222875b68dce61fe0de6`。r21/r4 及历史回执保持不变。

本批没有新增精确型号合同或计费单位。更多合同、token/分钟等语义及真实账单、170 条旧记录原身份与在线恢复、真人读屏/完整操作、新 Windows 和正式采用仍保留原缺口。没有收费生成、样片重生或生产素材服务切换。目标继续进行。
