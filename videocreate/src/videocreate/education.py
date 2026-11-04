"""Source-grounded explainer authoring. Verification is a recorded editorial act."""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import math
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from .config.storage import ConfigError, atomic_json
from .planning.project import content_hash, load_project, within


def empty_research(topic: str = "") -> dict:
    return {"schema_version": 1, "topic": topic, "sources": [], "claims": [], "narration": [],
            "note": "Add verified sources/claims and timed narration before paid explainer generation. AI B-roll is illustration, not documentary evidence."}


def _records(value, label, errors):
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        errors.append(label + ": expected an array of records")
        return {}
    result = {}
    for record in value:
        rid = record.get("id")
        if not isinstance(rid, str) or not rid.strip() or rid in result:
            errors.append(label + ": missing/duplicate id")
        else:
            result[rid] = record
    return result


def _finite(v):
    return isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)


def validate_research(bundle: dict, *, root: Path | None = None, ready=False, shot_ids=None) -> dict:
    errors, warnings = [], []
    research = bundle.get("research", {})
    if not isinstance(research, dict) or research.get("schema_version") != 1:
        return {"ok": False, "errors": ["Explainer requires research.json schema_version=1"], "warnings": []}
    sources = _records(research.get("sources", []), "sources", errors)
    claims = _records(research.get("claims", []), "claims", errors)
    narration = _records(research.get("narration", []), "narration", errors)
    for sid, source in sources.items():
        url = urlsplit(str(source.get("url", "")))
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            errors.append(sid + ": use an attributable HTTPS source URL")
        for key in ("title", "publisher", "accessed_at", "path", "sha256"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                errors.append(sid + ": missing " + key)
        try:
            dt.date.fromisoformat(source.get("accessed_at", ""))
        except (ValueError, TypeError):
            errors.append(sid + ": accessed_at must be YYYY-MM-DD")
        if root and source.get("path"):
            try:
                path = within(root, source["path"])
                if hashlib.sha256(path.read_bytes()).hexdigest() != source.get("sha256"):
                    errors.append(sid + ": source snapshot bytes changed")
            except ConfigError as error:
                errors.append(sid + ": " + str(error))
    used = set()
    for shot in bundle["director"]["shots"]:
        if shot_ids is not None and shot["id"] not in shot_ids:
            continue
        ids = shot.get("claim_ids", [])
        if not isinstance(ids, list) or any(not isinstance(cid, str) for cid in ids):
            errors.append(shot["id"] + ": claim_ids must be strings")
            ids = []
        used.update(ids)
        if not ids:
            (errors if ready else warnings).append(shot["id"] + ": explainer shot needs explicit claim_ids")
        if shot.get("visual_purpose") not in {"illustration", "map", "graphic", "evidence"}:
            errors.append(shot["id"] + ": classify B-roll, map, graphic or actual sourced evidence")
        if shot.get("visual_purpose") == "evidence":
            errors.append(shot["id"] + ": generated video cannot be classified as factual footage; import attributable footage separately")
    for nid, line in narration.items():
        ids = line.get("claim_ids", [])
        if not isinstance(ids, list) or any(not isinstance(cid, str) or cid not in claims for cid in ids):
            errors.append(nid + ": unknown narration claim_ids")
            ids = []
        if line.get("kind", "factual") == "factual" and not ids:
            errors.append(nid + ": factual narration requires source claims")
        if not isinstance(line.get("text"), str) or not line["text"].strip():
            errors.append(nid + ": narration text is required")
        start, end = line.get("start"), line.get("end")
        target = bundle["brief"].get("target_seconds", 120)
        if not _finite(start) or not _finite(end) or not 0 <= start < end <= target:
            errors.append(nid + ": narration interval outside target duration")
        if shot_ids is None:
            used.update(ids)
    if used - set(claims):
        errors.append("Unknown used claim IDs: " + ", ".join(sorted(used - set(claims))))
    for cid, claim in claims.items():
        kind = claim.get("kind")
        if kind not in {"descriptive", "statistic", "ranking"}:
            errors.append(cid + ": explicitly classify kind as descriptive, statistic or ranking")
        if not isinstance(claim.get("text"), str) or not claim["text"].strip():
            errors.append(cid + ": claim text is required")
        ids = claim.get("source_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(s, str) or s not in sources for s in ids):
            errors.append(cid + ": claim needs known source_ids")
            continue
        if claim.get("status") not in {"draft", "verified", "disputed"}:
            errors.append(cid + ": status must be draft, verified or disputed")
        if claim.get("status") != "verified":
            (errors if ready and cid in used else warnings).append(cid + ": fact remains " + str(claim.get("status")))
        else:
            review = claim.get("review", {})
            if not isinstance(review, dict) or not all(isinstance(review.get(k), str) and review[k].strip() for k in ("reviewer_id", "excerpt", "source_id", "source_sha256")):
                errors.append(cid + ": verified fact requires reviewer and source excerpt/hash")
            elif review["source_id"] not in ids or review["source_sha256"] != sources[review["source_id"]].get("sha256"):
                errors.append(cid + ": claim review belongs to different source bytes")
            elif root:
                try:
                    raw = within(root, sources[review["source_id"]].get("path", "")).read_text(encoding="utf-8-sig")
                    normalize = lambda s: " ".join(html.unescape(s).split())
                    if normalize(review["excerpt"]) not in normalize(raw):
                        errors.append(cid + ": supporting excerpt not found in preserved UTF-8 source")
                except (ConfigError, UnicodeError, OSError) as error:
                    errors.append(cid + ": cannot verify source excerpt: " + str(error))
        metric = claim.get("metric")
        if kind in {"statistic", "ranking"} and metric is None:
            errors.append(cid + ": quantitative claim requires metric and year/definition")
        if metric is not None:
            if not isinstance(metric, dict) or not all(metric.get(k) for k in ("name", "unit", "year", "geography", "definition")) or not _finite(metric.get("value")):
                errors.append(cid + ": quantitative claims need value/name/unit/year/geography/definition")
        comparison = claim.get("comparison")
        if kind == "ranking" and comparison is None:
            errors.append(cid + ": ranking requires comparison universe, date and coverage")
        if comparison is not None:
            if not metric or not isinstance(comparison, dict) or not all(comparison.get(k) for k in ("universe", "as_of", "ranking_basis", "coverage")):
                errors.append(cid + ": ranking needs metric, comparison universe, as_of, ranking_basis and coverage")
    intervals = sorted((v["start"], v["end"]) for v in narration.values() if _finite(v.get("start")) and _finite(v.get("end")))
    if any(b[0] < a[1] for a,b in zip(intervals, intervals[1:])):
        errors.append("Narration intervals overlap; use one intelligible main narration track")
    if not claims:
        (errors if ready else warnings).append("Research has no facts; illustrative planning only")
    if not narration:
        (errors if ready and shot_ids is None else warnings).append("No independent narration authored")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "used_claims": sorted(used),
            "fact_status": "editorially_verified" if ready and not errors else "planning_only", "paid_creates": 0}


def add_source(root: Path, source_id: str, source: Path, *, url: str, title: str, publisher: str) -> dict:
    import re
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", source_id or ""):
        raise ConfigError("Source id must be a safe identifier")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or not title.strip() or not publisher.strip():
        raise ConfigError("Source needs HTTPS URL, title and publisher")
    source.read_text(encoding="utf-8-sig")
    bundle = load_project(root)
    if "research" not in bundle:
        raise ConfigError("Use an explainer project with a research layer")
    if any(s.get("id") == source_id for s in bundle["research"]["sources"]):
        raise ConfigError("Source id already exists; preserve reviewed snapshots")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    target = root / "assets" / "research" / f"{source_id}-{sha[:12]}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    record = {"id": source_id, "url": url, "title": title, "publisher": publisher,
              "accessed_at": dt.date.today().isoformat(), "path": target.relative_to(root).as_posix(), "sha256": sha}
    bundle["research"]["sources"].append(record)
    atomic_json(within(root, bundle["project"]["files"]["research"]), bundle["research"])
    return {"ok": True, "source": record, "paid_creates": 0}


