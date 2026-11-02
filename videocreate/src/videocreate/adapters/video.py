from __future__ import annotations

import hashlib
import mimetypes
import tempfile
from pathlib import Path
from typing import Any, Iterable

from ..catalog.bindings import Binding, validate_request
from ..config.storage import ConfigError


class BindingVideoClient:
    """Validate and prepare a binding-specific create; retain proven read paths.

    prepare() is offline and returns the exact semantic request plus parameter
    consumption. It runs before the attempt is reserved/persisted by the engine.
    Credentials and inline reference bytes never enter a project snapshot.
    """

    def __init__(self, binding: Binding, reader: Any):
        self.binding, self.reader = binding, reader
        self.model, self.base_url = binding.remote_model, binding.base_url
        self.last_submission: dict[str, Any] = {}

    def __getattr__(self, name: str):
        return getattr(self.reader, name)

    def _submit(self, *args, **kwargs):
        import media_client as wire
        from provider_contracts import SubmissionUnknownError
        from vc_common import APIError
        try:
            return wire.request_json(*args, **kwargs)
        except APIError as error:
            self.last_submission["trace_ids"] = {"request_id": error.request_id} if error.request_id else {}
            if error.status not in self.binding.options.get("confirmed_rejection_http_statuses", []):
                raise SubmissionUnknownError(str(error)) from None
            raise

    def prepare(self, prompt: str, *, seconds: float, size: str, resolution: str = "480p",
                aspect_ratio: str = "16:9", generate_audio: bool = False,
                references: Iterable[Path]) -> dict[str, Any]:
        refs = list(references)
        request = dict(operation="image-to-video" if refs else "text-to-video", prompt=prompt,
                       seconds=seconds, resolution=resolution, aspect_ratio=aspect_ratio,
                       generate_audio=generate_audio, references=refs)
        report = validate_request(self.binding, request)
        if not prompt.strip():
            report["errors"].append("Prompt must not be empty")
        for path in refs:
            if not path.is_file():
                report["errors"].append("Reference file does not exist")
            if mimetypes.guess_type(path.name)[0] not in self.binding.capabilities["reference_mime_types"]:
                report["errors"].append("Reference MIME type is unsupported")
        if report["errors"]:
            raise ConfigError("; ".join(report["errors"]))
        consumption = {key: "transmitted" for key in ("prompt", "seconds", "resolution", "aspect_ratio", "references", "model")}
        audio = self.binding.capabilities["audio_control"]
        consumption["generate_audio"] = "transmitted" if audio == "explicit" else audio
        from media_client import size_orientation_matches_aspect_ratio
        consumption["size"] = ("transmitted" if self.binding.adapter == "newapi-multipart-v1" and
            size and size != "auto" and size_orientation_matches_aspect_ratio(size, aspect_ratio)
            else "derived-from-resolution-and-aspect-ratio")
        return {"binding_snapshot": self.binding.snapshot(), "operation": request["operation"],
                "parameters": {k: v for k, v in request.items() if k not in {"references", "prompt"}},
                "remote_model": self.model, "prompt": prompt,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "references": [{"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in refs],
                "parameter_consumption": consumption, "warnings": report["warnings"]}

    def create(self, prompt: str, *, seconds: float, size: str, resolution: str = "480p",
               aspect_ratio: str = "16:9", generate_audio: bool = False,
               references: Iterable[Path]) -> str:
        import media_client as wire
        from provider_contracts import SubmissionUnknownError, task_id
        refs = list(references)
        self.last_submission = self.prepare(prompt, seconds=seconds, size=size, resolution=resolution,
            aspect_ratio=aspect_ratio, generate_audio=generate_audio, references=refs)
        adapter = self.binding.adapter
        fields: dict[str, Any] = {"model": self.model, "prompt": prompt,
            "duration" if adapter == "sub2api-json-v1" else "seconds": seconds,
            "resolution": resolution, "aspect_ratio": aspect_ratio}
        if self.binding.capabilities["audio_control"] == "explicit":
            fields["generate_audio"] = bool(generate_audio)
        endpoint = "/v1/videos/generations" if adapter == "sub2api-json-v1" else "/v1/videos"
        with tempfile.TemporaryDirectory(prefix="videocreate-outbound-") as folder:
            if adapter == "newapi-multipart-v1":
                if self.last_submission["parameter_consumption"]["size"] == "transmitted":
                    fields["size"] = size
                body, content_type = wire.multipart_body(
                    [(k, str(v).lower() if isinstance(v, bool) else str(v)) for k, v in fields.items()],
                    [("input_reference", path) for path in refs])
                response = self._submit("POST", wire.api_url(self.base_url, endpoint), key=self.binding.key,
                    body=body, content_type=content_type, timeout=self.binding.options.get("request_timeout_seconds", 120))
            else:
                prepared = ([wire._prepare_sub2api_reference(path, aspect_ratio, Path(folder)) for path in refs]
                            if adapter == "sub2api-json-v1" else refs)
                if adapter == "sub2api-json-v1":
                    urls = [{"url": wire.Sub2ApiVideoClient._data_url(path)} for path in prepared]
                    if len(urls) == 1:
                        fields["image"] = urls[0]
                    elif urls:
                        fields["reference_images"] = urls
                elif prepared:
                    fields["images"] = [wire.Sub2ApiVideoClient._data_url(path) for path in prepared]
                response = self._submit("POST", wire.api_url(self.base_url, endpoint), key=self.binding.key,
                    value=fields, timeout=self.binding.options.get("request_timeout_seconds", 120))
        # request_id is a trace unless this particular protocol explicitly declares otherwise.
        keys = self.binding.options.get("task_id_fields", ["task_id", "taskId", "job_id", "jobId", "id"])
        created = task_id(response, keys=keys)
        self.last_submission["trace_ids"] = {key: str(response[key])[:500] for key in ("request_id", "requestId", "trace_id", "traceId") if response.get(key)}
        if not created:
            raise SubmissionUnknownError("Create response has no protocol task ID; hold and reconcile, do not resubmit")
        return created
