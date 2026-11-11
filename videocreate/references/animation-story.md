# 动画故事创作

使用 `python scripts/videocreate.py animation --help`。源码仓库则从根目录运行 `python videocreate/scripts/videocreate.py`。以下命令省略这一前缀。新模块使用 v3 五层计划，共用独立模型/上游、图片任务、视频任务、预算、候选、剪辑与审核。

## 创作边界

真人原片只提供剧情依据，不能默认决定动画角色外貌、背景、服装、时长、构图或镜头数量。先提炼目标、障碍、选择、后果、情绪与题眼，再设计新世界和分镜。若笑点依赖具体接触，保留接触造成反应的因果；不能用不相关的拥抱替代。

角色图比外观猜测优先。噜噜与噜妹是水豚：橙色圆钝大鼻吻部、小嘴、小圆耳、短肢、橘子头饰；默认噜噜橙色短裤，噜妹白色荷叶边睡帽与粉色睡衣。不得把口鼻改成扁平鸭嘴。`lulu-lumei` 是可替换主题；`cloud-couriers` 为毛毡狐狸/兔子。内置描述包不等于已经通过视觉一致性验收。

## 从参考到可执行计划

也可直接原创，不要求提供参考视频。`animation init` 后直接提交原创 `outline/adaptation`，`sources=[]`、`study.observations=[]`，把原创要点标为 `origin=original`；人物图仍可作为身份依据。故事参考与角色参考各自独立。

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

长片可以先概览，再用 `animation inspect PROJECT 原片.mp4 --start 90 --end 140 --max-frames 24` 针对一段补充抽帧。区间使用原视频秒数，仍绑定完整源文件哈希与总时长；不会裁成新视频或把 90 秒重置为 0。相同来源、用途、抽样区间去重，不同区间保留独立研究，旧观察不被覆盖。抽样区间只限定帧证据，音量与候选切点测量仍基于整片；这些测量均不是剧情或听音验收。

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

用户说“脸不像”时，先比较当前选定版本的眼睛大小/间距、口鼻宽度与突出程度、脸部色块、嘴形及表面材质；同种动物和相同衣服不足以证明身份一致。用户后来选定的视频造型可以成为新的身份版本：抽取清晰正脸与侧脸、记录源视频哈希和时刻，仅裁出对应人物。保留旧版与被否决候选，重做依赖该身份的首帧和视频，避免把冲突的旧公仔脸与新电影脸混合指导。

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

同机位的连续动作出现闪跳时，优先从上一段实际保留区间的最后一帧接续；单独重画下一首帧会改变姿势、尺度和道具状态。把道具的藏放处、空手伸取、拿出、递出、接稳后松手写成可见动作阶段，不能让“下一首帧手里已有道具”替代取物过程。可将紧密相关的揭示和递接安排在同一连续镜头内，按实际节奏规划时长并验证动作负荷；不用转场特效掩盖缺失的动作。

## 动作速度与故事节奏

`pace_profile` 用于动作负荷验证，本身不等于已向模型发出速度指令。需要快节奏时，每镜可填写 `timing={"motion_tempo":"brisk","action_start_by":0.2,"action_complete_by":2.5,"max_reaction_hold":0.5}`；数值是源视频秒数，须处于 planned_seconds 内。编译器会传入开动与结果时间、短反应要求；`plan audit` 提示阶段起点、结果期限和过长保留停顿的冲突。它们是创作预算，实际速度仍以小样为准。

首帧已经接近行动位置，避免先站稳、长时间注视、慢慢伸手、再收回并微笑数秒。生活短剧仍保留取物与递接路径；战斗按一次来袭—应对—可见后果设计，不能把敌人换成无人的展示来获得“稳定”。反应看清即可切，动作片可从约 0.8–2 秒的单信息镜头起步；关键交锋保留完整的因果。柔情戏和慢镜头是明确选择，不作为所有动画的默认表演。

用户要判断打斗速度时，小样应包含实际对手的来袭、主角的躲避/格挡与反击后果，不能仅给英雄站姿或对白特写。先保留一段原速连续交锋，再按实际动作剪掉尾部等待，并记录源区间；这样才能区分模型动作偏慢与剪辑停留过长。脸部相似度和动作速度分别收集反馈，不能用某一项改善代替另一项通过。

