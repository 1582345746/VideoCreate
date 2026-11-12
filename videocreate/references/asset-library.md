# 跨项目素材与制作统计

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

管理器提供搜索、卡片详情、从项目入库和导入指定版本。当前没有自动缩略图、声音试听和跨版本对照板；需要实际视听审核的功能仍使用项目审片流程。

`production metrics` 是只读报告，统计口径为当前项目：

- `generated_known`：所有哈希有效、时长已测的完成候选，含未选中候选；另列缺失时长和文件损坏数。
- `retained_available_playback`：当前选中素材实际覆盖的保留区间，按变速计算播放时长；重复使用片段会重复贡献播放时长。
- `retained_unique_source`：按源文件哈希合并重叠区间后的独立源时长。
- `reviewed_usable_playback`：当前保留区间通过所有适用源片审核层的播放时长。最终剪辑、故事与声音仍须成片审核。
- 重做率：有多次预算预留的任务数 / 已预留的视频任务数；另列额外尝试数。预算预留不证明实际扣款。
- 成本：按币种分别列已知估算、已知实付和未知项；只有该币种实际账单齐全且存在合格源片时才计算单位成本。包括项目内图片和重试支出，是项目成本分摊，不是模型单价。不同币种仅为独立组成部分，不换算或相加。

审核记录过期、文件变动或最终 manifest 无法验证时，审核指标保持未知；不沿用缓存的 content_status。显式剪辑素材路径如果不能对应当前生成候选，不进入源任务质量样本。报告只陈述样本，不自动生成模型优劣排名。
