# -*- coding: utf-8 -*-
"""Build the handoff checklist from the committed dev43 baseline, never user config."""
import collections
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMIT = 'aed9f160ed8d07007ab5b2ef3950706ce0d3a207'
baseline = json.loads(subprocess.check_output([
    'git', 'show', COMMIT + ':videocreate/assets/module-catalog.json'], cwd=ROOT))

# ID | existing implementation | remaining work | acceptance | representative core paths
ROWS = r'''
A01|已有机器模块目录、modules list/roadmap 和真实入口/限制字段；dev43 保留 73 项状态。|按本轮 Web 边界更新模块说明，关联可复验的离线/在线证据，持续同步发行状态。|每个模块可查入口、限制、版本及待办；未实施 Web 不计成已交付。|videocreate/assets/module-catalog.json
A02|Schema 4 和 v3 兼容已落地；model/upstream/binding/route 分层，草稿禁用。|保持核心实现，设计浏览器 DTO 映射及未来字段兼容，不再另起配置格式。|不完整草稿可保存且不会进入创建候选；CLI/Web 对同一输入给出一致错误。|videocreate/src/videocreate/config/schema_v4.py
A03|展示名、备注、标签、收藏、排序和声明已有核心及旧管理器入口。|补 Web 普通/高级表单、来源日期、长文本体验；审核展示变更不影响生成内容哈希。|修改备注/价格说明不重生视频；刷新后字段保持，供应商文字仅作为文本。|videocreate/src/videocreate/catalog/presentation.py
A04|字符计数、时长/画幅/分辨率及分类型参考数量、字节、时长、角色/组合检查已有实现。|补模型真实边界、通用条件规则及 Web 结构化编辑；未知值表达一致。|边界前后和混合输入整批预检；空枚举/未知不能误当全部支持。|videocreate/src/videocreate/catalog/media_constraints.py
A05|声明、执行范围、覆写与逐操作证据已有分层；存在分用途指纹。|审计所有入口和模型变更的证据范围；Web 分层呈现，限制失效只影响相关证据。|文生视频通过不推导参考通过；备注/标价变化不使无关内容审核过期。|videocreate/src/videocreate/catalog/evidence.py
A06|按次/秒/张、币种、报价状态及条件档位已有预算/比较核心。|核实组别、最低计费、取整、有效期和退款的真实合同；完善 Web 价格编辑。|未知报价不满足硬金额限额；币种不混加；页面标价与实付分别展示。|videocreate/src/videocreate/catalog/pricing.py
A07|版本化 DPAPI 凭据和非秘密账户 ID 已实现；旧版本保留供恢复。|新增只写 HTTP 凭据边界和跨文件失败处理，复用既有加密服务。|换钥后旧任务可恢复；响应/草稿/日志无密钥；换账户/域名须保留原实例。|videocreate/src/videocreate/config/secrets.py
A08|核心有修订/token、锁、校验、备份、原子替换、历史、归档与恢复身份保护。|接入 Web 预览/提交与并发冲突；验证多文件中断和历史写失败提示。|两窗口不会静默覆盖；原实例和旧凭据可恢复；错误时文件保持可读。|videocreate/src/videocreate/config/management.py
A09|v3→v4 预演/应用和保留后续身份的恢复已有；新版配置只读。|补复杂自定义字段迁移矩阵、Web 差异与回滚呈现；不按旧草图新造 Schema。|升级/恢复保留旧默认、用户扩展和新任务身份；未知新版禁止写回。|videocreate/src/videocreate/config/management.py
A10|按地址/账户保存目录观察，新增/消失提示和来源绑定禁用草稿导入已实现。|迁移到 Web，补来源过期/身份变化/重复导入交互和受控只读网络检查。|导入不覆盖备注、不启用、不删除旧接入；目录名不能自动证明合同。|videocreate/src/videocreate/catalog/observations.py
B01|双向目录、媒体/家族/收藏及任务参数/参考数量过滤、排除原因已有。|补 Web 目录/筛选/排序和缺失条件提示；完整预检保持在 Codex。|按上游或家族都能定位 binding；筛选匹配不标成可立即生成。|videocreate/src/videocreate/catalog/suitability.py
B02|核心能按模型/上游约束提供选择，技能规定唯一组合使用、歧义先询问。|审计全部自然语言别名和四种输入；在 Codex 合并缺失的图片/视频选择。|明确组合不重复问；缺项只问必要项；不偷偷选择相似型号。|videocreate/src/videocreate/selection.py
B03|selection_id、配置/候选绑定及序号校验已有离线实现。|补多菜单、跨项目和配置并发的端到端回归；Web 不取代对话选择。|回复序号落到原菜单稳定 ID；过期/非法/跨项目回复零创建。|videocreate/src/videocreate/selection.py
B04|一次/项目/全局范围和已有任务快照优先已有实现。|接入 Web 全局默认设置；审计一次选择从不自动写成全局。|图片/视频独立；已有项目/任务不被 Web 全局更改迁移。|videocreate/src/videocreate/selection.py
B05|route 解释、参数/报价预演、选中范围就绪与对比已有。|补每 adapter 消费报告及未知条件说明；Web 展示本地比较，完整预检留在 CLI。|无关坏上游不阻断选定路线；排除原因和报价单位可追溯。|videocreate/src/videocreate/catalog/bindings.py
B06|切换影响预演、固定任务和明确备用策略已有基础。|补全状态组合及多项目影响回归；Codex 解释切换范围。|仅指定未提交任务更改；已提交/未知始终使用原快照。|videocreate/src/videocreate/selection.py
B07|主 v3 图片/视频执行入口有选择门禁，离线策划可独立进行。|审计保留的 legacy/动画/批量入口，确保所有创建路径同一门禁。|无头缺项返回 selection_required 且零 POST；不因无关图片配置阻断本地剪辑。|videocreate/src/videocreate/runtime/jobs.py
C01|核心服务与 CLI 已分离；旧 Tk 直接复用核心，离线实现状态保留。|将主界面改为本机 Web 薄 API/DTO/前端；停扩 Tk，不把旧 C01 通过等同 Web 完成。|HTTP 直接调用核心；无 shell 拼接、无第二套预算/路由逻辑。|videocreate/src/videocreate/config/management.py
C02|旧表单可管理上游/型号/密钥/启用，核心增改归档已在用。|实现 URL/Key 两字段 Web 入口，内部 ID 自动生成，名称/备注可选；受控复制、归档、只写密钥和模型高级维护。|三家上游仅 URL/Key 即可保存，不要求用户写内部型号/binding/route；复制不泄露/复用不该复用的凭据。|videocreate/src/videocreate/config/management.py
C03|旧能力/价格/备注表单及徽标已有，校验走共享核心。|落实原型五页签、声明/执行/实测分层，基本与高级字段分离。|字段错误定位清楚；供应商声明不能绕过 adapter；取消保留原文件。|videocreate/src/videocreate/catalog/presentation.py
C04|旧目录搜索、收藏、比较、默认及任务筛选有实现。|在 Web 重做易用的表格/详情、比较和图片/视频默认策略；补键盘与缩放。|2–4 接入比较不联网/不生成；跨币种和未知价清楚；默认独立保存。|videocreate/src/videocreate/catalog/pricing.py
C05|旧 UI 有未保存提醒、冲突、JSON 修复、备份；dev44 强退恢复尚未完成。|Web 使用单一保存、来源 token、差异/冲突/修复；重新设计安全草稿，不延续 Tk widget 状态。|关闭/刷新/强退均无静默覆盖；未提交密钥不进草稿；损坏/新版配置受控。|videocreate/src/videocreate/config/repair.py
C06|目录观察、逐操作证据、离线 allowlist 诊断预览/导出已有。|增加 Web 安全检查/记录页及受控导出；生成试测统一由 Codex 执行。|所有 Web 按钮零媒体创建；默认诊断匿名，源变化重新预览，文件不覆盖。|videocreate/src/videocreate/diagnostics.py
C07|历史 wheel/便携 EXE 已在本机验收安装，干净机器未验收。|改为 Python+本机 Web 启动脚本和静态资源分发；迁移独立素材服务启动；补卸载/升级文档。|无需 Node 或 EXE UI 即可离线配置；依赖/端口明确，升级保留配置/凭据/8765。|install.ps1
D01|已取得用户提供的统一视频 create/query/content/HTTPS 参考文档并实现版本化合同。|继续核对各型号操作范围、报价、错误、上传差异；不再把已提供基础文档列为缺失。|每型号精确 ID 和各操作合同有来源；标价/账单差异有记录。|videocreate/references/xingapi-contract.md
D02|seedance2.5-V 独立接入已有真实 30 秒有声文生视频样片，保留原任务。|补参考输入、原生音频开关、边界及实付核对；实际听审/动作/口型尚未全过。|分别记录文生/图参/视参/音参结果；不重生现有样片以充当 UI 测试。|videocreate/src/videocreate/adapters/xingapi.py
D03|S/933/C/Q 等型号可独立登记，统一 adapter 有离线夹具。|逐精确 ID/账户核实合同和价格，再按授权做各操作小样，不继承 V 的通过记录。|每型号仅开放已核实组合；超时/失败恢复不重复 POST。|videocreate/src/videocreate/adapters/xingapi.py
D04|Wan 家族和独立 binding 的配置/统一协议基础已有。|逐 Wan 型号核实参数、参考语义、报价与跨站等价性，完成授权小样。|Wan 证据与 Seedance/Grok 独立，不因同 /v1 推断兼容。|videocreate/src/videocreate/adapters/xingapi.py
D05|参考按图片/视频/音频、角色与顺序贯穿校验/编译/快照；可派生时间切片。|补广泛真实语义、last-frame/特定模型角色合同；切片不是原生时间/末帧字段。|MP4/WAV 不塞图片字段；同类顺序和哈希保持，旧首帧行为可恢复。|videocreate/src/videocreate/media_references.py
D06|已有 8765 本机素材服务、HTTPS 隧道、发布/校验/撤销与账户范围传输记录。|补运行生命周期、过期/失效恢复与服务独立启动；S3/COS/OSS 暂非当前依赖，asset_id 上传按实际合同另做。|公网文件字节一致且整个生成期间可读；只发布明确文件，下载失效不重生视频。|videocreate/src/videocreate/media_server.py
D07|按字符/字节与 typed HTTPS 数组、数量/大小/时长/组合的批量预检已有。|补所有 adapter 的参数消费证明及各模型边界；不得仅登记能力就声称 payload 可发送。|整批参数错误在任何创建/预留前发现；无静默丢参考或互相冲突字段。|videocreate/src/videocreate/adapters/xingapi_references.py
D08|异步创建一次、保留完整 ID、同账户轮询、下载及跨域认证保护已有。|按真实服务补 SSE、asset_id、原生 cancel/idempotency，完善 Retry-After/下载有效性。|502/空响应只重查原任务；下载非媒体不落为 MP4；无文档不伪造取消/幂等。|videocreate/src/videocreate/adapters/video.py
E01|unknown 分类和冻结、已知任务恢复、明确拒绝才可备用等已有离线验证。|审计每创建入口和崩溃窗口；继续保留对账证据要求。|超时/5xx/只有 trace ID 零自动重建；内容失败不偷偷换上游。|videocreate/src/videocreate/runtime/failures.py
E02|本机注册 v3 项目的远端在途及 create/poll/download RPM 已持久化，共享组取最严限制。|补并发进程/重启压力及旧项目注册体验；明确不覆盖其他机器/外部客户端。|多个 binding 共用额度不能绕过；未知提交占位不自动过期。|videocreate/src/videocreate/runtime/quotas.py
E03|已有局部健康/冷却和故障范围处理。|完善退避、抖动、Retry-After、缺省响应与可读进度，按具体上游合同验收。|一个型号失败不冻结全站；不以付费探针自动恢复健康。|videocreate/src/videocreate/runtime/health.py
E04|快照固定 URL/账户/adapter 与凭据版本，改默认/归档后恢复已有离线覆盖。|Web 保存/轮换/归档回归沿用这些不变量，审计原账户密钥轮换。|原 task 只 GET/下载，禁止被新默认或新账户改写。|videocreate/src/videocreate/runtime/state.py
E05|预算预留/结算、未知与多币种以及生成/保留秒数指标已有。|真实失败收费/退款/结算核对，补复杂计费规则和账单导入范围。|候选/重做分别记账，未知实付不当零，保留 8 秒不按 8 秒估算 30 秒生成费。|videocreate/src/videocreate/runtime/budget.py
E06|状态从 state/jobs/review 派生，已有本机项目注册和旧任务面板。|完善可重建索引与跨项目状态查询，入口留 Codex/CLI；不开发新的 Web 任务中心。|删缓存可重建且账本不漂移；显示原任务/候选/未知与成本来源。|videocreate/src/videocreate/production.py
F01|production status/next、阶段输入输出/阻塞与检查点已有。|补所有分支和依赖的统一解释、缺失工具提示，留 Codex 工作流。|继续同项目定位当前阶段，不从头重生；状态以现有计划/任务/审核为准。|videocreate/src/videocreate/production.py
F02|brief 引导、主题/受众/目标/规格、outline 阅读稿已有离线实现。|完善技能引导质量和实际用户体验，不再扩展创作 Web 表单。|足够信息即可推进；偏好缺失只问影响创作的部分。|videocreate/src/videocreate/authoring.py
F03|director 结构化剧本、阅读稿导出和来源版本绑定导入已有离线实现。|审计长对白/多场景/动画 sidecar 的一致性和实际创作质量。|可读稿与结构源单向导出/受控导入明确，镜头 ID 不因改稿漂移。|videocreate/src/videocreate/authoring.py
F04|video/edit-only/mixed-video/image-only/gif-only/gif-local 及动画/系列分支有基础。|补科普/新闻/网页等分支整合及跳步原因，完成真实工作流覆盖。|纯剪辑不要求上游，纯图无视频时间线，分支共享执行底座但不混淆产物。|videocreate/src/videocreate/planning/profiles.py
F05|逐步/自动策略、选定检查点与来源预览已有；不是无人值守执行循环。|由 Codex 连续推进已授权步骤，明确授权/预算边界，不再造 Web 自动工作台。|既有授权内不机械逐镜确认；策略保存既不授权收费也不批准媒体。|videocreate/src/videocreate/production_policy.py
F06|五层映射、creative audit、编译与局部预检已有。|补主题/剧本/分镜/声音到实际请求的可读解释和早期能力反馈。|能解释单镜输入来源、最终参数及未消费项，不把计划验证当艺术验收。|videocreate/src/videocreate/planning/creative_audit.py
F07|输入影响、候选保留、来源局部审核与最终编辑失效已有。|覆盖复杂依赖、引用/声音/时间线变更的影响；在 Codex 输出局部影响清单。|改字幕/备注零生成，改动作只影响相关镜和实际依赖。|videocreate/src/videocreate/authoring.py
F08|status/next 和 token 绑定 continue-local 能定位计划、导入、渲染、审片页、交付。|完善 Codex 的继续制作指引和失败恢复；保留生成显式入口，不迁入配置 Web。|继续复用当前产物；过期 token 重新预览；本地动作无上游创建。|videocreate/src/videocreate/production_continue.py
F09|不同产物类型的交付清单、映射、审核状态与集合交付已有。|补可读说明和所有分支的一致性，成本未知/审片未完成完整呈现。|清单哈希绑定实际文件；review_pending 不伪装正式验收成片。|videocreate/src/videocreate/production.py
G01|跨项目角色/场景/道具/声音不可变版本及项目拷贝/哈希已有离线实现。|补批量检索、跨版本对照、来源追溯及实际复用体验，入口留 Codex/CLI。|修改原库文件不会静默改变旧项目；导入不继承媒体审批。|videocreate/src/videocreate/asset_library.py
G02|身份/服装/表情/风格分层卡片、本地对照板和引用快照已有。|补自动抽帧/跨版本比较、真实身份稳定验收和局部变更影响。|原图/首帧/候选可对照；对照板不等于通过身份或动作质量。|videocreate/src/videocreate/project_assets.py
G03|道具状态/物理条件与场景资产已有共享卡片。|补复杂尺度/可达性/布局约束和实际接触/遮挡验收。|道具来源与动作条件进入分镜；计划声明不能代替实际接触检验。|videocreate/src/videocreate/project_assets.py
G04|动画主题与角色版本化和共享执行底座已有。|完善主题/世界/风格包独立版本与迁移，不为每套角色复制执行器。|同底座可切主题，旧项目引用版本不变。|videocreate/src/videocreate/animation
G05|有哈希/区间/开场条件的互动库和描述性动作建议已有。|补失败撤销、适配展示与更广实际审阅样例；描述保持 description-only。|未播放观察不进已审核动作库；换主题不假定动作已适用。|videocreate/src/videocreate/animation
G06|连载/独立集及声线快照已有基础。|补乱序创建、重选声音和角色/道具/场景状态不污染的真实验收。|独立集不继承上集结尾，连载才按明确连续性；源快照完整。|videocreate/src/videocreate/series.py
H01|原生视频声、独立音轨、静音/保留源声已有。|补声音路线消费报告和实际听审，严格尊重用户选择。|出现对白不自动安装 TTS；计划台词不自动当实听字幕。|videocreate/src/videocreate/timeline/render.py
H02|固定声线/系列快照与既有配音入口保留。|在 Codex 完善试听、局部换声及可选语音/口型服务真实验证；不做新声音 Web。|逐字对白、说话者、非人脸口型分开观察；健康检查不代表声音合格。|videocreate/src/videocreate/animation/voice_cast.py
H03|旧 ASR/字幕相关入口和时间线字幕已保留。|按需要接入可选 ASR/对齐到 v3，检查额外台词/截半句和说话者。|字幕依据实际听到的内容；ASR 文本不自动批准音质。|videocreate/src/videocreate/timeline/model.py
H04|v3 转场、滤镜、响度、烧录、格式 4 及旧 edit-plan v1/v2 的新项目迁移已有。|补编码/字体/字幕/声音差异的真实比较和更多受控编辑效果；留 CLI/Codex。|实际像素/音频及完整解码通过，源不变；迁移不带旧媒体审批。|videocreate/src/videocreate/timeline/finishing.py
H05|未实现速度曲线、补帧、动态遮罩/跟踪和屏幕合成完整能力。|按实际项目需求选做，定义派生映射/伪影预览/可选依赖；优先级 P2。|保存原片与实际派生链，补帧不冒充原生高帧，修改后重新审片。|videocreate/src/videocreate/timeline
H06|可播放/听的本地 review page、前后片对照和观察导出已有。|完成用户实际播放/听审体验、区间定位和工具可用性；它是项目审片页，不是配置 Web 扩张。|连续动作需视频证据、声音需听审；开页面/抽帧不自动通过。|videocreate/src/videocreate/review/page.py
H07|指定任务新候选/replan、局部剪辑/声轨和影响预览已有。|完善缺陷定位→局部修复→复验的实际路径与预算解释。|旧失败/候选保留；只重做明确选中任务；不弱化验收条件掩盖缺陷。|videocreate/src/videocreate/runtime/candidates.py
H08|按审核来源统计有效镜头、已知生成/保留秒、重做和分币种费用已有。|补理解反馈、合格成本解释及代表性样本，真实费用未知继续未知。|说明分母与样本范围；不以单一艺术分或旧过期审核代替判断。|videocreate/src/videocreate/production_metrics.py
I01|科普 research/claim/narration、历史/新闻保留工具已有。|将需要的旧流程接入 v3 阶段，完善来源、主张与 AI 示意标记。|来源可核对；生成示意不冒充事实证据；阶段可恢复。|videocreate/src/videocreate/education.py
I02|Muse 工作流准备/交接包已有，网页执行仍 prepared_only。|在新会话确认可调用工具后实现真实提交/恢复/下载/对账，不以工具目录存在宣称已接通。|实际网页任务和文件回执可核对；失败回原任务，不自动重复提交。|videocreate/src/videocreate/workflows.py
I03|ChatCut/剪映等素材或草稿导出桥保留。|验证实际安装版本/任务工具导入与还原效果，失败仍可交付原生 MP4。|导出成功与编辑器实际导入分开；需要真实打开/渲染证据。|videocreate/references/legacy-v2-workflow.md
I04|GPT/Grok 图片、纯图/GIF 与本地视频/序列帧转 GIF、审核和集合交付已有。|逐 binding 的生成/编辑/GIF 合同小样，循环/体积/透明检查和真实异步/SSE按需补齐。|动画帧数与连续播放验证；本地转换不依赖视频上游，不能当模型 GIF 已验证。|videocreate/src/videocreate/image_production.py
I05|未建立可比的多模型场景/质量/延迟/成本基准数据集。|定义同条件样本、模型专属提示与统计口径，再在授权预算内采样。|无可比样本不做质量排行/用途推荐；不同模型替代需明确选择。|videocreate/assets/module-catalog.json
J01|Schema/配置/加密/冲突/修复已有大量离线及发行验证。|增加 HTTP DTO、CSRF/Host、Web 双窗口、密钥跨文件中断和干净用户数据保护。|真实配置不进包，原始备份可核对，未来版本只读，故障不丢恢复身份。|tests/test_provider_management.py
J02|稳定编号、任务筛选与范围已有离线覆盖。|新增 Web 默认与技能协同，补四种输入、别名、跨项目/多菜单和全部创建入口矩阵。|菜单过期零创建，已选项目不重复问，图片视频独立。|tests/test_catalog_task_filter.py
J03|统一协议、typed 参考、精确 ID、诊断隐私有 fixture 和测试。|补 HTTP/浏览器合同与各 adapter×operation 边界矩阵，以及未核实真实合同。|假服务器断言 payload/认证/请求数；测试密钥哨兵不进入响应/日志。|tests/test_xingapi.py
J04|unknown、恢复、配额及并发预算有离线故障覆盖。|补 Web 换钥/归档与真实多进程/断电窗口，审计下载和旧任务回归。|以实际 POST 数量和账本核对，无重复创建，无未知占位泄漏。|tests/test_submission_unknown.py
J05|多 profile、政策/继续、迁移、时间线和局部审核有离线与仓库外夹具。|补真实创作分支、复杂依赖和已有 30 秒样片连续动作/听审。|小样与全片分开，改字幕不重生，源通过不自动批准最终剪辑。|tests/test_production_continue.py
J06|已有 XingAPI 文生视频样片和目录观察；不等于各 binding/参考/声音通过。|按后续明确生成授权/预算开展逐操作小样及账单核对；优先复用已有产物。|记录完整本地回执，公开报告脱敏；离线夹具从不标为在线通过。|videocreate/references/runtime-and-review.md
J07|dev43 1063 全回归、wheel/技能/便携 EXE 的仓库外和本机安装验收已完成。|新 Web 全链路、静态资源入包、离线/干净机器、升级/回滚/独立素材服务及文档同步。|版本/源码/安装字节一致、零秘密包；发布记录明确在线/人工未核实范围。|docs/20261113-dev43-acceptance.zh-CN.md
'''