现有素材先剪掉空等与多余尾部。小样 `segments` 支持显式 `rate`，仅无台词镜头可在该简化入口改变速度，并指定 `source_audio=retime|mute`；源环境音使用 FFmpeg atempo 保持音高。含台词镜头保留原速；重叠的独立音轨、字幕或叠加需要到完整时间线明确设计映射，不能静默挤压。模型意外多说的话仍需实际听审，不能仅凭计划“无对白”认证声音。变速输出有新哈希与速率映射，旧审核不能直接沿用。

## 声音、剪辑与验收

对白示例默认使用视频模型原声 `native-dialogue`，时间线保留生成素材音轨，不创建外部配音占位或自动附上尚未听到的脚本字幕。先规划每镜少量短句、说话者与不重叠时间窗，尽量在台词前完成复杂身体动作；明确男女声、听者闭嘴、是否有音乐与额外接话。跨镜音色与口型须检查实际结果，提示词不能锁定跨集音色。

需要独立配音时显式选择 `animation example PROJECT --scenario dialogue --audio-mode independent-voice`，或在新剧本填写 `independent-voice`；后者从新剧本规划说话者、时间窗和独立音轨。用户选择模型原声时，不为完成开发验收而强制安装配音服务。可选本地合成入口复用现有 CosyVoice/Voicebox loopback 服务，不安装或下载模型：

```text
animation synthesize PROJECT --shot shot-1 --line 0 --service-url http://127.0.0.1:9880 --voice-id 已有声线ID
animation voice PROJECT --shot shot-1 --line 0 --file 实际音频.wav --voice-id 固定声线ID --reviewer 审核者 --notes 听到的内容与节奏
timeline render PROJECT
animation review PROJECT --output 剧情审核模板.json
animation review PROJECT --file 实际剧情审核.json
review status PROJECT
```

合成先返回 listening_required，试听后再导入；音频必须能解码并放进台词窗口，不能无声截断。每个角色的 voice_id 记录在 `animation-voices.json`；替换某人的声音只更新其音轨与后期。非人脸口型仍需实测，不因固定音色而自动通过。普通字幕来自新剧本，在后期添加。

长期复用可先在项目或 `animation series-init` 目录配置 `animation voice-cast PROJECT --file voices.json`。文件结构：

```json
{
  "schema_version": 1,
  "characters": {
    "lulu": {
      "version": "1", "provider": "cosyvoice",
      "service_url": "http://127.0.0.1:9880", "language": "zh-CN",
      "voice": {"voice_id": "实际已安装并试听选定的预设ID"}
    }
  }
}
```

给每个需要配音的角色设置自己的条目；示例 ID 是说明文字。Voicebox 使用 `provider=voicebox`、实际本地地址，以及 `voice.preset_voice_id/preset_engine/model_size`；可记录 `model/model_revision/seed`，沿用旧适配器核查已下载的模型。此桥接仅接预设声线；授权参考音频的克隆仍用原声音工作流，不能将陌生人的声音自动作为角色配音。

配置后 `synthesize` 可省略 service-url/voice-id，`voice` 导入也可省略 voice-id，自动匹配说话者档案。`voice-cast PROJECT --check-service` 只读检查服务健康，不生成或下载。变更已有档案需要增加对应角色的 version 并给出 `--reason`；旧档案、音频和试听记录保留。旧合成候选不能冒充新声线导入。更换一人的档案只使其声音记录过期；另一人的音轨与视频输入哈希保持有效。系列新准备的独立集保存当前声线快照，已有集不被后来的选声变动覆盖。配置成功不认证音色；仍需逐句试听、核对说话者和台词，再分别审核口型。

原生对白试镜要记录实际听到的原话、说话者和额外接话，分别判断声音自然、男女声归属、跨镜声线、口型和逐字按稿。Grok 小样曾正确生成男女声及对应口型，同时给听者自行添加一句未写入剧本的回应；这证明该样片能说话，不能证明逐字可控或固定角色音色。出现额外接话时保留源片和偏差，不为适配输出改写原请求、把音频审核直接标为全通过，或按原计划时间给未听到的台词加字幕。原生路线先局部简化台词与动作负荷，再生成新候选并听审；旧候选失败继续保留。若用户要求当前原生能力达不到的逐字台词或跨集固定音色，说明实测限制并由用户选择后续方案，不能擅自切换配音路线。独立配音的非人脸口型也需单独验收。

