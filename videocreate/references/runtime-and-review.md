# Runtime 与内容验收

## Task execution panel and preview

**项目与任务 → 生成任务执行** supports explicit video and image/GIF provider jobs. Select one or more planned tasks, an operation (generate/continue, recovery only, content retry or replan), a new-request limit and wait timeout. Content retry/replan require one selected task and an actual reason. Local sources and local GIF recipes keep their own services. The panel reads saved project/configuration files and shows actual task status, original/planned binding, planned operation and per-create quote; unknown prices remain unknown and estimates are distinct from actual bills.

Preflight includes video dependencies and validates all selected jobs before a create or budget reservation. It may read HTTPS reference files to verify exact hashes. Missing routes return the existing numbered menu; choose once or current project, then preflight again. A once choice never changes global defaults. Already submitted tasks stay on their original snapshot. New attempts execute on the exact bindings shown in this preview, without implicit route fallback.

The preview token binds the saved plan, complete task/ledger state, saved configuration, project selections, selected IDs, mode, reason, request allowance, timeout and per-job prepared-input fingerprints. Execution preflights again and rejects stale tokens. The operation's request cap can only lower the existing project cap, and budget estimates are simulated against the existing ledger before dispatch. Existing runtime locks, task snapshots and final input checks remain authoritative; this does not lock the filesystem throughout network/media work or grant spending authorization.

CLI uses the same service:

```text
videocreate jobs prepare PROJECT --job job-001 --new-requests 1
videocreate jobs execute PROJECT --job job-001 --new-requests 1 --token RETURNED_TOKEN
videocreate jobs resume PROJECT --job job-001
```

Use `--mode content|replan --reason ...` for an explicitly selected replacement, and the same options for prepare and execute. A concrete `--binding ID` fixes selected new attempts; dependencies retain their own routing unless individually chosen. Missing selections still use `selection choose`. Pure image/GIF plans also use prepare/execute; their recovery mode reprocesses a saved original response or reuses a current completed output. It does not invent an asynchronous image query contract. An unresolved image without its original response needs the existing upstream-result recovery receipt.

Recovery-only video execution uses `allow_create=False`, checked for the entire dependency set and again under the state transition lock. It cannot turn a missing task ID, unknown submission or changed task into a new request. Download/read failures retain the original task, adapter and account. Previews and execution do not automatically approve output. Actual observed content defects still use review receipts and explicit local repair/new-candidate paths.

The panel executes in a background worker, reports video phases and retains durable state. Repeated clicks are suppressed while an operation is active. Closing it cancels UI callbacks; the started operation continues until its wait/network limits. Local waiting does not cancel a remote task. Reopen and recover the same task later. Separate buttons import actual reconciliation or billing receipts through their existing shared validators; they do not turn “not found” into confirmed rejection. GUI lifecycle and clean-machine acceptance remain separate from offline form construction.

## Saved runtime states

`submitting` means request intent and budget reservation have been persisted before the HTTP write. A process found dead before a definitive task response is `submission_unknown`, never eligible for an automatic create retry. A trace/request ID is not a task ID unless that exact protocol explicitly declares it. The default parser ignores trace fields.

`queued/in_progress` always retains the saved binding. Polling 404/timeout is a read failure; resume that task. A confirmed terminal task failure permits a separately authorized new content attempt. `cancel-local` only stops local polling.

The completed provider result is persisted before video download. If the download fails, a known task resumes from that saved result without querying or creating again; a missing or damaged saved result falls back to querying the original task. Input-change checks still apply: preserve the original project inputs when recovering, and use replan only for an explicitly selected new generation.

Reconciliation receipt must include job ID, attempt ID, binding fingerprint, reviewer ID, method and actual hashed evidence. `accepted` also includes the provider task ID that can be queried. `not-received` requires an upstream audit record explicitly confirming both submission not received and no task created. “查不到” remains unknown.

`rejected-before-task` separately records a request received but explicitly rejected before task creation. The only current contract is `suanliai-reference-image-fetch-20261116`: the exact Flash 480p/720p NewAPI v2 HTTP 400 image-fetch error from `https://suanliai.top`, under its documented reference-material rejection rule. Use `method=documented-create-response`, the original saved `request_id`, and hashed `provider-contract` evidence. The original response, trace and binding are checked; missing logs, video-fetch errors, generic HTTP 400 responses and timeouts do not qualify. Original attempt history and actual-cost uncertainty remain; this resolution does not submit another request or settle its bill.

