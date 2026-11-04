"""Local playable review packet. Samples and measurements never approve content."""
from __future__ import annotations

import html
import hashlib
import os
import shutil
from pathlib import Path

from ..config.storage import ConfigError, atomic_json
from ..planning.project import within
from ..timeline.render import run
from .receipts import contracts, template


def packet(root: Path, bundle: dict, *, output_name="preview.mp4") -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ConfigError("FFmpeg required")
    assets = contracts(root, bundle, output_name=output_name)
    if not assets:
        raise ConfigError("No actual media to review")
    folder = root / "reviews" / ("packet-" + output_name[:-4])
    folder.mkdir(parents=True, exist_ok=True)
    sections, records = [], {}
    for aid, asset in assets.items():
        source = within(root, asset["path"])
        sample_paths = []
        for n, (start, end) in enumerate(asset["windows"]):
            for j in range(4):
                at = start + (end-start) * (j+.5)/4
                target = folder / f"{aid}-{n}-{j}.jpg"
                run([ffmpeg, "-v", "error", "-y", "-ss", str(at), "-i", str(source), "-frames:v", "1",
                     "-vf", "scale=480:-2", str(target)])
                sample_paths.append({"path": target.relative_to(root).as_posix(), "source_time": at,
                                     "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        relative = Path(os.path.relpath(source, folder)).as_posix()
        text = html.escape(aid + " | retained source windows: " + str(asset["windows"]))
        sections.append(f'<section><h2>{text}</h2><video controls preload="metadata" src="{html.escape(relative, quote=True)}"></video><p>Review every retained interval, including sound where applicable.</p>' +
            "".join(f'<img src="{Path(s["path"]).name}" alt="sample at {s["source_time"]:.2f}s">' for s in sample_paths) + '</section>')
        records[aid] = {**asset, "samples": sample_paths,
            "defects": [], "motion_review": "unverified", "audio_review": "unverified"}
    target = folder / "index.html"
    target.write_text('<!doctype html><meta charset="utf-8"><title>VideoCreate review</title><style>body{background:#14202b;color:#eee;font:16px sans-serif;margin:32px}video{width:min(900px,100%)}img{width:22%;margin:1%}section{margin-bottom:40px}</style><h1>VideoCreate 审片包</h1><p>抽帧仅供定位；动态、剪辑和声音需要实际播放。缺陷记录：category / source_start / source_end / severity / observation / repair_component。</p>' + "".join(sections), encoding="utf-8")
    atomic_json(folder / "observations.template.json", {"schema_version": 1, "reviewer_id": "", "assets": records,
        "defect_categories": ["identity", "anatomy", "contact", "motion", "framing", "continuity", "speech", "edit", "facts", "overlay"]})
    atomic_json(folder / "content-review.template.json", template(root, bundle, output_name=output_name))
    return {"ok": True, "review_page": str(target), "observations": str(folder / "observations.template.json"),
            "content_status": "unverified", "paid_creates": 0}
