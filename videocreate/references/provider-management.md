# 上游、型号和制作进度

配置格式 v4 与项目格式 v3 独立。旧 v3 配置可读；新建配置默认在缺少明确型号时询问。统一文件仍是 `%LOCALAPPDATA%/VideoCreate/videocreate.config.json`，不另建 providers 数据库。`manager` 与 CLI 调用相同的配置事务、校验与选型服务。

## 管理与迁移

```text
videocreate providers list
videocreate providers show
videocreate providers migrate
videocreate providers migrate --apply
videocreate manager
videocreate providers discover --upstream UPSTREAM_ID
```

`show` 脱敏输出并返回保存 token。`save --file FILE --token TOKEN` 先校验，再检查并发修改、备份和原子替换。修改地址或账户需要建立新实例；归档保留旧凭据供恢复。恢复备份保留后来增加的身份为禁用条目，不能通过回滚丢掉其恢复入口。未知新版本保持只读。`config validate --ready` 是全配置体检，实际生成只检查选定路线。

管理器提供上游/型号表单、备注、收藏、排序、能力与价格页、只读目录查询和草稿导入。添加型号时分别指定媒体类型、远端 ID、adapter 与操作。远端 ID 大小写原样保留。供应商声明放入 `declared_capabilities`，展示报价放入 `listed_pricing`；这些字段不会授予执行能力。可执行约束放入 `capability_overrides`。草稿的 adapter 为 `unconfigured`、enabled 为 false，不会进入生成候选。

管理器的表单变量绑定各自控件和 Tcl 解释器，关闭所属控件时在界面线程移除 trace 和变量。关闭目录查询或素材服务面板会取消界面轮询；已开始的服务操作继续完成，界面回调不传给后台线程。关闭面板不停止素材服务、不取消远端任务。CPython/Tk 运行时暂留仍被 Python 对象引用的解释器，在后续界面操作或正常进程退出时由界面线程释放，避免后台垃圾回收触发 Tcl 跨线程析构。

目录可按媒体类型、家族、搜索词和收藏筛选，并按配置顺序、名称、上游或家族排序。Ctrl/Shift 选择 2–4 个型号，点击“比较所选”查看并排参数、完整备注、供应商声明与来源、按操作区分的实测和同一参数下的估算。原样保留不同币种与费率单位，不作价格排名；估算复用预算核心，支持条件档位、最低计费、取整、生效与失效时间。条件不唯一、过期、未核实或仅有展示价时，金额保持未知。

比较仅核对参数范围，不检查实际素材、HTTPS 直链、凭据或完整请求，不替用户选中路线，也不提交生成。所选为草稿、禁用或归档时明确显示；单型号编辑、收藏、归档和默认设置拒绝多选，避免误改。主表现在直接显示条件档位费率，详情按可读字段展示，供应商声明与执行限制分开。

价格页新增“条件档位”，可用表单增改操作/分辨率/画幅/时长区间与每次/每秒费率；0 是明确的零费率，空白表示未填写。备注支持多行。多媒体限制页可直接勾选七种类型组合，并用是/否/空白记录音频参考与声音生成能否同时使用；普通字段没有覆盖的高级约束继续保留。

同样的离线比较可由 CLI 调用：

```text
videocreate providers compare --binding BINDING_A --binding BINDING_B --seconds 5 --operation text-to-video --resolution 720p --aspect-ratio 16:9
```

“逐操作实测”按钮按文生视频、图生视频等操作分别检查回执。一个操作的成功不代表另一个操作通过，失效证据不能产生通过状态，存在失败记录时不被成功记录隐藏。目录、合同、小样和内容质量仍分别展示。

提示词上限支持 Unicode 码点、UTF-16 单元或 UTF-8 字节。`prompt_limit` 配置必须指定计数规则；不能把未知的“15000 字符”假设成 15000 字节。现有图片 adapter 仍有 4096 字节硬上限。图片/视频/音频可通过 [本机素材服务](media-hosting.md) 建立 HTTPS 传输绑定，`xingapi-video-v2` 在明确 media_reference_limits 后可传三类数组，不接受把视频/音频塞进图片字段。

价格可记录按次、按秒、最小秒数、取整步长、有效期和条件档位。档位须唯一匹配；未知报价不能满足硬金额上限。`listed_pricing` 不用于预算。报价和实际账单分开；不同币种分别汇总，不自动折算。共享账户的多个入口可填相同 `capacity_group`，共用最严格的提交并发上限；远端在途与 RPM 的本机范围见下方共享账户配额说明。

## 编号选择

```text
videocreate selection list PROJECT --kind video
videocreate selection list PROJECT --upstream UPSTREAM_ID --model MODEL_ID
videocreate selection choose PROJECT --selection-id RETURNED_ID --number 2 --scope project
videocreate selection impact PROJECT --job job-001
videocreate jobs run PROJECT --job job-001 --binding BINDING_ID
```

缺项返回结构化 `selection_required`，退出码 2，没有收费创建。向用户展示 choices 的原序号、上游、远端型号、备注、报价和排除理由，再调用 choose。菜单绑定配置哈希及项目；配置改变后应重新列举。`--scope once` 返回 binding ID，不保存项目选择；把它传入当前生成命令。`--scope project` 保存独立的图片/视频选择。全局默认只由明确用户要求设置。

