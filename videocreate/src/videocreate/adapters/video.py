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
                references: Iterable[Path] | None = None, primary_reference: Path | None = None,
                reference_images: Iterable[Path] = ()) -> dict[str, Any]:
        primary, additional = self._split_references(primary_reference, reference_images, references)
        request = dict(operation="image-to-video" if primary or additional else "text-to-video", prompt=prompt,
                       seconds=seconds, resolution=resolution, aspect_ratio=aspect_ratio,
                       generate_audio=generate_audio, primary_reference=primary,
                       reference_images=additional)
        report = validate_request(self.binding, request)
        if not prompt.strip():
            report["errors"].append("Prompt must not be empty")
        for path in ([primary] if primary else []) + additional:
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
        primary_info = ({"name": primary.name, "sha256": hashlib.sha256(primary.read_bytes()).hexdigest()}
                        if primary else None)
        additional_info = [{"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                           for path in additional]
        return {"binding_snapshot": self.binding.snapshot(), "operation": request["operation"],
                "parameters": {k: v for k, v in request.items() if k not in {"primary_reference", "reference_images", "prompt"}},
                "remote_model": self.model, "prompt": prompt,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "primary_reference": primary_info, "reference_images": additional_info,
                "references": ([primary_info] if primary_info else []) + additional_info,
                "parameter_consumption": consumption, "warnings": report["warnings"]}

    def create(self, prompt: str, *, seconds: float, size: str, resolution: str = "480p",
               aspect_ratio: str = "16:9", generate_audio: bool = False,
               references: Iterable[Path] | None = None, primary_reference: Path | None = None,
               reference_images: Iterable[Path] = ()) -> str:
        import media_client as wire
        from provider_contracts import SubmissionUnknownError, task_id
        primary, additional = self._split_references(primary_reference, reference_images, references)
        self.last_submission = self.prepare(prompt, seconds=seconds, size=size, resolution=resolution,
            aspect_ratio=aspect_ratio, generate_audio=generate_audio,
            primary_reference=primary, reference_images=additional)
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
                    [("input_reference", path) for path in ([primary] if primary else []) + additional])
                response = self._submit("POST", wire.api_url(self.base_url, endpoint), key=self.binding.key,
                    body=body, content_type=content_type, timeout=self.binding.options.get("request_timeout_seconds", 120))
            else:
                images = ([primary] if primary else []) + additional
                if adapter == "sub2api-json-v1":
                    prepared_primary = (wire._prepare_sub2api_reference(primary, aspect_ratio, Path(folder))
                                        if primary else None)
                    prepared_additional = [wire._prepare_sub2api_reference(path, aspect_ratio, Path(folder))
                                           for path in additional]
                    if prepared_primary:
                        fields["image"] = {"url": wire.Sub2ApiVideoClient._data_url(prepared_primary)}
                    if prepared_additional:
                        fields["reference_images"] = [
                            {"url": wire.Sub2ApiVideoClient._data_url(path)} for path in prepared_additional]
                elif images:
                    fields["images"] = [wire.Sub2ApiVideoClient._data_url(path) for path in images]
                response = self._submit("POST", wire.api_url(self.base_url, endpoint), key=self.binding.key,
                    value=fields, timeout=self.binding.options.get("request_timeout_seconds", 120))
        # request_id is a trace unless this particular protocol explicitly declares otherwise.
        keys = self.binding.options.get("task_id_fields", ["task_id", "taskId", "job_id", "jobId", "id"])
        created = task_id(response, keys=keys)
        self.last_submission["trace_ids"] = {key: str(response[key])[:500] for key in ("request_id", "requestId", "trace_id", "traceId") if response.get(key)}
        if not created:
            raise SubmissionUnknownError("Create response has no protocol task ID; hold and reconcile, do not resubmit")
        return created

    @staticmethod
    def _split_references(primary_reference: Path | None, reference_images: Iterable[Path],
                          references: Iterable[Path] | None) -> tuple[Path | None, list[Path]]:
        additional = list(reference_images)
        if references is not None:
            legacy = list(references)
            if primary_reference is not None or additional:
                raise ConfigError("Use either legacy references or explicit primary/reference_images fields")
            primary_reference = legacy[0] if legacy else None
            additional = legacy[1:]
        return primary_reference, additional
