# VideoCreate dev14：上游管理与制作流程阶段验收

日期：2026-11-12。版本：3.0.0.dev14。原始开发清单共 73 项，**本报告是阶段交付，不代表整个路线图完成**。目标保持 active。

## 已交付的可用内容

- 配置 v4：保留 models / upstreams / bindings / routes；草稿与启用分开；中文备注、标签、收藏、排序、供应商声明和报价可保存。
- 单 JSON 管理：共同校验、原子保存、并发 token、修订、备份、归档及恢复。账户/地址更换建立新实例；本机密钥通过 DPAPI 引用读取。
- 编号选型：缺项返回 selection_required，菜单绑定配置版本和项目；支持本次与项目选择、图片/视频分别选择、临时 CLI 型号/上游覆盖与切换影响报告。
- 任务恢复：旧任务保持原快照；未知提交不重发；已确认拒绝可按显式自动备用策略另选同型号；明确固定选择不继承自动备用。
- 参数与预算：字符计数、简单/条件档位、最低计费/取整、报价有效期、按币种汇总、共享提交容量组。价格未知不满足硬金额上限。
- Windows 原生管理器：上游与型号表单、能力/价格/备注页、收藏搜索、比较、只读目录导入、保存差异、备份恢复、制作步骤和任务表格。
- 制作进度：status/next、创作检查点、按授权推进策略、剧本阅读稿/带版本 JSON 导入、镜头变更影响、活读项目索引、交付清单。
- 本地审片页：真实源片与成片播放器、保留区间定位、相邻镜对照、观察记录导出；导入仍走现有哈希与区间审核。
- 机器功能目录：18 个模块、73 个工作包，入口、限制和测试索引均可由 modules 命令读取。

## 本机安装和数据

- 技能：`C:\Users\FBX\.codex\skills\videocreate`。
- 原技能备份：`C:\Users\FBX\.codex\skill-backups\videocreate-pre-dev14-20261112-a56cf27501`。
- 管理器：`C:\Users\FBX\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\VideoCreate\manager\3.0.0.dev14\VideoCreateManager.exe`。
- 权威配置实际路径：`C:\Users\FBX\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\VideoCreate\videocreate.config.json`。
- 配置迁移备份：`C:\Users\FBX\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\VideoCreate\backups\videocreate.config-8c165472cde50065b2eb79fc07eec8510f898963a707dbda7a045c5b4c8dc157.json`。
- 配置目前为 v4、修订 1，共 5 个上游、25 个 binding；6 个星光草稿均禁用。
- Codex Windows 包会重定向 LOCALAPPDATA。安装的管理器通过旁置 manager.settings.json 指向已解析的权威配置，避免从资源管理器启动时另读一份配置。发行包不包含这个用户路径文件。
- 星光密钥已保存在本机加密存储，本文和发行包不包含密钥。

## 本轮测试证据

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| 最终全量回归 | 508 项通过，0 失败、0 错误、0 跳过；342.672 秒 | 单元、协议 fixture、运行恢复、FFmpeg、既有动画/系列等；日志见 acceptance/20261112-management/full-regression.log |
| 图形表单 smoke | 通过 | 窗口和表单实例化、六个星光型号、制作进度面板；不是人工视觉验收 |
| 便携 EXE | 通过 | 解压到仓库外中文路径，离线启动、5 上游/25 型号；没有改配置或发网络请求 |
| 安装 EXE | 通过 | 改变默认配置目录后仍读取安装时固定的同一份权威配置 |
| wheel 离仓库 | 通过 | 安装、版本、配置初始化、模块目录、计划创建、制作状态、剧本导出 |
| 技能校验 | 通过 | 使用 UTF-8 模式运行 skill-creator 验证器 |
| 审片网页 | JS 语法与哈希合同测试通过 | 浏览器交互和实际观看未完成，未批准内容 |
| 发行检查 | 源文件及 wheel 通过 | 排除运行缓存，未发现密钥形态或用户配置 |

全量通过后额外修正了管理器的 Windows 配置路径定位，并通过安装 EXE 的独立 smoke 验证；没有再次重复整套 508 项。初次全量遇到新增测试自身变量错误，修正后已完成上述最终全量，不计作产品验收失败。

便携包实测：10752238 字节（约 10.75 MB），解压 24651801 字节；包含 Python/Tcl/Tk，目标机器不需另外安装 Python。包未签名，尚未做干净机器/杀毒产品验收。EXE SHA-256：`fe8201c1d83231e3be27501a21d1c2bce62d77e4ec7ed85f782628a60f9bf30a`。

## 两次真实生成测试

本轮总共发起 2 次创建，各独立项目限 1 次。没有针对未知提交重复创建，没有向星光发送生成请求。两次实际扣费均未拿到账单，不把未填写价格视为免费。

| 上游 / 请求 | 实际观察 | 结论 |
| --- | --- | --- |
| Aivalux / Grok Video 1.5 | create 只给 request_id，先进入 submission_unknown；随后用原站只读查询证实任务存在，按证据恢复。服务回报 muse-video；content 读取持续失败 | 原任务保留 read_pending；不能记为 Grok 可用或内容通过 |
| RapidAPI / Grok Video 1.5 | 请求/回报 ID 一致；任务完成并下载，6.041667 秒、1280×720、24 fps、145 帧、H.264、存在音轨；完整解码通过 | 单一 6 秒文生视频技术 smoke 通过；动作、声音质量和其他参数组合未验证 |

RapidAPI 产物位于 `acceptance/20261112-management/rapidapi-smoke/`。源音轨保留在 source.mp4；按测试计划，独立剪辑预览静音。`reviews/viewer.html` 可播放实际媒体。只保存 smoke 回执，不建立 quality pass。

星光 `/v1/models` 已再次通过安装版读取，精确型号：seedance-933、seedance2.0-933-C、seedance2.0-933-Q、seedance2.5-V、seedance2.5-s、wan3.0-prime-720P。其大小写来自 API。截图中的参考数/时长/价格保存为声明；网站接入文档接口返回 401，API key 不是网站登录凭据。

## 尚未完成的主要工作

1. 星光真实 create/query/upload 合同、逐型号音视频参考传输与边界试测；未获取文档前保持禁用。
2. 通用媒体参考类型/角色/区间、上传与失效恢复；目前仍是已实现的图片参考链路，不能使用 30 图/10 视频/10 音频的混合请求。
3. 更细的逐操作参数合同、旧 v3 质量证据与新指纹的显式沿袭、图像长提示词合同、金额退款审计与计费条件。
4. 远端在途/RPM/轮询/下载配额、Retry-After 与按故障范围的退避；已实现共享组的提交并发。
5. 管理器无效 JSON 修复、完整冲突合并、更多参数动态表单、易读并排比较、干净机器与人工 UI 验收。
6. 完整的仅剪辑/纯图/GIF 分支引导、跨项目角色/场景/声音浏览、风格包/世界包及道具卡片统一管理。
7. 可选 ASR 对齐、声音与非人脸口型实际评测、剪辑转场接口整合、速度曲线/补帧/跟踪、缺陷修复向导和有效镜头成本指标。
8. Muse 浏览器实际执行、ChatCut/剪映导入验收、可比模型基准。这些还受当前可用浏览器/桌面工具和供应商接口约束。

全量测试通过不等于上面这些待办已实现。逐项状态见 [73 项进度表](20261112-development-progress.zh-CN.md) 和 `videocreate/assets/module-catalog.json`。
