# Offline production authoring

Use the manager's **新建制作项目** for an editable starting plan, then **项目与任务 → 编辑主题与规格 / 编辑故事大纲 / 编辑剧本与分镜**. Creation, preview, save and reading-copy export never select or call a model. A profile supplies a starting structure; the agent still authors the user's actual story and shots. Topic, audience and the viewer's intended understanding are separate fields, not automatically generated prompts.

The theme form edits `brief` only: topic, audience, viewer goal, viewing intent, pace, explicit target duration, generation aspect ratio/resolution, sound policy and visual constraints. It preserves the workflow profile. Generation specifications do not resize the timeline or rewrite shots. The title is set when creating the project and remains read-only here.

The outline form edits `story` only: logline, goal, obstacle, choice, consequence, optional payoff, initial state and ordered causal beats. Each beat retains its stable ID, causal predecessors, viewer information, visible-evidence IDs and requires/effects. The state table supports text, finite numbers, booleans and null; existing nested JSON values remain exact until deliberately replaced. Reordering or deleting a beat does not silently remap director shots or repair causal links. A resulting coverage/state error is shown in preview and remains a generation blocker.

The screenplay form edits `director` scenes and shots: geography/axis/positions, stable beat and scene links, shot purpose and framing, ordered actions, explicit performance and timing, optional prose/structured entry/exit states, and ordered dialogue with speakers, source-time intervals and on-screen flags. Its project-card tab edits characters, scenes, props and voice samples; the project panel also opens these cards separately while preserving scenes/shots. Advanced shot fields remain exact. Refresh the ID lookup after adding unsaved cards. Changing shot order does not change playback order. New/deleted/renamed shots, scenes and cards do not silently create or remap jobs, timeline segments, references or sources; preview shows missing links and input changes, and execution stays blocked until repaired. Planned seconds, provider seconds and retained timeline intervals remain separate; the timeline has its own editor below.

Each save writes only its selected authoritative `brief`, `story`, `director`, `generation-plan` or `timeline` layer. Other layers, task state, candidates, ledger and stage decisions are preserved. Existing checkpoints become stale through their normal input hashes; saving never accepts a stage or media. Animation story/director/generation plans owned by a sidecar must be edited at that source, so neither the form nor script import creates a competing animation source.

## Generation plans

The project panel's **生成任务与参考** edits the existing generation layer. Video projects show stable job IDs, ordered shot IDs, operation, generated seconds, readiness dependencies and required observed-quality checks. Resolution/aspect ratio still come from brief, and sound intent comes from the associated shots; the editor does not add unsupported per-job provider parameters. Pure image/GIF projects instead show prompts, operation, size, quality and output format. Local GIF conversions retain their separate conversion/recipe service.

Model and binding dropdowns read the saved configuration, including labeled disabled/draft entries for planning. **由所选接入填写型号** explicitly fills the canonical model from that exact binding; it does not set a project/global default or enable it. Empty route fields retain normal numbered selection when execution needs a choice. Saving does not certify protocol readiness, credentials, model limits, pricing or output quality; runtime preflight remains authoritative. An imported unknown route ID is preserved for repair.

Reference rows preserve order, kind, role and derivation. **选取项目内参考文件** probes bytes and fills its path/hash in the unsaved form; external files must first use project asset staging or `media-ref register`. **导入已登记参考 JSON** checks its actual local bytes and retains supported reference fields; a pure image job accepts only images, using the existing image inspector so animated GIF inputs retain their actual frames. A binding must separately support native GIF input/output at runtime. Removing/reordering rows does not delete files. Choose a compatible operation yourself: text-to-video with references, an absent opening-frame primary or mixed untyped/typed input stays blocked. These controls do not publish HTTPS links, upload or clone voices; hosting/link preflight remains separate.

