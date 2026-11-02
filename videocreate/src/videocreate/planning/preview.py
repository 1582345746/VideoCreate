from __future__ import annotations

import html
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config.storage import ConfigError, atomic_json
from ..timeline.model import mapping
from .project import content_hash


def preview(root: Path, bundle: dict, *, video: bool = False) -> dict:
    plan = mapping(bundle["timeline"])
    shots = {s["id"]: s for s in bundle["director"]["shots"]}
    cards = [{**seg, "shot": shots[seg["shot_id"]]} for seg in plan["segments"]]
    output = root / "deliverables"
    output.mkdir(parents=True, exist_ok=True)
    data = json.dumps(cards, ensure_ascii=False).replace("<", "\\u003c")
    title = html.escape(bundle["project"]["title"])
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VideoCreate · TITLE</title><style>body{background:#10151b;color:#ebeee9;font:18px system-ui;max-width:1050px;margin:40px auto;padding:20px}small{color:#93a6b8}#card{background:#1b2530;border-radius:20px;padding:32px;min-height:350px}h1{font-size:30px}h2{color:#e1b86d}button{padding:12px 25px;background:#e1b86d;border:0;border-radius:8px}input{width:100%}.meta{color:#97c8ba}#strip{display:flex;gap:8px;flex-wrap:wrap}#strip button{background:#263747;color:white;margin:8px 0}</style>
<h1>TITLE</h1><p><small>无付费生成的文字分镜预演 · draft_preview · 不代表人物、动作、声音已经实现</small></p>
<div id="card"></div><p><button id="play">播放预演</button> <span id="clock"></span></p><input id="seek" type="range" min="0" step="0.01"><div id="strip"></div>
<script>const cards=DATA;let t=0,playing=false,last=0;const duration=cards.at(-1).timeline_end,seek=document.getElementById('seek'),card=document.getElementById('card');seek.max=duration;
function text(tag,value,cls){const e=document.createElement(tag);e.textContent=value;if(cls)e.className=cls;card.append(e)}
function draw(){const c=cards.find(x=>t>=x.timeline_start&&t<x.timeline_end)||cards.at(-1);card.replaceChildren();text('p',c.id+' / '+c.shot.id+' · '+c.shot.role,'meta');text('h2',c.shot.information_goal);text('p','画面：'+c.shot.framing);text('p','动作：'+c.shot.actions.map(a=>a.description).join('；'));text('p','表演：'+(c.shot.performance?.visible_response||'道具/环境覆盖'));text('p','声音：'+(c.shot.audio?.lines||[]).map(l=>(l.on_screen?'画内':'画外')+' '+l.speaker+'：“'+l.text+'”').join('；'));text('small','切点：'+c.cut_reason);seek.value=t;document.getElementById('clock').textContent=t.toFixed(1)+' / '+duration.toFixed(1)+' 秒'}
seek.oninput=()=>{t=+seek.value;draw()};document.getElementById('play').onclick=()=>{if(t>=duration)t=0;playing=!playing;last=0};for(const c of cards){const b=document.createElement('button');b.textContent=c.shot.id;b.onclick=()=>{t=c.timeline_start;draw()};document.getElementById('strip').append(b)}
function tick(now){if(playing){if(last)t=Math.min(duration,t+(now-last)/1000);if(t>=duration)playing=false;draw()}last=now;requestAnimationFrame(tick)}draw();requestAnimationFrame(tick);</script></html>'''
    # Replace payload last; a user-authored title cannot become a JS token.
    page = page.replace("TITLE", title).replace("DATA", data)
    path = output / "animatic.html"
    path.write_text(page, encoding="utf-8")
    result = {"ok": True, "status": "draft_preview", "html": str(path), "duration": plan["duration"],
              "paid_creates": 0, "content_verified": False, "plan_hash": content_hash(bundle)}
    if video:
        result["video"] = str(render_cards(output, cards, bundle["project"]["title"]))
    atomic_json(output / "animatic.manifest.json", result)
    return result


def render_cards(output: Path, cards: list[dict], title: str) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise ConfigError("MP4 cards need Pillow; HTML preview is already available (no package was downloaded)") from None
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ConfigError("MP4 cards need local FFmpeg; HTML preview is already available")
    fonts = [Path("C:/Windows/Fonts/msyh.ttc"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font_path = next((p for p in fonts if p.exists()), None)
    def font(size):
        return ImageFont.truetype(str(font_path), size) if font_path else ImageFont.load_default()
    with tempfile.TemporaryDirectory(prefix="videocreate-animatic-", dir=output) as temp:
        folder, parts = Path(temp), []
        for index, card in enumerate(cards):
            im = Image.new("RGB", (720, 1280), "#10151b")
            draw = ImageDraw.Draw(im)
            y = 80
            def line(value, size=30, color="#e9eee9"):
                nonlocal y
                # Pixel measurement handles CJK/Latin mixes without truncation.
                current = ""
                for char in value:
                    if draw.textlength(current + char, font=font(size)) > 620:
                        draw.text((50, y), current, font=font(size), fill=color)
                        y += size + 15
                        current = ""
                    current += char
                if current:
                    draw.text((50, y), current, font=font(size), fill=color)
                    y += size + 20
            line("VideoCreate / 文字分镜预演", 24, "#9aabb9")
            line(title, 36)
            line(card["shot"]["id"] + " · " + card["shot"]["role"], 26, "#97c8ba")
            line(card["shot"]["information_goal"], 38, "#e1b86d")
            for action in card["shot"]["actions"]:
                line(action["description"])
            for speech in card["shot"].get("audio", {}).get("lines", []):
                line(('画内' if speech["on_screen"] else '画外') + "：“" + speech["text"] + "”", 30, "#e1b86d")
            draw.text((50, 1170), "draft_preview · 无人物生成 · 无实际配音", font=font(22), fill="#9aabb9")
            image = folder / f"card-{index:03}.png"
            part = folder / f"part-{index:03}.mp4"
            im.save(image)
            subprocess.run([ffmpeg, "-v", "error", "-y", "-loop", "1", "-i", str(image), "-t", str(card["duration"]),
                "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(part)], check=True, capture_output=True)
            parts.append(part)
        concat = folder / "concat.txt"
        concat.write_text("\n".join("file '" + p.name + "'" for p in parts), encoding="utf-8")
        target = output / "animatic.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-c", "copy", "-movflags", "+faststart", str(target)], check=True, capture_output=True)
    return target