Budget ledger stores request count, binding price estimate, actual reported cost if available, and uncertainty. It does not claim a provider charged zero when no amount is returned. Per-upstream submission gates use short local lock windows; the project lock is released for HTTP work. Configured image/video task pools run independent work concurrently and honor `depends_on` in waves. Submission gates wait without reserving budget until a slot is available; polling and downloads do not occupy submission slots. The completed review inbox is ordered by completion time and excludes unresolved attempts. Use `review inbox PROJECT --pending-only` to work through pending assets one by one.

`jobs settle PROJECT --receipt billing.json` records an observed upstream charge without generating. The receipt contains job_id, attempt_id, amount, currency, reviewer_id, upstream_record_id and evidence (path/sha256). It must match the original reservation and currency. Reapplying identical evidence is idempotent; conflicting settlement is rejected to preserve the audit. A settled amount can exceed an estimate and then block later creates under the configured cap.

Image requests are synchronous and have independent binding/budget entries. A timeout keeps the attempt unresolved. `assets recover PROJECT --job-id ID --source ORIGINAL_IMAGE --receipt recovery.json` can register an original result obtained from the upstream. The receipt requires original attempt_id/binding_fingerprint, output_sha256, method=upstream-result, reviewer_id, upstream_record_id and actual hashed evidence. It performs no network request or paid retry. Missing original output/evidence continues to hold; use `jobs status` to inspect the attempt.

Image review records bind pass/fail and the reviewer observation to the current output hash. They communicate a human acceptance decision, not objective quality certification. Video review continues to require interval-scoped layer receipts with actual media evidence.

Image responses that arrived but cannot decode are saved as `output_invalid` with the original response. `assets reprocess PROJECT --job-id ID` retries decoding that saved result without a paid create. For a reviewed invalid/completed result, `assets image ... --retry content --reason "observed defect"` requests an explicit new candidate and preserves attempt history. Changed inputs need `--retry replan`. Transport timeouts without a result remain `submission_unknown`; neither flag permits duplicating that unresolved request.

## Review receipts

Video batches prepare the complete selected job set and its dependencies locally before any create or budget reservation. Prompt limits, binding eligibility, reference input contracts and animation opening/pilot guards apply to the whole selected batch, in both serial and concurrent execution. A local failure stops that batch before submission. Each worker rechecks current inputs and locked task state when it executes; network/provider outcomes remain per task. An unselected shot's overlong prompt does not block an explicitly selected valid shot. Known tasks retain their original binding snapshots; unknown submissions remain held.

`review template` hashes every actual source/deliverable and its relevant content contract and retained intervals. Review evidence includes path/hash, source interval and kind. A changed file or changed creative contract invalidates only relevant evidence; title metadata does not invalidate the review. A failure on the same reviewed bytes/scope overrides a pass.

Layer status is `pass`, `fail`, `unverified`, or `not_applicable`:

- `narrative`: reviewer answers what the actual picture/sound says happened, without reading the plan first.
- `performance_motion`: actual moving video covers every retained interval; stills cannot pass it.
- `identity`: compare registered character/prop continuity using relevant image/video evidence.
- `spatial_continuity`: movement, eye line, entry/exit and prop/vehicle states match across actual clips.
- `audio`: listening or ASR plus listening; verify words, speaker, timing, mouth motion and cut bridges.
- `clean_frame`: inspect actual moving output over the retained range for marks/overlays. OCR and sampled stills are signals only.
- `editorial`: inspect actual final timeline, pacing and audio bridges, over the retained output.

An initial file-level template marks content unverified. Structural schema and FFmpeg decode only prove structure/technical integrity. Any missing review tool keeps the corresponding layer unverified. Final delivery remains `review_pending` until each applicable layer passes; a rejection remains visible until media/contract changes and the new bytes are reviewed.

### 原片与候选逐段对照

`review compare PROJECT --spec comparison.json` 导出本机对照页。将原片与候选放入项目，分别填写相对路径和实际 SHA-256。可用 `asset_ids` 指向已导入的角色卡。每个事件有独立的原片和候选秒数区间，可以对照裁切、错拍或有时差的镜头。

```json
{
  "schema_version": 1,
  "source": {"path": "input/motion.mp4", "sha256": "<原片 SHA-256>"},
  "candidate": {"path": "deliverables/candidate.mp4", "sha256": "<候选 SHA-256>"},
  "asset_ids": ["hero"],
  "events": [
    {"id": "first-beat", "label": "首拍抬手", "source": [0, 1], "candidate": [0.25, 1.25]}
  ]
}
```