This editor refuses edits to active/unresolved jobs, including submitting, unknown, queued, in-progress and read-pending records. Saved task entries cannot be deleted, renamed or moved to another media kind, and a new job cannot claim an orphan history ID. Completed/failed/rejected jobs may keep their ID for an explicitly planned new attempt; originals, candidates, task IDs, route snapshots and ledger remain unchanged. Route changes show the original binding and future-only scope. Video input hashes exclude route selection for existing-task recovery; pure-image route edits may also make the planned image stale. Neither behavior submits a new request. Use the existing selected-job replan/retry command and authorization when actually creating a replacement.

The generation form preserves `local_sources` and `local_gifs`; CLI authoring also rejects changes to those records, which belong to their original services. Job add/remove/order changes do not remap clips or playback. Preview exposes complete-plan errors; incomplete shot links and dependency cycles can be saved as schema-valid drafts, and execution remains blocked. Animation-owned generation plans continue to be authored through their sidecar. This protection covers the authoring service; earlier specialized reference/import commands keep their separate behavior and are not claimed to be a universal edit transaction.

## Timeline edits

Video project panels expose **剪辑时间线与声音**, sharing `authoring show/preview/save --layer timeline`. Set output fps/canvas separately from generation specifications; canvas dimensions must be even integers from 64 to 4096. Clip rows map stable IDs to generated jobs/selected candidates or registered local sources. **使用所选来源的默认素材** explicitly uses a local source's registered path or clears a generated clip's path override. It never changes the original task or selected candidate. Imported source paths/shot mappings remain subject to the existing runtime validator.

Retained segments play in list order with `[source_in,source_out)` and optional speed. Edit source sound separately: `mute`, `retime`, or `preserve`; non-unit speed with preserved speech remains a validation error. Independent sound events retain natural speed and an explicit timeline start/gain. `clip_id` takes precedence over `path` when both are present. A file picker associates existing project files, without copying, probing content or uploading; render verifies actual media and records hashes. Keep the source files available.

Registered static image clips use source_in=0, source_out=hold seconds, rate=1 and mute; this is authored hold time, not captured source time. Import them through **导入静态图片** or `production import-image` before selecting their registered path here. A hold can be lengthened or repeated without manufacturing source duration; independent audio supplies voice/music. The project and runtime validator reject video-speed/source-audio settings on static images. Image-source observations and final-video playback review remain separate; see [production-workflows.md](production-workflows.md).

Subtitles choose source intervals on stable segment IDs or absolute timeline intervals. Source cues follow the retained window, rate and segment order; partial cuts remain errors. Absolute cues, independent sound and overlays retain their authored timeline times after reordering. Changing the subtitle coordinate mode removes the former coordinates and requires explicit new values; it does not silently calculate them. Text/image overlays enter the picture render, while subtitle cues export to SRT. Planned native dialogue is not an observed transcript.

**更新时间线示意** draws the current unsaved mapping with picture/audio/subtitle/overlay lanes; clicking a picture segment opens its form. This is a proportional edit schematic, without thumbnails, waveform, video playback or drag trimming. **刷新素材与片段选项** includes unsaved clip/segment IDs in dropdowns without remapping existing links. Preview exposes old/new mappings and full-plan errors; schema-valid incomplete edits may be saved as drafts. Saving preserves task state/candidates/budget and all other layers, even when a task is active. It does not render or submit anything. Render through `timeline render`, or use the project-panel **渲染当前时间线** button; the latter runs the same local renderer in a background worker after re-reading the current project and state. **导出交付清单** calls the shared delivery service after re-reading current status and file hashes. Neither action loads provider configuration or creates a model task. A delivery export can remain `review_pending`; exporting a manifest never approves the media. Review the changed final edit; source review is neither deleted nor promoted to final approval. Animation may edit its local timeline without changing its sidecar, projected screenplay or jobs; explicitly rebuilding the animation plan can replace its projected edit topology. Image/GIF collections do not have a video edit layer.

## Preview and save

The form binds a source token to the current complete plan. Preview shows field differences, complete plan errors, changed request inputs/dependents and saved task statuses. Model tasks remain pinned. Metadata or an outline-only change does not recreate footage; a generation-specification change may make a request's inputs stale, requiring the existing explicit replan path later.

