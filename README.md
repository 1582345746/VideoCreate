# VideoCreate

[![VideoCreate CI](https://github.com/1582345746/VideoCreate/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/1582345746/VideoCreate/actions/workflows/ci.yml)

面向 Codex 的可恢复、多模型、多上游 AI 视频制作技能。产品名、技能入口和 Python 包统一为 **VideoCreate**。当前开发版为 `3.0.0.dev8`；这不是生产质量认证。

新工作使用分层 v3 计划：brief、story、director、generation-plan 和 timeline。旧的 v2 项目/任务仍保留兼容入口。v3 结构检查不会代替真实的视觉、动作和音频验收；模型和上游未通过实际样片验证时维持 unknown/unverified。

新用户配置一个 `%LOCALAPPDATA%/VideoCreate/videocreate.config.json`，把模型、上游实例、adapter 和路由分开配置。Sub2API/NewAPI 可以作为 Grok、Seedance 等模型的不同 binding；这表示架构可配置，不代表每种模型/渠道合同都经真实生成验证。安装和离线预演不创建付费任务。详见 [VideoCreate v3 开发计划与实施清单](docs/videocreate-v3-development-plan.zh-CN.md)、[技能运行说明](videocreate/SKILL.md)、[配置说明](videocreate/references/configuration.md) 和 [v3 项目说明](videocreate/references/v3-project.md)。

dev6 新增 [动画故事创作模块](videocreate/references/animation-story.md)：参考剧情→原创世界/场景→主题角色→v3 分镜，附水豚噜噜/噜妹与毛毡狐狸/兔子两套主题。支持角色图裁剪与身份指导、开场状态校验、相邻小样、独立短剧、固定声线音轨和剧情保真审核。`animation example PROJECT --scenario reaction` 可离线创建完整示例；使用 `--theme cloud-couriers` 检验换角色。真实生成与质量边界见 [开发验收记录](docs/20261111-animation-story-acceptance.zh-CN.md)。

dev7 增加 `animation preview`：独立修剪已生成的小样，保留完整故事计划、任务与候选；按保留窗口重排声音和字幕，拒绝截断半句，小样不能当作完整成片验收。复用判断使用与真实提交一致的输入哈希，包含参考图字节和画幅参数。

dev8 修正 Windows 短路径下的参考哈希计算，限制 FFmpeg 归一化线程并提供按片段时长的超时诊断。动画示例明确取物、递接与接稳后松手，第二主题不再混入噜噜名称；连续镜头优先从实际保留末帧接续。首条完整故事曾被用户指出闪跳和道具跳现，修正版须重新播放验收。

dev5 已有 GPT Image 2.6 三型号与 Grok Image 2.0 目录、创建前图片选型、图片/视频同型号备用和候选预检查、本机故障冷却，以及 GIF 校验与本地转换。账户级测试结果见 [模型路由交付记录](docs/20261107-model-routing-gif-acceptance.zh-CN.md)。

Muse 路线新增同一 JSON 中的 `browser_services/workflows`，支持描述 API 生图＋API 生视频、Muse 独立生图或视频、Muse 生图＋视频、API 生图＋Muse 视频。`workflow list/describe/prepare` 可离线校验并输出当前镜的浏览器交接包；当前未交付无人值守站点运行器，也未验证账号内 Muse 生成。默认优先内置浏览器，操作接口不足时明确阻塞，不自动换浏览器。详见 [Muse 接入与实测清单](docs/muse-browser-workflows.zh-CN.md)。

开始使用：`python videocreate/scripts/videocreate.py config init`，编辑返回路径的 JSON 后运行 `config validate --ready`。无付费测试：`plan init <项目目录> --example smart-car`、`plan validate`、`plan preview --video`。样片任务由明确的 `jobs run` 命令执行；结果默认仍需人工观片/听审后才可接受交付。

## 安装与首次配置

Windows PowerShell：

```powershell
.\install.ps1
python .\videocreate\scripts\videocreate.py config open
python .\videocreate\scripts\videocreate.py config validate --ready
```

安装仅复制技能和配置，不执行模型生成，不下载可选 TTS/口型模型。已有 v2 配置会保留原文件并复制 DPAPI 密文，新配置引用其本机凭据；旧技能在成功安装后归档到 skills 之外。升级使用 `-Force`，卸载 `-Uninstall` 只移除技能，保留凭据、项目与缓存。首次用户在返回的单一 JSON 里填写 URL、auth、remote_model 并启用 binding。

无需安装 Python 包可直接运行薄入口；源码仓库中也可 `pip install .`，或安装提供的 wheel，之后运行 `videocreate` 或 `python -m videocreate`。ZIP 用户直接使用 install.ps1 或薄入口。Python 支持范围为 3.9 及以上；核心无额外依赖，媒体编辑需本机 FFmpeg/FFprobe，文字卡片 MP4 与角色图裁剪/合并另需 Pillow，HTML 预演不需要。

## 新流程

1. 明确目标、受众、叙事/展示意图和节奏，梳理产品功能怎样改变角色选择与结果。
2. 用 `plan init` 建立五层计划，填写因果、镜头、表演和独立时间线。`--example smart-car` 提供诸葛亮运粮、汽车导航与误认笑点的可改例子。
3. 注册参考素材；需要时使用独立图片 binding 生成开场关键帧。人物参考、开场构图与出口帧的作用分开；未验证参考方式不假装支持。
4. 离线 `plan validate`、`plan compile`、`plan preview`。文字预演可看叙事顺序与停顿，不代表演员或动作已实现。
5. 已授权生成时按 selected jobs 小样先行；保存实际 prompt、参考哈希、model/adapter/URL 快照。已知 task 固定原实例，未知提交不重发。
6. 挑选实际素材区间，在独立时间线上剪辑。局部速度、字幕映射与独立对白/音乐/环境/效果轨分开；声音能跨反应和产品特写。
7. 对真实保留区间分层观片/听审。结构检查、解码、帧率只给技术结论。运动/表演、身份、空间、剧情、声音、clean-frame 和剪辑有独立内容回执。

## 配置与协议

`models`、`upstreams`、`bindings`、`routes` 分层。同一个服务器可以对 Grok 采用 Sub2API JSON，对 Seedance 采用 NewAPI JSON；多个同类服务器也可有不同 URL、Key 和远端别名。真实 `remote_model` 保留大小写，`/v1` 统一拼接避免重复。

固定路由不会被备用覆盖。自动模式只按同模型候选执行，且创建失败只有被该协议明确确认为未接收的 rejection 才可切备用；默认 502/超时/trace-only 都保持 unknown。`request_id` 默认是跟踪号，只有显式协议字段定义才可以作为 task ID。

能力只标 `configured` 或只读目录可见；不能因模型字符串存在就宣称支持原生声音、首尾帧、多参考或高帧率。Sub2API 现适配器不发音频开关，输出由模型默认决定并显示参数消费警告。新增特殊协议需要 adapter 开发和合同验证。

## 质量边界与进度

当前为 v3 开发版，真实 Grok/Seedance × 两类渠道的视频效果与费用对照、人物身份稳定性、模型服从度和最终盲评均未由本次重构验证。无付费本地 fixture、FFmpeg 小样和结构预演不能代替这些结果。

局部 24 fps 源片 0.5 倍慢放仅约 12 个源帧样本/播放秒；转成 30 fps 容器不等于高帧率采集。人物台词需要独立自然速度声音轨，不能随慢镜拖长。光流补帧/动态跟踪不在此核心默认流程中。

`review_pending`、`rejected`、`accepted_delivery` 与 `draft_preview` 明确分开。同字节上已发现的缺陷优先于通过回执，修改后的内容需要重新审核。没有听审工具时声音仍未验证。

## 文档与开发

- [2026-11-07 多模型、多上游与 GIF 开发清单](docs/20261107-model-routing-gif-development-plan.zh-CN.md)
- [完整开发清单和质量审计](docs/videocreate-v3-development-plan.zh-CN.md)
- [v3 实施与验收、后续未完成项](docs/v3-implementation-and-acceptance.zh-CN.md)
- [技能入口说明](videocreate/SKILL.md)
- [单文件配置](videocreate/references/configuration.md)
- [v3 项目与命令](videocreate/references/v3-project.md)
- [恢复、预算和内容回执](videocreate/references/runtime-and-review.md)
- [旧项目操作参考](videocreate/references/legacy-v2-workflow.md)

v3 包以 config/catalog/adapters/planning/runtime/timeline/review 分层；scripts 内保留现有项目、系列、新闻、音频与编辑实现。新的用户流程不继续在旧单文件引擎堆业务。旧名称只在迁移常量、旧文件 shim、旧锁和历史审计证据中保留。GitHub 仓库为 VideoCreate，真实模型 ID 中的 grok 继续保留。

测试：`python -X utf8 -m unittest discover -s tests -p "test_*.py" -q`。测试不需要远端付费请求；发行前还应执行 wheel/zip 离仓库安装、配置迁移、升级回滚和脱敏检查。
