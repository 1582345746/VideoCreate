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