# ID | priority | title | maps | dependency | acceptance
WEB = r'''
W01|P0|冻结页面与职责边界|C01,C02,C03,C04,F08|无|确认原型只配置上游；Codex 创作/生成不搬入 Web，基本/高级和单保存规则落文档。
W02|P0|搭建可选 Web 工程和离线静态构建|C01,C07,J07|W01|Vue/TS 构建资源由 Python 同源服务；纯 CLI 不强装 Web 依赖，运行不需要 Node；冻结兼容当前 Python 3.9 的依赖，或明确完成运行时升级迁移。
W03|P0|安全只读 DTO 与 HTTP 错误合同|A03,A05,C01,J03|W02|所有列表白名单；legacy 明文凭据/加密值/引用不回显；不返回 raw config 或任意异常正文。
W04|P0|本机会话与网络边界|A07,C01,J01,J03|W02,W03|loopback、Host/Origin/CSRF、DNS rebinding、CORS、CSP、会话引导和密钥哨兵测试通过；无任意文件/shell/URL代理。
W05|P0|配置摘要、真实路径和只读模式|A02,A09,C05|W03,W04|版本/修订/来源路径可见；缺失/损坏/未来版本区别处理，不静默初始化覆盖。
W06|P0|前端上游/模型目录主视图|B01,C02,C04|W05|真实 DTO 替换演示数据；搜索、类型/家族/收藏、详情、空态、加载/失败清楚。
W07|P0|配置预览/提交事务|A08,C05,J01|W05|expected_token+草稿/预览绑定、白名单 patch、核心校验、差异、锁、备份、单次提交、冲突 409。
W08|P0|URL/Key 简化入口和上游维护|A07,A08,C02,E04|W06,W07|首次只填 URL/Key，名称可选、内部 ID 自动生成；保存与接入识别结果分开；账户/地址更改走新实例，旧引用保留，复制不复制敏感值。
W09|P0|只写密钥与凭据轮换|A07,C02,E04,J04|W04,W07,W08|复用 DPAPI；保留旧版本；失败不破坏原引用；无未提交密钥持久化/响应/日志泄露。
W10|P0|Codex 接入整理与模型高级维护|A03,A04,A05,C03,D01,D07|W06,W07|Codex 依据已有 adapter 合同/文档匹配精确 ID、操作和参数，保存来源；不凭模型名或目录猜协议，不以收费 POST 试错；无法确认显示待补资料，手工协议不是用户必填。
W11|P1|报价与条件档位|A06,C03,C04,E05|W10|币种/单位/组别/有效期/已核对状态明确；未知不为零；对子表单一次保存。
W12|P1|筛选/比较/收藏/排序|B01,B05,C04|W10,W11|共享现有 suitability/pricing；2–4 个比较零网络/生成；排序稳定，不改变 Codex 已发菜单。
W13|P0|图片/视频默认和缺省策略|B03,B04,B07,C04,J02|W07,W10|绑定启用接入；ask/use-default 明确；不改项目/旧任务，不把一次选择写全局。
W14|P1|只读检查与目录观察/草稿导入|A10,C06,D01,J03|W04,W08,W09,W10|明确点击才 GET；缓存按地址/账户；目录缺失保留已保存 URL/Key 并提示文档途径；导入来源绑定、重复和过期受控、零生成；合同另行匹配。
W15|P1|证据详情与匿名诊断导出|A05,C06,J03,J07|W05,W10|按操作区分；allowlist 脱敏预览→新文件导出；变化失效，零外部凭据读取。
W16|P0|备份、恢复、无效 JSON 修复|A08,A09,C05,J01|W07|受控文件 ID；精确原文备份、来源/草稿绑定、未来版只读、保留后续恢复身份。
W17|P1|未保存提醒和安全草稿恢复|C05,J01|W07,W10,W11|重新设计 Web 草稿；不序列化 Tk 或未提交密钥；来源变化先合并/另存，不覆盖新配置。
W18|P0|本机启动器、端口与浏览器|C07,J07|W02,W04,W05|双击脚本/CLI、8787、--no-browser、依赖诊断、重复实例身份/配置路径校验和端口冲突；具体参数实施时冻结。
W19|P0|Codex/CLI 互通与旧任务回归|B02,B03,B04,B06,B07,E04,J02,J04|W08,W09,W10,W13|仅填 URL/Key→Codex 目录/合同整理→同文件候选；已知/未知协议、四种选择、换默认/归档后原 task 恢复；识别过程不创建收费任务。
W20|P1|素材服务独立启动与旧界面退役|C07,D06,E04,J07|W18,W19|8765/现有隧道和文件哈希保持；先迁服务再退 EXE 启动方式；不删除旧项目/安装包。
W21|P1|易用性与无障碍验收|C02,C03,C04,C05,J07|W06,W10,W11,W13,W14,W16|键盘/焦点、长中文、100–200%缩放、窄屏、取消/恢复/错误状态；三上游任务由用户体验验收。
W22|P0|全回归、干净环境和发行交接|J01,J02,J03,J04,J05,J07,C07|W01–W21|冻结源码、适当全回归、wheel/静态资源、仓库外启动、升级回滚、秘密扫描、版本/模块目录/文档一致；报告不虚称在线/人工通过。
'''

