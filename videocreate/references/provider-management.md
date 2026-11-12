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

提示词上限支持 Unicode 码点、UTF-16 单元或 UTF-8 字节。`prompt_limit` 配置必须指定计数规则；不能把未知的“15000 字符”假设成 15000 字节。现有图片 adapter 仍有 4096 字节硬上限。视频/音频参考尚无已核实的上传合同，不接受把它们塞进图片字段。

价格可记录按次、按秒、最小秒数、取整步长、有效期和条件档位。档位须唯一匹配；未知报价不能满足硬金额上限。`listed_pricing` 不用于预算。报价和实际账单分开；不同币种分别汇总，不自动折算。共享账户的多个入口可填相同 `capacity_group`，共用最严格的提交并发上限；远端在途和 RPM 配额仍待扩展。

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

阶段包括主题、故事大纲、剧本、角色场景、分镜、参考、生成、剪辑、审核和交付。status 从当前五层计划、state.json、审核回执计算，不复制运行状态。stage 文件只保存创作检查点和内容哈希；修改内容后检查点过期。无角色/参考的计划会跳过相应步骤。完整的纯图/GIF、仅剪辑分支引导尚未完成。

剧本阅读稿由 director 单向导出。JSON 交换稿带源版本哈希；导入只更新 director 并保留备份，既有 job/candidate 不被删除。改字幕不改变视频输入哈希。impact 列出输入已变化的镜头、应检查的依赖和可复用输入；它不自行执行重做。

`auto-within-authorization` 让 next 跳过重复的创作确认；它不直接调用上游、扩大授权或自动通过媒体审核。`assisted` 显示首个未确认创作步骤。未知提交优先进入对账。

## 实际审片与能力目录

`review page PROJECT` 导出 `reviews/viewer.html`，可在浏览器播放本地媒体、定位保留区间、对照相邻片段并下载审核 JSON。记录实际观察后，用 `review apply --receipt FILE` 进入现有哈希和区间校验。页面不判断质量，未观看/聆听的层保持未核实。

`modules list` 显示模块入口、限制、测试文件；`modules roadmap` 映射 73 项开发工作包。`implemented-offline` 表示有本地实现与测试，不等于供应商合同、真实生成或艺术质量已经通过。具体已测范围看日期验收报告和 `binding-evidence`。

星光接口文档已由用户提供，专用 `xingapi-video-v1` 支持文生视频的创建、原任务查询和下载。参见 [接口合同与限制](xingapi-contract.md)；各 binding 只开放核对的参数组合，其余型号仍保留草稿。多媒体参考需要独立 HTTPS 素材地址，当前版本不能发送本地多媒体参考。Grok 的不同上游也可能返回不同型号，必须记录 `provider_reported_model` 并独立判断。

`library add/list/show/import/impact` 与管理器的“角色与素材库”共用本机配置目录下的素材库，项目保存独立快照。详见 [跨项目素材与统计](asset-library.md)。
