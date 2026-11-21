# 上游、型号和制作进度

配置格式 v4 与项目格式 v3 独立。旧 v3 配置可读；新建配置默认在缺少明确型号时询问。统一文件仍是 `%LOCALAPPDATA%/VideoCreate/videocreate.config.json`，不另建 providers 数据库。`manager` 与 CLI 调用相同的配置事务、校验与选型服务。

dev44 候选增加本机 `config-web`：用户主要填写 URL/Key，名称、备注可选；Codex 根据已知合同整理模型和协议。Web 与 CLI 共享配置事务、备份、原账户凭据版本和独立图片/视频默认，页面不生成或恢复媒体。详见[Web 使用与恢复边界](config-web.md)。旧 Tk 表单的“应用后主窗口保存”行为保留为历史兼容；Web 实体只有一次面向用户的保存动作。

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

上游、型号、价格档位和凭据表单在关闭时检查尚未应用的输入，包括无效数字/JSON；主窗口关闭也检查已打开的创作、素材导入、流程策略和迁移表单。取消任一步会保留所有窗口及输入。放弃表单不会自动应用、保存、生成或录入密钥；配置表单“应用”后仍需主窗口“保存配置”，价格档位先应用到型号表单。重新载入配置会先核对配置表单草稿，仅在磁盘读取成功后关闭过期配置表单；制作项目表单保留。域名/端口和流程策略成功保存后重置其草稿基线；策略重新载入也提示放弃修改。本地复制/保存等事务完成前会阻止用户关闭，远端生成面板仍可关闭并稍后恢复原任务。强制结束进程不会保存尚未应用的表单。

## 损坏配置的离线修复（dev40+）

启动时若 JSON 语法损坏、不是 UTF-8 或不符合受支持的配置结构，管理器打开“配置检查与修复”。初始不显示原文；需要时选择“读取原文到编辑器”，或“载入有效备份为草稿”。编辑仅发生在本机，原文可能有旧式明文密钥，不要复制到聊天。替换有改动的草稿或关闭窗口时可以取消；保存事务进行中不能关闭。

先预览，再按该预览保存。源文件、草稿文本或基准备份变化后，原预览失效。替换前将原始字节（含 BOM、换行或无法解码的内容）保存并校验为 `backups/<原名>-damaged-<SHA256>.raw`，再原子写入配置，成功后返回管理器。`.raw` 是原始损坏证据，不能当有效 JSON 备份自动恢复。修复历史不记录配置值；历史写入失败会明确提示配置已修复及原文备份已保留。

```text
videocreate providers repair-inspect --config DAMAGED
videocreate providers repair-preview --config DAMAGED --file LOCAL_DRAFT --token SOURCE_SHA [--baseline VALID_BACKUP]
videocreate providers repair-apply --config DAMAGED --file LOCAL_DRAFT --token SOURCE_SHA --preview-token PREVIEW_TOKEN [--baseline VALID_BACKUP]
```

可解析原文和选中基准备份中的已知上游地址/账户必须一致，不能用旧备份偷偷换账户；不同账户需要不同稳定 ID。缺失的已知型号、上游、binding、route 保留，前三类归档，binding 禁用；仍有损坏的保留条目必须在草稿明确修正。预览列出保留条目、保护的身份与未核实范围。无法解析的原文不能证明全部历史身份，须在本机对照备份；离线修复也不证明密钥可用或旧任务可恢复。DPAPI、项目、任务、账本不改，不联网、不生成媒体。明确不支持的版本保持只读，包括后续语法损坏的较新版本；有效配置继续使用普通保存/恢复入口。

## 目录浏览与能力

dev42 起，“只读检查 / 导入目录”打开“上游目录变化与草稿导入”，执行一次 `GET /models`。界面可搜索并筛选相比上次新增、未再出现、可导入以及本地未出现在目录的型号；尚未导入但本次消失的型号也保留变化行。“查看已保存目录”直接读取本地观察，不联网、不读密钥。刷新失败不替换上一份完整观察；首次观察明确没有可比基线，完整空目录可记录，但不会删除或禁用本地接入。

