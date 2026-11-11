# 动画故事创作

使用 `python scripts/videocreate.py animation --help`。源码仓库则从根目录运行 `python videocreate/scripts/videocreate.py`。以下命令省略这一前缀。新模块使用 v3 五层计划，共用独立模型/上游、图片任务、视频任务、预算、候选、剪辑与审核。

## 创作边界

真人原片只提供剧情依据，不能默认决定动画角色外貌、背景、服装、时长、构图或镜头数量。先提炼目标、障碍、选择、后果、情绪与题眼，再设计新世界和分镜。若笑点依赖具体接触，保留接触造成反应的因果；不能用不相关的拥抱替代。

角色图比外观猜测优先。噜噜与噜妹是水豚：橙色圆钝大鼻吻部、小嘴、小圆耳、短肢、橘子头饰；默认噜噜橙色短裤，噜妹白色荷叶边睡帽与粉色睡衣。不得把口鼻改成扁平鸭嘴。`lulu-lumei` 是可替换主题；`cloud-couriers` 为毛毡狐狸/兔子。内置描述包不等于已经通过视觉一致性验收。

## 从参考到可执行计划

```text
animation init PROJECT --title 新故事 --theme lulu-lumei
animation inspect PROJECT "原片.mp4" --purpose story
animation schema --output animation.schema.json
animation study PROJECT --file study-and-outline.json
animation adapt PROJECT --file adaptation.json
animation plan PROJECT --model muse-video --binding YOUR_MUSE_BINDING
animation validate PROJECT
```

`animation.authoring.json` 是创作工作区。`study/adapt` 的文件是包含 `study`、`outline`、`adaptation` 中一项或多项的 JSON；不是自然语言自动理解服务。Codex 在实际观察后编写这些内容，脚本负责验证和投射。其他配置不得通过该入口修改。完整字段可查动画 Schema，或用 `animation example` 创建实例后查看其 authoring 文件。

来源记录 SHA-256、媒体规格、用途与本地分析报告；相同字节和用途去重，中文/空格/#/emoji 路径可用。`story` 用于剧情，`character/art` 用于人物或美术，不能自动变为剧情事实。合集可在 `study.segments` 中分段，时间区间必须在源片内。

每条观察包含 source_id、start/end、kind、method、certainty、notes 与 evidence_ids。静帧只支持可见状态、画面文字或明确标记的推断，不证明连续动作或听到的对白。字幕是 `overlay`，听音才可填 audible dialogue；ASR 不证明画面。静帧 ID、时间与字节必须与报告一致。没有音视频观察条件时，保留待核实项，不能伪造动作或听审通过。

`outline.core_points` 区分 source/original/user。来自原片的要点必须引用 story 用途观察；推断保持明确标记。`adaptation.point_map` 给每个要点列出新 beat_ids、shot_ids 与说明，不能漏掉题眼。新增场景逐项填写 description/layout/scale/lighting。casting 把剧情功能映射给主题人物，variants 独立选衣服；配角应加入自定义主题，而非偷偷替换固定主角。

每镜填写 `opening_frame`，描述**开始时**的单画面、道具状态与角色准备姿势。例如后续笑点是空饼干盒，开场不能已经展示一整盒饼干。动作过程写在 actions/performance/action_phases，接触双方必须是可见资产。镜头数、人数和时长由剧情决定，Muse 单请求上限仍由 binding 校验，不超过 10 秒；更长动作应重新拆镜。

## 人物参考、首帧与小样

```text
animation reference PROJECT --character lulu --source "噜噜三视图.png" --crop X Y WIDTH HEIGHT
animation reference PROJECT --character lumei --source "噜妹三视图.png" --crop X Y WIDTH HEIGHT
animation keyframes PROJECT
animation keyframes PROJECT --generate --model gpt-image-2.6 --binding YOUR_IMAGE_BINDING
```

crop 是确定性裁剪，不是 AI 重画；保留原图哈希和裁剪来源。裁剪前实际看图，选择完整、清晰、无标签的单人视图。多个人物指导图会在本地组合成一张身份指导图，以适配只能接收一张图片的上游；不把这张拼图选成视频首帧。原用户图只留本机项目，不自动加入公开技能包。

