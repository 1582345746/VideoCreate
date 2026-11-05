"""Single-exchange coverage examples: source duration is independent of edit duration."""
from __future__ import annotations

import math


def build(bundle: dict, profile: str, seconds: float) -> dict:
    animal = profile == "animal-comedy"
    bundle["brief"]["visual_style"] = (
        "Photorealistic textures and grounded contact, one clear subject per shot, crisp normal-speed action. "
        "No slow motion, time ramp, orbit, montage or internal cut within an individual generated shot."
    )
    lead = {
        "id": "lead", "kind": "character", "identity_origin": "fictional animal" if animal else "fictional adult",
        "description": "One adult orange tabby cat with amber eyes, white chin and short dense fur; no clothes" if animal else
                       "One fictional adult East Asian martial artist, short black hair, charcoal training jacket and dark trousers",
        "references": [], "invariants": ["same face and markings", "same body proportions", "same wardrobe or fur",
            "four feline legs and natural cat paws, never human hands" if animal else "human hands and feet, same jacket and trousers"],
    }
    target = {"id": "target", "kind": "prop", "description":
        "One low black circular robot vacuum, broad flat top, no logo; same size and shape in every shot" if animal else
        "One suspended dark canvas training bag, unmarked, hanging from a fixed frame; same size in every shot"}
    bundle["director"]["assets"] = [lead, target]
    place = "A quiet living room, pale wooden floor, sofa behind; one cat and one robot vacuum only" if animal else \
            "A plain outdoor training court, gray wall behind; one performer and one suspended canvas bag only"
    bundle["director"]["scenes"] = [{"id": "scene-01", "map": place,
        "axis": "Camera stays on the near side of the lead-to-target axis; lead at frame left, target at frame right",
        "positions": {"lead": "frame left facing right", "target": "frame right"}}]
    bundle["story"].update(
        logline="橘猫把扫地机器人当成强敌，拍了一掌，发现它只是交通工具，最后坐上去被带走。" if animal else
                "练习者看准沙袋，快速出掌一次；接触引起沙袋摆动，练习者收掌确认结果。",
        goal="赶走靠近的机器人" if animal else "完成一次清楚有力的击打",
        obstacle="机器人继续朝猫靠近" if animal else "沙袋仍静止，需要准确接触",
        choice="先拍一下试探，再主动坐上去" if animal else "保持站位，仅出掌一次",
        consequence="假想的大战变成搭便车" if animal else "沙袋摆动，手收回，站位保持",
        initial_state={"stage": "unaware"}, beats=[])
    # Each row is one information unit, one source take, and one provisional retained window.
    if animal:
        rows = [
            ("setup", "medium two-subject view with floor gap visible", ["lead", "target"],
             "The vacuum rolls slowly from frame right toward the stationary cat at frame left; stop with a visible gap.", "机器人正在靠近猫", "physical"),
            ("reaction", "tight cat face close-up", ["lead"],
             "The cat fixes its eyes offscreen right; ears tilt toward the approaching motor sound, mouth stays closed.", "猫把它当成威胁", "reaction"),
            ("detail", "close detail of one front paw and planted feline legs", ["lead"],
             "The cat lifts its right front paw just above the floor while the other three paws stay planted.", "准备试探", "physical"),
            ("action", "medium side view containing the whole cat, paw and vacuum rim", ["lead", "target"],
             "The raised front paw makes one brisk short swat against the vacuum rim and retracts. Show the contact clearly; no second swat or body turn.", "一掌确实拍中外壳", "physical"),
            ("result", "close detail of vacuum rim, wheel and floor; cat outside the crop", ["target"],
             "After the preceding swat, the vacuum's bumper releases; it backs away to frame right without turning. The shell stays intact.", "机器人没有被打败，只是避障后退", "physical"),
            ("reaction", "cat face close-up, same side of axis", ["lead"],
             "The cat follows the motor sound with its eyes toward frame right; its ears relax without a head turn.", "猫从戒备变成好奇", "reaction"),
            ("payoff", "readable medium-wide side view, whole cat and vacuum visible", ["lead", "target"],
             "The same cat is already seated comfortably on the broad vacuum top. The vacuum carries it steadily to frame right; cat keeps all four paws tucked naturally. No jump or mounting action.", "原来猫最后搭了便车", "physical"),
        ]
    else:
        rows = [
            ("setup", "medium-wide side view, performer feet and entire bag visible", ["lead", "target"],
             "The performer stands planted at frame left in guard, looking at the still bag at frame right.", "人与目标的位置明确", "hold"),
            ("reaction", "tight eyes close-up", ["lead"],
             "The performer fixes their eyes offscreen right on the target; one short focused breath, no head turn.", "明确瞄准目标", "reaction"),
            ("detail", "close detail of open palm and forearm, same side of axis", ["lead"],
             "The open palm draws back a few centimeters into guard; wrist stays straight.", "准备出掌", "physical"),
            ("action", "medium side view including arm, torso and entire bag contact surface", ["lead", "target"],
             "One brisk straight open-palm strike meets the bag once, then retracts. Bag starts swinging to frame right at contact; feet stay planted. No slow motion or second strike.", "手掌接触后沙袋向右摆动", "physical"),
            ("result", "close detail of bag edge and suspension, performer outside crop", ["target"],
             "The bag is already moving away to frame right from the preceding contact; rope stays taut. Show one readable outgoing swing, no new impact.", "接触产生可见结果", "physical"),
            ("reaction", "face close-up, same eyeline and camera side", ["lead"],
             "The performer watches the swinging bag offscreen right and exhales once, mouth closed.", "练习者确认结果", "reaction"),
            ("payoff", "medium-wide side view, both feet and bag visible", ["lead", "target"],
             "The performer has returned to the same balanced guard; bag is already swinging slightly from the preceding strike. No new strike.", "完成收势并回到原有空间", "hold"),
        ]
    weights = [2.2, 1.5, 1.0, 1.5, 1.3, 1.5, 6.0] if animal else [2.5, 1.5, 1.0, 1.5, 1.5, 2.0, 5.0]
    previous = None
    total = 0.0
    for i, (role, framing, asset_ids, action, information, kind) in enumerate(rows):
        sid, jid, cid, bid = (f"{prefix}-{i+1:03}" for prefix in ("shot", "job", "clip", "beat"))
        stage = f"stage-{i+1}"
        bundle["story"]["beats"].append({"id": bid, "requires": {"stage": previous or "unaware"},
            "effects": {"stage": stage}, "causes": [f"beat-{i:03}"] if i else [],
            "audience_learns": information, "visible_evidence_needed": [sid + "-visible"]})
        previous = stage
        # Source handles allow edit changes. A pilot is still needed to find usable frames.
        retained = round(seconds * weights[i] / 15, 6) if i < len(rows)-1 else round(seconds-total, 6)
        total += retained
        source_in = 0.5
        generated = min(10, max(4, math.ceil(retained + 1)))
        actors = ["lead"] if "lead" in asset_ids else []
        shot = {"id": sid, "beat_id": bid, "scene_id": "scene-01", "role": role,
            "information_goal": information, "framing": framing,
            "camera_position": "fixed near-side view at cat eye height" if animal else "fixed near-side view at chest height",
            "camera_motion": "locked camera; subject motion supplies speed; no pan, orbit, zoom or internal cut",
            "screen_direction": "lead faces right; target stays to its right", "eyeline": "lead looks toward target at frame right",
            "asset_ids": asset_ids, "actors": actors, "actions": [{"kind": kind, "description": action}],
            "visible_evidence": [sid + "-visible"], "planned_seconds": generated,
            "entry_state": {"location": "scene-01", "light": "same soft side daylight", "axis": "near side"},
            "exit_state": {"location": "scene-01", "light": "same soft side daylight", "axis": "near side"},
            "cut_motivation": "Cut after this single information unit is readable; choose actual source frames and match the next result/reaction, not the clip boundary",
            "audio": {"mode": "ambience", "lines": [], "ambience": "quiet room tone and motor" if animal else "quiet outdoor tone; one contact sound in the contact shot only"}}
        if actors:
            shot["performance"] = {"trigger": information, "attention": "the established target to frame right",
                "visible_response": action, "decision": "complete only this shot's action"}
        if role == "action":
            shot["contacts"] = [{"subject": "cat's front paw" if animal else "performer's open palm",
                "object": "vacuum rim" if animal else "canvas bag", "relation": "one brief visible contact; no penetration or merged anatomy"}]
            shot["action_phases"] = [
                {"phase": "prepare", "start": 0, "end": .5, "description": "Already poised; no extended wind-up"},
                {"phase": "action", "start": .5, "end": .9, "description": "One brisk forward movement at normal speed"},
                {"phase": "contact", "start": .9, "end": 1.1, "description": "One readable touch, target responds immediately"},
                {"phase": "recovery", "start": 1.1, "end": 1.5, "description": "Limb retracts along the same path"},
                {"phase": "settle", "start": 1.5, "end": generated, "description": "No new strike; hold for an editable tail"},
            ]
        bundle["director"]["shots"].append(shot)
        bundle["generation-plan"]["jobs"].append({"id": jid, "shot_ids": [sid], "operation": "text-to-video", "seconds": generated})
        bundle["timeline"]["clips"].append({"id": cid, "job_id": jid})
        bundle["timeline"]["segments"].append({"id": f"segment-{i+1:03}", "shot_id": sid, "clip_id": cid,
            "source_in": source_in, "source_out": round(source_in+retained, 6), "rate": 1, "source_audio": "retime",
            "cut_reason": "Provisional normal-speed window. Inspect real contact/result and adjust both sides; no automatic quality acceptance"})
    return bundle
