from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from ..catalog.bindings import validate_request
from ..config.storage import ConfigError


class BindingImageClient:
    def __init__(self, binding):
        self.binding = binding

    def prepare(self, prompt: str, references: list[Path], *, size: str, quality: str) -> dict:
        binding = self.binding
        if binding.adapter != "openai-images-v1":
            raise ConfigError("Image generation requires its own image adapter")
        if not prompt.strip() or not size.strip() or not quality.strip():
            raise ConfigError("Image prompt, size and quality must not be empty")
        result = validate_request(binding, {"operation": "image-edit" if references else "text-to-image",
            "prompt": prompt, "references": references})
        if not result["ok"]:
            raise ConfigError("; ".join(result["errors"]))
        for path in references:
            if not path.is_file() or mimetypes.guess_type(path.name)[0] not in binding.capabilities["reference_mime_types"]:
                raise ConfigError("Unsupported image reference file")
        return {"binding_snapshot": binding.snapshot(), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "operation": "image-edit" if references else "text-to-image", "size": size, "quality": quality,
            "references": [{"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in references],
            "parameter_consumption": {k: "transmitted" for k in ("model", "prompt", "size", "quality", "references")}}

    def create(self, prompt: str, references: list[Path], *, size: str, quality: str) -> bytes:
        self.prepare(prompt, references, size=size, quality=quality)
        from ..cli import legacy_engine
        legacy_engine()
        import media_client as wire
        binding = self.binding
        fields = {"model": binding.remote_model, "prompt": prompt, "n": 1,
                  "size": size, "quality": quality, "response_format": "b64_json", "output_format": "png"}
        options = {"key": binding.key, "timeout": binding.options.get("request_timeout_seconds", 120)}
        if references:
            body, content_type = wire.multipart_body([(k, str(v)) for k, v in fields.items()], [("image", p) for p in references])
            payload = wire.request_json("POST", wire.api_url(binding.base_url, "/v1/images/edits"),
                body=body, content_type=content_type, **options)
        else:
            payload = wire.request_json("POST", wire.api_url(binding.base_url, "/v1/images/generations"), value=fields, **options)
        return wire._extract_image(payload)