def export(root: Path, *, apply=False) -> dict:
    bundle = load_project(root)
    report = validate_research(bundle, root=root, ready=True)
    if not report["ok"]:
        raise ConfigError("; ".join(report["errors"]))
    research = bundle["research"]
    subtitles = None
    if apply:
        from .timeline.model import mapping
        existing = list(bundle["timeline"].get("subtitles", []))
        mapped_existing = mapping(bundle["timeline"])["subtitles"] if existing else []
        subtitles = list(existing)
        intervals = list(mapped_existing)
        for line in sorted(research["narration"], key=lambda item: item["start"]):
            cue = {"text": line["text"], "start": line["start"], "end": line["end"]}
            duplicate = False
            for prior in intervals:
                overlaps = cue["start"] < prior["end"] and prior["start"] < cue["end"]
                if not overlaps:
                    continue
                same_window = abs(cue["start"] - prior["start"]) < 0.001 and abs(cue["end"] - prior["end"]) < 0.001
                if same_window and cue["text"] == prior["text"]:
                    duplicate = True
                else:
                    raise ConfigError("Narration subtitle overlaps an existing cue; resolve the timeline conflict explicitly")
            if not duplicate:
                subtitles.append(cue)
                intervals.append(cue)
        subtitles.sort(key=lambda item: item.get("start", 0))
    target = root / "deliverables" / "narration-script.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = sorted(research["narration"], key=lambda l: l["start"])
    target.write_text("# " + research["topic"] + "\n\n" + "\n\n".join(
        f"{l['start']:.2f}–{l['end']:.2f}s [{', '.join(l.get('claim_ids', []))}]\n{l['text']}" for l in lines) +
        "\n\n资料来源：\n" + "\n".join(s["title"] + " " + s["url"] for s in research["sources"]), encoding="utf-8")
    if apply:
        bundle["timeline"]["subtitles"] = subtitles
        atomic_json(within(root, bundle["project"]["files"].get("timeline", "timeline.json")), bundle["timeline"])
    return {"ok": True, "script": str(target), "subtitles_applied": apply,
            "alignment": "authored timings, not verified transcription", "paid_creates": 0}


