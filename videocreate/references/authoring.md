# Offline theme and outline authoring

Use the manager's **新建制作项目** for an editable starting plan, then **项目与任务 → 编辑主题与规格 / 编辑故事大纲**. Creation, preview, save and reading-copy export never select or call a model. A profile supplies a starting structure; the agent still authors the user's actual story and shots. Topic, audience and the viewer's intended understanding are separate fields, not automatically generated prompts.

The theme form edits `brief` only: topic, audience, viewer goal, viewing intent, pace, explicit target duration, generation aspect ratio/resolution, sound policy and visual constraints. It preserves the workflow profile. Generation specifications do not resize the timeline or rewrite shots. The title is set when creating the project and remains read-only here.

The outline form edits `story` only: logline, goal, obstacle, choice, consequence, optional payoff, initial state and ordered causal beats. Each beat retains its stable ID, causal predecessors, viewer information, visible-evidence IDs and requires/effects. The state table supports text, finite numbers, booleans and null; existing nested JSON values remain exact until deliberately replaced. Reordering or deleting a beat does not silently remap director shots or repair causal links. A resulting coverage/state error is shown in preview and remains a generation blocker.

`brief` and `story` remain authoritative. The director, generation plan, timeline, state, candidates, ledger, references and stage decisions are not rewritten by an authoring save. Existing checkpoints become stale through their normal input hashes; saving never accepts a stage or media. Animation outlines owned by an animation sidecar must be edited at that source, so this form does not create a competing animation story.

## Preview and save

The form binds a source token to the current complete plan. Preview shows field differences, complete plan errors, changed request inputs/dependents and saved task statuses. Model tasks remain pinned. Metadata or an outline-only change does not recreate footage; a generation-specification change may make a request's inputs stale, requiring the existing explicit replan path later.

Shape-invalid values are rejected. A schema-valid but incomplete plan can be saved as a draft; generation/render/delivery retain their normal gates. Never present successful saving as an executable or approved film. New empty montage/local/image profiles may still have authoring or media blockers.

Save binds the exact proposed value, plan and task state to the preview. Editing after preview, another plan edit or a task-state transition requires a fresh preview. Save rechecks plan/task versions under the shared lock, backs up the old layer and atomically replaces that one layer. No-op saves create no backup. Media hashing/probing happens outside that short lock and in a background GUI worker; the form waits while its operation completes. This is a single-layer transaction with cooperating writers, not an OS-level immutable media snapshot or a multi-file crash transaction.

New-project creation claims a new directory exclusively; it rejects existing empty folders, partial projects and populated projects. Layer files are saved before `project.json`. An interrupted/failed creation may leave a partial directory for inspection; it is preserved rather than deleted or overwritten automatically. Choose a new directory or repair that partial project explicitly.

## CLI

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

Use `--layer story` for a structured outline. `authoring outline` exports `production/outline.md` with a source hash, topic/specifications, causal order, requires/effects, evidence and actual shot coverage. The reading copy is a read-only projection; editing it never imports changes. Existing `production script-export/script-import` remains the versioned director exchange. Shot/character/timeline graphical authoring is separate work.