命令行 `jobs run --model/--upstream/--binding` 只作用于未提交任务或明确选择的终态重做。已接受、未知或下载中的任务沿用原快照。改全局默认不重生视频。已完成片段需要换路重做时，使用指定 job、`--retry content/replan` 与原因；不能用普通继续请求触发新创建。明确固定选择不继承全局自动备用策略。

管理器的“生成任务执行”与 `jobs prepare/execute` 共用带 token 的任务/依赖、路线与费用预检，缺项直接展示编号选择。当前窗口的临时选择或明确的项目选择只影响新尝试；已受理任务保留原快照。“仅恢复原任务”与 `jobs resume` 在运行时禁止创建。执行、重做和对账/账单回执入口详见 [runtime-and-review.md](runtime-and-review.md)。

## 共享账户配额

上游编辑器的“配额”页可设置 `max_remote_inflight`、`create_rpm`、`poll_rpm`、`download_rpm`，均为正整数；留空表示未配置，不能据此宣称供应商无限。它们与 `max_concurrent_submissions` 和图片/视频工作线程数分开。同一非秘密账户标识或容量组的入口使用传递关联后的最严格限制，包括归档入口。

`providers quotas --config FILE --upstream ID` 显示已保存策略、本机在途、请求窗口、未知任务和缺失项目；加 `--project PROJECT` 登记已有 v3 项目。新执行的项目自动登记，已有 `production track` 项目也纳入。管理器可在选择上游后点“查看共享账户配额”。查看不发请求、不改配置，但会更新本地派生缓存。

提交前在项目锁和全局配额锁内检查，先于预算预留和持久化尝试。排队、运行中、未知提交、未确认终态的本地超时持续占用远端名额，没有自动 TTL。已确认远端完成或失败后释放；下载失败只恢复原下载。任务真相仍来自项目 `state.json`；索引只存路径与已观察占用，项目不可读时保留占用，恢复原状态后重新推导，不提供强制清空未知任务的按钮。

创建、轮询、下载各有持久化 60 秒滑动窗口；跨进程使用同一配置目录，重启不会重置。创建准入可能计入后续本地预算/写入失败的尝试，作为保守限速而不是已发送/实付统计。查询或下载限流会留下可恢复状态、原任务号和建议等待时间，不重发 POST；稍后按原任务恢复。一个内容下载调用中的端点/备用链接重试分别消耗下载请求名额，跳转链按一次客户端调用计。远端 Retry-After 继续由相应协议处理，本地限速不改变供应商响应。

范围仅为本机同一配置目录、已登记的 v3 项目；其他机器、外部客户端、旧版生成程序和未登记旧项目不计入。此功能不能当作服务器总配额或跨机器调度。已知旧项目应在启用硬在途上限前登记。

## 制作进度和剧本

```text
videocreate production status PROJECT
videocreate production next PROJECT
videocreate production impact PROJECT
videocreate production metrics PROJECT
videocreate production script-export PROJECT
videocreate production script-import PROJECT --file EDITED_SCRIPT_JSON
videocreate production checkpoint PROJECT --stage theme --hash CURRENT_HASH --reason USER_REVIEW
videocreate production policy PROJECT --mode auto-within-authorization --reason USER_INSTRUCTION
videocreate production track PROJECT
videocreate production projects
videocreate production deliver PROJECT --output-name preview.mp4
```

阶段包括主题、故事大纲、剧本、角色场景、分镜、参考、生成、剪辑、审核和交付。status 从当前五层计划、state.json、审核回执计算，不复制运行状态。stage 文件只保存创作检查点和内容哈希；修改内容后检查点过期。无角色/参考的计划会跳过相应步骤。纯图/GIF 与仅剪辑使用各自的导入、审核和交付路径；“继续制作”按当前步骤提供对应入口，完整策略界面仍在推进。

剧本阅读稿由 director 单向导出。JSON 交换稿带源版本哈希；导入只更新 director 并保留备份，既有 job/candidate 不被删除。改字幕不改变视频输入哈希。impact 列出输入已变化的镜头、应检查的依赖和可复用输入；它不自行执行重做。

`auto-within-authorization` 让 next 跳过重复的创作确认；它不直接调用上游、扩大授权或自动通过媒体审核。`assisted` 显示首个未确认创作步骤。未知提交优先进入对账。

## 实际审片与能力目录

`review page PROJECT` 导出 `reviews/viewer.html`，可在浏览器播放本地媒体、定位保留区间、对照相邻片段并下载审核 JSON。记录实际观察后，用 `review apply --receipt FILE` 进入现有哈希和区间校验。页面不判断质量，未观看/聆听的层保持未核实。

`modules list` 显示模块入口、限制、测试文件；`modules roadmap` 映射 73 项开发工作包。`implemented-offline` 表示有本地实现与测试，不等于供应商合同、真实生成或艺术质量已经通过。具体已测范围看日期验收报告和 `binding-evidence`。

星光接口文档已由用户提供，专用 `xingapi-video-v1` 支持文生视频，`xingapi-video-v2` 增加类型化多媒体 URL 数组；原任务保持创建时协议。参见 [接口合同与限制](xingapi-contract.md)；各 binding 只开放核对的参数组合，其余型号仍保留草稿。Grok 的不同上游也可能返回不同型号，必须记录 `provider_reported_model` 并独立判断。

`library add/list/show/import/impact` 与管理器的“角色与素材库”共用本机配置目录下的素材库，项目保存独立快照。详见 [跨项目素材与统计](asset-library.md)。
