# VideoCreate Production Workflows

Choose the profile by the viewer's task. Profiles create editable starting plans, not finished scripts or guaranteed model behavior.

## Existing local video editing

Use the explicit `edit-only` profile for MP4/MOV/MKV/WebM footage already on disk. It starts as an empty draft: `production next` asks for an import. Do not add placeholder generation jobs or select an upstream. Retained source windows determine duration; omit `--seconds` during initialization.

```powershell
python scripts/videocreate.py plan init projects/local-edit --profile edit-only --title "Local edit"
python scripts/videocreate.py production import-clip projects/local-edit --source "D:/media/source.mp4" --source-id take-001 --start 2 --end 8
python scripts/videocreate.py plan validate projects/local-edit
python scripts/videocreate.py plan compile projects/local-edit
python scripts/videocreate.py timeline render projects/local-edit
python scripts/videocreate.py production script-export projects/local-edit
python scripts/videocreate.py review page projects/local-edit
python scripts/videocreate.py production deliver projects/local-edit
```

Import requires local FFmpeg/FFprobe and full decoding; no tool is downloaded. Original bytes remain intact. The registered project copy is content-addressed under `assets/local-sources`; each source ID gets its own shot/clip/segment. Identical bytes can share storage while retaining different windows. IDs must be unique (1–48 ASCII letters/digits/dots/underscores/hyphens); `final` is reserved for final review. `--mute` discards source sound in the edit; otherwise available audio is retained at speed 1. The manager's project panel provides the same import form and performs file checks in a background thread.

The three changed plan layers are backed up under `production/backups`. An ordinary write error attempts to restore their exact original bytes; a rollback error identifies the backup. This is not a claim of atomic recovery from power loss across multiple files. Changing a registered copy's bytes, duration or metadata blocks render/review; restore the original or import a new source ID. Edit retained windows in `timeline.json` instead of reimporting the same ID. Later trimming, audio, subtitles and overlays use the existing timeline pipeline.

Status lists imported sources separately from remote tasks, skips unused outline/script/generation stages, and keeps actual review pending. `production script-export` renders the current source-to-timeline mapping as a read-only edit list; its structured JSON still projects only the director layer. Deliveries include local provenance separately from provider jobs. Metrics include retained footage in playback/source seconds and exclude it from generated attempts and model quality rates. Real playback/listening is still required; a successful import or local render approves no content. This branch accepts local videos only. Use mixed-video below for local footage and generated video jobs; pure images/GIFs use independent profiles.

## Local footage with generated video shots

`mixed-video` creates an empty v3 montage plan with zero provider jobs and no invented source duration. Start with `production import-clip`, authored generated shots, or both. Use `--seconds` only for an explicit final target: import does not silently extend that target, and inconsistent retained duration must be repaired. Canvas initialization supports 16:9 and 9:16. Existing scene/action/narrative/reference checks still apply to authored generated shots; the local footage's action load is observed rather than treated as a generation request.

```powershell
python scripts/videocreate.py plan init projects/mixed --profile mixed-video --title "Existing footage with a generated insert"
python scripts/videocreate.py production import-clip projects/mixed --source "D:/media/source.mp4" --source-id archive-001 --start 2 --end 5
# Author additional director shots, generation-plan jobs and timeline clips/segments.
python scripts/videocreate.py plan validate projects/mixed
python scripts/videocreate.py plan compile projects/mixed --config <config-file>
python scripts/videocreate.py plan route projects/mixed --config <config-file>
python scripts/videocreate.py jobs run projects/mixed --job generated-001 --config <config-file>
python scripts/videocreate.py timeline render projects/mixed
python scripts/videocreate.py review page projects/mixed
python scripts/videocreate.py production deliver projects/mixed
```

Local imports use the same full-decode, hash-bound project snapshot and rollback service as edit-only. Source IDs cannot shadow planned/saved model tasks; a locally supplied shot cannot also be covered by a generation job. The source remains separate from `state.jobs` and the ledger. Adding local footage does not change another shot's compiled prompt, overwrite a completed candidate or require model selection by itself. A local-only phase compiles/routes/runs with no provider configuration; once generation jobs exist, existing per-kind selection and batch preflight apply only to those jobs.

For an already authored shot, add `--shot-id EXACT_SHOT_ID` to `production import-clip` in a mixed-video project. The shot must have no generation job, local source or timeline segment. Import preserves its entire director record, including beat/evidence, actions, scene and audio intent, and adds a new source, clip and retained segment. No existing task or edit is replaced. The new segment is appended; position it explicitly in the shared timeline. Omit `--description` for this mode and edit the director layer to revise the shot's purpose. Without `--shot-id`, import creates a new local shot as before. A narrative plan must author its causal beats and cover each shot; mapping footage is not evidence that the planned action or dialogue actually occurred.

