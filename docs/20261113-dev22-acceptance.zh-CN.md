# VideoCreate dev22：纯图与原生 GIF 制作流程

日期：2026-11-13；版本：3.0.0.dev22。继续原路线图 F04/F08/F09、I04、J05/J07 的相关范围；原 73 项总目标仍进行中。

## 功能与真实范围

此前独立图片/GIF 已有生成与审核入口，但统一步骤仍要求视频镜头、生成秒数和时间线。dev22 新增 `image-only` 与 `gif-only` 五层计划分支，通过 `generation-plan.image_jobs` 描述独立图片任务，不制造视频 job、shot、clip 或时长。

| 范围 | 本批行为 |
| --- | --- |
| 计划 | 每张图声明 ID、提示词、text-to-image/image-edit、尺寸、quality、输出格式、可选型号/binding 和有序参考图哈希；空提示词是待完善草稿 |
| 预检 | `plan validate/compile/route` 检查参考字节、操作与格式，复用图片路由和真实参数消费报告；未指定选择继续返回编号菜单，零创建 |
| 执行 | `production images-run` 复用原 image batch、任务、预算、配额及同型号策略；批次后项参数不合法时创建数为 0。它不授予付费权限 |
| 恢复 | 已完成且输入/输出未变时复用原型号/binding，改全局默认不重建；unknown/submitting 继续核对原尝试，不因“继续制作”再次付费 |
| 重做 | 输入改变显示 stale；必须明确选一个 job，给出 content/replan 和 reason。旧尝试与账本保留，不用标题变动重画 |
| 阶段 | 跳过未使用的大纲、剧本和视频剪辑；生成、实际审核、交付按当前图片任务推导 |
| 创作单 | `production script-export` 导出只读图片提示词/规格/参考阅读稿；编辑源为 image_jobs，不再导出空白视频剧本 |
| 审核 | `review page/status/image` 进入图片流程；按原始字节、当前输入及真实回执判定。GIF 必须多帧并声明完整播放观察；静帧和单帧 GIF 不能通过动图审核 |
| 交付 | `production deliver` 输出图片集合 manifest：项目输出路径/哈希、可用实际元数据、参考映射、原路线标识、预算和未核实项；全部计划输出须存在且当前有效 |
| 统计 | 单列图片数、当前有效数、审核通过/失败数和动图数，不伪算为生成视频秒数或模型动作质量 |
| 管理器 | 步骤面板显示图片任务/状态、图片统计与实际图片/GIF 审核页；不在此批承诺完整可视创作编辑器 |

原生 GIF 必须由所选图片 binding 明确启用，不能因模型目录可见便开放。`media export-gif/frames-gif` 本地派生仍保留独立入口，尚未归入这条原生 GIF 制作分支。混合图片/视频/本地来源项目仍未统一。图片集合交付目前是引用项目输出的 manifest，不是独立搬运的素材 ZIP。

静态图片的保留头部检查器可能不能确定实际宽高，未知值保持未知；请求 size、brief 画幅和返回成功不能证明上游实际像素尺寸或内部采用的型号。GIF 结构检查不代表动画内容自然或符合提示词。没有新增上游实测、实际审片、账单核验或干净机器/人工界面验收。

## 离线验证

新增 **15 项**测试：独立分支、零视频结构、批次后项错误零创建、已完成复用与固定原路线、输入变更/局部重做、结果字节变动、unknown 不重发、多帧/单帧 GIF、完整播放要求、缺失/错配回执、缺少选型、参考哈希、只读创作单、CLI 和原生离屏步骤面板。

相关 75 项兼容测试通过；最终定向 **104 项通过**（37.797 秒），包含旧图片/GIF、视频交付、仅剪辑、阶段、媒体审核、统计和管理器表单。全量 **631 项通过，0 失败、0 错误、0 跳过**（外层 448.281 秒）。

wheel 已在仓库外隔离 Python 中分别验证纯图和 GIF 全链路 fixture：每项 mock 创建一次、继续执行不新增 mock 调用、计划有效、交付保持 review_pending。其上游响应为合成 fixture，真实外部创建数为 0；没有把测试回执作为实际内容通过。源码与构建 EXE 均实际离屏载入 5 上游/25 binding，以及仅剪辑、纯图、GIF 面板。

证据目录：`acceptance/20261113-dev22/`；发行目录：`dist/dev22/`、`dist/manager-dev22/`。本批开发/测试未修改权威配置或凭据，未重新生成既有喜剧或失败的参考任务。

## 安装与发行

技能已安装到 `C:/Users/FBX/.codex/skills/videocreate`，与源码 **205 个文件哈希一致**；升级前备份为 `C:/Users/FBX/.codex/skill-backups/videocreate-pre-dev22-534ac50726`。权威配置修订仍为 4、5 个上游/25 个 binding；配置字节哈希不变，原账户和加密凭据保留。

管理器安装到 `C:/Users/FBX/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/VideoCreate/manager/3.0.0.dev22/VideoCreateManager.exe`。在故意错误的默认目录环境中，EXE 仍由 sidecar 读取权威配置，并实际构造仅剪辑、图片和 GIF 面板。检查是离屏构造/数据验证，未进行人工视觉或干净机器验收。

素材服务已切换至新版 EXE（PID 29776）；公网健康实例头匹配，PNG/MP4/WAV 完整 GET 哈希一致，合成检查链接已撤销。隧道沿用 `HTTP → host.docker.internal:8765`；没有安装自动启动项。

wheel、管理器 ZIP 已通过隐私/缓存扫描。管理器 ZIP **10,904,816 字节**，便携目录 **24,821,776 字节**，需保留完整目录；目标机无需另装 Python，媒体处理仍依赖 FFmpeg/FFprobe。程序未签名。

| 产物 | SHA-256 |
| --- | --- |
| wheel | `88b743256b3b09bdec058318cf4fa55da86f7b328228edfa798e9a8e6802480e` |
| 管理器 ZIP | `2030b854e94ac8d4beed91d9c4a338518e32ed7c597bd4b9fd39422a26cf49a6` |
| 管理器 EXE | `5deb2af4778f34f9f9652757330bfdb0c4349867fd8b602c5c96af65a498f122` |

技能 ZIP 的提交、干净源码标记和校验和由相应 `.version.json/.sha256` 记录。总目标仍进行中，未以本批阶段成果替代 73 项完整验收。