def parse_rows(text):
    return [row.split('|') for row in text.strip().splitlines()]

detail = {r[0]: r for r in parse_rows(ROWS)}
assert len(detail) == 73
web = [dict(zip(['id','priority','title','maps','depends_on','acceptance'], r)) for r in parse_rows(WEB)]
for w in web:
    w['maps'] = w['maps'].split(',')
    w['status'] = 'planned-production; interactive-prototype-only'

work = []
for old in baseline['work_packages']:
    ident, current, remaining, acceptance, paths = detail[old['id']]
    source_paths = paths.split(',')
    assert all((ROOT/p).exists() for p in source_paths), source_paths
    modules = [m for m in baseline['modules'] if ident in m.get('work_packages', [])]
    tests = sorted({t for m in modules for t in m.get('test_evidence', []) if (ROOT/'tests'/t).is_file()})
    channel = 'Web 配置 + 共享核心' if ident[0] in 'AC' else 'Codex / CLI + 共享核心'
    if ident[0] == 'B': channel = 'Codex 选择；Web 目录/全局默认'
    if ident[0] == 'J': channel = '测试 / 发行 / 文档'
    work.append({**old,'current_implementation':current,'remaining':remaining,
                 'acceptance':acceptance,'delivery_surface':channel,'source_paths':source_paths,
                 'existing_test_index':tests,'web_subitems':[w['id'] for w in web if ident in w['maps']]})