在页面选择事件后可原速对播，或用滑条按区间比例定位。逐项填写观察和审核人，导出后用 `review compare-apply PROJECT --spec comparison.json --receipt event-observations.json` 写入版本化回执。输入视频、视觉卡或事件映射发生变化后须重新核对。逐项观察只适用于对应区间。整片采用与交付仍沿用现有分层审片流程。

审核正在交付的版本时，在对照规格中填写 `review_asset_id`，使用当前作业 ID、本地来源 ID 或 `final`。系统将候选文件哈希与该对象的审核要求绑定。若失败事件的整段仍在剪辑中，交付状态为 `rejected`。仅保留部分时为待复核，完全剪除时保留历史观察。历史比对和整片审听可分别保存。

### 将事件定位到最终剪辑

先用 `reference analyze VIDEO --output STUDY` 测量参考片，再用 `reference events REPORT --output source-events.json` 创建事件表。记录人物编号、动作／镜头／对白等类别、原片起止秒数、说明和 `must_preserve`。每项的 `status` 可为 `unverified`、`observed` 或 `inferred`。已有观察使用 `method` 记录抽帧、视频或听审方式，抽帧项填写 `frame_ids`，对白可填 `transcript`。语音转录推测保留为 `inferred` 或 `unverified`。

`reference profile REPORT --observations source-events.json` 输出按内容编号的版本文件。修订事件表会生成新版本，原观察与测量文件继续保留。事件表记录每个时间区间的观察方法和未核实范围。使用 `reference attach PROJECT --profile FILE` 可把分析和事件版本复制进项目。

`timeline map PROJECT --events event-map.json` 读取原片、可选的参考音频和当前时间线。为每个动作填入各素材中对应的左闭右开秒数区间。一个事件内按两端线性对应，速度变化或重排的交界处应另起事件并填写原因。

```json
{
  "schema_version": 1,
  "source": {"path": "input/motion.mp4", "sha256": "<原片 SHA-256>"},
  "audio": {"path": "input/beat.wav", "sha256": "<参考音频 SHA-256>"},
  "target_job": "job-solo",
  "tolerance_seconds": 0.04,
  "events": [
    {"id": "paw-push", "source": [6, 8], "audio": [1, 3], "target": [4, 6], "reason": "去掉准备动作，推爪仍占两秒"}
  ]
}
```

输出中的 `target_clock` 记录当前采用的本地素材或候选哈希。生成前的时长来自作业计划。每个 `occurrences` 条目给出某次使用保留的原片、参考音频、目标素材和最终时间段，包含剪辑理由、播放速度以及时长差是否在容差内。同一素材可在时间线上出现多次。完全剪除的事件显示为空。参考音频坐标供定位和听审使用，最终混音的实际相位和人物动作仍需播放核对。

如果同一份音频已用在时间线上，可在规格中加入 `audio_track_id`。映射会核对音轨文件的哈希、截取起点和剪辑偏移，分别报告每次出镜的起点与终点相差几秒。用 `review compare PROJECT --events event-map.json --output-name final.mp4` 打开原片与已渲染成片的对照页。重复出现的动作逐次列出，支持原速对播、按剪辑速度对播和参考音频试听。用相同的事件规格和文件名执行 `review compare-apply` 导入观察。

视频作业可在 `event_map` 中保存这份规格的项目相对路径和 SHA-256，例如 `{"path":"assets/events.json","sha256":"<规格 SHA-256>"}`。请求预览与新提交的本地回执会保存对应事件时间表。之后修改本地剪辑映射时可继续恢复原任务，原请求回执仍保存提交时的版本。新建请求会先核对当前时间表及来源文件。

已有原片事件表时，时间规格使用 `schema_version: 2`，增加 `source_profile` 的路径与哈希。每个映射项填写 `source_event_id`，省略 `source` 即复用该原片事件的区间。裁去一部分时可显式缩小 `source`。必保留事件在当前剪辑中覆盖不足时，会列入 `source_event_issues`。确需压缩或移除时，用 `source_event_changes` 按原事件编号填写原因。新建请求检查这些缺口，对照页仍允许查看漏掉的事件并定位原片，观察结果进入当前版本的回执。

### 从同一剪辑交付多种声音版本

`timeline render PROJECT --audio-output silent --output-name silent.mp4` 导出纯视频流。项目的 `brief.audio_policy` 为 `silent` 时，默认导出也会移除音轨。需后期配乐或对白时，分别使用 `music`、`dialogue` 或 `dialogue-music` 并指定不同文件名，这三种模式选取时间线中相应类型的独立音轨。使用 `timeline` 会按完整的原声、混音和效果设置导出。每份导出回执分别保存音轨选择、原素材哈希、剪辑映射和 FFprobe 流检查。
