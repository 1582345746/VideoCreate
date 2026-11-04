# v3 项目文件

新项目用 `plan init <folder> --title ... --intent narrative|demonstration|montage|single-shot --pace comedy|dialogue|suspense|slow-cinema|action|product-demo`。`--example smart-car` 会建立一个可改的诸葛亮、智能车和运粮喜剧分镜。

```text
project.json           产品名、schema、标题和文件索引
brief.json             受众、意图、节奏、产品功能、规格
story.json             beats、前置状态/结果、因果、观众信息与可见证据
director.json          角色/道具/场景资源、空间地图、表演、镜头
generation-plan.json   generation jobs、shot 关系、参考、依赖
timeline.json          源 clip、保留区间、字幕、独立声音轨和变速
assets/                原始注册参考与生成资产
jobs/<job>/<attempt>/  实际 request、attempt 和下载的原始片段
reviews/               对实际内容观察后填写的哈希/区间绑定回执
deliverables/          animatic、字幕、preview 和 manifest
state.json             恢复与预算账本
```

IDs 互不替代：beat 是状态事件，shot 是镜头覆盖，job 是 API create，clip 是返回素材，segment 是时间线采用区间。一个 job 可以涵盖多个 shots，但模型切点必须回看并拆成独立 clip 证据。

## 命令顺序

```powershell
python scripts/videocreate.py plan schema --output .\videocreate.plan.schema.json
python scripts/videocreate.py plan init project --example smart-car
python scripts/videocreate.py plan validate project
python scripts/videocreate.py plan compile project --config <config-file>
python scripts/videocreate.py plan preview project --video
python scripts/videocreate.py jobs run project --job job-001
python scripts/videocreate.py jobs status project
python scripts/videocreate.py timeline validate project
python scripts/videocreate.py timeline map project
python scripts/videocreate.py timeline render project
python scripts/videocreate.py review template project
python scripts/videocreate.py review apply project --receipt project/reviews/observed.json
python scripts/videocreate.py review status project
```

人物/动作短片、科普和连续剧的生产步骤见 [production-workflows.md](production-workflows.md)。

`plan compile/preview`, `timeline map/validate`, `jobs status` are local/read-only. `jobs run` creates billable tasks and must follow the active user authorization, configured request limits and pricing. Initially run two adjacent critical shots first, then inspect before expanding. Binding constraints are enforced before state reservation. Unknown submissions are held.

Plan validation reports declared structure only. `structural=pass` always keeps `content=unverified`. The director specifies acting and visible evidence; it cannot make a remote model obey. Preview cards contain text, not generated characters. Identities without registered references are flagged as unverified.

### Story and directing

Every narrative beat has `requires`, `effects`, `causes`, `audience_learns` and `visible_evidence_needed`. A shot can be reaction/coverage without changing story state, but the declared visible action must support that role. Product stories connect function → character choice → visible result. State changes such as entering/exiting a car need an explained transition with actual coverage, not an arbitrary `state_change_reason`.

A performance shot declares trigger, attention, visible response and decision, plus eyeline/screen direction. Keep primary movement simple. Comedy, slow cinema and product demonstrations have separate pacing profiles; no universal 3.5-second cut rule or mandatory dialogue. Dialogue intervals remain inside the source clip and retained timeline window, or become an independent speech track.

### References and likeness

`assets register` copies and hashes local image references. It does not prove a real person's likeness rights or output identity. Keep character identity, pose/opening composition, prop and scene references separate. Current adapters only transmit supported opening-frame/image references. Asset schemas preserve their roles, but an unsupported role cannot be silently converted into a generation hint.

### Job recovery

Attempt intent and budget are durably saved before one create. A process found dead during `submitting` becomes `submission_unknown`. It stays held until upstream evidence resolves that exact attempt. A known task ID pins model, remote ID, adapter and endpoint. `--retry network` polls/downloads that task; `--retry content` is a new paid candidate; `--retry replan` makes a new attempt for changed shot inputs. Each new create needs an explicit job and reason. Changing titles, subtitles or edit choices must not regenerate clips.

An amount cap only accepts a hard limit when prices are configured on every selected binding. Unknown pricing is reported and bounded by request counts; it is never treated as zero under a hard monetary cap.
