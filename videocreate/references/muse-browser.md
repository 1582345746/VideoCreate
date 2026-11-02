# Muse and browser generation

Use this reference for Muse-only generation or an API-image → Muse-video workflow. Muse is a website execution route, not a Sub2API/NewAPI adapter. The same story, director plan, asset hashes and media reviews apply.

## Configuration and current implementation

In the existing user JSON, `browser_services` defines site URLs and browser choices; `workflows` defines ordered API/browser stages. The shipped example contains `api-image-api-video`, `muse-image`, `muse-video`, `muse-image-video`, and `api-image-muse-video`. These are recipes, not assertions that Muse supports every requested operation. `requested_operations` records intent; it never certifies capability.

`workflow list` lists recipes; `workflow describe --workflow ID` resolves configured stage targets without reading credentials or visiting the site. `workflow prepare PROJECT --workflow ID --stage ID` creates a content-hashed local browser handoff. It does not launch a browser, reserve budget, generate media, or run the workflow automatically. No site-specific submit/poll/download driver has been validated yet. API stages still use `assets image` / `jobs run` with their selected binding. `config validate --ready` checks the API route, not browser readiness; browser preparation needs no API credentials.

Video stages require `--job ID`. The existing project's job operation must match the stage. To switch an intended shot to image-to-video, explicitly update that job's operation and opening-frame references (path/sha256), then validate. The compiler retains only the current shot's composition, motivated actions, reactions, geography and sound. It does not send the whole story as one confused prompt. Image stages accept a standalone directory containing `--prompt-file`; when a valid v3 project is present, its brief contributes optional display parameters only. Image-edit also requires an actual `--reference`. Reference paths are relative to the project (or absolute inside it). Text-only operations reject attached images instead of silently changing modes.

Examples from the skill directory:

```text
python scripts/videocreate.py workflow list
python scripts/videocreate.py workflow describe --workflow muse-video
python scripts/videocreate.py workflow prepare PROJECT --workflow muse-video --stage video --job job-001
python scripts/videocreate.py workflow prepare PROJECT --workflow muse-image --stage image --prompt-file prompts/opening.txt
python scripts/videocreate.py workflow prepare PROJECT --workflow api-image-muse-video --stage video --job job-001
```

The packet is `prepared_only`, `can_execute: false`, `not_submitted`. Repeating preparation reuses the same hash without touching API job state. A configured local prompt cap is not evidence of the website's actual limit. An `input_from` link requires checking that the uploaded image is the downloaded output of that stage; the graph alone does not prove provenance. The 2026-11-02 built-in-browser capability query confirmed the account exposes text-to-image, image editing, text-to-video and image-to-video, but did not create a task; model selection, exact duration, resolution and per-task cost remain unavailable or unverified.

## Browser choice and account session

Honor the user's browser choice. Prefer the Codex built-in browser when chosen; inspect the actual tools available in the current turn. Opening a tab alone cannot read or operate it. If read, click, input, upload or download is unavailable, report exactly which operation is blocked and continue independent local preparation. Do not promise the user that logging in will fix missing automation tools.

`driver: codex-browser` needs the host's supported browser tools. `driver: playwright-local` is an optional dedicated local browser selected by the user; this version does not include a packaged Playwright runner. Do not silently fall back, share sessions, probe internal debugging ports, or extract cookies from another browser. A local driver may use `profile_directory`; the built-in driver must not. The user performs login and verification directly in the chosen browser. No passwords, cookies, tokens or browser storage belong in project packets or the config.

## Live test, when tools and the real generation page are available

1. Read the current page and final origin. Confirm it is the intended service; `allowed_origins` lists exact approved HTTPS origins. Stop on an unexpected destination and clarify the actual service; do not infer a generator from the name Muse. Do not navigate to guessed endpoints. Login redirects can require the user's manual interaction.
2. Inspect actual controls for each operation: text-to-image, text-to-video and image-to-video independently. Record visible model choices, image roles, duration/aspect ratio/resolution and displayed cost. If a parameter is unavailable, report the mismatch before generating. Enabling a JSON service does not verify these controls.
3. Use the current stage's handoff and actual local reference files. Verify their SHA-256 hashes again before upload. Respect any host upload/download restrictions. If the host cannot upload the required file, keep the stage blocked instead of silently running text-to-video.
4. Before a generation click, persist a separate browser attempt record alongside the packet with packet_id, unique attempt_id, service/driver, operation, input hashes, status `submitting`, observed cost, and UTC timestamp. Check the project's API and browser attempts together against the user's request and money limits. Unknown money cannot satisfy a hard amount cap. These browser checks are currently agent-managed, not enforced by an automatic browser runtime.
5. Click once within the user's existing authorization. Save the real task ID or task-detail URL plus observable page evidence. On timeout or unclear acceptance, mark `submission_unknown` and reconcile that same attempt; absence from history is inconclusive and does not permit a second click. Resume known tasks; do not create replacements during polling.
6. Download original image/video files only through supported site/browser controls. Record source task, file size, hash and media properties. Keep external browser records separate from API job state; do not forge an API completion. A screenshot or a result card is not the downloaded media.
7. Register image assets with the existing asset workflow. For video, use the existing timeline's `clip.path` for a local source (inside the project) and preserve its browser provenance separately. Inspect actual motion, identity, expression, framing, audio and viewer comprehension with the standard review receipts. A successful download is not content approval.

A public-page probe, a login, a simulated test, or a successful image generation cannot certify video generation. Report each tested operation and evidence separately. If no generation was performed, say so.
