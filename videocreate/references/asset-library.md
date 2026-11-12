# 项目素材、跨项目复用与制作统计

## 项目卡片和本地参考

管理器的项目面板提供“角色与项目素材”，剧本表单也有同一入口；它们通过 `authoring show/preview/save --layer director` 保存同一份 `director.assets`，不建立另一套素材数据库。可以新增、编辑、移除和排序角色、场景、道具及声音卡片；改 ID 不自动重写镜头、台词或任务映射。动画 sidecar 管理的导演层仍从动画创作源编辑。

卡片可分别保存 `visual_design.identity`（身份/面部/物种结构）、`wardrobe`、`expression_range`、`visual_style`，以及 `physical_design.scale`、`placement`、`contact_constraints`。镜头构图继续保存在镜头本身。只有镜头 `asset_ids` 引用的卡片设计进入对应任务提示词，保存前可以查看实际任务影响；文字约束不保证模型执行尺度、接触或身份一致。

```text
videocreate assets stage-reference PROJECT --source IMAGE --asset-kind character
videocreate assets stage-reference PROJECT --source AUDIO --asset-kind voice
videocreate assets board PROJECT --asset-id hero
```

`stage-reference` 无须选择上游，复制本地文件到 `assets/references/snapshots/完整SHA256.扩展名`，检查复制前后的哈希和文件格式，保留原文件；已有快照损坏时拒绝覆盖。图片支持 PNG/JPEG/WebP/GIF（本地上限 48MB），声音支持 WAV/MP3/M4A/FLAC/OGG（256MB，并需 FFprobe）；这些是本地导入限制，不是模型参数。图片仅做格式标识/GIF 结构检查，不代表完整解码或视听通过。

GUI 后台复制完成后先加入未保存的参考列表，保存卡片才建立引用。CLI 则把返回的相对路径显式加入卡片 `references` 后通过 director 预览/保存。取消编辑或移除引用不删除原文件及已复制快照。卡片参考不会自动上传、公开、发给模型或变成克隆声线；生成仍须显式关联 job 的 typed reference。

`board` 导出本地只读 HTML，显示已保存卡片参考、关联任务首帧参考、当前选中的生成候选及相关本地原片；支持图片、视频和音频控件。缺失或哈希不符的文件显示不可用。首帧参考不是视频实际首帧，页面不自动截取或批准身份、动作、对白和声音。导出期间计划/任务或媒体变化会拒绝混合版本，应重新导出。未保存的表单修改不进入对照页；它不是跨版本差异工具。

源片审核合同现在绑定相关镜头引用的卡片和对白 `voice_asset_id`，包括参考文件当前哈希与可用性。改相关卡片或文件会使该源片旧审核过期，无关源片观察保留；所有旧任务、候选和审核原记录仍在。升级到 dev27 后，旧版未记录卡片上下文的源片通过记录需要按当前合同复核，不代表需要重新生成。

## 跨项目素材库

素材库位于所选配置文件旁的 `asset-library/items/素材ID/版本哈希/`，不包含上游密钥。角色、场景、道具保存描述、固定特征和图片；声音卡片保存描述和音频。图像登记检查格式标识，声音登记使用 FFprobe 检查音轨，二者都不代表实际视听审核。已有动画主题和已审片互动库继续独立工作。

```text
videocreate library add SOURCE_PROJECT --asset-id hero --library-id hero --title 主角 --tag 喜剧 --notes 身份与服装说明
videocreate library list --kind character --query 主角
videocreate library show --library-id hero --version FULL_VERSION_HASH
videocreate library import TARGET_PROJECT --library-id hero --version FULL_VERSION_HASH --asset-id hero-v1
videocreate library impact TARGET_PROJECT --asset-id hero-v1
videocreate production metrics TARGET_PROJECT
```

命令支持 `--config` 选择配置对应的库。版本必须使用 list 返回的完整哈希，不按“最新”悄悄切换。重复保存相同卡片和文件是幂等操作；描述、备注、标签或文件变更会形成新版本。导入复制文件到项目 `assets/library/`，并在 director.assets 建立卡片；原库更新或源项目移动后，已导入项目仍可使用自己的文件。库和项目里的已有文件若哈希不符，会报告损坏而不覆盖。

导入不覆盖已有不同内容的 asset ID。需换角色版本时，先用 impact 查看直接镜头、直接任务和传递依赖，再以新 ID 导入，显式修改分镜、参考图和声音映射。旧候选及快照保留。声音样本不是声线模型，不会自动建立克隆声音、TTS 或口型能力。

管理器提供搜索、卡片详情、从项目入库和导入指定版本。新视觉/物理字段随不可变版本保存，旧卡片仍可导入；旧版客户端不保证认识新增字段。项目对照页提供本地查看/试听，素材库仍没有自动缩略图或跨版本差异板；内容验收继续走实际审片流程。

## 制作统计

`production metrics` 是只读报告，统计口径为当前项目：

- `generated_known`：所有哈希有效、时长已测的完成候选，含未选中候选；另列缺失时长和文件损坏数。
- `retained_available_playback`：当前选中素材实际覆盖的保留区间，按变速计算播放时长；重复使用片段会重复贡献播放时长。
- `retained_unique_source`：按源文件哈希合并重叠区间后的独立源时长。
- `reviewed_usable_playback`：当前保留区间通过所有适用源片审核层的播放时长。最终剪辑、故事与声音仍须成片审核。
- 重做率：有多次预算预留的任务数 / 已预留的视频任务数；另列额外尝试数。预算预留不证明实际扣款。
- 成本：按币种分别列已知估算、已知实付和未知项；只有该币种实际账单齐全且存在合格源片时才计算单位成本。包括项目内图片和重试支出，是项目成本分摊，不是模型单价。不同币种仅为独立组成部分，不换算或相加。

审核记录过期、文件变动或最终 manifest 无法验证时，审核指标保持未知；不沿用缓存的 content_status。显式剪辑素材路径如果不能对应当前生成候选，不进入源任务质量样本。报告只陈述样本，不自动生成模型优劣排名。
