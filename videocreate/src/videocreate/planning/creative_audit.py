"""Advisory checks on declared coverage; never an appraisal of generated footage."""
from __future__ import annotations

import re


def audit(bundle: dict) -> dict:
    shots = bundle["director"]["shots"]
    jobs = bundle["generation-plan"]["jobs"]
    timeline = bundle["timeline"]
    findings = []

    def add(code, scope, reason, remedy):
        findings.append({"code": code, "scope": scope, "reason": reason, "remedy": remedy})

    clips = {c["id"]: c for c in timeline["clips"]}
    by_job = {j["id"]: j for j in jobs}
    full = []
    for seg in timeline["segments"]:
        job = by_job.get(clips.get(seg["clip_id"], {}).get("job_id"), {})
        if (job.get("seconds", 0) >= 8 and seg["source_in"] == 0 and
                abs(seg["source_out"]-job["seconds"]) < .01 and seg.get("rate", 1) == 1):
            full.append(seg["id"])
    if len(full) >= 3 and len(full) / max(1, len(timeline["segments"])) >= .75:
        add("full-long-takes", full, "Most of the edit retains whole long generated takes; source boundaries may be determining the rhythm.",
            "Inspect usable intervals; cut on new information, action result or reaction. Long takes remain valid when their actual performance sustains them.")
    fast = bundle["brief"].get("pace_profile") == "action" or bundle["brief"].get("workflow_profile") == "animal-comedy"
    roles = {s.get("role") for s in shots}
    if fast and len(shots) >= 3:
        if not roles.intersection({"setup", "establishing", "environment"}):
            add("missing-spatial-coverage", [s["id"] for s in shots], "No explicit setup/establishing/environment shot role is declared; existing framing may still establish space.",
                "Show the subject, target, separation and direction in a readable medium or wide view before detail shots.")
        if not roles.intersection({"result", "payoff"}):
            add("missing-result-coverage", [s["id"] for s in shots], "No explicit result or payoff shot role is declared; inspect existing coverage before adding a take.",
                "Show what changed because of the action, then a reaction; a contact close-up alone may not explain the outcome.")
    pov_jobs = []
    for job in jobs:
        job_shots = [s for s in shots if s["id"] in job["shot_ids"]]
        if any(re.search(r"\bpov\b|first[ -]person|第一人称", " ".join(str(s.get(k, "")) for k in ("framing", "camera_position")), re.I) for s in job_shots):
            pov_jobs.append(job)
    if len(pov_jobs) > 1 and not any(j.get("depends_on") for j in pov_jobs):
        add("independent-pov-continuity", [j["id"] for j in pov_jobs], "Multiple POV takes are independent; the plan cannot enforce actual end-state handoff.",
            "For continuous movement, inspect the prior ending and use a saved opening-frame handoff plus dependency. For independent coverage, author an intentional cut and compare geography.")
    for shot in shots:
        sid = shot["id"]
        if fast and len(shot.get("actors", [])) > 2:
            add("dense-action-cast", [sid], "More than two active characters share an action shot.",
                "Reduce active bodies for the pilot or separate background spectacle from contact coverage.")
        if fast and len(shot.get("actions", [])) > 1:
            add("multiple-action-units", [sid], "Several action units are declared in one fast-action take.",
                "Try one exchange per take, with separate result and reaction coverage; inspect actual timing before scaling up.")
        phases = shot.get("action_phases", [])
        timing = shot.get("timing", {})
        if timing.get("motion_tempo") == "brisk":
            starts = [p["start"] for p in phases if p["phase"] in {"action", "contact"}]
            if starts and min(starts) > timing["action_start_by"] + .01:
                add("timing-start-conflict", [sid], "Declared action phases begin after this brisk shot's start deadline.",
                    "Shorten preparation or change the explicit timing budget; keep contact readable.")
            holds = [p for p in phases if p["phase"] == "settle"]
            kept = [s for s in timeline["segments"] if s.get("shot_id") == sid]
            if any(max(0, min(p["end"], s["source_out"]) - max(p["start"], s["source_in"])) / s.get("rate", 1)
                    > timing["max_reaction_hold"] + .05 for p in holds for s in kept):
                add("long-reaction-hold", [sid], "The retained settling phase exceeds this shot's reaction budget.",
                    "Trim the actual tail after its reaction is legible; do not remove the decisive contact or accelerate dialogue.")
            if any(p["end"] > timing["action_complete_by"] + .01 for p in phases if p["phase"] in {"action", "contact", "recovery"}):
                add("timing-result-conflict", [sid], "An action phase extends past this shot's result deadline.",
                    "Rewrite its phases for brisk movement or split the exchange; preserve the visible consequence.")
        contacts = [p for p in phases if p["phase"] == "contact"]
        if fast and contacts and min(p["start"] for p in contacts) > 2:
            add("late-contact", [sid], "The planned first contact occurs after two source seconds; this may create a long wind-up.",
                "For a brisk hit, keep preparation short and contact brief, then trim actual frames. Preserve a longer buildup when dramatically motivated.")
        camera = " ".join(str(shot.get(k, "")) for k in ("framing", "camera_motion"))
        slow = r"slow[ -]?motion|slow push|slow track|慢动作|慢镜头"
        camera = re.sub(r"(?:\bno\b|\bwithout\b|\bavoid\b|不要|禁止|不使用|没有|无)\s*(?:" + slow + ")", "", camera, flags=re.I)
        if fast and re.search(slow, camera, re.I):
            add("slow-camera-in-action", [sid], "A fast-action plan includes slow camera or slow-motion wording.",
                "Specify subject speed, camera movement and edit duration separately; remove conflicting slow direction if unintended.")
    return {"ok": True, "evidence_kind": "declared-plan-advisory", "content": "unverified",
        "findings": findings, "finding_count": len(findings), "paid_creates": 0,
        "limit": "Heuristics identify planning risks, not actual defects or creative quality. No findings is not approval. Run plan validate separately; inspect moving footage and listen to audio."}