```text
videocreate providers discover --upstream UPSTREAM_ID
videocreate providers catalog-show --upstream UPSTREAM_ID
videocreate providers catalog-show --upstream UPSTREAM_ID --file OBSERVATION_JSON
videocreate providers import-models --upstream UPSTREAM_ID --kind video --file CATALOG_REPORT_JSON
```

观察在配置目录的 `runtime/catalog-observations/` 下按上游 ID、地址和账户隔离，保存原样远端 ID、来源 URL、带时区时间及内容 SHA-256。相同账户的凭据轮换可沿用观察；不同账户或地址不可混用。旧无账户范围的 `runtime/catalogs/` 文件原样保留，不当作对比基线。损坏、哈希/文件名不符和不支持的观察保持原文件但不参与自动对比；报告列出忽略数量。SHA-256 只核对本地记录完整性，不是供应商签名或真实性认证。

GUI 导入前重新核对配置和来源观察，变化后需重读；仅新增禁用、`unconfigured` 草稿，写入目录 URL、观察时间及哈希来源。已有接入的备注、报价、限制和启用状态保持，不自动合并同名的跨上游型号。应用只修改管理器待保存配置，需主窗口“保存配置”才落盘；关闭时可保留尚未应用的媒体类型/家族输入。关闭窗口仅停止 UI 回调，已开始的 GET 可完成并保存观察，不取消网络工作。

CLI 导入接受完整 discover/catalog-show 报告或原始观察 JSON，校验来源范围与所选 ID，预览不改配置；`--apply --token TOKEN` 沿用配置并发保护。手动 `{"ids":["Exact-Model-ID"]}` 仍可导入，但没有目录观察来源。任何目录可见/消失、草稿导入或哈希一致都不能证明协议、可用性、参考语义、价格或影片质量。

dev41 起，“按任务筛选”可填写操作、生成时长、分辨率、画幅和声音开关；选中“核对参考数量”后分别填写图片、视频、音频数，0 表示明确不使用该类素材。没有勾选时不假设数量为 0。图片任务不能填写视频时长/分辨率/画幅/声音参数。预览展示全部目录的符合、不符合和未核实条目及原因；应用到主表后继续叠加上游、家族、搜索和收藏条件。可以同时显示排除条目，或清除任务筛选；不会修改配置、项目选择或默认路线。条件修改后须重新预览，关闭时可以保留尚未应用的输入。

CLI 使用同一服务，默认只输出参数范围相符的条目，`--include-excluded` 显示全部条目和原因；`--upstream`、`--kind`、`--family`、`--query`、`--favorites`、`--order` 可组合。任务文件只接受以下字段，未填写的参数不参与筛选：

```json
{
  "operation": "reference-to-video",
  "seconds": 10,
  "resolution": "720p",
  "aspect_ratio": "16:9",
  "reference_counts": {"image": 2, "video": 1, "audio": 0},
  "generate_audio": true
}
```

```text
videocreate providers filter --scenario-file TASK_JSON --include-excluded
```

时长、条件档位和声音参数复用请求校验；多媒体数量、组合和参考音频与生成声音冲突复用实际参考校验。旧图片参考仍区分总数和附加图上限。备注/供应商声明不会授予支持能力；草稿、禁用、归档和未登记路线不能成为匹配项，未知参考合同保持“未核实”。报价按原币种和预算规则估算，缺少视频时长或价格未核实时金额未知，不能当实付或排名。

范围相符仅证明已填写参数与数量满足配置；没有读取或伪造素材，不检查实际提示词、参考角色/顺序/哈希/大小/时长/URL、凭据、完整请求、预算或远端服务，也不证明生成品质。正式编号选择和生成预检仍必需。此筛选不为图像任务推断任意宽高比、GIF 或尺寸参数；图片参数继续由正式图片请求预检检查。

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

