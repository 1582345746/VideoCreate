"""Executable original stories; these are not claimed adaptations of unseen video."""
from .project import AUTHOR, author, initialize, plan, read


def create(root, *, theme="lulu-lumei", scenario="reaction", model=None, binding=None):
    if scenario not in {"reaction", "dialogue", "contact"}:
        raise ValueError("Choose reaction, dialogue or contact")
    initialize(root, title={"reaction": "饼干盒里的意外", "dialogue": "嘴硬的关心", "contact": "困了就靠一下"}[scenario], theme=theme)
    document = read(root)
    a, b = [c["id"] for c in document["theme"]["characters"][:2]]
    location = "圆窗小屋的茶歇角" if theme == "lulu-lumei" else "云上邮局的茶歇台"
    if scenario == "reaction":
        rows = [("想独享饼干", f"{a}把饼干盒护在胸前，偷看{b}", "setup"),
                ("发现空盒", f"{a}打开空盒，笑容僵住，视线落进盒内", "reveal"),
                ("反被照顾", f"{b}空手伸向衣物侧边口袋，清楚取出最后一块饼干递给{a}；{a}接稳后{b}才松手，{a}愧疚地松肩微笑", "reaction")]
        goal, obstacle, choice, result = "独享饼干", "自己护着的盒子早已空了", "接受对方分享并放下戒备", "对方的关心反衬自己的小心思"
        point = "从自私的期待到空盒失落，再到被照顾后的羞愧与暖意"
    elif scenario == "dialogue":
        rows = [("表面生气", f"{a}抱臂偏头，但目光仍追随{b}", "setup"),
                ("关心被揭穿", f"{b}指向{a}提前放好的保温杯，{a}耳边微红", "reveal"),
                ("嘴硬缓和", f"{a}把杯子推近{b}后小幅扬嘴角，{b}捧杯微笑", "reaction")]
        goal, obstacle, choice, result = "掩饰关心", "提前准备的热饮暴露了心意", "嘴上否认却把杯子推近", "两人释然相视"
        point = "话语与关心的动作形成反差，揭示后有清楚的情绪缓和"
    else:
        rows = [("发现困倦", f"{b}坐在矮软垫边揉眼，{a}看见后停下手里的事", "setup"),
                ("给予支撑", f"{a}坐稳后将靠垫推到{b}手边，{b}双手接住", "action"),
                ("接纳照顾", f"{b}抱着靠垫轻靠{a}肩侧，{a}保持坐稳并放松微笑", "reaction")]
        goal, obstacle, choice, result = "让困倦的同伴休息", "同伴坐在垫边缺少支撑", "先坐稳递靠垫，再等待对方靠近", "同伴安全依靠，关心被接纳"
        point = "照顾先有支撑和等待，接触后有放松的回应"
    seconds = 5 if scenario == "contact" else 4
    beats, shots = [], []
    openings = {
        "reaction": [f"{a}左，{b}右，嘴巴合拢；桌上只有一个完全盖住的不透明饼干铁盒。两人双手没有饼干，盒盖未打开，内容不可见。{a}双臂准备护住盒子。",
            f"{a}双手捧住完全盖着的不透明铁盒，准备打开。{b}安静看着；嘴巴合拢。禁止可见饼干或开着的盒盖。",
            f"{a}面前的铁盒已经打开，盒内清楚地完全空着。{b}双手空着，唯一饼干藏在衣物侧边口袋内不可见，尚未伸手取。{a}失落垂眼；嘴巴合拢。"],
        "dialogue": [f"{a}左侧抱臂偏头，{b}右侧刚到，桌面一只保温杯", f"{b}右侧看向桌上保温杯，{a}左侧抱臂略显紧张", f"{a}左侧手掌在杯旁，杯子尚未推近{b}，双方表情开始放松"],
        "contact": [f"{b}右侧坐在软垫边缘困倦揉眼，{a}左侧尚未递物，靠垫在{a}腿旁",
            f"{a}左侧坐稳，靠垫在两人之间的座面上，{b}右侧尚未接住，双方双脚有支撑",
            f"{b}右侧抱住靠垫，尚未靠肩，{a}左侧坐稳等待；角色肩部距离很近且高度适合轻靠"]}[scenario]
    for i, (information, action, role) in enumerate(rows, 1):
        bid, sid = f"beat-{i}", f"shot-{i}"
        beats.append({"id": bid, "requires": {"stage": i-1}, "effects": {"stage": i},
            "causes": [] if i == 1 else [f"beat-{i-1}"], "audience_learns": information, "visible_evidence_needed": [f"evidence-{i}"]})
        shot = {"id": sid, "beat_id": bid, "scene_id": "rest", "role": role, "information_goal": information,
            "opening_frame": openings[i-1],
            "framing": "平视双人中景，表情和道具清楚", "camera_motion": "固定机位",
            "eyeline": "两人目光与当前道具相连", "screen_direction": f"{a}左，{b}右",
            "asset_ids": [a, b, "story-prop"], "actors": [a, b],
            "actions": [{"kind": "reaction" if role == "reaction" else "physical", "description": action}],
            "performance": {"trigger": information, "attention": "对方与道具", "visible_response": action, "decision": information},
            "visible_evidence": [f"evidence-{i}"], "planned_seconds": 6 if scenario == "reaction" and i == 3 else seconds,
            "entry_state": {"a_position": "left", "b_position": "right"}, "exit_state": {"a_position": "left", "b_position": "right"},
            "cut_motivation": "保留情绪停顿后进入下一次因果反应", "audio": {"mode": "ambience", "ambience": "轻微室内环境声，无可辨识人声"}}
        if scenario == "contact" and i >= 2:
            shot["contacts"] = [{"subject": b, "object": "story-prop" if i == 2 else a, "relation": "双手接住靠垫" if i == 2 else "有靠垫支撑地轻靠肩侧"}]
            shot["action_phases"] = [{"phase": phase, "start": start, "end": end, "description": desc} for phase,start,end,desc in
                [("prepare", 0, 1, "先确认座位稳定和双方距离"), ("contact", 1, 3.5, action), ("settle", 3.5, 5, "保留接触与表情结果")]]
        if scenario == "dialogue":
            speaker, text = [(a, "我才没等你。"), (b, "那热饮给谁呀？"), (a, "快喝，别凉了。")][i-1]
            shot["audio"] = {"mode": "independent-voice", "lines": [{"speaker": speaker, "text": text,
                "on_screen": True, "start": .5, "end": 3, "voice_asset_id": "voice-" + speaker}]}
        if scenario == "reaction" and i == 3:
            shot["action_phases"] = [{"phase": phase, "start": start, "end": end, "description": desc} for phase,start,end,desc in
                [("prepare", 0, 1, f"{b}空手移向衣物侧边口袋"),
                 ("action", 1, 2.5, f"{b}伸入口袋并清楚取出唯一饼干；手和取物路径始终可见"),
                 ("contact", 2.5, 4.5, f"{b}递出，{a}双手接稳后{b}才松手"),
                 ("settle", 4.5, 6, f"{a}看向{b}，愧疚地松肩微笑，保留回应")]]
        shots.append(shot)
    if scenario == "reaction":
        # The payoff cookie must not leak into setup/reveal image prompts.
        shots[-1]["asset_ids"].append("cookie")
    outline = {"premise": document["title"], "goal": goal, "obstacle": obstacle, "choice": choice, "result": result,
        "payoff": rows[-1][0], "roles": ["initiator", "responder"], "emotion_curve": [r[0] for r in rows],
        "core_points": [{"id": "point-1", "description": point, "origin": "original", "observation_ids": []}]}
    adaptation = {"design_origin": "newly-designed", "rationale": "原创回归故事，剧情与场景独立设计；不声称源自未经观察的视频",
        "casting": {"initiator": a, "responder": b}, "variants": [{"character_id": cid, "variant_id": "home"} for cid in (a,b)],
        "scene_designs": [{"scene_id": "rest", "description": location, "layout": "矮桌居中，左侧和右侧留两人活动空间",
            "scale": "桌面低于角色胸口，短手可触及道具，坐垫支撑完整", "lighting": "柔和明亮的窗光与暖色补光"}],
        "point_map": [{"point_id": "point-1", "beat_ids": [b["id"] for b in beats], "shot_ids": [s["id"] for s in shots], "explanation": point}],
        "pilot_shot_ids": ["shot-1", "shot-2"],
        "brief": {"intent": "narrative", "genre": "animation-comedy" if scenario != "contact" else "animation-care",
            "pace_profile": "comedy", "aspect_ratio": "9:16", "resolution": "720p", "visual_style": "表情清楚，留出反应停顿",
            "audio_policy": "dialogue" if scenario == "dialogue" else "ambience"},
        "story": {"logline": document["title"], "goal": goal, "obstacle": obstacle, "choice": choice, "consequence": result,
            "payoff": rows[-1][0], "initial_state": {"stage": 0}, "beats": beats},
        "director": {"assets": [{"id": "story-prop", "kind": "prop", "description": {"reaction": "唯一一个奶油色圆形金属饼干铁盒，橙白格纹盖，盒盖与盒身等直径；不是方盒，没有盘子", "dialogue": "无字保温杯", "contact": "柔软小靠垫"}[scenario]},
            *([{"id": "cookie", "kind": "prop", "description": f"唯一一块圆饼干，起初藏在{b}衣物侧边口袋内，取出后才可见"}] if scenario == "reaction" else [])],
            "scenes": [{"id": "rest", "map": "原创茶歇空间", "axis": "两人左右的互动轴", "positions": {a: "left", b: "right"}}], "shots": shots}}
    author(root, {"outline": outline, "adaptation": adaptation})
    return plan(root, model=model, binding=binding)
