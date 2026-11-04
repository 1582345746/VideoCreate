"""Deterministic text/graphics compositing, separate from model-generated pixels."""
from pathlib import Path
from ..config.storage import ConfigError
from ..planning.project import within


def raster(root, item, width, height, target):
    from PIL import Image, ImageDraw, ImageFont
    canvas = Image.new("RGBA", (width, height))
    if item.get("path"):
        source = within(root, item["path"])
        with Image.open(source) as image:
            image = image.convert("RGBA")
            image.thumbnail((width, height))
            y = 0 if item.get("position") == "top" else height-image.height if item.get("position") == "bottom" else (height-image.height)//2
            canvas.alpha_composite(image, ((width-image.width)//2, y))
    else:
        font_path = next((p for p in [Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")] if p.is_file()), None)
        if not font_path:
            raise ConfigError("Overlay text needs a local TrueType font")
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.truetype(str(font_path), max(14, height//24))
        lines, line = [], ""
        for char in item["text"]:
            if char == "\n" or draw.textlength(line+char, font=font) > width*.88:
                lines.append(line)
                line = "" if char == "\n" else char
            else:
                line += char
        lines.append(line)
        text = "\n".join(lines)
        box = draw.multiline_textbbox((0,0), text, font=font, spacing=8, align="center")
        tw, th = box[2]-box[0], box[3]-box[1]
        if th > height*.8:
            raise ConfigError("Overlay text too long for canvas; split timed overlays")
        x = (width-tw)/2
        y = height*.06 if item.get("position") == "top" else height-th-height*.06 if item.get("position", "bottom") == "bottom" else (height-th)/2
        draw.rounded_rectangle((x-18, y-12, x+tw+18, y+th+12), radius=8, fill=(0,0,0,165))
        draw.multiline_text((x-box[0],y-box[1]), text, font=font, fill="white", spacing=8, align="center")
    canvas.save(target)


def composite(root, timeline, source, output, folder, ffmpeg, duration):
    from .render import run
    width, height = timeline.get("width",720), timeline.get("height",1280)
    args = [ffmpeg, "-v", "error", "-y", "-i", str(source)]
    graph, previous = [], "0:v"
    for i, item in enumerate(timeline["overlays"], 1):
        target = folder / f"overlay-{i:03}.png"
        raster(root, item, width, height, target)
        args += ["-loop", "1", "-i", str(target)]
        label = f"ov{i}"
        graph.append(f"[{previous}][{i}:v]overlay=0:0:enable='gte(t,{item['start']})*lt(t,{item['end']})'[{label}]")
        previous = label
    args += ["-filter_complex", ";".join(graph), "-map", f"[{previous}]", "-map", "0:a?", "-t", str(duration),
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(output)]
    run(args)
