"""Offline workflow configuration and browser handoffs; never drives a browser.

Browser capabilities and login are live observations, not JSON settings. Nothing
in this module turns a prepared request into an accepted or completed task.
"""
from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from urllib.parse import urlsplit

from .config.storage import ConfigError, atomic_json, load_json
from .planning.project import compile_job, content_hash, load_project, validate_plan, within

IMAGE_OPERATIONS = {"text-to-image", "image-edit"}
REFERENCE_OPERATIONS = {"image-to-video", "image-edit"}
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def _origin(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or any(c.isspace() for c in url) or "\\" in url or "*" in parsed.hostname):
            raise ValueError()
        return "https://" + parsed.hostname.lower() + (":" + str(port) if port not in {None, 443} else "")
    except ValueError:
        raise ConfigError("Browser URL must be HTTPS without credentials, query or fragment") from None


def api_selection(config: dict, stage: dict) -> tuple[str, str]:
    kind = "image" if stage["operation"] in IMAGE_OPERATIONS else "video"
    model = stage.get("model", config["defaults"].get(kind + "_model", ""))
    binding = stage.get("binding", config["routes"].get(model, {}).get("preferred_binding", ""))
    return model, binding


def validate_workflows(config: dict) -> list[str]:
    """Semantic validation after the strict JSON schema has checked types."""
    errors = []
    services, workflows = config.get("browser_services", {}), config.get("workflows", {})
    for group, values in (("browser_services", services), ("workflows", workflows)):
        if any(not ID.fullmatch(key) for key in values):
            errors.append(f"$.{group}: invalid ID")
    for sid, service in services.items():
        path = "$.browser_services." + sid
        try:
            origins = {_origin(value) for value in service["allowed_origins"]}
            if any(urlsplit(value).path not in {"", "/"} for value in service["allowed_origins"]):
                errors.append(path + ".allowed_origins: use origins without paths")
            if _origin(service["base_url"]) not in origins:
                errors.append(path + ".base_url: origin is not allowed")
        except ConfigError as error:
            errors.append(path + ": " + str(error))
        if "profile_directory" in service:
            if service["driver"] != "playwright-local" or not service["profile_directory"].strip():
                errors.append(path + ".profile_directory: only a chosen playwright-local driver uses a dedicated profile")
    for wid, workflow in workflows.items():
        previous = {}
        for stage in workflow["stages"]:
            path = "$.workflows." + wid + "." + stage["id"]
            if not ID.fullmatch(stage["id"]) or stage["id"] in previous:
                errors.append(path + ": invalid or duplicate stage ID")
            if "input_from" in stage:
                source = previous.get(stage["input_from"])
                if not source or source["operation"] not in IMAGE_OPERATIONS:
                    errors.append(path + ".input_from: must reference an earlier image stage")
                if stage["operation"] not in REFERENCE_OPERATIONS:
                    errors.append(path + ".input_from: operation does not consume images")
            if stage["executor"] == "browser":
                if any(key in stage for key in ("model", "binding")):
                    errors.append(path + ": browser stages cannot select API models or bindings")
                service = services.get(stage.get("service"))
                if not service or stage["operation"] not in service["requested_operations"]:
                    errors.append(path + ".service: unknown service or operation not requested")
            else:
                if "service" in stage:
                    errors.append(path + ": API stages cannot select browser services")
                model, binding = api_selection(config, stage)
                kind = "image" if stage["operation"] in IMAGE_OPERATIONS else "video"
                item = config["bindings"].get(binding, {})
                route = config["routes"].get(model, {})
                if (config["models"].get(model, {}).get("kind") != kind or item.get("model") != model
                        or binding not in route.get("candidates", []) or stage["operation"] not in item.get("operations", [])):
                    errors.append(path + ": API stage needs a matching model, route, binding and operation")
            previous[stage["id"]] = stage
    if "workflow" in config["defaults"] and config["defaults"]["workflow"] not in workflows:
        errors.append("$.defaults.workflow: unknown workflow")
    return errors


