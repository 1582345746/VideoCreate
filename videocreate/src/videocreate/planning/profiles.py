"""Editable production plans for different viewing goals, independent of API routes."""
from __future__ import annotations

from .project import LAYERS
from ..config.storage import ConfigError

PROFILES = {
    "portrait": {"title": "写实人物", "seconds": 15, "intent": "single-shot", "pace": "slow-cinema",
                 "audio": "silent", "focus": "眼神、重心、呼吸与克制的反应"},
    "action-insert": {"title": "动作插镜", "seconds": 10, "intent": "demonstration", "pace": "action",
                      "audio": "ambience", "focus": "准备、发力、接触或避让、收势；一次主要动作"},
    "action-montage": {"title": "快速动作组接", "seconds": 15, "intent": "narrative", "pace": "action",
                       "audio": "ambience", "focus": "一次交锋的空间、预备、接触、结果与反应"},
    "animal-comedy": {"title": "动物动作反转", "seconds": 15, "intent": "narrative", "pace": "comedy",
                      "audio": "ambience", "focus": "严肃铺垫、一次动作、清楚结果与生活化反转"},
    "scenic": {"title": "环境电影镜头", "seconds": 15, "intent": "single-shot", "pace": "slow-cinema",
               "audio": "ambience", "focus": "空间层次与一个明确的摄影机运动"},
    "explainer": {"title": "有来源的科普", "seconds": 45, "intent": "montage", "pace": "slow-cinema",
                  "audio": "voiceover", "focus": "问题、证据、解释；事实和示意画面分开"},
    "series-episode": {"title": "连续剧单集", "seconds": 60, "intent": "narrative", "pace": "dialogue",
                       "audio": "native-experimental", "focus": "可见的目标、阻碍、选择、结果及下集悬念"},
}


