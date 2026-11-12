# VideoCreate dev23：本地 GIF 派生制作流程

日期：2026-11-13；版本：3.0.0.dev23。推进原路线图 F04/F07/F08/F09、I04、J05/J07 的相关范围；73 项总目标仍进行中。

## 功能和边界

此前视频转 GIF、静帧转 GIF 只有独立工具入口。现在新增 `gif-local` 计划分支，将本地转换接入项目步骤、影响分析、实际审核、统计和集合交付。它无需上游配置，不建立 provider job、账本条目或模型请求。

| 入口 | 当前行为 |
| --- | --- |
| `plan init --profile gif-local` | 创建没有视频镜头、图片生成任务和时间线的本地动图草稿；下一步提示导入来源 |
| `production gif-video --gif ID --source VIDEO` | 复制本地视频，完整解码，按 start/duration/fps/width/loop 转换；原文件保留 |
| `production gif-frames --gif ID --frame IMAGE ...` | 保留静帧顺序和重复项，检查单帧、实际尺寸与格式；时长由数量/fps 决定 |
| `generation-plan.local_gifs` | 保存独立 GIF ID、项目内素材路径/哈希、转换配方，以及当前派生记录路径/哈希 |
| `production gif-rebuild --gif ID` | 明确重建一个已登记配方，保存新输出和派生链；旧输出和记录保留，不沿用旧通过回执 |
| `production status/next/impact` | 跳过上游生成，单列本地 GIF；源片、参数、输出或记录变化时提示失效 |
| `review page/inbox/status`、`review gif` | 播放实际动图；需要完整播放观察和独立回执，同字节的缺陷优先于通过 |
| `production script-export/deliver/metrics` | 导出配方阅读稿、项目内集合 manifest 和本地转换统计；不计入模型生成秒数、任务数或质量率 |
| 管理器项目面板 | 分别提供视频、静帧转换表单和后台处理，单列本地 GIF 路径及审核状态 |

视频支持 MP4/MOV/MKV/WebM，区间必须位于实测源视频内，0.1–30 秒。静帧支持 PNG/JPEG/WebP，要求单帧、相同实际尺寸与格式，1–1800 张、0.1–30 秒。FPS 1–60、宽度 64–2048；loop=0 无限循环，-1 不循环。输出必须为实际多帧 GIF，最多 48 MB；GIF 不含声音，实际时长受帧和延时量化影响。转换需要已有 FFmpeg/FFprobe，不自动下载。

素材副本和输出按项目相对路径保存，搬迁项目后仍可校验。转换在锁外执行，登记前检查原计划字节、项目路径映射和任务 ID 冲突；只原子替换 generation-plan 一层，之前保存备份。并发修改被保留并报告冲突。失败或中断可能保留未登记的副本/派生产物，供检查恢复；不宣称多文件断电事务。GIF 重建使用已保存配方，CLI 拒绝会被忽略的参数。混合视频来源时间线、图形化配方编辑器和通用剪辑器仍未完成。

## 验证

新增 **18 项**回归，覆盖零网络/零任务/零预算、原文件保护、快照与搬迁、有序重复静帧、实际时长/循环、区间与尺寸拒绝、ID 冲突、并发保存、保存失败、来源/记录/输出失效、明确重建、审核回执与缺陷优先、CLI、参数消费和两个离屏表单。

最终定向 **122 项通过**，0 失败/错误/跳过，54.844 秒。全量 **649 项通过**，0 失败/错误/跳过，unittest 471.412 秒，外层 475.437 秒。全量进程还出现过两条 Tkinter Variable 析构线程提示，未造成断言失败；专项及 EXE 离屏构造未复现，不能以测试通过替代人工界面验收。

最终 wheel 在仓库外隔离 Python 中实际完成视频转 GIF、静帧转 GIF、计划检查/编译/路由、审核页/收件箱、统计和集合交付。本地 GIF 数为 2，上游任务与账本数为 0，交付保持 review_pending。合成素材和测试回执不代表真实内容验收。本批没有新建真实上游任务，也没有重试既有混合参考失败任务。

源码/打包 EXE 已离屏加载 5 个上游、25 个 binding，构造仅剪辑、纯图、原生 GIF、本地 GIF 项目面板及两个转换表单。wheel 与管理器 ZIP 通过隐私/缓存扫描。技能校验器通过；项目 Schema、模块目录、技能说明和流程参考同步更新。

证据保存在 `acceptance/20261113-dev23/`；发行目录为 `dist/dev23/`、`dist/manager-dev23/`。

## 安装和可复核产物

技能安装到 `C:/Users/FBX/.codex/skills/videocreate`，源码与安装副本 **207 个文件哈希一致**。升级前备份：`C:/Users/FBX/.codex/skill-backups/videocreate-pre-dev23-f36adf015a`。

管理器：`C:/Users/FBX/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/VideoCreate/manager/3.0.0.dev23/VideoCreateManager.exe`。sidecar 继续固定权威配置位置；原配置字节哈希不变，修订 4、5 个上游/25 个 binding 和加密凭据保留。

素材服务已切换至 dev23 EXE（PID 8628）。公网健康实例头匹配；PNG、MP4、WAV 完整 GET 的内容哈希均一致，合成检查链接已撤销。隧道继续使用 `HTTP → host.docker.internal:8765`，没有增加自动启动项。

管理器 ZIP **10,917,018 字节**，便携目录 **24,838,558 字节**；需保留完整目录，程序未签名。人工视觉、干净机器、线上参考语义、逐型号质量和实际账单仍是独立待验收项。

| 产物 | SHA-256 |
| --- | --- |
| wheel | `ef52b2ab5751e6b1a6dbf24ae58e82a184f1051d8aeae9be2f658ff3864e917d` |
| 管理器 ZIP | `3d85badab8c36e7dfa72e8dfcf361cc6fdbbad8ad4ddb8834a24263bacfd1ae2` |
| 管理器 EXE | `7914c007b621c0ec028431d8160f18844dfb280f5197d67ae7bbf80fdc404269` |

技能 ZIP 的提交、干净源码标记与校验和由对应 `.version.json/.sha256` 保存；本批安装与版本交付不表示原 73 项整体完成。