def select_workflow(config: dict, workflow_id: str | None) -> tuple[str, dict]:
    wid = workflow_id or config["defaults"].get("workflow")
    if wid not in config.get("workflows", {}):
        raise ConfigError("Select a configured --workflow; add browser_services/workflows to the same user JSON")
    return wid, config["workflows"][wid]


def describe(config: dict, workflow_id: str | None) -> dict:
    wid, workflow = select_workflow(config, workflow_id)
    rows = []
    for stage in workflow["stages"]:
        row = dict(stage)
        if stage["executor"] == "browser":
            service = config["browser_services"][stage["service"]]
            row.update(driver=service["driver"], base_url=service["base_url"], enabled=service["enabled"],
                       status="browser_runtime_check_required" if service["enabled"] else "disabled",
                       login="unverified", generation="unverified", automatic_execution=False)
        else:
            model, binding = api_selection(config, stage)
            item = config["bindings"][binding]
            row.update(model=model, binding=binding, enabled=item["enabled"],
                       status="configured" if item["enabled"] else "disabled",
                       command_family="assets image" if stage["operation"] in IMAGE_OPERATIONS else "jobs run")
        rows.append(row)
    return {"ok": True, "workflow": wid, "stages": rows, "verification": "configuration-only",
            "automatic_workflow_runner": False, "network_requests": 0, "paid_creates": 0}


def _image_reference(root: Path, relative: str, role: str) -> dict:
    path = within(root, relative)
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ConfigError("Browser references must be local PNG/JPEG/WebP files inside the project")
    _verify_image_bytes(path, data, mime)
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(data).hexdigest(),
            "mime_type": mime, "role": role}


def _verify_image_bytes(path: Path, data: bytes, mime: str) -> None:
    """Reject files that have a recognizable header but cannot be decoded.

    Pillow is optional in VideoCreate. When it is installed, use its decoder;
    otherwise perform conservative container checks that catch truncated files
    without adding a mandatory runtime dependency.
    """
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is not None:
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
                image.load()
        except Exception:
            raise ConfigError("Reference image is not a decodable PNG/JPEG/WebP file") from None
        if width < 1 or height < 1:
            raise ConfigError("Reference image dimensions must be positive")
        return

    if mime == "image/png":
        if len(data) < 33 or data[12:16] != b"IHDR" or data[-12:-8] != b"IEND":
            raise ConfigError("Reference image is a truncated or invalid PNG")
        width, height = struct.unpack(">II", data[16:24])
        if not width or not height:
            raise ConfigError("Reference image dimensions must be positive")
    elif mime == "image/jpeg":
        if len(data) < 4 or not data.endswith(b"\xff\xd9"):
            raise ConfigError("Reference image is a truncated or invalid JPEG")
    elif mime == "image/webp":
        if len(data) < 12 or int.from_bytes(data[4:8], "little") + 8 > len(data):
            raise ConfigError("Reference image is a truncated or invalid WebP")


