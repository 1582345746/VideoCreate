"""Deterministic identity crops and single-image guidance for limited upstreams."""
from pathlib import Path
from ..config.storage import ConfigError, atomic_json
from ..planning.project import content_hash, within
from ..references import digest


def register(root, character_id, source, *, crop=None):
    from .pipeline import checked
    bundle = checked(root)
    characters = {c["id"] for c in bundle["animation"]["theme"]["characters"]}
    if character_id not in characters:
        raise ConfigError("Choose a character from this animation theme")
    from PIL import Image
    source_sha = digest(source)
    with Image.open(source) as image:
        image.load()
        if crop:
            x, y, width, height = crop
            if min(x, y) < 0 or min(width, height) < 1 or x + width > image.width or y + height > image.height:
                raise ConfigError("Identity crop must stay inside the source image")
            image = image.crop((x, y, x+width, y+height))
        fingerprint = content_hash({"source_sha256": source_sha, "crop": list(crop) if crop else None})
        target = root / "assets/animation/identity-crops" / (fingerprint + ".png")
        target.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(target)
    from ..assets import register as register_asset
    result = register_asset(root, character_id, target)
    atomic_json(target.with_suffix(".json"), {"character_id": character_id, "source": str(source.resolve()),
        "source_sha256": source_sha, "crop_xywh": list(crop) if crop else None, "derived_sha256": digest(target),
        "purpose": "identity-only-not-video-opening"})
    return result


def guidance_sheet(root, references):
    if len(references) <= 1:
        return references
    from PIL import Image
    signature = [{"path": r, "sha256": digest(within(root, r))} for r in references]
    fingerprint = content_hash(signature)
    target = root / "assets/animation/identity-sheets" / (fingerprint + ".png")
    # Fixed raster geometry and order make the same input reproducible.
    canvas = Image.new("RGB", (512 * len(references), 640), "#f7f4ed")
    for i, relative in enumerate(references):
        with Image.open(within(root, relative)) as source:
            image = source.convert("RGB")
            image.thumbnail((496, 624), Image.Resampling.LANCZOS)
            canvas.paste(image, (i*512 + (512-image.width)//2, (640-image.height)//2))
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target)
    atomic_json(target.with_suffix(".json"), {"inputs": signature, "sha256": digest(target),
        "purpose": "multi-character-identity-guidance-not-video-opening"})
    return [target.relative_to(root).as_posix()]