源参考时间用于剧情证据；生成素材时间用于 source_in/out；最终时间线按保留窗口与变速映射。修改字幕不会重生成视频。`animation status` 显示逐任务输入哈希、可复用字节、未知提交、请求预算、已知/未知价格、重做原因、完成秒数与已审核可用秒数。

只有前两镜完成时，使用独立小样入口，保留完整制作计划和目标时长：

```text
animation preview PROJECT --output-name pilot.mp4
animation preview PROJECT --edit-file pilot-edit.json --output-name pilot-trimmed.mp4
```

`pilot-edit.json` 示例：`{"reason":"首镜提前开盖，与第二镜重复；切在首镜开盖前", "segments":{"seg-001":{"source_out":1.0}}}`。仅允许修剪选定小样原保留区间，以及修改 source_audio/cut_reason 或显式无对白变速；不改生成任务与生产分镜。独立声音、字幕和画面叠加按原时间映射到修剪后的小样，不能截断半句台词或字幕。只要求小样已有的配音，不要求尚未制作的后续镜头音轨。输出同名 `.timeline.json` 和 `.manifest.json`，标记 `scope=animation-pilot`、`full_story_delivery=false`，不会调用上游或覆盖默认完整 `preview.mp4`。已观看小样的反馈应绑定其文件哈希和时间映射，不把小样时间冒充源视频时间。

共用源素材审核允许视频证据带 `mapped_view`：`start/end` 是源素材时间，`mapped_view` 内的 `start/end` 是实际观看文件时间，并提供该文件的 `manifest` 和 `timeline` 项目相对路径。校验观看文件哈希、剪辑配方/映射、源片哈希及时间对应；只接受原速、无画面叠加的区间，听音还需保留原声且无独立混音。其他改编音轨或合成画面应审核派生结果本身，不能用于认证原片。

最终仍执行共用七层视频审核，并增加 animation review 的逐题眼保真与主题一致性。后者必须实际连续观看最终视频，覆盖全部要点与完整时长，绑定成片/计划/主题哈希。任何相同字节上的真实失败优先于通过。结构通过、静帧通过、API 成功或 FFmpeg 可解码都不能代替内容验收。

## 独立短剧与复用

```text
animation series-init SERIES --title 水豚日常 --theme lulu-lumei --episodes 20
animation episode SERIES --episode 2 --file AUTHORING_PROJECT/animation.authoring.json --model muse-video
```

可以先准备第 2 条，不要求第 1 条通过；每条使用自己的初始状态和新场景。系列固定 theme 哈希；共享 canonical references 可在 series.json 的 characters/reference_hashes 注册，按哈希复制进每条故事。换主题应创建新的系列版本。原 `series init` 默认 serial，仍要求上一集真实验收结尾；`series init --mode independent` 也提供通用独立模式。

三个可执行原创示例：`animation example PROJECT --scenario reaction|dialogue|contact`。可加 `--theme cloud-couriers` 验证换人物和新世界；这些例子是创作与本地流程测试，不冒充从用户原片抽出的完整剧情，也不代表模型质量已通过。

## 本地互动片段库

将已经实际播放审核的生成片段作为表演参考，记录适用的开场条件：

```text
animation library-add PROJECT --library LOCAL_LIBRARY --id cushion-v1 --job JOB_ID --start 0 --end 10 --contact --description "实际观察到的递接与靠肩" --opening-conditions "双方坐稳、靠垫可触达、肩部高度合适"
animation library-list LOCAL_LIBRARY
```

区间使用源视频时间，必须处于当前保留窗口内。审核使用特定成片名时，添加对应 `--output-name NAME.mp4`。入口核查动作、身份、干净画面，接触还需空间连续性通过；从真实片段抽取开场帧，绑定视频、主题和审核合同哈希。库条目保留来源项目引用；来源移走、字节/合同变化、增加失败审核或抽帧被修改时，查询返回 unavailable。保留源项目以便复核。

库只证明已审核范围的表演，不认证整条故事的题眼，也不自动认证未听审的声音。跨主题复用的是动作逻辑和前置条件；按新角色身体、道具和场景重新设计，不能把旧片段直接当作另一个主题的已验收成片。用户片段与人物图留在本机库，不加入公开技能包。