Shape-invalid values are rejected. A schema-valid but incomplete plan can be saved as a draft; generation/render/delivery retain their normal gates. Never present successful saving as an executable or approved film. New empty montage/local/image profiles may still have authoring or media blockers.

Save binds the exact proposed value, plan and task state to the preview. Editing after preview, another plan edit or a task-state transition requires a fresh preview. Save rechecks plan/task versions under the shared lock, backs up the old layer and atomically replaces that one layer. No-op saves create no backup. Media hashing/probing happens outside that short lock and in a background GUI worker; the form waits while its operation completes. This is a single-layer transaction with cooperating writers, not an OS-level immutable media snapshot or a multi-file crash transaction.

New-project creation claims a new directory exclusively; it rejects existing empty folders, partial projects and populated projects. Layer files are saved before `project.json`. An interrupted/failed creation may leave a partial directory for inspection; it is preserved rather than deleted or overwritten automatically. Choose a new directory or repair that partial project explicitly.

## Continue the current project

**项目与任务 → 继续制作** resolves the current `production.status` next step each time. An authoring step shows its exact current inputs, input hash and associated editor; **登记本阶段计划已核对** requires an explanation and rechecks that hash. Another saved edit makes the old inspection stale. Animation sidecar stages keep their original source instead of offering an ordinary story/director/generation editor. Local GIF recipes keep their explicit conversion/rebuild service.

For edit/review/delivery, the button runs one local action in the background: render the saved timeline, export and open the actual review page, or export a delivery manifest. It does not automatically approve any stage or dispatch provider jobs. Existing task IDs, original routes, candidates and ledger remain authoritative. Generation and unknown submissions show the current task rows and explicit next entries; an unknown submission does not fall through to a new request. Empty local/mixed/GIF projects offer their corresponding import or authoring entry. Invalid plans show their actual errors.

The CLI uses the same resolver:

```powershell
python scripts/videocreate.py production continue-local PROJECT
python scripts/videocreate.py production continue-local PROJECT --execute --token <returned token>
```

The first command only describes. The second executes only a currently executable local render, review-page export or delivery, and rejects a changed description. It never opens a browser itself; use the returned `page` path. This is a check at action start, not a long project lock across FFmpeg or an immutable filesystem snapshot. Concurrent subsequent edits can stale the output through the existing manifest/review rules. Assisted authoring and authorized automatic continuation retain the existing policy semantics; this entry grants no spending authorization.

## CLI authoring

The CLI uses the same service as the manager. It requires no provider configuration:

```powershell
python scripts/videocreate.py authoring create projects/ancient-cs --profile mixed-video --title "古代计算机喜剧" --topic "程序员穿越" --audience "大学生" --viewer-goal "理解修复系统造成的反转"
python scripts/videocreate.py authoring show projects/ancient-cs --layer brief
```

Copy the returned `value` to an edit JSON file and retain its `source_token`. After editing that layer:

```powershell
python scripts/videocreate.py authoring preview projects/ancient-cs --layer brief --file brief-edit.json --source-token <source_token>
python scripts/videocreate.py authoring save projects/ancient-cs --layer brief --file brief-edit.json --source-token <source_token> --preview-token <preview_token>
python scripts/videocreate.py authoring outline projects/ancient-cs
```

Use `--layer story` for an outline, `--layer director` for scenes/shots/cards, `--layer generation-plan` for jobs or `--layer timeline` for edits; the same source and preview tokens apply. See [asset-library.md](asset-library.md) for local reference staging and separated visual/physical design. `authoring outline` exports `production/outline.md` with a source hash, topic/specifications, causal order, requires/effects, evidence and actual shot coverage. The reading copy is a read-only projection; editing it never imports changes. `production script-export` exports readable scenes, beat links and timed dialogue plus the versioned `script.json` exchange. `production script-import` shares the preview/save service and still requires a semantically complete plan; the form/authoring command can save schema-valid drafts. Dialogue, performance and emotion descriptions are plans, not proof that generated speech, lips or acting succeeded.