def create(profile: str, *, title: str = "", seconds: float | None = None, topic: str = "",
           aspect_ratio: str = "16:9") -> dict:
    if profile not in PROFILES:
        raise ConfigError("Unknown production profile")
    p = PROFILES[profile]
    seconds = p["seconds"] if seconds is None else seconds
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 5 <= seconds <= 120:
        raise ConfigError("Profile duration must be 5–120 seconds")
    if profile in {"portrait", "action-insert", "action-montage", "animal-comedy", "scenic"} and not 10 <= seconds <= 20:
        raise ConfigError("Short profiles use 10–20 seconds; author a custom plan for other lengths")
    if aspect_ratio not in {"16:9", "9:16"}:
        raise ConfigError("Profile canvas must be 16:9 or 9:16")
    bundle = {
        "project": {"schema_version": 3, "product": "VideoCreate", "title": title or p["title"],
                    "files": {k: k + ".json" for k in LAYERS}, "status": "draft_plan"},
        "brief": {"intent": p["intent"], "genre": profile, "workflow_profile": profile,
                  "pace_profile": p["pace"], "audio_policy": p["audio"], "target_seconds": seconds,
                  "aspect_ratio": aspect_ratio, "resolution": "720p", "audience": "短视频观众",
                  "visual_style": "Photorealistic live-action cinema, natural skin texture, motivated soft side light, grounded weight, restrained performance",
                  "reference_profiles": [], "forbidden_elements": ["水印", "生成字幕", "多格画面"]},
        "story": {"initial_state": {}, "beats": [], "logline": topic or p["focus"]},
        "director": {"assets": [], "scenes": [], "shots": []},
        "generation-plan": {"jobs": []},
        "timeline": {"fps": "24/1", "width": 1280 if aspect_ratio == "16:9" else 720,
                     "height": 720 if aspect_ratio == "16:9" else 1280,
                     "clips": [], "segments": [], "audio_tracks": [], "subtitles": [], "overlays": []},
    }
    if profile in {"action-montage", "animal-comedy"}:
        from .short_coverage import build
        return build(bundle, profile, seconds)
    if profile == "series-episode":
        bundle["story"].update(goal="待写：主角本集要达成的可见目标", obstacle="待写：具体阻碍",
                              choice="待写：有代价的选择", consequence="待写：实际结果")
        # No invented plot/accepted ending; author the episode before generation.
        return bundle
    human = profile in {"portrait", "action-insert"}
    if human:
        bundle["director"]["assets"] = [{"id": "lead", "kind": "character", "identity_origin": "fictional adult",
            "description": "Fictional adult East Asian woman, around 28, short black hair, charcoal cotton coat, no jewelry",
            "references": [], "invariants": ["age and facial identity", "hair length", "coat color and fabric"]}]
    if profile == "action-insert":
        bundle["director"]["assets"][0].update(
            description="Fictional adult East Asian woman, around 28, short black hair, plain charcoal training jacket and dark training trousers, no jewelry",
            invariants=["age and facial identity", "hair length", "charcoal training jacket", "dark trousers"])
        bundle["director"]["assets"].append({"id": "target", "kind": "prop",
            "description": "A plain dark canvas training bag suspended from a sturdy frame at chest height; no logos or markings"})
    bundle["director"]["scenes"] = [{"id": "scene-01", "map": "Quiet riverside walkway; water behind the subject; open walking space to camera right",
        "axis": "camera stays on river side of travel axis", "positions": {"lead": "center foreground"} if human else {}}]
    if profile == "action-insert":
        bundle["director"]["scenes"][0].update(map="Open outdoor training area beside a riverside path; one suspended canvas training bag stands at arm's reach in front of the performer",
            axis="Camera stays on the near side of the performer-to-bag axis; performer remains on frame right facing frame left",
            positions={"lead": "frame right, facing frame left", "target": "frame left, chest height, clear space between performer and bag"})
    if profile == "scenic":
        bundle["director"]["scenes"][0].update(map="Single railway curves through a snowy pine forest; train moves left to right behind foreground trees",
            axis="Camera stays south of the tracks; train always travels left to right")
    elif profile == "explainer":
        bundle["director"]["scenes"][0].update(map="Author the actual place and landmark positions from sourced research before generation",
            axis="Choose an axis from the authored geographic scene")
    import math
    count = max(1, math.ceil(seconds / 10))
    for i in range(count):
        sid, jid, cid = f"shot-{i+1:03}", f"job-{i+1:03}", f"clip-{i+1:03}"
        retained = min(10, seconds - i * 10)
        generated_seconds = min(10, max(1, math.ceil(retained)))
        action = "Her attention shifts toward a quiet offscreen sound; eyes lead a small head turn; she settles into a soft attentive look" if profile == "portrait" else (
            ("From a balanced guard, she makes one controlled open-palm strike into the chest-height canvas bag. The bag swings back slightly at the single visible contact; she retracts the hand to guard without stepping or turning. No second strike." if i == 0 else
             "After the single contact, her hand settles back to guard beside the bag. Its small swing slows; there is no new strike or contact.") if profile == "action-insert" else
            "A red passenger train travels steadily left to right through a snowy pine forest")
        shot = {"id": sid, "scene_id": "scene-01", "role": "performance" if human else "environment",
            "information_goal": action if i == 0 or profile == "action-insert" else "A complementary detail of the same subject; preserve established identity and setting",
            "framing": "medium close-up, eyes prominent, shoulders visible" if profile == "portrait" else "close detail of forearm, open palm and bag, same side of axis" if profile == "action-insert" and i > 0 else "wide full-body frame containing the performer's head, both feet, striking hand and entire bag, with clear space around the contact point" if profile == "action-insert" else "wide establishing view with foreground parallax",
            "camera_position": "eye level, 50mm equivalent" if profile == "portrait" else "fixed three-quarter side close detail, 50mm equivalent; keep hand and bag inside frame" if profile == "action-insert" and i > 0 else "fixed three-quarter side view at waist height, 35mm equivalent; include both feet and the entire target with room for the arm to extend" if profile == "action-insert" else "elevated oblique view, 35mm equivalent",
            "camera_motion": "locked tripod; no pan, tracking, orbit, zoom or cut during the strike" if profile == "action-insert" else "one slow 30cm lateral track, constant speed; no orbit or zoom",
            "screen_direction": "performer stays frame right and faces the bag at frame left" if profile == "action-insert" else "subject faces camera right",
            "eyeline": "eyes stay on the bag throughout; no glance toward camera" if profile == "action-insert" else "toward offscreen right, briefly back near lens",
            "asset_ids": ["lead", "target"] if profile == "action-insert" else ["lead"] if human else [], "actors": ["lead"] if human else [],
            "actions": [{"kind": "reaction" if profile == "portrait" else "physical", "description": action}],
            "planned_seconds": generated_seconds, "cut_motivation": "Hold through preparation, one visible contact, hand recovery and the bag settling; no cut during the action" if profile == "action-insert" and i == 0 else "Cut after the bag's small swing settles" if profile == "action-insert" else "Hold through visible settling; cut on a completed attention change" if human else "Cut after the train clears the foreground trees",
            "visible_evidence": [], "audio": {"mode": "mute" if profile == "portrait" else "ambience", "lines": []}}
        if human:
            shot["performance"] = {"trigger": "quiet sound from camera right" if profile == "portrait" else "a deliberate practice cue",
                "attention": "eyes move before head" if profile == "portrait" else "eyes remain on the bag; shoulders and hips stay mostly side-on",
                "visible_response": "small gaze shift and weight adjustment" if profile == "portrait" else "feet remain planted; the palm meets the bag once, the bag swings slightly, and the hand returns to guard",
                "decision": "settle into attention" if profile == "portrait" else "return to balanced guard"}
            if profile == "action-insert" and i == 0:
                prepare_end = round(generated_seconds * .2, 2)
                action_end = round(generated_seconds * .55, 2)
                contact_end = round(generated_seconds * .65, 2)
                recovery_end = round(generated_seconds * .8, 2)
                shot["contacts"] = [{"subject": "lead's open palm", "object": "suspended canvas training bag",
                    "relation": "one clear chest-height contact; the bag swings away slightly"}]
                shot["entry_state"] = {"wardrobe": "charcoal training jacket", "location": "riverside training area", "hands": "balanced guard"}
                shot["exit_state"] = dict(shot["entry_state"])
                shot["action_phases"] = [
                    {"phase": "prepare", "start": 0, "end": prepare_end, "description": "Balanced side-on guard; both feet remain planted; eyes fixed on the still bag"},
                    {"phase": "action", "start": prepare_end, "end": action_end, "description": "One straight open-palm strike toward the bag; no step, spin or second strike"},
                    {"phase": "contact", "start": action_end, "end": contact_end, "description": "Palm touches the bag once; bag swings away slightly; no explosive debris"},
                    {"phase": "recovery", "start": contact_end, "end": recovery_end, "description": "Hand withdraws smoothly along the same path back to guard; feet stay planted"},
                    {"phase": "settle", "start": recovery_end, "end": generated_seconds, "description": "Hold balanced guard while the bag's small swing settles"}]
            elif profile == "action-insert":
                recovery_start = round(generated_seconds * .2, 2)
                settle_start = round(generated_seconds * .7, 2)
                shot["contacts"] = []
                shot["entry_state"] = {"wardrobe": "charcoal training jacket", "location": "riverside training area", "hands": "balanced guard"}
                shot["exit_state"] = dict(shot["entry_state"])
                shot["action_phases"] = [
                    {"phase": "prepare", "start": 0, "end": recovery_start, "description": "Bag is already swinging gently after the preceding contact"},
                    {"phase": "recovery", "start": recovery_start, "end": settle_start, "description": "Hand settles beside the bag and returns to guard; no new contact"},
                    {"phase": "settle", "start": settle_start, "end": generated_seconds, "description": "The bag's small swing slows while the recovered hand holds still"}]
            else:
                prepare_end = round(generated_seconds * .2, 2)
                action_end = round(generated_seconds * .6, 2)
                shot["entry_state"] = {"wardrobe": "charcoal coat", "location": "river walkway"}
                shot["exit_state"] = dict(shot["entry_state"])
                shot["action_phases"] = [
                    {"phase": "prepare", "start": 0, "end": prepare_end, "description": "Relaxed balanced posture, natural breathing"},
                    {"phase": "action", "start": prepare_end, "end": action_end, "description": action},
                    {"phase": "settle", "start": action_end, "end": generated_seconds, "description": "Finish the motion and hold the new pose with small breathing movement"}]
        if i and profile == "portrait":
            shot.update(framing="tight face close-up, same camera side and wardrobe; preserve head proportions",
                camera_motion="locked eye-level camera; only small natural actor movement",
                information_goal="A quiet response completes the earlier attention shift",
                actions=[{"kind": "reaction", "description": "She holds her new eyeline toward offscreen right, exhales gently, then gives a barely visible smile"}])
            shot["performance"].update(trigger="recognition of the offscreen presence", attention="same established eyeline",
                visible_response="a gentle exhale softens the mouth and eyes", decision="stay and acknowledge the presence")
            shot["action_phases"][1]["description"] = shot["actions"][0]["description"]
        if i and profile == "action-insert":
            shot.update(role="detail", actions=[{"kind": "physical", "description": action}])
            shot["performance"].update(trigger="the single strike has finished", attention="follow the diminishing swing of the bag",
                visible_response="hand returns to guard as the bag slows", decision="hold position")
        if profile == "explainer":
            shot.update(information_goal=f"Illustrative B-roll for {topic or '待选科普主题'}; source-based claims are supplied separately",
                        framing="wide or close detail appropriate to the verified claim", camera_motion="one restrained motivated camera move")
            shot["actions"] = [{"kind": "hold", "description": "Observe the landscape or local craft; no generated map boundaries or readable statistics"}]
            shot["claim_ids"] = []
            shot["visual_purpose"] = "illustration"
            shot["audio"] = {"mode": "mute", "lines": []}
        bundle["director"]["shots"].append(shot)
        bundle["generation-plan"]["jobs"].append({"id": jid, "shot_ids": [sid], "operation": "text-to-video", "seconds": generated_seconds})
        bundle["timeline"]["clips"].append({"id": cid, "job_id": jid})
        source_in = (generated_seconds - retained) / 2
        bundle["timeline"]["segments"].append({"id": f"segment-{i+1:03}", "shot_id": sid, "clip_id": cid,
            "source_in": source_in, "source_out": source_in + retained, "source_audio": "mute" if profile in {"portrait", "explainer"} else "retime", "rate": 1,
            "cut_reason": "Provisional window; inspect actual candidate before selecting"})
    if profile == "explainer":
        from ..education import empty_research
        bundle["project"]["files"]["research"] = "research.json"
        bundle["research"] = empty_research(topic)
    return bundle
