# VideoCreate Production Workflows

Choose the profile by the viewer's task. Profiles create editable starting plans, not finished scripts or guaranteed model behavior.

## Photorealistic shorts

Use `portrait` for one quiet human performance, `action-insert` for one readable physical action, and `scenic` for a landscape or vehicle movement. These profiles target 10–20 seconds and split jobs into clips of at most 10 seconds. `muse-video` has a hard 10-second maximum per request, so longer edits use multiple jobs and are assembled locally. A 10-second action stays in one shot with distinct preparation, contact, recovery and settle phases; longer edits separate the main action from recovery/detail coverage. Keep one primary subject action and build a new opening image only when the actor, costume, pose, or composition needs stronger control.

```powershell
python scripts/videocreate.py plan init projects/my-short --profile portrait --seconds 15 --aspect-ratio 9:16
python scripts/videocreate.py plan validate projects/my-short
python scripts/videocreate.py plan route projects/my-short --config <config-file>
python scripts/videocreate.py plan compile projects/my-short --config <config-file>
python scripts/videocreate.py plan preview projects/my-short
```

Before generation, replace the starter action and setting with the requested subject and action, add reference assets when useful, and verify that each job has a fixed intended model/binding. For a connected action, run one completed shot, inspect it, then use `assets handoff` to extract a timestamped frame as the next job's opening-frame reference. This is an image-to-video continuation aid; it does not prove native last-frame control.

After generation, use `jobs candidates` and `jobs select` to record which completed attempt is being edited. Selection preserves the original and is not approval. Choose source in/out windows from the actual clip, validate and render the timeline, then open `review packet` and review moving footage and audio. Keep the deliverable labeled `draft_preview` while applicable review layers remain unverified.

For a reference video, first run `reference analyze <video> --output <study-folder>`. Inspect its contact sheet and measurements, then record human observations against sampled frame IDs or the actual video interval. Static frames can support composition, color, wardrobe, and visible subjects; they cannot verify camera motion, action timing, cuts, or sound. Create and attach a profile only after those observations are accurate.

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