def prepare(root: Path, config: dict, workflow_id: str | None, stage_id: str, *,
            job_id: str | None = None, prompt_file: Path | None = None,
            references: list[Path] | None = None) -> dict:
    root = root.resolve()
    wid, workflow = select_workflow(config, workflow_id)
    stage = next((item for item in workflow["stages"] if item["id"] == stage_id), None)
    if not stage or stage["executor"] != "browser":
        raise ConfigError("prepare requires a browser stage; API stages use assets image or jobs run")
    service = config["browser_services"][stage["service"]]
    bundle = None
    # Image handoffs are useful as a small standalone operation. A v3 bundle,
    # when present and valid, contributes only its optional display parameters;
    # video handoffs still require and validate the complete bundle below.
    if stage["operation"] in IMAGE_OPERATIONS:
        if (root / "project.json").is_file():
            try:
                bundle = load_project(root)
            except (ConfigError, OSError):
                bundle = None
    else:
        bundle = load_project(root)
    refs = []
    # The upper bound protects a local packet; it is not a claimed website limit.
    byte_limit = service.get("max_prompt_bytes", 1_000_000)
    requested = ({k: bundle["brief"][k] for k in ("aspect_ratio", "resolution") if k in bundle["brief"]}
                 if bundle else {})
    source = {"input_kind": "project" if bundle else "standalone-image"}
    if bundle:
        source["project_brief_hash"] = content_hash(bundle["brief"])
    if stage["operation"] not in IMAGE_OPERATIONS:
        if prompt_file or not job_id:
            raise ConfigError("Browser video preparation requires --job and the project director plan, not --prompt-file")
        report = validate_plan(bundle, root)
        if not report["ok"]:
            raise ConfigError("Invalid project plan: " + "; ".join(report["errors"]))
        job = next((item for item in bundle["generation-plan"]["jobs"] if item["id"] == job_id), None)
        if not job:
            raise ConfigError("Unknown selected job")
        if job["operation"] != stage["operation"]:
            raise ConfigError("Selected job operation differs from workflow stage; explicitly update the job and its references first")
        compiled = compile_job(bundle, job, max_bytes=byte_limit)
        prompt = compiled["prompt"]
        requested["seconds"] = job["seconds"]
        source.update(job_id=job_id, shot_ids=job["shot_ids"], compiled=compiled)
        for reference in job.get("references", []):
            item = _image_reference(root, reference["path"], reference["role"])
            if item["sha256"] != reference["sha256"]:
                raise ConfigError("Reference changed during preparation")
            refs.append(item)
    else:
        if job_id or not prompt_file:
            raise ConfigError("Browser image preparation requires --prompt-file inside the project, not --job")
        path = within(root, str(prompt_file))
        prompt = path.read_text(encoding="utf-8-sig")
        source["prompt_file"] = path.relative_to(root).as_posix()
        source["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    for reference in references or []:
        item = _image_reference(root, str(reference), "image-input")
        if item["sha256"] not in {ref["sha256"] for ref in refs}:
            refs.append(item)
    source["reference_sha256"] = [ref["sha256"] for ref in refs]
    if not prompt.strip() or len(prompt.encode("utf-8")) > byte_limit:
        raise ConfigError("Prompt is empty or exceeds configured/local packet byte limit; no text was truncated")
    if stage["operation"] in REFERENCE_OPERATIONS and not refs:
        raise ConfigError("This operation needs an actual local reference image; a planned image stage is insufficient")
    if stage["operation"] not in REFERENCE_OPERATIONS and refs:
        raise ConfigError("Text-only operation cannot silently become a reference-image operation")
    checks = ["browser_tools_required", "login_check_required", "generation_capability_unverified",
              "ui_parameters_and_cost_check_required"]
    if not service["enabled"]:
        checks.insert(0, "service_disabled")
    if stage.get("input_from"):
        checks.append("source_stage_output_provenance_check_required")
    packet = {"schema_version": 1, "product": "VideoCreate", "status": "prepared_only", "can_execute": False,
              "workflow": wid, "stage": dict(stage), "service": dict(service), "source": source,
              "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
              "references": refs, "requested_parameters": requested,
              "parameter_support": "unverified", "live_checks_required": checks,
              "budget": dict(config.get("budget", {})), "budget_reserved": False,
              "submission": {"status": "not_submitted", "task_id": None},
              "content_status": "unverified", "network_requests": 0, "paid_creates": 0}
    packet_id = content_hash(packet)
    packet["packet_id"] = packet_id
    destination = within(root, f"browser-handoffs/{wid}/{stage_id}/{packet_id}.json", exists=False)
    if destination.exists():
        if load_json(destination) != packet:
            raise ConfigError("Existing prepared packet differs from its content hash; inspect it before continuing")
    else:
        atomic_json(destination, packet)
    return {"ok": True, "status": "prepared_only", "packet": str(destination), "packet_id": packet_id,
            "can_execute": False, "live_checks_required": checks, "paid_creates": 0, "network_requests": 0}
