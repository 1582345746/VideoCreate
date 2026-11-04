# Runtime 与内容验收

## Runtime states

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