def import_narration(root: Path, source: Path) -> dict:
    bundle = load_project(root)
    if bundle["brief"].get("audio_policy") != "voiceover":
        raise ConfigError("Independent narration import requires voiceover workflow")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ConfigError("FFprobe required")
    result = subprocess.run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)], capture_output=True, check=True)
    info = json.loads(result.stdout)
    duration = float(info["format"]["duration"])
    if not any(s["codec_type"] == "audio" for s in info["streams"]) or not _finite(duration) or not 0 < duration <= bundle["brief"]["target_seconds"] + 0.01:
        raise ConfigError("Narration must contain audio and fit picture duration")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    target = root / "assets" / "narration" / (sha[:16] + source.suffix.lower())
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    timeline = bundle["timeline"]
    timeline["audio_tracks"] = [t for t in timeline.get("audio_tracks", []) if t["id"] != "narration-main"] + [
        {"id": "narration-main", "kind": "dialogue", "path": target.relative_to(root).as_posix(),
         "source_in": 0, "source_out": duration, "timeline_start": 0, "gain_db": 0}]
    for seg in timeline["segments"]:
        seg["source_audio"] = "mute"
    atomic_json(target.with_suffix(target.suffix + ".provenance.json"), {"sha256": sha, "duration": duration,
        "listening": "unverified", "research_hash": content_hash(bundle.get("research", {}))})
    atomic_json(within(root, bundle["project"]["files"].get("timeline", "timeline.json")), timeline)
    return {"ok": True, "audio": str(target), "duration": duration, "alignment": "review_pending", "paid_creates": 0}


