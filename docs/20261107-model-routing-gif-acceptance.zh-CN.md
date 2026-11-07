# VideoCreate 3.0.0.dev5：交付与实际验收

日期：2026-11-07。完整路线图仍见 [开发清单](20261107-model-routing-gif-development-plan.zh-CN.md)；这里记录当前实现和实际测试范围。

## 已实现

- 目录以模型家族 → 图片/视频 → 型号 → 平台/实例/协议绑定展示。新增四个 GPT 图片型号、Grok Image 2.0、Grok Video 1.5 与 Muse 的配置模板；原 Seedance 和 NewAPI 路径保留。
- 图片可显式指定型号，也可在创建前按操作、参考上限、尺寸、质量、输出格式及可用凭据选择首个兼容型号。显式型号不跨型号替换；这不是自动画质评测器。
- 图片单张/批量与视频使用同型号路由。候选在创建前检查；固定绑定不改选。明确拒绝只有在 binding 的拒绝合同允许时才切下一上游，创建次数受任务及项目预算约束。内容拒绝不借换站绕过。
- 超时、网络错误、5xx 或无确认 task ID 保持未知提交。视频恢复使用原 URL、型号、adapter；图片下载/解码失败保留响应，重新解码不重新生图。已完成图片在修改默认型号后可复用原产物。
- binding 的本机 60 秒冷却只影响新的自动任务，无后台付费探测。同账户多个型号复用同一 upstream 实例，共享已有提交槽；未实现跨机器 RPM/远端在途额度调度。
- Images 请求字段、尺寸、质量和返回模式按 binding 配置，不要求每个站点接受同一组 GPT 字段。
- GIF 标识、块结构、帧数、帧延时、循环和大小约束；原生 GIF 请求必须返回多帧 GIF，静态替代产物保持 output_invalid，恢复也不能绕过。
- 本地视频转 GIF、静帧序列转 GIF、显式按时间取帧，均保存哈希与来源。动画审核要求完整播放观察，不能凭首帧批准。

配置保留 schema 3，新增字段是可选扩展，未强制重写现有用户文件或运行中任务；软件版本与项目 schema 分开。通用 schema 4 迁移/回滚工具仍属于后续工作。本机此次修改有独立配置备份，安装器也会备份旧技能。

## 真实账户测试

经用户授权，共发起 7 次图片创建、2 次视频创建；恢复视频没有新增创建。这里统计 HTTP 创建尝试，实际结算费用未知。结果摘要及产物哈希见 [机器可读记录](design/20261107-live-smoke-results.json)。原媒体和完整任务记录只保存在本机。

| 路径 | 实际观察 | 可据此启用的范围 |
|---|---|---|
| Aivalux / GPT Image 2.6 | PNG 生成 32.67 秒；编辑 56.34 秒；原生 GIF 46.20 秒 | 此账户的单张生成、单参考编辑、GIF 输出 |
| Aivalux / Flare | PNG 生成 41.47 秒 | 此账户的该次 PNG 生成；编辑/GIF 未测 |
| Aivalux / Sunburst | PNG 生成 56.72 秒 | 此账户的该次 PNG 生成；编辑/GIF 未测 |
| GateAI / GPT 2.6 | 目录未列出请求型号；创建返回 503 / No available compatible accounts | 凭据/URL 已配置，当前不能认定可生成；没有重复提交 |
| Aivalux / Grok Image 2.0 | 创建返回 502 / Upstream service temporarily unavailable | 型号配置保留，当前生成未通过；没有重复提交 |
| RapidAPI / Grok Video 1.5 | 下载成功，约 4.04 秒、848×480、24 fps、存在音轨；查询型号一致 | 作为本机视频首选；声音内容和运动质量未批准 |
| Aivalux / 请求 Grok Video 1.5 | 下载成功，4 秒、1280×720、24 fps、存在音轨；查询却报告 muse-video | 能取回媒体，但型号等价与 480p 参数服从性未确认，不能冒称精确 Grok 同质备用 |

原生 GIF 实际为 439×390、9 帧、1.8 秒、无限循环；独立解码得到 9 个不同画面，证明确为多帧内容。请求中的 1024×1024 和提示中的 2 秒未被精确遵守，故不能推导出可靠尺寸/时长控制。另已把 RapidAPI 视频的 2 秒片段本地转为 20 帧 GIF，零上游创建。

