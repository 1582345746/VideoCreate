# 清理记录与当前保留范围

> 迁移补充（2026-11-13）：下文 E 盘位置是清理发生时的历史记录；相同归档现已逐文件校验复制到 `F:/VideoCreate/_local/archive/json-only-20261113-171206/retired-ui-and-generated-files.zip`。当前开发仓库为 `F:/VideoCreate`，详见[迁移说明](20261113-f-drive-migration.zh-CN.md)。

日期：2026-11-13。最终方向为本机 Web，默认只填 URL/Key，高级配置可选；视频制作继续在 Codex。仅 JSON 用户入口的短暂尝试已撤回。

## 已完成的清理

工作区以下生成目录已移除：`build/`、`dist/`、`acceptance/`、`.pytest_cache/`、`.tmp-reference-frames/`、`analysis-frames/`、`UNKNOWN.egg-info/`。对应 39,526 个文件、1,342,994,318 字节（约 1.34 GB）；另外清除了源码/测试的可再生 Python 字节码缓存。

删除前已归档并逐文件验证 ZIP 中内容哈希，归档共含 39,693 个文件（还包含清理前源码、测试和文档快照）：

```text
E:/MyFiles/ToolSkills/VideoCreate-archive/json-only-20261113-171206/retired-ui-and-generated-files.zip
```

归档 SHA-256：`57168ff191118b739518e2fc50d507f053b0a8bc0540d50b980676ce25867f59`；压缩后 895,209,911 字节。归档目录还有 cleanup-plan、cleanup-inventory、cleanup-report、protected-baseline 和清理前未提交 Git patch，可按需恢复单个文件。

这个归档包含历史本机验收材料，作为私有恢复备份保留，不加入可分享文档包。不得将它当作已脱敏的对外诊断。

## 恢复与保留

用户在清理过程中最终决定仍使用 Web。此前移出的旧 Tk 源码、界面测试、混合测试中的 GUI 部分和 Web 文档/原型已按清理前原始字节恢复。未完成 dev44 的 11 个文件保持原哈希，不把它们算成新 Web 实现。

创建过的 URL/Key 专用 JSON 模块、示例和测试三个新文件已撤回，当前没有遗留该入口。现有完整 Schema 4 配置仍是技能使用的数据源。

所有项目保留，包括名称中带 smoke/test 的项目，避免删除真实付费素材。项目整体为 5466 个文件，清理前后聚合 SHA-256 为 `a1189e6af65c990fc0414212ccce7287fc5d00b0964203236e549bbd1c436666`。

本机权威配置、凭据文件和已安装技能保持；没有停止素材服务、改变隧道或创建收费任务。清理后再次逐文件核对全部项目、已安装技能和配置/凭据，结果见[保护检查](20261113-cleanup-protection-verification.json)及[整体验证](prototypes/handoff-verification.json)，清理摘要见[机器记录](20261113-cleanup-summary.json)。

旧 Tk 源码暂留作兼容和迁移参考；新的产品主方向为 Web。退役 Tk 的入口、打包器及界面专用测试，应在 Web 替代功能和独立素材服务迁移通过后完成，不在这次文档/原型任务中留下一个缺模块的运行包。核心回归测试继续保留。

## 在新对话中查旧证据

`acceptance/` 与 `dist/` 已不在当前工作区。交接文档所述 dev43 完整回归、dev44 局部失败、旧发行产物均为历史验收结果，原文件可在上述 ZIP 中按原相对路径读取；需要重跑时先提取相关脚本并审查固定版本/路径，不能误执行旧安装脚本。

不要整包恢复 `build/dist` 才开始新开发；日常继续读当前源码、设计、完整清单和交接即可。真实项目仍在当前 `projects/`，无需从归档恢复。