Generated jobs may list a local source ID in `depends_on`. Serial/parallel scheduling verifies these prerequisites as available snapshots without manufacturing completed provider tasks. Missing or stale bytes prevent dispatch before create/budget reservation, and local dependencies are checked again during request preparation. This is a readiness dependency: it neither uploads footage nor certifies its content, and does not automatically condition or regenerate the model output when a different valid snapshot is deliberately substituted. Use explicit typed reference records for actual media guidance. Late file edits after the last hash check remain possible without an OS-level immutable file handle; such later changes invalidate project validation/render/review on the next inspection.

Status and delivery list local sources and model jobs separately. The readable script includes a read-only source-to-timeline map; structured script import still modifies only the director layer. Metrics count both kinds in retained playback/source seconds, with generated-attempt rates and ledger costs restricted to actual model work. Source observations remain valid only for their own current bytes, scope and retained windows. A subtitle edit or another source's changed contract cannot erase unaffected source observations from the same receipt; the final edit is separately stale/unverified until rerendered and reviewed. Full receipts remain strictly checked at import. A successful render does not approve either source or final content.

This branch covers local video plus generated video. Static-image timeline clips, mixed image-generation plans, graphical shot/timeline authoring and broader online model acceptance remain separate work. No live provider request is implied by initializing, importing or inspecting a mixed plan.

## Pure generated images and native GIFs

`image-only` and `gif-only` create independent v3 image plans. They have `generation-plan.image_jobs`, with no video jobs, shots, retained windows or fictional video duration. Each job declares ID, operation, prompt, size, quality, output format, optional model/binding and ordered reference-image paths with hashes. Blank prompts remain drafts; `--seconds` is rejected. A native GIF image job requires a binding whose actual image contract supports native multi-frame GIF output; it does not automatically substitute another model or invoke video generation. GIF collections may also register local conversions in `local_gifs`; `gif-local` starts without any provider image jobs.

```powershell
python scripts/videocreate.py plan init projects/poster --profile image-only --topic "A boat at sunset"
python scripts/videocreate.py plan validate projects/poster
python scripts/videocreate.py plan compile projects/poster --config <config-file>
python scripts/videocreate.py production images-run projects/poster --config <config-file>
python scripts/videocreate.py review page projects/poster
python scripts/videocreate.py review image projects/poster --job image-001 --status pass --reviewer <reviewer> --observation "Actual observed detail"
python scripts/videocreate.py production deliver projects/poster
```

Use `image-edit` only with registered in-project references whose actual bytes still match their declared hashes. `plan compile/route` prepares the selected image route and parameter-consumption report offline. `production images-run` reuses the existing whole-batch parameter preflight, task ledger, quota and selection services. It does not grant spending permission. A malformed later item blocks dispatch before any image create. A completed unchanged image keeps its original model/binding even when defaults change. An active/unknown image create stays held for reconciliation; do not submit another job as recovery. Explicit content/replan retries require one selected `--job`, `--retry content|replan` and a nonempty `--reason`.

The production panel skips unused outline/script/video editing stages and uses image output/review state. `production script-export` emits a read-only image creative brief, edited at its source `generation-plan.image_jobs`. `review page` uses actual local output files; it approves nothing. Static images need observed image review; GIFs require full temporal observation as well as a structurally valid multi-frame result. Video-layer template/apply/packet receipts are inapplicable here. Missing or mismatched image receipts never grant acceptance. Title changes preserve source review; prompt/reference/size/quality/output format/model/binding changes invalidate the corresponding image plan. Changed result bytes block delivery.

`production deliver` writes `deliverables/images.delivery.json` with artifact hashes, actual available metadata, source reference mappings, original route identifiers, budget and pending/rejected observations. It is a collection manifest referencing project outputs, not a separate media archive. All current planned outputs must exist; final acceptance additionally requires their own valid receipts. Static-image width/height may remain unknown in the retained header inspector; requested size is not proof of actual dimensions or provider internals. Metrics count images/GIFs separately and report no generated video seconds for them. GUI checks remain distinct from real content observation.

## Local video or frames to GIF

Use `gif-local` when all inputs already exist. It starts as an empty draft; `production next` asks for a video or ordered static frames. Neither initialization, conversion, plan compile/route, review nor delivery needs provider configuration. No task is inserted into `state.jobs`, no ledger entry is created, and local GIF counts stay outside model quality/paid-attempt rates.