两路视频最初仅返回 request_id。默认规则将其保留为未知提交；随后在原站 GET 查询确认它们是实际任务标识，用哈希绑定的 accepted 回执恢复并下载。之后仅在这两个本机 binding 中加入 request_id 字段合同。模板仍不把所有服务的 request_id 当作 task ID。

三个 GPT 型号每个只有一个普通构图样本。三张图均可见蓝纸船、黄叶和水面，但样本不足以判断延迟分布、费用、中文文字或复杂编辑质量；不能将 Flare 固定解释成快速版、Sunburst 固定解释成高质量版。默认使用普通 2.6；另两型可显式选择，自动选择依据配置顺序及硬条件。

## 本机测试配置

配置：`%LOCALAPPDATA%/VideoCreate/videocreate.config.json`；凭据：同目录 `secrets.dpapi`。本轮提供的四组账户均已写入 Windows DPAPI，普通 JSON 只引用凭据。原有账户、NewAPI binding、Seedance、旧任务和自定义选项保留。

新图片默认 GPT 2.6；普通 2.6 的 Aivalux binding 启用 PNG/GIF 输出，其他变体保持未测试的动画能力。Grok 图片使用用户纠正的 `grok-imagine-image-2.0`。视频首选 RapidAPI，Aivalux 保留且标明服务回报型号/分辨率差异。RapidAPI Muse 目录未见，继续禁用；Muse 显式型号与 Seedance 本轮没有新生成验收。

本机新 binding 的鉴权 401 列为明确拒绝；429、5xx、超时未配置成自动重发。未收到确认任务的原尝试仍需对账，不能换站重复创建。用户可在该 JSON 中调整候选顺序、enabled、精确协议及请求上限。

```powershell
python <已安装技能>/scripts/videocreate.py models list
python <已安装技能>/scripts/videocreate.py models explain-image --output-format gif
python <已安装技能>/scripts/videocreate.py assets image <项目> --job-id img-001 --prompt-file prompt.txt --model gpt-image-2.6
python <已安装技能>/scripts/videocreate.py assets image <项目> --job-id gif-001 --prompt-file motion.txt --model gpt-image-2.6 --output-format gif
python <已安装技能>/scripts/videocreate.py media export-gif <项目> --source source.mp4 --job-id preview-gif --duration 2
```

## 验证和后续

最终代码在本机全量 `430 tests / OK`（274.783 秒）；GitHub dev4 标签的 Linux、Windows CI 均通过。GitHub 首轮发现的 Windows 短/长路径混用、无 Pillow 时 PNG 结束标记偏移错误及 CI 媒体测试依赖缺失均已修复；dev5 另将视频轮询并发测试改为线程同步验证，消除固定等待时间造成的偶发失败，相关单项通过。`python -S` 不加载可选依赖时的浏览器交接 19 项也通过。回归覆盖参数与精确型号、图片和视频故障注入、未知提交、固定路由、预算、恢复、GIF 静态替代、帧序列与取帧、动画审核及密钥隔离。

wheel 与 ZIP 均通过发布内容检查，并在仓库外以 Python 隔离模式验证入口与 GIF 路由。209 个 Git 候选文件的密钥模式扫描零命中，技能独立校验通过。`install.ps1 -Force` 已把 dev5 安装到本机 `C:/Users/FBX/.codex/skills/videocreate`，安装后的版本与 `config validate --ready` 检查通过；安装前后配置 JSON 和 DPAPI 文件哈希一致。旧技能已备份到 skills 目录之外。

发布标签为 `v3.0.0.dev5`，属于预发布开发版；源代码位于 `codex/videocreate-v3` 分支。较早的 dev3/dev4 标签和失败记录保留，不覆盖历史。GitHub 上的跨平台测试与发布结果以 dev5 标签对应的 Actions 记录为准。

仍需外部证据或后续开发：GateAI 账户可用性、Grok 图片服务恢复、Aivalux 视频型号等价说明、全部 8 条 GPT binding 的生成/编辑矩阵、变体 GIF 与动画输入合同、真实计费、盲评用途标签、异步/SSE 图片协议、结构化厂商错误合同与 Retry-After、共享速率额度、自动跨型号替代及新的 Seedance 供应商协议。当前未实现的字段和协议不以配置占位冒称已接入。