不带 `--generate` 的 keyframes 只准备提示词与当前 input_hash，不调用 API。默认只准备两个相邻试镜。审核实际返回图后，编写 observation：

```json
{
  "sha256": "实际图片哈希",
  "input_hash": "keyframes 返回的当前镜头 input_hash",
  "method": "codex-vision",
  "reviewer_id": "实际审核者",
  "notes": "记录实际身份、人数、服装、手脚、道具与开场状态",
  "checks": {
    "single_frame": "pass", "identities": "pass", "character_count": "pass",
    "wardrobe": "pass", "limbs": "pass", "props": "pass", "opening_state": "pass"
  }
}
```

```text
animation select PROJECT --shot shot-1 --image 开场.png --observation 观测.json
animation run PROJECT --stage pilot
review template PROJECT
review apply PROJECT --file 实际视频审核.json
animation run PROJECT --stage full
```

命令中的 shot ID 以实际计划为准。所有检查通过才选择首帧；只审核图不代表视频动作通过。扩展制作需小样所有适用内容层通过，包括需要的听音与接触连续性。未知提交仍由原运行器 hold，不能换主题或上游重发。显式局部重试使用 `--shot/--job`、`--retry content|replan` 和 `--reason`；网络恢复沿用已知 task ID。旧候选保留。

视频默认只传已审核的单场景首帧，角色参考已经用于构建这张图。仅当视频 binding 明确支持额外图片时，才在 select 时使用 `--include-guidance`。`required_quality_checks` 是“上游已有历史质量证据”的选型条件，不是初次试镜的内容验收列表；模块不会为首次实验自动填入它。试镜结果仍需完整内容审核，才允许扩展制作。

## 声音、剪辑与验收

对白可以使用原生实验路线，也可以 `independent-voice`；后者从新剧本规划说话者、时间窗和独立音轨。可选本地合成入口复用现有 CosyVoice loopback 服务，不安装或下载模型：

```text
animation synthesize PROJECT --shot shot-1 --line 0 --service-url http://127.0.0.1:9880 --voice-id 已有声线ID
animation voice PROJECT --shot shot-1 --line 0 --file 实际音频.wav --voice-id 固定声线ID --reviewer 审核者 --notes 听到的内容与节奏
timeline render PROJECT
animation review PROJECT --output 剧情审核模板.json
animation review PROJECT --file 实际剧情审核.json
review status PROJECT
```

合成先返回 listening_required，试听后再导入；音频必须能解码并放进台词窗口，不能无声截断。每个角色的 voice_id 记录在 `animation-voices.json`；替换某人的声音只更新其音轨与后期。非人脸口型仍需实测，不因固定音色而自动通过。普通字幕来自新剧本，在后期添加。

源参考时间用于剧情证据；生成素材时间用于 source_in/out；最终时间线按保留窗口与变速映射。修改字幕不会重生成视频。`animation status` 显示逐任务输入哈希、可复用字节、未知提交、请求预算、已知/未知价格、重做原因、完成秒数与已审核可用秒数。

最终仍执行共用七层视频审核，并增加 animation review 的逐题眼保真与主题一致性。后者必须实际连续观看最终视频，覆盖全部要点与完整时长，绑定成片/计划/主题哈希。任何相同字节上的真实失败优先于通过。结构通过、静帧通过、API 成功或 FFmpeg 可解码都不能代替内容验收。

## 独立短剧与复用

```text
animation series-init SERIES --title 水豚日常 --theme lulu-lumei --episodes 20
animation episode SERIES --episode 2 --file AUTHORING_PROJECT/animation.authoring.json --model muse-video
```

可以先准备第 2 条，不要求第 1 条通过；每条使用自己的初始状态和新场景。系列固定 theme 哈希；共享 canonical references 可在 series.json 的 characters/reference_hashes 注册，按哈希复制进每条故事。换主题应创建新的系列版本。原 `series init` 默认 serial，仍要求上一集真实验收结尾；`series init --mode independent` 也提供通用独立模式。

三个可执行原创示例：`animation example PROJECT --scenario reaction|dialogue|contact`。可加 `--theme cloud-couriers` 验证换人物和新世界；这些例子是创作与本地流程测试，不冒充从用户原片抽出的完整剧情，也不代表模型质量已通过。
