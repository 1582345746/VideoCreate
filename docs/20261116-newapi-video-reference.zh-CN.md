# 2026-11-16 算力AI Flash 视频参考接通记录

本机已安装并启用视频参考通路。MP4 作为独立 `videos` 输入，与 `images`、可选 `audios` 分开传输。已通过源码及现用安装版的模拟上游测试、真实素材公网 GET 和生成预检；没有向算力AI创建收费任务。模型实际参考效果、带视频参考的实际账单仍待真实成片验证。

## 当前可用入口

- 上游：`suanliai-main`，原 URL 与原 DPAPI 凭据。
- 精确型号：`官渠sd2.5-flash(20参任选/10-5-5/5-30秒/720P)`。
- 视频参考 binding：`suanliai-sd25flash720-ref--suanliai-main`，`reference-to-video`，`newapi-json-v2`。
- 原图片 binding `suanliai-sd25flash720--suanliai-main` 保留。全局默认、账户、预算及原 binding 均未改变。
- 参考视频只增加输入，不增加生成任务数。两条 30 秒可各生成一次；按当前同型号目录价估算合计 ¥9.70，不代表实际新任务已扣费。

用户给视频并说明借鉴动作、运镜、节奏或场景后，Codex 负责看参考、选片段、准备至少一张图片、托管引用、写新剧本及提示词，再按既有生成授权执行。至少一张图片是用户提供的 Flash 合同要求；有新角色/产品时应使用相应图片。直接输入原片不保证模型自动复现节奏和叙事。

执行约束、准确字段、限制来源和命令见 [NewAPI 视频参考合同](../videocreate/references/newapi-media-contract.md)。数量上限来自用户提供的 Flash 文档；字节和参考时长上限明确标为本机保守工作范围。输出仍按已有 5/10/15/20/25/30 秒配置。

## 实施和验证

新增版本化适配器，复用文件检查、来源链、HTTPS 校验、批量预检和预算保护。请求使用 `POST /v1/videos`，字段 `seconds/aspect_ratio/resolution/images/videos/audios`。空数组及模型默认声音开关省略；不使用星光的 `duration/ratio`。查询/下载沿用 NewAPI 读取方式，跨域文件请求不附模型 Key。

测试覆盖混合媒体与顺序、最少一图、数量/大小/时长/组合、失效链接、无哈希证明、本地最后拦截零提交、完整任务号、trace ID 区分、未知受理防重复提交、旧接口快照恢复、结果 URL 下载和输入链接脱敏。

| 验证 | 结果 | 证据 |
|---|---|---|
| F 盘源码相关回归 | 64 项通过 | `_local/20261116-newapi-reference/source-regression-tests.log` |
| Web 兼容等集成验证 | 42 项通过（与前组有重叠，不累加） | 同目录 `integration-tests.log` |
| dev43 加本轮增量补丁 | 64 项通过；日志首行记录实际加载的暂存安装路径 | 同目录 `staged-tests.log` |
| 用户原始视频 | 《下载 (2).mp4》，31.033333 秒，1280×720；选取 0–8 秒做链路检查，原片未改 | 同目录 `real-reference-check.json` |
| 实际素材运输 | 1 张 PNG + 1 段 8 秒 MP4，公网完整 GET 的字节和 SHA-256 全部一致 | 同目录 `real-reference-check.json` |
| 已安装技能正式生成预检 | `ok=true`，1 次新请求、30 秒、估算 CNY 4.85，账本 0、状态 not-submitted | 同目录 `real-reference-preflight/generation-preview.json` |
| 保留现有工作 | 原 binding/defaults/upstreams/budget 一致；钢材和胶带项目 11 个关键文件哈希一致 | 同目录 `final-integrity.json` |

真实素材检查项目只是测试工装，其示例剧本不是用户新制作方案；没有调用 execute/run，没有新增样片，也没有改变原钢材/胶带成片的审查结论。

## 本机安装及服务

本机仍是 **3.0.0.dev43 + 20261116-newapi-reference 本地补丁**；F 盘继续保留未发行的 dev44 和全部原有未提交修改。只把本轮差异三方合并到 dev43 暂存副本，验证后部署 12 个必要文件。Web DTO 的改动只留在 F 盘源码。静态配置 schema 分别由各自版本生成，没有把 dev44 的其他字段混入 dev43。

本轮访问的配置别名仍是 `C:/Users/FBX/AppData/Local/VideoCreate/videocreate.config.json`。本机路径解析指向既有 `Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/VideoCreate`；沿用同一个文件和凭据，配置事务保存为 revision 10，备份路径见 `config-applied.json`。没有新建替代配置，也没有全局修改历史路径。

检查时 8765 已无监听，原服务记录为停止状态；随后用原配置启动既有素材服务，最终 PID 49984，端口 8765，公网域名保持 `https://videofiles.hn.takin.cc`。本轮没有停止或重启运行中的素材服务。检查素材链接有效期 4 小时，后续生成前由技能重新验证或刷新。

补丁清单与 SHA-256：`_local/20261116-newapi-reference/installed-manifest.json`。已安装标记：`C:/Users/FBX/.codex/skills/videocreate/local-patches/20261116-newapi-reference.json`。

## 恢复资料

本轮编辑前源码、安装版和增量 diff 分别保存在 `_local/20261116-newapi-reference/source-before`、`installed-before`、`installed-dev43.patch`。需要撤销时，先通过配置事务移除或停用新 reference binding 并恢复其 route 候选列表，再按清单恢复本轮安装文件；保留其他并发配置变更和历史任务。已有 v2 任务必须先保留其读取适配器，不能为了回退令在途任务失去恢复能力。正常使用不需要回退。