```powershell
python scripts/videocreate.py plan init projects/local-gif --profile gif-local
python scripts/videocreate.py production gif-video projects/local-gif --source "D:/media/source.mp4" --gif loop-001 --start 1 --duration 3 --fps 15 --width 480 --loop 0
# Alternative: --frame order is retained, including duplicate frames.
python scripts/videocreate.py production gif-frames projects/local-gif --frame "D:/media/a.png" --frame "D:/media/b.png" --gif loop-002 --fps 10 --width 480
python scripts/videocreate.py plan compile projects/local-gif
python scripts/videocreate.py review page projects/local-gif
python scripts/videocreate.py review gif projects/local-gif --gif loop-001 --status pass --reviewer <reviewer> --observation "Actual full playback observation" --temporal-observation
python scripts/videocreate.py production deliver projects/local-gif
```

Sources are copied content-addressed into `assets/local-gif-sources`; originals remain intact. Video input accepts MP4/MOV/MKV/WebM, with a finite in-source interval of 0.1–30 seconds. Ordered static PNG/JPEG/WebP frames must decode to one frame each and share actual dimensions and image format; 1–1800 frames and 0.1–30 seconds are allowed. Frame duration is count/fps. FPS is 1–60, width 64–2048, loop 0 means infinite, -1 omits repeat, and positive values set repeat count. Output duration is measured from GIF delays and can differ slightly due to frame/delay quantization. Source audio is absent from GIF output.

Conversion fully decodes inputs/output, requires multiple output frames and preserves exact source hashes, recipe, actual output metadata and derivation hash. `generation-plan.local_gifs` references the current derivation; previous files remain intact. Editing its recipe makes that GIF stale. Explicitly run `production gif-rebuild PROJECT --gif ID` to convert its saved snapshots again. Each rebuild requires review of the new derivation; any defect receipt on identical output bytes continues to dominate passes. Changed/missing snapshots, output or manifests block review and delivery. Titles alone do not invalidate the output.

Only the generation-plan layer is atomically replaced after conversion, under an optimistic byte check and project lock; the prior layer is backed up. Concurrent edits are preserved and reported as conflicts. Interrupted/failed conversion can leave unregistered source copies or outputs for inspection; it creates no remote ambiguity. This is not a multi-file power-loss transaction. The manager project panel provides asynchronous video/frame conversion forms and a separate local GIF list. Review remains explicit full playback; GUI construction tests do not certify visual usability. `production deliver` uses the same project-relative collection manifest as generated images. Mixed local/generated video timelines and a graphical recipe editor remain separate work.

## Photorealistic shorts

Use `portrait` for one quiet human performance, `action-insert` for a controlled single-action demonstration, and `scenic` for a landscape or vehicle movement. For brisk exchanges use `action-montage`; for a pet/action reversal use `animal-comedy`. These profiles target 10–20 seconds with jobs of at most 10 seconds. `muse-video` has a hard 10-second maximum per request, so longer edits use multiple jobs and are assembled locally. The demonstration profile holds preparation, contact and recovery for inspection; it is not a fast fight preset. The new coverage profiles create seven editable source takes with shorter retained windows. Read [fast-action-and-animal-comedy.md](fast-action-and-animal-comedy.md) before adapting them. Keep one primary subject action per take and build a new opening image only when identity, pose or composition needs stronger control.

```powershell
python scripts/videocreate.py plan init projects/my-short --profile portrait --seconds 15 --aspect-ratio 9:16
python scripts/videocreate.py plan validate projects/my-short
python scripts/videocreate.py plan audit projects/my-short
python scripts/videocreate.py plan route projects/my-short --config <config-file>
python scripts/videocreate.py plan compile projects/my-short --config <config-file>
python scripts/videocreate.py plan preview projects/my-short
```

Before generation, replace the starter action and setting with the requested subject and action, add reference assets when useful, and verify that each job has a fixed intended model/binding. For a connected action, run one completed shot, inspect it, then use `assets handoff` to extract a timestamped frame as the next job's opening-frame reference. This is an image-to-video continuation aid; it does not prove native last-frame control.

After generation, use `jobs candidates` and `jobs select` to record which completed attempt is being edited. Selection preserves the original and is not approval. Choose source in/out windows from the actual clip, validate and render the timeline, then open `review packet` and review moving footage and audio. Keep the deliverable labeled `draft_preview` while applicable review layers remain unverified.

For a reference video, first run `reference analyze <video> --output <study-folder>`. Landscape, square and portrait sources use matching thumbnail canvases. For a screen recording, inspect an original frame then use `--crop X Y WIDTH HEIGHT` with an even, in-bounds content rectangle to exclude player UI. Cropping is explicit and hash-bound; it does not rewrite the source. Sampling fills long gaps when scene candidates are sparse, but remains incomplete. Inspect the contact sheet and measurements, then record observations against sampled frame IDs or the actual video interval. Static frames can support composition, color, wardrobe, and visible subjects; they cannot verify camera motion, action timing, cuts, or sound. Create and attach a profile only after those observations are accurate.

