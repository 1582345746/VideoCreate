# 用户配置

配置默认位于 `%LOCALAPPDATA%/VideoCreate/videocreate.config.json`。运行 `config init` 创建一次；直接编辑该文件即可。配置示例和 JSON Schema 与技能随附。URL、auth 密钥、精确 remote_model、启用绑定是接入必填项；安装、validate 和 show 不调用付费生成，show 总是脱敏。

新配置的默认生图模型为 `gpt-image-2.6`。目录同时列出 `gpt-image-2.6-flare`、`gpt-image-2.6-sunburst`、`gpt-image-2.5` 和 `grok-imagine-image-2.0`，但新增 binding 默认禁用且能力未验证。`model_selection.image.policy=first-compatible` 会按 `candidates` 顺序，在创建前根据已配置操作、参考数、输出格式和可用凭据选择第一个可用型号；它不代表画质排序。没有评测证据前，不根据 `flare` 或 `sunburst` 名称推测速度或质量。用 `assets image ... --model MODEL` 固定一次请求的型号；显式型号不跨型号兜底。已有配置和运行中任务保留原型号/快照。

API 对象不能混为一谈：

- `models` 是内部 canonical model 和 family，比如 Grok 或 Seedance。
- `upstreams` 是可有多个实例的服务器 URL、凭据、并发上限和超时。
- `bindings` 指定每个模型在具体实例上的精确远端 model ID 和一个 adapter。
- `routes` 对每个 canonical model 选择 preferred binding 与同模型候选。`fixed` 不切备用；`automatic-same-model` 只允许明确列出的同模型 binding。

`execution.max_concurrent_image_tasks` 与 `execution.max_concurrent_video_tasks` 分别限制本机同时处理的生图/视频 job，范围 1-50；`upstreams.<id>.max_concurrent_submissions` 只限制同一 upstream 正在进行的创建请求。示例配置默认允许每个上游最多50个创建请求，作业池为6；请按实际额度调低。视频任务创建后，轮询与下载可并行运行。并发任务仍逐项记账，未知提交会暂停该 job 且不会自动重复创建。

可选的 `browser_services` 和 `workflows` 与这些 API 对象位于同一个 JSON。网页服务填写 `enabled`、`driver`、`base_url`、精确 `allowed_origins` 和 `requested_operations`；不填写 API key、cookies 或密码。`codex-browser` 表示偏好内置浏览器，不代表当前会话一定有页面操作工具。`playwright-local` 仅用于用户选择的独立会话，当前尚未打包站点执行器。`requested_operations` 只是希望使用的操作，不是能力验证。

每个 workflow 的有序 `stages` 用 `executor: api/browser` 选择执行方式。API 阶段可指定 canonical `model` 和候选 `binding`，省略时使用对应图片/视频默认模型及其首选 binding；浏览器阶段指定 `service`，不能同时指定 API 模型。`input_from` 只可引用前面的图片阶段，且当前操作必须消费图片。`defaults.workflow` 可选；未指定时调用命令需明确 `--workflow`。旧配置不含这些字段仍保持兼容。`workflow prepare` 只写本地交接包，不自动执行阶段或宣称已提交。详情见 [muse-browser.md](muse-browser.md)。

目前的 adapter 是 Sub2API JSON、NewAPI JSON 和 NewAPI multipart；图片是独立 binding。新增服务器实例只填 JSON；新增 wire protocol 必须实现 adapter 和 fixture tests。remote_model 保留大小写。Sub2API JSON 的音频是 model default，不能通过本适配器控制；能力未验证前，参考音频/视频、首尾帧、原生高帧率保持 unknown 并阻断。

若上游明确使用 `POST /v1/videos` JSON 且首帧字段为 `first_frame`（例如 RapidApi 网页客户端所示合同），选择 `newapi-json-v1`，设置 `adapter_options.primary_image_field: first_frame`。它只传一个 opening-frame，出站时按目标画幅裁切副本，原图不变；额外指导图会在提交前拒绝。省略该选项继续使用原有 `images` 数组字段。此选项不代表支持 last-frame。

`capability_overrides` 是上游合同证据的人工配置入口，不是目录探测。只填已核实的条件限制。能力快照等级仍保持 `configured`。精确模型名在目录出现也不代表生成成功。

`routes[MODEL]` 只允许同一 canonical model 的 binding。`automatic-same-model` 的图片和视频 route 可在候选 binding 中故障切换；只有 `adapter_options.confirmed_rejection_http_statuses` 中经该服务验证为“创建前明确拒绝”的状态码才允许自动新建备用任务。网络错误、超时、HTTP 5xx、200 但无任务 ID、结果解析失败都不会转备用，以免重复计费。显式 `--binding` 是固定路由。已受理的视频任务继续使用原快照。

图片默认为 PNG。binding 的 `capability_overrides.output_formats` 列出确实支持的格式；GIF 必须同时声明 `animated_output: supported` 才允许原生动画输出。GIF 输入需同时声明 `image/gif` 和 `animated_input: supported`。这些字段只是操作者录入的合同，不是自动探测结果。`media inspect FILE` 可检查 GIF 是否多帧、各帧延时和循环次数；`media export-gif PROJECT --source FILE.mp4 --job-id ID` 用 FFmpeg 将本地视频片段转为 GIF，不调用上游。不要把动画 GIF 静默当作视频首帧；视频参考目前要求显式导出静帧。

