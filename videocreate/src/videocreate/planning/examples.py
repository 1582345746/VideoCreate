"""Editable worked example, not generated media or claimed likeness evidence."""
from __future__ import annotations

from .project import LAYERS


def smart_car() -> dict:
    bundle = {
        "project": {"schema_version": 3, "product": "VideoCreate", "title": "孔明借车东风",
            "files": {name: name + ".json" for name in LAYERS}, "status": "draft_plan"},
        "brief": {"intent": "narrative", "genre": "historical-product-comedy", "pace_profile": "comedy",
            "audience": "短视频观众", "aspect_ratio": "9:16", "resolution": "720p",
            "visual_style": "真人古装电影，山谷自然侧光，克制表演，真实接触和重量",
            "allowed_elements": ["现代智能SUV", "剧情内导航地图（准确图形由后期合成）"],
            "product": {"function": "导航识别可通行的替代路线", "enables_choice": "b-choice",
                "visible_result": "b-arrival", "removal_breaks_story": "军师的纸图没有标出可通行支路；没有导航信息便无法在时限内送粮"}},
        "story": {"logline": "粮道塌方，孔明借智能车导航送粮，士兵却把车当成了军师。",
            "goal": "天黑前把粮送到前线", "obstacle": "原路塌方，纸图没有安全绕路",
            "choice": "跟随智能车给出的替代路线", "consequence": "粮队抵达，士兵向车行礼",
            "payoff": "孔明决定给汽车也配一把羽扇", "initial_state": {"route": "blocked", "grain": "valley", "credit": "undecided"}, "beats": []},
        "director": {"assets": [
            {"id": "kongming", "kind": "character", "description": "诸葛亮，纶巾、白色古装、短须和羽扇；身份参考需单独注册并实际传给模型", "references": []},
            {"id": "suv", "kind": "prop", "description": "同一台银灰智能SUV，四轮接地，保持车身与车门结构一致", "references": []},
            {"id": "grain-cart", "kind": "prop", "description": "木制运粮车与麻布粮袋"},
            {"id": "soldiers", "kind": "character", "description": "两名同服色古代士兵"}],
            "scenes": [
                {"id": "valley", "map": "落石在画面右侧；粮车停在左侧；支路从画面左后方延伸。", "axis": "粮队向右前进", "positions": {"kongming": "road-left", "suv": "road-center"}},
                {"id": "junction", "map": "主路右侧被堵，支路沿左上方离开；车辆全片从左向右。", "axis": "movement-left-to-right"},
                {"id": "camp", "map": "孔明在左前，SUV在右后；士兵从中央走向右后方汽车。", "axis": "soldier-to-suv"}], "shots": []},
        "generation-plan": {"jobs": []},
        "timeline": {"fps": "30/1", "width": 720, "height": 1280, "clips": [], "segments": [], "audio_tracks": [], "subtitles": []},
    }
    # Each row is a coverage shot. A reaction may cover the preceding beat
    # without pretending that a second plot event happened.
    rows = [
        ("b-obstacle", "obstacle", "valley", "落石堵路，停住的粮车", "wide", ["grain-cart"], False, "落石和车队同框，原路不可通行", 2.5),
        ("b-obstacle", "reaction", "valley", "纸图无路，羽扇停住", "closeup", ["kongming"], True, "目光从纸图抬向堵路处，羽扇轻摇后停住", 2.5),
        ("b-car", "discovery", "valley", "车灯穿雾，轮胎停下", "insert", ["suv"], False, "智能SUV缓缓停住，轮胎接地压住小石子", 2.0),
        ("b-car", "reaction", "valley", "古人发现车会识路", "closeup", ["kongming", "suv"], True, "孔明目光先移向车窗，再轻前倾确认，手中羽扇保持停顿", 2.0),
        ("b-choice", "choice", "valley", "可见导航绕开红色落石点", "insert", ["suv"], False, "车内屏幕为明确的平面地图构图；后期叠加绕过障碍的路线", 3.0),
        ("b-follow", "action", "junction", "粮队跟随进入支路", "wide", ["suv", "grain-cart"], False, "SUV从左向右转入支路，后方粮车按同一方向跟随", 4.0),
        ("b-arrival", "consequence", "camp", "粮食抵达营地", "insert", ["grain-cart", "soldiers"], True, "士兵双手接住从粮车递下的一袋粮，脚踏营地地面", 3.0),
        ("b-mistake", "reversal", "camp", "士兵绕过军师拜汽车", "wide", ["kongming", "soldiers", "suv"], True, "两名士兵从孔明身旁经过，面向右后方汽车抱拳，孔明仍在左前景", 4.0),
        ("b-answer", "reaction", "camp", "孔明看车又看羽扇", "closeup", ["kongming"], True, "孔明目光转向汽车，再垂眼看羽扇，短暂停顿后平静下令", 4.0),
        ("b-payoff", "payoff", "camp", "汽车也配上羽扇", "insert", ["suv"], False, "静止车镜旁挂着一把羽扇，微风轻摆，兑现上一句命令", 3.0),
    ]
    state_effects = {"b-obstacle": {"paper_map": "no-safe-route"}, "b-car": {"car": "arrived"},
        "b-choice": {"route": "navigation-detour"}, "b-follow": {"grain": "detour"},
        "b-arrival": {"grain": "camp"}, "b-mistake": {"credit": "suv"},
        "b-answer": {"order": "give-car-fan"}, "b-payoff": {"car_has_fan": True}}
    previous_beat, prior_shot = None, None
    state = dict(bundle["story"]["initial_state"])
    beats = {}
    for index, (bid, role, scene, goal, framing, assets, acting, action, keep) in enumerate(rows, 1):
        sid, jid, cid = f"shot-{index:03}", f"job-{index:03}", f"clip-{index:03}"
        evidence = f"evidence-{index:03}"
        if bid not in beats:
            beat = {"id": bid, "requires": dict(state), "effects": state_effects[bid],
                "causes": [previous_beat] if previous_beat else [], "audience_learns": goal, "visible_evidence_needed": []}
            beats[bid] = beat
            bundle["story"]["beats"].append(beat)
            state.update(state_effects[bid])
            previous_beat = bid
        beats[bid]["visible_evidence_needed"].append(evidence)
        shot = {"id": sid, "beat_id": bid, "scene_id": scene, "role": role,
            "information_goal": goal, "framing": framing + "; " + goal,
            "camera_position": "在场景轴线同一侧", "camera_motion": "静止或轻微跟随主体，避免无目的推拉",
            "screen_direction": "运动从左到右；营地行礼朝画面右后方汽车",
            "eyeline": "朝当前触发对象，不看镜头" if acting else "not-applicable",
            "asset_ids": assets, "actors": [a for a in assets if a in {"kongming", "soldiers"}] if acting else [],
            "actions": [{"kind": "reaction" if role == "reaction" else "physical", "description": action}],
            "visible_evidence": [evidence], "planned_seconds": keep,
            "entry_state": goal + "动作开始前的状态", "exit_state": "保留当前动作的可剪出口",
            "cut_motivation": "观众取得本镜信息后切向下一信息或反应", "contacts": [],
            "audio": {"mode": "ambience", "ambience": "山风、车轮与衣料的自然声音", "lines": []}}
        if acting:
            shot["performance"] = {"trigger": goal, "attention": shot["eyeline"], "visible_response": action,
                "decision": "顺着刚得到的信息继续当前行动；不做无由来的点头或定格"}
        if index == 7:
            shot["contacts"] = [{"subject": "soldiers", "object": "grain-bag", "relation": "both-hands-support-weight"}]
        if index in {2, 5, 8, 9}:
            text = {2: "原路走不通了。", 5: "它竟识得山路？", 8: "多谢军师！", 9: "来人，给它也配把羽扇。"}[index]
            speaker = "soldiers" if index == 8 else "kongming"
            shot["audio"] = {"mode": "native-dialogue" if index != 5 else "offscreen", "lines": [{"speaker": speaker,
                "text": text, "on_screen": index != 5, "start": 0.4, "end": keep + 0.15}]}
        bundle["director"]["shots"].append(shot)
        bundle["generation-plan"]["jobs"].append({"id": jid, "shot_ids": [sid], "operation": "text-to-video",
            "seconds": int(keep + 1.99), "references": [], "depends_on": []})
        bundle["timeline"]["clips"].append({"id": cid, "job_id": jid})
        bundle["timeline"]["segments"].append({"id": f"segment-{index:03}", "shot_id": sid, "clip_id": cid,
            "source_in": 0.25, "source_out": keep + 0.25, "rate": 1,
            "source_audio": "retime", "cut_reason": shot["cut_motivation"]})
        prior_shot = sid
    return bundle