def draw_map(source: Path, output: Path, *, source_url: str) -> dict:
    """Draw supplied GeoJSON polygons; never invent precise boundaries from prompts."""
    if output.suffix.lower() != ".svg" or output.resolve() == source.resolve():
        raise ConfigError("Choose a separate .svg output; source data must be preserved")
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ConfigError("Map data needs a source URL")
    value = json.loads(source.read_text(encoding="utf-8-sig"))
    if value.get("type") == "FeatureCollection":
        geometries = [f.get("geometry") for f in value.get("features", []) if isinstance(f, dict)]
    else:
        geometries = [value.get("geometry")] if value.get("type") == "Feature" else [value]
    polygons = []
    for geometry in geometries:
        if not isinstance(geometry, dict):
            raise ConfigError("GeoJSON requires polygon geometry")
        if geometry.get("type") == "Polygon":
            polygons.append(geometry.get("coordinates"))
        elif geometry.get("type") == "MultiPolygon":
            if not isinstance(geometry.get("coordinates"), list):
                raise ConfigError("MultiPolygon coordinates must be an array")
            polygons.extend(geometry["coordinates"])
        else:
            raise ConfigError("Map accepts Polygon or MultiPolygon geometries")
    if not polygons or any(not isinstance(poly,list) or not poly or any(not isinstance(ring,list) or len(ring)<4 for ring in poly) for poly in polygons):
        raise ConfigError("GeoJSON polygons need rings with at least four coordinates")
    points = [p for poly in polygons for ring in poly for p in ring]
    if not points or any(not isinstance(p,list) or len(p) < 2 or not all(_finite(v) for v in p[:2]) or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in points):
        raise ConfigError("Map coordinates must be finite WGS84 longitude/latitude")
    if any(ring[0][:2] != ring[-1][:2] for poly in polygons for ring in poly):
        raise ConfigError("GeoJSON polygon rings must be closed")
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    if max(xs)-min(xs) > 180:
        raise ConfigError("Antimeridian maps need a suitable projected source; automatic wrapping is not implemented")
    scale = min(1160 / max(max(xs)-min(xs), .001), 600 / max(max(ys)-min(ys), .001))
    paths = []
    for poly in polygons:
        d = " ".join("M " + " L ".join(f"{60+(x-min(xs))*scale:.2f},{660-(y-min(ys))*scale:.2f}" for x,y,*_ in ring) + " Z" for ring in poly)
        paths.append(f'<path d="{d}" fill="#77afbe" stroke="#e5f4f3" stroke-width="1.5" fill-rule="evenodd"/>')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="#11202c"/>' + "".join(paths) + '</svg>', encoding="utf-8")
    from PIL import Image, ImageDraw
    raster = Image.new("RGB", (1280,720), "#11202c")
    drawing = ImageDraw.Draw(raster)
    for poly in polygons:
        for i, ring in enumerate(poly):
            coords = [(60+(p[0]-min(xs))*scale,660-(p[1]-min(ys))*scale) for p in ring]
            drawing.polygon(coords, fill="#77afbe" if i == 0 else "#11202c", outline="#e5f4f3")
    raster.save(output.with_suffix(".png"))
    provenance = {"source_url": source_url, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "raster_sha256": hashlib.sha256(output.with_suffix(".png").read_bytes()).hexdigest(), "projection": "equirectangular; not suitable for area comparisons",
        "boundary_review": "unverified", "note": "Source attribution does not verify legal boundaries, labels or territorial completeness"}
    atomic_json(output.with_suffix(".provenance.json"), provenance)
    return {"ok": True, "map": str(output), "raster": str(output.with_suffix(".png")), **provenance, "paid_creates": 0}
