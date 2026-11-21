# 本机素材与 HTTPS 直链

适用于用户将本机文件通过既有 HTTPS 内网穿透提供给媒体模型的场景。与上游目录使用同一个 `videocreate.config.json`，可在管理器“本机素材与 HTTPS 直链”中配置。只托管明确选择的文件快照，不暴露素材所在文件夹。

## 服务与内网穿透

```text
videocreate media-server configure --public-base-url https://YOUR_DOMAIN --port 8765
videocreate media-server start
videocreate media-server status
videocreate media-server list
videocreate media-server revoke --publication-id PUBLICATION_ID
videocreate media-server stop
```

服务监听 Windows 的 `127.0.0.1`。穿透客户端在 Windows 时，目标使用 `HTTP → 127.0.0.1:8765`；在 Docker Desktop 容器中时，目标使用 `HTTP → host.docker.internal:8765`。公网使用 HTTPS，转发全部路径。不要改为容器的 `127.0.0.1`。`/health` 返回 204，实例头必须匹配当前本机服务，旧进程或别的站点响应不算接通。

服务独立于管理器窗口，关闭窗口后仍可运行；不会自动安装系统开机服务。生成期间需保持电脑、服务和隧道在线。端口修改后先停止旧服务再启动。持久运行信息和素材快照在权威配置旁的 `local-media/`，用户文件及凭据不会打包到技能。

## 项目引用与链接

```text
videocreate media-ref register PROJECT --source FILE --kind image --role identity
videocreate media-ref host PROJECT --source FILE --kind video --role motion --upstream UPSTREAM_ID
videocreate media-ref host PROJECT --source FILE --kind audio --role sound --upstream UPSTREAM_ID --lifetime 14400
videocreate media-ref list PROJECT
videocreate media-ref check PROJECT --reference REFERENCE_JSON --upstream UPSTREAM_ID
videocreate media-ref attach PROJECT --reference REFERENCE_JSON --job JOB_ID
videocreate media-ref slice PROJECT --reference REFERENCE_JSON --start 2.5 --end 6
videocreate media-ref host PROJECT --reference DERIVED_REFERENCE_JSON --upstream UPSTREAM_ID
```

`register` 检查真实格式、大小、时长和 SHA-256，并将不可变快照复制到项目。当前支持 PNG/JPEG/WebP、MP4、MP3/WAV，单文件不超过 512 MiB，使用 FFprobe 检查。`host` 为快照生成链接，再通过公网完整 GET 核对类型、字节和哈希，成功后将链接用 Windows DPAPI 保存；项目 JSON 只保留凭据引用、源哈希、过期时间和验证证据。失败时撤销刚生成的链接。

外部已有 HTTPS 文件可用 `media-ref link PROJECT --reference REFERENCE_JSON --upstream UPSTREAM_ID --url-file PRIVATE_FILE --expires-at ISO_TIMESTAMP`，或通过 `--url-env VARIABLE_NAME` 读取；也可在终端隐藏输入。稳定链接需明确 `--permanent`，这只是用户对可用性的声明。URL 文件和环境变量不得进入项目或发行包。无需在聊天或命令参数中粘贴链接。

链接按上游、账户和源哈希绑定，更新链接保留历史且不改变源身份。默认有效期 4 小时，检查默认要求至少剩余 2 小时；可按模型排队时间调整。模型必须能在无登录、Cookie 和额外认证头的情况下读取。检查会验证重定向，拒绝私网和保留地址，不向文件服务器发送模型密钥。

管理器“生成文件直链”只创建文件发布，不自动绑定到项目；链接在结果窗口临时显示，可显式复制。CLI `media-server publish --source FILE --kind image --output PRIVATE_RECEIPT_JSON` 将链接保存到指定私有回执。日志与发布列表不输出完整链接。链接持有人在有效期内可下载；撤销和过期阻止后续访问，不能撤回已经下载的副本。

## 接入生成

`attach` 在保存计划备份后，将带 kind/role/path/sha256 的引用加入指定 job，操作设为 `reference-to-video`。重复添加相同引用不重复写入。它不改变当前任务或自动执行生成；已提交任务输入改变仍需显式 replan。旧图生视频未注明 kind 的图片保持原样，不自动迁移为多媒体请求；要使用 v2，应明确所有引用的 kind。已有 `image-to-video` 仍要求恰好一张 opening-frame，且为图片数组中的第一张。通用 `reference-to-video` 可按模型合同使用没有首帧的身份、动作或声音参考。

使用 `xingapi-video-v2` 或 `newapi-json-v2` 的 binding 必须显式配置 `media_reference_limits`。管理器型号页新增“多媒体限制”：每类数量、单文件/总字节、MIME、角色，视频和音频还需要单文件/总时长；合计数量、合计字节和链接剩余有效秒数。高级字段 `allowed_combinations` 用类型数组列出允许组合，例如 `[["image"],["image","video"]]`；`audio_reference_with_generated_audio` 是是否允许参考音频与声音生成同时使用的布尔值。未知限制不可当作无限；未使用类型的数量填 0。可另设 maximum_width/height/sample_rate/channels 等边界。供应商备注不会自动生成这些执行约束。

整批待执行任务在首个预算预留/POST 前检查本地源和全部参数，解析对应上游/账户的链接并完整核对公网文件。编译器在提示词与 reference_map 中保留用途及每类从 1 开始的序号；请求发送独立的 `images`、`videos`、`audios` 字符串数组，不把视频转首帧，不丢弃音频。只在 binding 声音开关为 explicit 时发送 `generate_audio`。持久化请求仅保存媒体元数据，XingAPI v2 响应中的文件 URL 被脱敏，下载使用原任务的认证 content 端点。NewAPI v2 脱敏输入链接和请求回显，保留结果 URL 用于 content 端点不可用时的下载恢复，见 [NewAPI 合同](newapi-media-contract.md)。

`slice` 从已注册的视频或音频按源时间的 `[start,end)` 区间生成真实片段：视频解码后重编码为 H.264/AAC MP4（有原音轨时保留），音频输出 PCM WAV 并保留采样率/声道。单独记录请求区间和实际输出时长，视频按帧、音频按采样边界量化；不是无损码流裁切。使用 FFmpeg/FFprobe，原文件与原计划不改写，不发模型请求。

派生引用带 `derivation: {path,sha256}`，指向按内容寻址的清单，保存原引用、原哈希/元数据、请求区间、输出哈希/元数据、方法版本和 FFmpeg 版本。重复裁切可复用同一记录；相同输出字节但不同来源区间保留不同派生记录。嵌套裁切最多八层，项目校验/预检重新核对整条来源链；缺失或篡改即拒绝。这证明来源记录与当前字节一致，不代表内容已审片。管理器尚无裁切表单，请使用 CLI。

`slice` 返回的 `reference_file` 应直接用于 `host --reference` 和 `attach --reference`，避免重新按原始文件注册而丢失派生信息。更新链接不改变派生身份。仍不接受未实现的原生区间字段，也未实现末帧锁定；上传的是已裁切的完整新文件。`xingapi-video-v1` 继续只支持文生视频，升级不自动转换用户 binding 或启用声明能力。真实型号参考效果以逐次样片验收为准，不从协议成功推断全部语义。

原任务的查询和下载沿用原任务号、账户及适配器快照，不依赖素材链接续期。临时链接失效不会触发重新生成。创建前最后的本地校验若拒绝请求，账本保留 not-submitted 证据和零费用，不把它计为已发出的请求；真正发送后的超时仍保持 submission_unknown。
