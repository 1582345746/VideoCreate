from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from ..catalog.bindings import validate_request
from ..config.storage import ConfigError


class BindingImageClient:
    def __init__(self, binding):
        self.binding = binding

    def prepare(self, prompt: str, references: list[Path], *, size: str, quality: str,
                output_format: str = "png") -> dict:
        binding = self.binding
        if binding.adapter != "openai-images-v1":
            raise ConfigError("Image generation requires its own image adapter")
        if not prompt.strip() or not size.strip() or not quality.strip():
            raise ConfigError("Image prompt, size and quality must not be empty")
        if size not in binding.capabilities.get("image_sizes", []):
            raise ConfigError("Image size is not configured for this binding")
        if quality not in binding.capabilities.get("image_quality_values", []):
            raise ConfigError("Image quality is not configured for this binding")
        fields = set(binding.options.get("image_request_fields", ["n", "size", "quality", "response_format", "output_format"]))
        if "quality" not in fields and quality != "auto":
            raise ConfigError("This image binding does not transmit a quality override")
        if "size" not in fields and size != "auto":
            raise ConfigError("This image binding does not transmit a size override; use auto")
        if "output_format" not in fields and output_format != "png":
            raise ConfigError("This image binding does not transmit an output format override")
        if output_format not in binding.capabilities.get("output_formats", ["png"]):
            raise ConfigError("Output format is not configured for this image binding")
        if output_format == "gif" and binding.capabilities.get("animated_output") != "supported":
            raise ConfigError("Animated GIF output is not verified for this image binding")
        result = validate_request(binding, {"operation": "image-edit" if references else "text-to-image",
            "prompt": prompt, "references": references})
        if not result["ok"]:
            raise ConfigError("; ".join(result["errors"]))
        for path in references:
            mime = mimetypes.guess_type(path.name)[0]
            if not path.is_file() or mime not in binding.capabilities["reference_mime_types"]:
                raise ConfigError("Unsupported image reference file")
            if mime == "image/gif":
                if binding.capabilities.get("animated_input") != "supported":
                    raise ConfigError("GIF input is not verified for this image binding")
                from ..media.gif import inspect_gif
                metadata = inspect_gif(path.read_bytes())
                if (metadata["frame_count"] > binding.capabilities.get("max_animation_frames", 3000)
                        or metadata["duration_ms"] > binding.capabilities.get("max_animation_duration_seconds", 30) * 1000):
                    raise ConfigError("GIF input exceeds this binding's animation limit")
        return {"binding_snapshot": binding.snapshot(), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "operation": "image-edit" if references else "text-to-image", "size": size, "quality": quality,
            "output_format": output_format,
            "references": [{"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in references],
            "parameter_consumption": {k: "transmitted" if k in fields or k in {"model", "prompt", "references"} else "provider-default"
                for k in ("model", "prompt", "size", "quality", "references", "output_format")}}

    def create_payload(self, prompt: str, references: list[Path], *, size: str, quality: str,
                       output_format: str = "png") -> dict:
        self.prepare(prompt, references, size=size, quality=quality, output_format=output_format)
        from ..cli import legacy_engine
        legacy_engine()
        import media_client as wire
        binding = self.binding
        optional = {"n": 1, "size": size, "quality": quality,
                    "response_format": binding.options.get("image_response_format", "b64_json"), "output_format": output_format}
        allowed = binding.options.get("image_request_fields", list(optional))
        fields = {"model": binding.remote_model, "prompt": prompt, **{k: optional[k] for k in allowed}}
        options = {"key": binding.key, "timeout": binding.options.get("request_timeout_seconds", 120)}
        if references:
            body, content_type = wire.multipart_body([(k, str(v)) for k, v in fields.items()], [("image", p) for p in references])
            payload = wire.request_json("POST", wire.api_url(binding.base_url, "/v1/images/edits"),
                body=body, content_type=content_type, **options)
        else:
            payload = wire.request_json("POST", wire.api_url(binding.base_url, "/v1/images/generations"), value=fields, **options)
        return payload

    def create(self, prompt: str, references: list[Path], *, size: str, quality: str,
               output_format: str = "png") -> bytes:
        import media_client as wire
        return wire._extract_image(self.create_payload(prompt, references, size=size, quality=quality,
                                                       output_format=output_format))