## Source-grounded explainers

Use `explainer` for geography, history, science, or current-affairs explainers. Treat generated visuals as illustration unless a separately attributable source clip is imported. Research claims and narration before video jobs; every factual narration line needs claim IDs, and every quantitative claim needs a value, unit, year, geography, and definition. Rankings also need a dated comparison universe, basis, and coverage.

```powershell
python scripts/videocreate.py plan init projects/my-explainer --profile explainer --topic "Topic" --seconds 45
python scripts/videocreate.py education source projects/my-explainer --source-id source-1 --url https://example.org/report --title "Report title" --publisher "Publisher" --file .\source-notes.txt
python scripts/videocreate.py education validate projects/my-explainer
python scripts/videocreate.py education validate projects/my-explainer --ready
python scripts/videocreate.py education export projects/my-explainer
```

The source command preserves a local UTF-8 snapshot and its hash; it does not independently decide whether a source supports a claim. A reviewer must record a matching excerpt and source hash for a verified claim. Validate before any paid job. Prefer independent narration and accurate post-produced subtitles. Use supplied, attributable GeoJSON for precise maps; do not ask a video model to draw exact boundaries or statistics.

## Episodic series

Use a series bible to freeze shared characters, references, world rules, season arc, and episode count. Each episode remains its own v3 project with its own reviewed ending. Start a new episode only after the previous episode's source and final reviews have been accepted.

```powershell
python scripts/videocreate.py series init projects/my-series --title "Series title" --episodes 20
python scripts/videocreate.py series prepare projects/my-series --episode 1 --seconds 60
python scripts/videocreate.py series check projects/my-series/episodes/episode-001
```

Author each episode's goal, obstacle, choice, consequence, beats, shots, dialogue, and next-episode question before generation. Review and render the episode, then provide an observation grounded in the actual final interval to `series accept`. An unaccepted script or planned ending is not episode continuity. Expand to 20 episodes only after the character and visual style remain usable in a reviewed first episode.

## Model routing and quality evidence

Use `plan route` after assigning the exact model and optional fixed binding to each job. Model family, upstream platform, and wire adapter are separate settings. Do not switch models silently to fill a missing route. A configured or catalog-visible binding is not evidence that it produces natural movement, consistent identity, usable speech, or good sound. Record quality evidence only after reviewing the exact output bytes for the exact operation; required quality checks block a route until matching evidence exists.

Keep API creation limits explicit. Resume a known task rather than submitting again. Treat transport errors, trace IDs without task IDs, and missing dashboard records as unresolved until the upstream confirms whether a task was created.

## First-person historical films

Anchor every shot to a named camera owner, a concrete location, visible clothing/props, and an observable entry/exit state. For example: concealed behind the same ridge rock, blue-gray hands and wooden rifle remain in the lower frame while a distant convoy passes below. A continuous take needs an explicit camera limit and action; generic instructions such as "continue the state" do not describe what the model must show. Supporting characters can appear and react naturally in the first-person frame.

Keep each shot's visible asset list specific. A signal closeup needs the signaling comrade and foreground gear; adding the whole opposing army and convoy can dilute that shot. Preserve important location sound and voice direction alongside dialogue. Verify viewpoint, weapon/prop shape and foreground hands at several times after the opening; a matching first frame alone does not show that the rest of the clip follows it.

When framing or camera position declares first-person/POV (including 第一人称), the compiler adds an explicit viewpoint continuity instruction. This is prompt guidance, not a provider camera-control feature: a real Muse test still switched to external views and another retry lost the action and location. Compare candidates before selection; retain the more informative take and record remaining defects. Stop at the configured per-project request and per-job attempt limits; more retries do not guarantee better output.

Separate costume identity from composition when creating opening images. A full scenic master can pull every new frame back to the same viewpoint; for a turn or arrival, a local sleeve/prop crop can preserve material details while leaving the new camera location free. Check adjacent frames together for time of day, movement axis and whether the ending visibly reaches its destination. Independent coverage can run concurrently after the pilot inspection. A shot that must start at the preceding shot's observed ending needs a saved frame handoff and a dependency, which limits that portion's concurrency.

Record the date, opposing forces, invented viewpoint and factual limits of historical reconstructions. Mark literary episodes such as Zhuge Liang borrowing arrows as dramatizations of *Romance of the Three Kingdoms*. Keep sampled-frame findings separate from moving-video and listening review; missing evidence remains unverified.
