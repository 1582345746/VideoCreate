# 星光视频协议 v1

来源：用户于 2026-11-12 提供的完整《图片与视频 API 对接文档》（站内更新日期 2026-10-30）。`/models` 与当前 Key 的 `/pricing` 已独立读取；本文是外部合同记录，具体模型成功范围以本机 binding 回执和阶段验收报告为准。

`providers pricing --upstream xingapi-main` 读取账户报价、保存带时间的证据和描述变更提示，不自动启用模型或覆盖本地参数、备注和预算价格。价格接口 2026-11-12 返回 USD；单一 720P 档位为：933 每条 2.79、C 每条 2.89、Q 每条 1.35、S 每秒 0.299、V 每条 4.9、Wan 每秒 0.22。字段名 per_request_price 在按秒模型也被复用，必须结合 video_billing_unit 和 pricing.unit 解读。多档或不明确结构保持原始数据，不任意选择报价。报价不是实付账单。

当前价格接口说明将 S 写为 30 图 / **0 视频** / 10 音频，Wan 写为 10 图 / 5 视频 / **5 音频**；与旧截图说明分别保留来源，不静默合并成已验证能力。完整文档另说明图片生成使用 JSON，图片编辑可以是 image_url 对象数组或按模型支持的 multipart 文件字段；不能把图片编辑协议用于视频参考。

| 操作 | 合同 |
| --- | --- |
| 创建 | POST `/v1/videos/generations`，Bearer API key，JSON |
| 必填/显式参数 | `model` 原样、`prompt`、整数 `duration`、`ratio`、`resolution` |
| 任务号 | 根对象或 data 对象中的非空字符串 `id` / `task_id` / `request_id`；保留完整前缀 |
| 查询 | GET `/v1/videos/{完整任务号}`；路径编码但不截断 |
| 下载 | GET `/v1/videos/{完整任务号}/content`；可能 302；跨域不转发密钥 |
| 常见等待状态 | preparing / queued / pending / submitted |
| 生成状态 | running / processing / in_progress |
| 完成状态 | completed / succeeded / success / done / finished |
| 失败终态 | failed / failure / error / cancelled / canceled / expired |

查询按 10、30、60 秒循环，429 使用 Retry-After（整数秒或 HTTP 日期），暂时网络错误和无效 JSON 保留任务号继续读取。停止本地等待不取消远端任务。创建响应没有任务号或连接中断则保留回执并进入 submission_unknown，不自动重发。X-Client-Request-Id 不代表幂等保证。

下载检查 Content-Type 和 MP4 文件标识，再由运行器用 FFprobe 测量。下载失败重用原任务号和本站 content 端点，不创建新视频。本站 API key 与网页登录 JWT 不混用。真实调用要绑定原上游、账户和模型快照。

文档允许按模型能力发送 `images` / `videos` / `audios` 独立 HTTPS URL 字符串数组，顺序必须保持；音频参考与 `generate_audio` 开关不同。通用合同没有本站上传接口：本地文件需先上传自己的 COS/OSS/S3 等存储。URL 必须无需额外 Cookie 或认证头并在生成期间有效，不能用本机路径、网盘页面、blob URL 或局域网地址。Base64、multipart、火山 content 不是通用协议。

**dev16 生成执行范围仍为文生视频。** 本地引用在创建前拒绝，不悄悄转换为 base64 或丢弃素材。[素材托管与传输绑定](media-hosting.md) 已独立实现，生成请求消费这些链接及混合参考仍待接入。`generate_audio` 仅在 binding 明确配置 explicit 时发送；当前 V 小样采用模型默认声音，没有验证开关。seed 同样不推定支持。

六个目录 ID 保留原大小写：seedance-933、seedance2.0-933-C、seedance2.0-933-Q、seedance2.5-V、seedance2.5-s、wan3.0-prime-720P。文档中特别提到的 seedance-2.5-480p-M2 不等于这些型号，不套用它的 25 秒限制。截图的参考数量、5–30 秒、全比例和 `$` 标价分别保留为供应商声明；不据此认定账户币种、实际扣款或所有参数组合已测。