counts = dict(collections.Counter(w['status'] for w in work))
assert counts == {'partial':60,'implemented-offline':11,'planned':2}, counts
assert {w['id'] for w in work} == set(detail)
data = {'schema_version':1,'date':'2026-11-13','type':'planning-handoff-not-runtime-config',
        'baseline':{'version':'3.0.0.dev43','commit':COMMIT,'source':'committed module-catalog.json',
                    'work_packages_total':73,'counts':counts,'full_regression_tests':1063},
        'scope':'Web only configures upstreams/models; production remains in Codex/CLI',
        'web_items_are_subitems_not_extra_original_packages':True,
        'production_web_implemented':False,'work_packages':work,'web_subitems':web}
dest = ROOT/'docs/20261113-development-checklist.json'
dest.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')

names = {'A':'配置、元数据、能力合同','B':'明确选型与编号交互','C':'本机 Web 配置界面（替代旧 EXE 主界面目标）',
         'D':'星光、Seedance、Wan 与多媒体协议','E':'运行、恢复与费用','F':'制作步骤与创作产物',
         'G':'角色、主题、资产与系列复用','H':'声音、剪辑、审核与修复','I':'专项模块','J':'验证与交付'}
labels = {'implemented-offline':'离线实现已落地','partial':'部分实现','planned':'待开发'}
out = ['# VideoCreate 最新完整开发清单\n',
'''日期：2026-11-13。本清单替代旧路线图中“继续做 EXE 管理器/把制作功能扩进管理器”的实施方向，保留原 73 项编号和完整需求。Web 只管理上游/模型；所有主题、剧本、生成、任务、剪辑与审片仍由 Codex + 技能 + CLI 完成。旧审片 HTML 是项目产物，不属于配置后台。\n
## 状态与计数\n
已安装并通过发行验收的是 **3.0.0.dev43**；源码的 dev44 是未完成工作，不计入本清单交付。dev43 基线为 **73 项：11 项离线实现、60 项部分实现、2 项待开发**。这是实现范围，不是完成率；11 项也不等于全功能在线/人工验收。H05、I05 是两个待开发项。\n
本轮交付交互原型和文档；正式 Web 的 W01–W22 都尚未实现。W 编号只是原工作包的子任务，不另加到 73 项。C01 的旧“离线实现”表示服务分离已存在，不能据此认为 Web 已完成。dev43 1063 项测试通过是历史发行证据，本轮只运行原型与文档检查。\n
最新决定：采用本机 Web，默认用户只填 URL/Key，显示名/备注可选；Codex 依据已知合同整理模型和协议，高级字段无需用户首次填写。URL/Key 自动整理全链路仍待实施，不承诺任意上游即插即用，不用收费 POST 猜协议。先前仅 JSON 入口方案已经取消。\n
权威证据：[dev43 验收](20261113-dev43-acceptance.zh-CN.md)、[完整交接](20261113-new-chat-handoff.zh-CN.md)、[机器可读清单](20261113-development-checklist.json)。旧需求原文来自提交 `aed9f160ed8d07007ab5b2ef3950706ce0d3a207` 的 module-catalog；下列“剩余/验收”按用户最新边界更新。\n
## 建议实施批次\n
| 批次 | 任务 | 交付条件 |\n| --- | --- | --- |\n| M0 设计交付 | 原型、73 项映射、交接 | 本轮完成；等待后续新对话实施授权 |\n| M1 安全只读壳 | W01–W06、W18 的初始启动 | 能在本机打开真实只读目录；不泄露凭据、不写配置 |\n| M2 配置可编辑 | W07–W11、W13、W16 | 三家上游、密钥、模型、默认、冲突/恢复闭环 |\n| M3 管理体验 | W12、W14、W15、W17、W21 | 比较、目录草稿、诊断、未保存/恢复、可用性通过 |\n| M4 技能互通/迁移 | W18–W20、W22 | 同文件协同、旧 task 恢复、8765 服务保持、完整发行 |\n| M5 协议/创作完善 | D/E/F/G/H/I 的剩余项及 J06 | 按依赖和真实项目价值推进；收费实测另有明确范围/预算 |\n
P0/P1/P2 保留原需求优先级；批次按依赖执行，P0 不表示把所有原 P0 同时开发。下一迭代先完成 M1/M2，避免重新扩展成视频工作台。\n
## Web 实施子清单\n
所有接口/命令/前端目录都是拟议设计，详见[Web 原型设计](20261113-web-provider-config-design.zh-CN.md)。每项都需独立记录实施版本及验收证据。\n''']
for w in web:
    out += [f"### {w['id']} · {w['priority']} · {w['title']}\n",
            f"- 关联原项：{', '.join(w['maps'])}；依赖：{w['depends_on']}；状态：正式功能待开发。",
            f"- 验收：{w['acceptance']}\n"]
