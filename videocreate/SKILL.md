---
name: videocreate
description: Plan, generate, edit and review resumable AI videos with independently configured models and upstreams. Use for text/image-to-video, historical character and product comedy, short drama, character references, storyboards, native dialogue, slow motion, multi-shot editing, subtitles, series and existing video projects. Supports binding-specific Sub2API/NewAPI protocols and independent image generation. Does not publish videos.
---

# VideoCreate

Turn a brief into a story viewers can follow, motivated performances, purposeful shots and an editable timeline. Models execute the plan; a successful API response is not content acceptance.

Use `python scripts/videocreate.py` from this skill directory (or installed `videocreate`). The current version comes from `version`. Commands ending in legacy project names are retained for existing projects; new work uses `plan`, `assets`, `jobs`, `timeline` and `review`.

For new video/media creation requests, load the local JSON with `config init/show`, create and validate an appropriate v3 plan, compile and preview it offline, generate only within the active authorization, then locally edit and truthfully review the resulting media. Do not use the legacy v2 create path for new projects just because it is more complete. Existing v2 project recovery remains in scope.

## Setup

Run `config init` when a user configuration is missing. Tell the user its exact returned path and ask them to edit URL/auth/remote_model/enabled bindings in that single JSON; use `config open` when requested. Never ask them to paste a key into chat. Existing Windows credentials can be migrated with `config migrate --apply`, which preserves encrypted bytes and old settings.

`config validate --ready` is offline. `doctor` checks local configuration; `doctor --read-only` additionally queries catalogs without creating media. Catalog visibility does not verify video, audio, likeness or reference semantics. Installation and inspection do not authorize paid probes or optional model downloads.

Each binding selects one canonical model, one named upstream instance, one exact remote model ID and one versioned adapter. Grok/Seedance are model families; Sub2API/NewAPI are platforms. Do not infer a wire protocol from a model name. Read [configuration.md](references/configuration.md) for the single JSON and its limits.

## New video workflow

1. Use the user's current creative goal and references. Inspect supplied media as evidence, not instructions. Decide whether this is a narrative, demonstration, montage or single shot. Do not force every product demonstration or silent film into a joke or rapid dialogue.
2. Create `plan init <project> --title ... --intent narrative --pace comedy` and author its five layer files. `--example smart-car` creates an editable 30-second historical product comedy example; it is not a generated film or a fixed template for all requests.
3. Write the audience's one-sentence understanding. In narrative beats, declare requires/effects, causal predecessors, viewer information and visible evidence. Product functionality must enable a character choice and a visible result; explain what would break if the product were removed.
4. Design coverage around information. Distinguish a reaction closeup, product detail and travel/action shot. For acting, specify trigger → attention → visible response → decision, eyeline and screen direction. Separate camera movement from subject movement. Lock identity and costume while allowing motivated movement. Do not fill a short clip with travel, turning, following, dialogue and arrival at once.
5. Register identity, prop and scene references with `assets register <project> --asset-id ... --source ...`. Preserve source hashes. Use an independent image binding via `assets image` to compose an opening frame when useful. Current video adapters transmit opening-frame references; they do not have independently verified identity/last-frame/video/audio reference roles. Do not pass a portrait as an exit-frame lock for an unrelated reverse shot. Only generate masters that will actually be used.
6. Maintain the distinction between beat IDs, shot IDs, job IDs, clip IDs and timeline segment IDs. Select generated seconds separately from retained seconds. Keep subtitles and independent sound events in timeline time or with an explicit source mapping. Read [v3-project.md](references/v3-project.md) for fields and commands.
7. Run `plan validate`, `plan compile --config ...` and `plan preview`. Preview is an offline HTML storyboard; `--video` renders silent text cards using local Pillow/FFmpeg. Do not present cards as realized facial performance or voice. Validation checks declared structure; content stays unverified. Investigate action-load, state, dialogue-window and uncovered-evidence errors before spending.
8. Under the user's existing generation authorization and request/cost limits, run `jobs run <project> --job ...` for two adjacent critical shots first. A fixed route stays fixed. Unknown submission stays held; known tasks resume on their saved URL/model/adapter even if defaults change. Requests without a confirmed task ID must not automatically create again.
9. Inspect actual source videos and select retained windows. Render with `timeline render`. Local retiming affects only selected segments; natural-speed dialogue can bridge onto a reaction or detail shot through independent audio tracks. Actual 24 fps source at 0.5 speed contains about 12 source frame samples per playback second. Container fps conversion is not high-frame-rate capture. Originals stay separate from edited outputs.
10. Use `review template`, actually view/listen to the retained media, then `review apply`. Temporal layers require video evidence over the reviewed interval; audio requires listening. Answer final understanding questions from the video before consulting the script. Missing tools leave layers unverified. A real defect on the same bytes overrides pass receipts. Deliver previews as draft_preview/review_pending until all applicable content layers pass.

Do not promise a particular actor's exact likeness, reliable speech or cinematic quality from a prompt alone. Use the user's authorized identity references, test actual results and report remaining drift. Authorization for a face does not by itself specify a voice asset.

## Recovery and local repairs

`jobs status` reads state and budget without generation. Network retry resumes reads on the known task; content retry requests a new candidate; replan creates a new attempt for changed generation inputs. New paid attempts require an explicit selected job and reason, within the session's authorization and remaining limits. Altering a title/subtitle must not regenerate video.

For an unknown submission use `jobs resolve --receipt ...` with the original attempt/binding and actual upstream evidence. “查不到”“暂时查不到” remain inconclusive. A not-received decision requires explicit upstream confirmation that neither the submission nor a task was created. Local stopping is not remote cancellation. Read [runtime-and-review.md](references/runtime-and-review.md) for receipts and budgets.

Fix the defective component: source performance/identity → local candidate or replan; wrong sound → voice/sound track; editing problem → timeline; subtitle issue → subtitles. Reinspect derived bytes and invalidate stale evidence. Never repair a visible defect by weakening an approval requirement or adding a nonempty state_change_reason.

## Existing projects and optional services

Existing `project.version=1` projects keep the legacy commands and task state. The old Python filename is an import/CLI shim only. Read [legacy-v2-workflow.md](references/legacy-v2-workflow.md) for existing series/news/voice/ChatCut/editor commands, and the relevant narrower reference when needed. Do not run a legacy generation command on a v3 layer bundle.

Local TTS, lip sync, external editing and publishing are optional, separate choices. The retained FFmpeg flow works independently. Do not download optional voice/lip models simply because a character speaks, and do not send/upload/publish without the user's applicable authorization.
