# NewAPI 类型化视频参考合同

`newapi-json-v2` 用于经过明确核对的 `POST /v1/videos` JSON 合同。它将图片、视频、音频分别发送为 `images`、`videos`、`audios` HTTPS 字符串数组，并使用 `seconds`、`aspect_ratio`、`resolution`。不发送 `reference_videos`、`duration`、`ratio`，不把视频变成图片输入。模型决定如何利用参考，接口接通不证明动作、节奏或人物一致性已验收。

创建读取协议 task ID，`request_id` 默认只是追踪编号。查询 `GET /v1/videos/{task_id}`；下载先尝试原 content 端点，再使用返回的结果 URL，跨域不附带模型 Key。持久化记录隐藏输入链接及请求回显，保留恢复下载所需的结果 URL。任务号、账户、接口版本和参数快照保持固定，已受理任务不依赖参考链接续期。未知受理状态不能重新 POST。

旧 `newapi-json-v1` 继续用于原图生视频路线和历史任务，不能把它的图片数组当作视频参考支持。v2 必须声明 `media_reference_limits`，并在新任务中明确每条参考的 kind 和 role。`reference-to-video` 支持身份图与动作视频等组合；`image-to-video` 另要求一张 opening-frame 且在图片序列第一位。v2 仅实现 `images` 图片数组，不支持 first_frame 别名。

## 本机算力AI Flash 720p

上游 `suanliai-main`，精确型号 `官渠sd2.5-flash(20参任选/10-5-5/5-30秒/720P)`。

- 原图生视频 binding：`suanliai-sd25flash720--suanliai-main`。
- 新视频参考 binding：`suanliai-sd25flash720-ref--suanliai-main`，operation 为 `reference-to-video`。选择此 binding，不修改全局默认。
- 用户提供的算力AI文档要求至少一张图片；最多 10 图、5 视频、5 音频，合计 20。视频可用于 motion、scene、style，图片可用于 identity、prop、scene、style。声音默认随模型，不发送 generate_audio。
- 输出暂按本机已有范围：5/10/15/20/25/30 秒、720p、16:9/9:16/1:1；提示词最多 5000 UTF-8 字节。
- 本机保守工作范围：PNG/JPEG 单图 10 MiB、图合计 100 MiB；MP4 单段 30 秒/50 MiB、视频合计 30 秒/100 MiB；MP3/WAV 单段 30 秒/20 MiB、音频合计 30 秒/50 MiB；全部文件合计 200 MiB。此处秒数、字节上限是本机约束，尚不能当作 Flash 上游硬边界。
- 当前报价沿用每次 ¥4.85 的目录证据；费用预检按目录价估算，带视频参考的实际账单和效果尚未实测，不自动加倍任务或费用。

## 技能执行方式

用户给参考视频并说明要参考动作、运镜、节奏或场景后，先观看分析，选有用区间；长片使用 `media-ref slice` 生成真实 MP4 片段。为新主题保留清楚的因果和镜头设计，在提示词按 `videos[1]` 等顺序标明借鉴范围，不承诺逐帧复刻。视频参考是附加输入，不会自动增加生成任务数；两条 30 秒视频仍可各一次生成。

1. 通过 `media-ref register/slice` 保存引用及来源哈希。
2. 准备至少一张合适图片。有新角色或新产品时使用它的参考图；仅复用原片视觉时可以明确提取原片一帧。图片的作用须写清楚，不能把原人物图当作新人物锁定。
3. 使用既有素材服务 `media-ref host ... --reference FILE --upstream suanliai-main`；不停止占用 8765 的现有服务。
4. `media-ref attach` 后给 job 设置上述新 binding，所有参考均需 kind。保持各类引用顺序。
5. `plan validate/compile/route` 和 `jobs prepare` 检查真实文件、来源链、大小、时长、组合、HTTPS 有效期和完整 GET 哈希。预检不提交生成。
6. 只有在用户已有生成授权和预算内才 `jobs execute/run`。真实结果须独立审片；接入开发和模拟测试不能记为线上通过。

具体命令和链接保密方式见 [本机素材服务](media-hosting.md)。

## 算力AI本站素材上传（2026-11-16 实测）

本站公开工作台 `suanliai-workbench-plus.js` 使用 `POST /v1/assets/review`，Authorization 与当前算力AI账户一致。使用 multipart 上传实际文件：图片字段 `images`、视频字段 `videos`、音频字段 `audios`。这是素材上传，不是 `/v1/videos` 生成请求。返回 `success`、`all_ok`、逐文件 `items[].ok` 以及对应类型的 URL 数组；失败或缺失 URL 时不能继续生成。

本机实际上传六张 PNG 与一段 MP4，均返回本站 `suanliai.top` 地址；无需认证的完整 GET 与原文件 SHA-256 一致。音频上传尚未实测。链接替换只改变传输记录，保留素材字节、角色、顺序与生成计划。既有本机素材服务无需停机。

本站响应未报告素材到期时间。记录为 `provider-managed-expiry-unspecified`，不得冒充用户声明永久有效或已验证的剩余有效期；每次新建任务前重新完整 GET，失败则停止。上传回执及链接保密保存。已受理任务沿用原任务号，不因素材链接变化而重新生成。

这是当前制作脚本使用的已核对上传合同；通用 `media-ref` CLI 尚无 `upload` 子命令。Base64 视频传输也尚未实现，不能把本站上传成功描述为 Base64 接入成功。


## 显式 Base64 直接传输（2026-11-16）

`newapi-json-v2` 新增 `adapter_options.reference_transport=data-uri`；未设置时仍走 HTTPS。该模式仅用于已核对支持 Base64 的精确模型合同。按类型发送实际注册文件的 `data:<mime>;base64,<bytes>` 数组，提交前重查文件哈希，本机原始总大小上限 32 MiB；不需要素材服务或公网链接。预检和回执不保存 Base64 或本地绝对输入路径，异常与回显中的 data URI 脱敏。未知提交不重发，已受理任务仍固定原快照恢复。

本次噜妹怀里告状项目中，两个 PNG 和实际 MP4 已通过该模式取得真实任务号；受理只证明接口接受请求，生成完成及表演效果需另查项目回执。输入视频已去黑边、去音轨，身份由已确认定妆图约束。详见 F 盘 docs/20261116-newapi-inline-reference.zh-CN.md。通用 `media-ref upload` 仍未实现，本站上传脚本与直接传输为两条独立方式。