out += ['## 原 73 项逐项台账\n',
        '下面的“已有实现”以 dev43 为基线；路径指向可复用的现有核心或证据，不指向尚未创建的 Web 文件。测试索引只是已有覆盖的入口，不表示整个原项已通过全部验收。\n']
for group, title in names.items():
    out.append(f'## {group} — {title}\n')
    for w in work:
        if not w['id'].startswith(group): continue
        out += [f"### {w['id']} · {w['priority']} · {labels[w['status']]}\n",
                f"原始需求：{w['requirement']}\n",
                f"**已有实现：** {w['current_implementation']}\n",
                f"**剩余工作：** {w['remaining']}\n",
                f"**验收条件：** {w['acceptance']}\n",
                f"**入口归属：** {w['delivery_surface']}。Web 子项：{', '.join(w['web_subitems']) or '无；保留为核心/制作工作'}。\n"]
        links = [f'[{p}](../{p})' for p in w['source_paths']]
        out.append('代码/证据：'+'；'.join(links)+'。\n')
        if w['existing_test_index']:
            ts = w['existing_test_index']
            out.append('已有测试索引：'+'；'.join(f'[{t}](../tests/{t})' for t in ts[:4])+('；其余见机器清单' if len(ts)>4 else '')+'。\n')
out += ['''## 跨模块验收与暂停事项\n
- Web 与 CLI 必须共用来源 token、校验、报价和恢复身份，不直接返回原始配置，不写回遮蔽字符串。\n- 真实密钥、DPAPI 文件、带签名 URL、用户项目和原始任务回执不进入原型/前端包/公开诊断。\n- 未拿到 task ID 或创建结果不明只对账；已有 task 查询/下载不触发新创建。\n- 离线夹具、目录可见、技术解码、连续播放/听审和实付是不同证据，逐 binding × operation 记录。\n- 旧 Tk 的新界面功能、可播放时间线/波形/拖拽编辑器不进入这轮 Web 配置交付；相关核心工作可按用户后续需求继续。\n- dev44 两项旧 manager 生命周期失败需记录并隔离；不要为了结束旧路线继续打磨被替换的 Tk 强退恢复界面。可复用的 config/drafts 服务先审计后决定。\n- 不重生现有 30 秒样片作为新界面测试，也不因本轮设计文档自动恢复已清除的目标。\n
发布前按实际改动完成必要专项、完整回归及仓库外验收；此前版本的测试数不能自动覆盖新版本。清单更新要保留尚未验证的范围，不用“一键通过”覆盖人工与在线证据缺口。\n''']
(ROOT/'docs/20261113-complete-development-checklist.zh-CN.md').write_text('\n'.join(out),encoding='utf-8')
print(json.dumps({'ok':True,'original_work_packages':len(work),'baseline_status_counts':counts,
                  'web_subitems':len(web),'output':str(dest)},ensure_ascii=False))