`media frames-gif PROJECT --frame A.png --frame B.png --fps 5 --job-id ID` 按顺序将同格式静帧变成 GIF；`media extract-frame PROJECT --source INPUT.gif --at 0.4 --job-id ID` 显式提取静帧并记录来源哈希。转换均为本地操作。多帧 GIF 的 `review image` 必须在完整播放观察后提供 `--temporal-observation`；首帧检查不能批准动态内容。

图片合同可用 `capability_overrides.image_sizes`、`image_quality_values` 限定参数。`adapter_options.image_request_fields` 控制是否传 `n/size/quality/response_format/output_format`，`image_response_format` 选择 `b64_json/url`。省略时兼容原 Images 请求。省略 size 字段的 binding 要求 `--size auto`；省略 quality 时仅接受 auto，不能静默忽略显式覆盖。GIF 请求若返回静态 PNG 或单帧 GIF，会保留响应为 output_invalid，重新解码也不会变成成功。

`models list --family gpt-image` 按家族、媒体类型、型号、平台/实例列出绑定；`models explain-image --output-format gif` 在创建前解释选型，均不创建媒体。自动路由在提交失败后将该 binding 冷却 60 秒，影响新的自动选择，显式 binding 与已受理任务继续固定原服务。冷却不触发付费探测，也不重发未知提交；同账户应复用 upstream 实例 ID，共享本机并发槽。

`muse-video` 单次请求最多 10 秒。VideoCreate 会按模型身份强制该上限，能力覆盖不能把它提高；超出时长会在路由、编译和 `jobs run` 提交前被拒绝。需要更长成片时，将其拆成多个不超过 10 秒的任务，再在本地时间线上剪辑拼接。

`auth` 必须且只能包含一种凭据来源：JSON 内的 `api_key`、环境变量名 `env`，或本机 DPAPI 的 `secret_ref`。`config show`、日志、项目快照不得输出凭据值。发布包不包含真实用户配置。

受硬金额上限约束时，必须在对应 binding 添加经上游确认的 `pricing.currency`，以及按请求和/或秒的价格；否则阻断，不能把未知记为零。没有 hard cap 时仍受 max request 数限制。

离线检查：

```powershell
python scripts/videocreate.py config validate
python scripts/videocreate.py config validate --ready
python scripts/videocreate.py config show
python scripts/videocreate.py config effective
python scripts/videocreate.py config effective --project <project> --job job-001
python scripts/videocreate.py doctor
```

`doctor --read-only` 才查询 `/models`，不创建媒体。它报告目录命中而非视频可生成性。

`config effective` 不读取密钥，逐项显示值和来源。新生成采用项目 job 的 model/binding 优先于配置默认；显式 binding 选择固定到该候选。项目 brief 的画幅、分辨率和节奏优先于配置。已存在的 task 继续按原快照恢复，不因默认值变更搬到另一上游。声音以每个 shot.audio 为准，配置 audio_mode 是旧项目初始化默认，不能替代每镜策略。

独立图片可通过 `assets batch PROJECT --manifest images.json` 提交。Manifest 使用 `{"images":[{"job_id":"frame-001","prompt":"...","references":[],"size":"1024x1024","quality":"auto"}]}`；所有条目会先完成本地校验，再按 `max_concurrent_image_tasks` 并发调用。使用 `review inbox PROJECT --pending-only` 查看已完成待审素材；图片通过 `review image PROJECT --job ID --status pass|fail --reviewer ID --observation "实际观察"` 写入哈希绑定的审核记录。

`capabilities status --binding <id>` 展示 configured、catalog、contract、smoke 和 quality。后四项分别有自己的证据；一个阶段通过不会替另一个阶段通过，也不会自动修改 capability_overrides。`doctor --read-only` 会保存目录响应及其哈希。其他证据用 `capabilities record --binding <id> --receipt <JSON>` 导入，字段为 binding_fingerprint、stage、result(pass/fail)、operation、reviewer_id、method、checks（布尔观察项）、evidence（绝对 path/sha256）。质量回执还需 `project_root`、原 attempt_id/task_id，并且证据必须包含该项目状态中同一 binding 下已完成任务的原始下载视频及匹配哈希。这样可阻止抽帧或文本文件被误记为动态质量观察。证据过期或缺失维持 unverified；报告显示 reported_pass 表示已记录观察，不能推广为所有场景的能力保证。

升级迁移用 `config migrate --source <旧配置目录> --destination <新配置目录>` 先预览，追加 `--apply` 才写入，已有目标配置不会覆盖。旧项目用 `config migrate-project --project <旧项目>` 检查，`--apply` 只写兼容迁移回执，原 project/state/素材不转写。旧创作合同不能机械变成新的导演合同；通过 `legacy <原命令>` 恢复旧任务，新创作另建 v3 计划。