价格可记录每请求、每秒、最小秒数、取整步长、有效期和条件档位。图片另支持 `per_image`，按请求明确发送的出图张数计价，可与每请求费相加；省略 `n` 时张数未知，不推定供应商默认值，不使用参考图数量、GIF 帧数或返回数量。按张仅用于图片，不能与秒费或时长规则/条件混用。选中档位的费率替代基础费率，档位须唯一匹配；未知报价不能满足硬金额上限。`listed_pricing` 不用于预算。报价和实际账单分开；不同币种分别汇总，不自动折算。旧 dev43 必须拒绝含新费率的配置，不静默删字段。共享账户的多个入口可填相同 `capacity_group`，共用最严格的提交并发上限；远端在途与 RPM 的本机范围见下方共享账户配额说明。

## 异常退出后的加密配置草稿（dev44+）

Windows 管理器每 1.5 秒将尚未保存的配置，以及有修改的上游、型号/参数/备注、条件价格档位和素材域名/端口表单暂存到当前配置目录 `runtime/manager-drafts/`。每个会话独立使用 DPAPI 文件，写临时文件前已经加密，仅原 Windows 账户可解密；不新增明文配置或密钥备份，不写入 `secrets.dpapi`。未点击“加密保存”的凭据输入窗口不在暂存范围。配置中本来存在的明文凭据随配置加密保存，不会出现在草稿文件原始字节中。

强制退出后，重新打开同版本管理器，点击“恢复配置草稿”查看时间、表单数和状态。原进程仍运行、无法确认已退出、配置已改变、版本不符或无法解密时不能恢复；原文件保留，不自动合并。恢复成功只放回待保存配置和原始表单输入，未完成的 JSON、无效数字、未应用子档位也原样保留。须核对、应用表单并点击“保存配置”，继续走正常校验、差异确认和并发保护。恢复不生成、不联网、不启动素材服务或发布链接。

每次已完成的快照通过原子替换保留，暂存失败时窗口提示且保留先前快照。强制退出前不足一个暂存周期的最新输入可能丢失，长时间 UI 阻塞会推迟暂存。正常关闭并确认放弃会移除本会话草稿；取消关闭保持；其他会话、已恢复的来源草稿不会自动删除，可明确选择“丢弃所选”。进程号复用或权限不足时保守阻止，不假定原进程死亡。跨版本自动迁移、断电后磁盘持久性保证、创作/项目/任务/选择与修复表单的异常退出恢复仍不包含。其他系统保留正常编辑与关闭检查，暂存提示不支持 DPAPI，不降级为明文。

## 脱敏诊断预览与导出（dev43+）

管理器“脱敏诊断导出”读取磁盘已保存配置、当前缓存目录和逐操作证据摘要；未保存的编辑不包含。可选择当前上游或全部上游，先预览“实际导出内容”，再选择新的 JSON 文件。默认使用报告内部代号，隐藏上游/型号/binding 标识；确需定位时可勾选加入型号 ID 和 API 主机名。账户/凭据版本、密钥及其引用、环境变量名、备注、文档与素材 URL、本机路径、任务号、原始日志、回执原文和实际价格金额始终不输出；主机名不包含 URL 路径、查询或签名。自定义参数字符串省略并计数，标准分辨率/画幅与数值限制保留。

报告包括配置结构状态、本地依赖是否可找到、接入的启用/草稿/归档、协议及执行约束、报价核实状态、路线关系、缓存目录变化计数及逐操作目录/合同/小样/质量证据摘要。不解密 DPAPI、不读取环境密钥、不联网、不执行 FFmpeg、不创建媒体；证据校验会读取其引用文件及相关任务以核对已有质量记录，不枚举全部项目。未知不是失败，已有通过记录也不保证当前凭据、完整请求、上游可用性或艺术质量。

```text
videocreate providers diagnostics --config CONFIG_JSON [--upstream UPSTREAM_ID] [--include-identifiers]
videocreate providers diagnostics-export --config CONFIG_JSON --file LOCAL_PREVIEW_JSON --output NEW_REPORT_JSON --token PREVIEW_TOKEN
```

第一条返回本机预览封装，含来源 token 和选项；在本机保存它供第二条使用。对外分享第二条输出的报告文件，封装本身不是分享报告。`external_credential_reads` 只统计外部凭据查询；保存 JSON 中已有的明文值仅用于清理可选标识中的误填内容，值不输出。勾选标识后仍须核对将披露的型号 ID 与主机。无法解析、无效或不支持的新配置只输出有限状态及问题数量，不复制原文或修改配置；CLI 可在管理器不能正常启动时使用。诊断报告不是可导入的上游配置。

导出重新核对源配置字节和当前摘要；配置、缓存观察、证据或依赖摘要变化后需重新预览。目标必须为新的 JSON 文件，使用同目录临时文件和原子“不替换”发布，已有文件保持；需支持硬链接的本机文件系统。导出期间用户关闭被阻止，预览期间关闭仅分离 UI 回调。报告不会自动上传或发送。

读取现有证据现在也使用录入时的结构/结果/布尔检查与方法校验；未知结果、缺失审阅者、矛盾的通过检查等回执保留为失效，不能生成通过摘要。原始证据不改写。

## 从保存名称查询身份

用户用名称描述新请求时，Codex 先提取媒体类型及实际出现的上游/型号词，再使用离线查询。不要把整句自然语言传入名称参数：

```text
videocreate providers identify --kind video --upstream-name "保存的上游名称" --model-name "保存的型号名称或精确远端 ID"
videocreate providers identify --kind image --model-name "精确远端 ID"
videocreate providers identify --kind video --upstream-name "保存的上游名称"
videocreate providers identify --kind video
videocreate providers identify --kind video --upstream UPSTREAM_ID --model-name "精确远端 ID"
```

`--config CONFIG_JSON` 可指定同一份配置。上游词按稳定 ID 优先，否则精确匹配保存名称或 platform；型号词按已知稳定 model ID 优先，否则精确匹配 remote_model、binding 显示名称、model 显示名称或已配置 family。大小写、空格均保留，不作子串、同义词或任意别名推断；家族名通常仍需选择具体型号。只给一个词就只限制该维度，两个都不给就列该媒体的全部接入，不自动套用默认。

结果包含规范 ID、匹配字段、配置 token 和接入状态。`identified` 只表示查到唯一身份，`readiness=not-checked` 明确没有检查凭据、请求、预算或可用性。`ambiguous` 的 `needs_choice` 指出上游、型号或同组合下的 binding 歧义；禁用、草稿及归档项参与歧义，不用“唯一启用项”猜用户账户。名称未知或上游暂无相符接入返回 `no_matches`，不能扩展到其他账户。`identifiers_redacted=true` 的结果不能作为可执行 ID，须核对误填到身份/标签中的凭据后重新查询。

对未遮蔽的唯一结果，把规范 `model_id`、`upstream_id`、必要时 `binding_id` 交给现有选择与完整请求预检；多结果先澄清 `needs_choice` 中的维度，再用稳定 ID 限定。需要编号时调用下面的正式 selection 菜单并保留它返回的编号，查询结果自身没有可选序号。配置改变后重新查询/列菜单。查询不写配置、项目选择或任务状态，不解密凭据、不联网。旧任务恢复仍以原快照或已有身份解析器为准，不能用显示名、当前默认或该查询重新分配旧任务账户。

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


算力AI Flash 720p 的视频参考使用新增 `newapi-json-v2` 合同与独立 reference binding，保留原图片路线。参数、至少一张图片要求、本机保守范围及操作步骤见 [NewAPI 视频参考](newapi-media-contract.md)。接入测试不记为线上生成证据。
