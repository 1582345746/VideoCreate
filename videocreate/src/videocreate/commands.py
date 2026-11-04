from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog.bindings import Binding, capabilities, configured_binding, route_bindings, validate_request
from .config.storage import ConfigError, atomic_json, load_json, user_config_path
from .planning.project import LAYERS, compile_job, load_project, save_bundle, validate_plan
from .planning.schema import plan_schema


def workflow_command(argv: list[str]) -> int:
    from .cli import print_result, read_config
    from .workflows import describe, prepare
    parser = argparse.ArgumentParser(prog="videocreate workflow")
    parser.add_argument("action", choices=["list", "describe", "prepare"])
    parser.add_argument("project", nargs="?", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--workflow")
    parser.add_argument("--stage")
    parser.add_argument("--job")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--reference", action="append", type=Path, default=[])
    args = parser.parse_args(argv)
    config = read_config(user_config_path(args.config))
    if args.action == "list":
        print_result({"ok": True, "default": config["defaults"].get("workflow"),
            "workflows": [{"id": key, "description": value.get("description", ""), "stages": len(value["stages"])}
                          for key, value in config.get("workflows", {}).items()], "paid_creates": 0})
    elif args.action == "describe":
        print_result(describe(config, args.workflow))
    else:
        if not args.project or not args.stage:
            raise ConfigError("Prepare requires PROJECT and --stage")
        print_result(prepare(args.project, config, args.workflow, args.stage, job_id=args.job,
                             prompt_file=args.prompt_file, references=args.reference))
    return 0


def plan_command(argv: list[str]) -> int:
    from .cli import print_result, read_config
    parser = argparse.ArgumentParser(prog="videocreate plan")
    parser.add_argument("action", choices=["init", "validate", "compile", "preview", "route", "schema"])
    parser.add_argument("project", nargs="?", type=Path)
    parser.add_argument("--output", type=Path, help="Output path for `plan schema`")
    parser.add_argument("--example", choices=["smart-car"])
    parser.add_argument("--profile", choices=["portrait", "action-insert", "scenic", "explainer", "series-episode"])
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--topic", default="")
    parser.add_argument("--aspect-ratio", choices=["16:9", "9:16"], default="16:9")
    parser.add_argument("--title", default="未命名视频")
    parser.add_argument("--intent", choices=["narrative", "demonstration", "montage", "single-shot"], default="narrative")
    parser.add_argument("--pace", choices=["comedy", "dialogue", "slow-cinema", "suspense", "product-demo", "action"], default="comedy")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--binding")
    parser.add_argument("--job", action="append")
    parser.add_argument("--video", action="store_true", help="Render local text storyboard cards to MP4; no model calls")
    args = parser.parse_args(argv)
    if args.action == "schema":
        if not args.output:
            raise ConfigError("plan schema requires --output")
        destination = args.output.resolve()
        atomic_json(destination, plan_schema())
        print_result({"ok": True, "schema": str(destination), "paid_creates": 0})
        return 0
    if not args.project:
        raise ConfigError("This plan action requires PROJECT")
    root = args.project.resolve()
    if args.action == "init":
        from .planning.examples import smart_car
        bundle = smart_car()
        if args.example and args.profile:
            raise ConfigError("Choose either --example or --profile")
        if args.profile:
            from .planning.profiles import create
            bundle = create(args.profile, title=args.title, seconds=args.seconds, topic=args.topic, aspect_ratio=args.aspect_ratio)
        elif not args.example:
            bundle["project"]["title"] = args.title
            bundle["brief"].update(intent=args.intent, pace_profile=args.pace)
            bundle["brief"].pop("product", None)
            bundle["story"] = {"logline": "", "goal": "", "obstacle": "", "choice": "", "consequence": "", "initial_state": {}, "beats": []}
            bundle["director"] = {"assets": [], "scenes": [], "shots": []}
            bundle["generation-plan"]["jobs"] = []
            for key in ("clips", "segments", "audio_tracks", "subtitles"):
                bundle["timeline"][key] = []
        save_bundle(root, bundle)
        print_result({"ok": True, "project": str(root / "project.json"), "status": "draft_plan",
            "next": "Author brief/story/director/generation-plan/timeline, then plan validate and plan preview", "paid_creates": 0})
        return 0
    bundle = load_project(root)
    if args.action == "route":
        from .routing import recommend
        path = user_config_path(args.config)
        print_result(recommend(bundle, read_config(path), store_root=path.parent))
        return 0
    report = validate_plan(bundle, root)
    if args.action == "validate":
        print_result(report)
        return int(not report["ok"])
    if not report["ok"]:
        print_result(report)
        return 1
    if args.action == "preview":
        from .planning.preview import preview
        print_result(preview(root, bundle, video=args.video))
        return 0
    path = user_config_path(args.config)
    config = read_config(path)
    rows = []
    for job in bundle["generation-plan"]["jobs"]:
        if args.job and job["id"] not in args.job:
            continue
        mid = job.get("model", config["defaults"]["video_model"])
        bid = args.binding or job.get("binding_id") or config["routes"][mid]["preferred_binding"]
        item = config["bindings"].get(bid)
        if not item or item["model"] != mid:
            raise ConfigError("Compile binding must reference the job's model")
        compiled = compile_job(bundle, job, max_bytes=capabilities(config, item)["max_prompt_bytes"], root=root)
        binding = configured_binding(config, bid)
        shots = [shot for shot in bundle["director"]["shots"] if shot["id"] in job["shot_ids"]]
        references = job.get("references", [])
        request = validate_request(binding, {"operation": job["operation"], "prompt": compiled["prompt"],
            "seconds": job["seconds"], "resolution": bundle["brief"]["resolution"],
            "aspect_ratio": bundle["brief"]["aspect_ratio"],
            "generate_audio": any(shot.get("audio", {}).get("mode", "ambience") in {"native-dialogue", "offscreen", "ambience"} for shot in shots),
            "primary_reference": object() if any(ref["role"] == "opening-frame" for ref in references) else None,
            "reference_images": [object() for ref in references if ref["role"] != "opening-frame"]})
        if not request["ok"]:
            raise ConfigError(job["id"] + ": " + "; ".join(request["errors"]))
        destination = root / "jobs" / job["id"] / "compiled.preview.json"
        atomic_json(destination, compiled)
        rows.append({"job_id": job["id"], "binding_id": bid, "enabled": item["enabled"],
            "remote_model": item["remote_model"], "compiled": str(destination), "utf8_bytes": compiled["utf8_bytes"]})
    if args.job and set(args.job) - {row["job_id"] for row in rows}:
        raise ConfigError("Unknown selected job")
    print_result({"ok": True, "jobs": rows, "verification": "offline-compiled-only", "paid_creates": 0})
    return 0


def jobs_command(argv: list[str]) -> int:
    from .cli import print_result, read_config
    from .runtime.state import read_state
    from .runtime.budget import summary
    parser = argparse.ArgumentParser(prog="videocreate jobs")
    parser.add_argument("action", choices=["run", "status", "cancel-local", "resolve", "settle", "candidates", "select"])
    parser.add_argument("project", type=Path)
    parser.add_argument("--job", action="append")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--poll-timeout", type=int, default=900)
    parser.add_argument("--retry", choices=["network", "content", "replan"])
    parser.add_argument("--reason", default="")
    parser.add_argument("--attempt")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    root = args.project.resolve()
    load_project(root)
    if args.action in {"candidates", "select"}:
        from .runtime.candidates import list_candidates, select
        if args.action == "select":
            if not args.job or len(args.job) != 1 or not args.attempt:
                raise ConfigError("Select requires one --job and --attempt, plus --reason")
            result = select(root, args.job[0], args.attempt, args.reason)
        else:
            if args.job and len(args.job) != 1:
                raise ConfigError("List candidates for one --job or omit it for all jobs")
            result = list_candidates(root, args.job[0] if args.job else None)
        print_result(result)
        return 0
    if args.action == "settle":
        if not args.receipt:
            raise ConfigError("Settlement requires a billing --receipt and actual upstream evidence")
        from .runtime.settlement import settle
        print_result(settle(root, load_json(args.receipt)))
        return 0
    if args.action == "status":
        state = read_state(root)
        # Request snapshots are already credential-free, but avoid dumping long prompts.
        print_result({"ok": True, "jobs": {jid: {k: rec.get(k) for k in ("status", "task_id", "attempt_id", "artifact", "content_status", "error")}
            for jid, rec in state["jobs"].items()}, "budget": summary(state), "paid_creates": 0})
        return 0
    if args.action == "cancel-local":
        print_result({"ok": True, "status": "local_stop_requested", "remote_cancellation": "unsupported",
            "note": "Stop the running local command to stop polling. Remote tasks may continue and bill; their IDs are retained.", "paid_creates": 0})
        return 0
    if args.poll_timeout <= 0:
        raise ConfigError("poll timeout must be positive")
    config_path = user_config_path(args.config)
    config = read_config(config_path, ready=True)
    if args.action == "resolve":
        if not args.receipt:
            raise ConfigError("Resolution needs a structured --receipt; absence from logs does not prove non-reception")
        from .runtime.reconcile import reconcile
        print_result(reconcile(root, config, load_json(args.receipt), store_root=config_path.parent))
        return 0
    from .runtime.jobs import generate
    def progress(value):
        print(json.dumps(value, ensure_ascii=False), file=sys.stderr, flush=True)
    result = generate(root, config, store_root=config_path.parent, job_ids=args.job,
        poll_timeout=args.poll_timeout, retry=args.retry, reason=args.reason, progress=progress)
    print_result(result)
    return int(not result.get("ok", False))


def capabilities_command(argv: list[str]) -> int:
    from .cli import print_result, read_config
    from .catalog.bindings import configured_binding
    from .catalog.evidence import record, status
    parser = argparse.ArgumentParser(prog="videocreate capabilities")
    parser.add_argument("action", choices=["status", "record"])
    parser.add_argument("--binding", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    path = user_config_path(args.config)
    binding = configured_binding(read_config(path), args.binding)
    if args.action == "record":
        if not args.receipt:
            raise ConfigError("Record needs a structured --receipt")
        print_result(record(path.parent, binding, load_json(args.receipt)))
    else:
        print_result({"ok": True, **status(path.parent, binding), "paid_creates": 0})
    return 0


def timeline_command(argv: list[str]) -> int:
    from .cli import print_result
    from .runtime.state import read_state
    from .timeline.model import mapping, validate_timeline
    parser = argparse.ArgumentParser(prog="videocreate timeline")
    parser.add_argument("action", choices=["validate", "map", "render"])
    parser.add_argument("project", type=Path)
    parser.add_argument("--output-name", default="preview.mp4")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    bundle = load_project(root)
    errors = validate_timeline(bundle["timeline"])
    if args.action == "validate" or errors:
        print_result({"ok": not errors, "errors": errors, "paid_creates": 0})
        return int(bool(errors))
    if args.action == "map":
        print_result({"ok": True, **mapping(bundle["timeline"]), "paid_creates": 0})
        return 0
    from .timeline.render import render
    print_result(render(root, bundle, read_state(root), output_name=args.output_name))
    return 0


def review_command(argv: list[str]) -> int:
    from .cli import print_result
    from .review.receipts import apply, inbox, review_image, summary, template
    parser = argparse.ArgumentParser(prog="videocreate review")
    parser.add_argument("action", choices=["template", "apply", "status", "packet", "inbox", "image"])
    parser.add_argument("project", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--output-name", default="preview.mp4")
    parser.add_argument("--pending-only", action="store_true")
    parser.add_argument("--job")
    parser.add_argument("--status", choices=["pass", "fail"])
    parser.add_argument("--reviewer")
    parser.add_argument("--observation")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    if args.action == "inbox":
        print_result(inbox(root, pending_only=args.pending_only))
        return 0
    bundle = load_project(root)
    if args.action == "packet":
        from .review.packet import packet
        print_result(packet(root, bundle, output_name=args.output_name))
    elif args.action == "image":
        if not args.job or not args.status or not args.reviewer or not args.observation:
            raise ConfigError("Image review needs --job, --status, --reviewer and --observation")
        print_result(review_image(root, job_id=args.job, status=args.status,
            reviewer_id=args.reviewer, observation=args.observation))
    elif args.action == "template":
        path = root / "reviews" / "content-review.template.json"
        atomic_json(path, template(root, bundle, output_name=args.output_name))
        print_result({"ok": True, "template": str(path), "status": "unverified"})
    elif args.action == "apply":
        if not args.receipt:
            raise ConfigError("--receipt required")
        print_result(apply(root, bundle, load_json(args.receipt)))
    else:
        print_result({"ok": True, **summary(root, bundle, output_name=args.output_name)})
    return 0


def assets_command(argv: list[str]) -> int:
    from .cli import print_result, read_config
    from .assets import generate_image, generate_images, register, recover_image, reprocess_image
    parser = argparse.ArgumentParser(prog="videocreate assets")
    parser.add_argument("action", choices=["register", "image", "batch", "recover", "reprocess", "handoff"])
    parser.add_argument("project", type=Path)
    parser.add_argument("--asset-id")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--job-id")
    parser.add_argument("--at", type=float)
    parser.add_argument("--next-job")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--reference", action="append", type=Path, default=[])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--binding")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", default="auto")
    parser.add_argument("--retry", choices=["content", "replan"])
    parser.add_argument("--reason", default="")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    root = args.project.resolve()
    load_project(root)
    if args.action == "handoff":
        from .runtime.candidates import handoff
        if not args.job_id or args.at is None:
            raise ConfigError("Handoff requires --job-id and --at source timestamp")
        print_result(handoff(root, args.job_id, args.at, next_job=args.next_job))
    elif args.action == "register":
        if not args.asset_id or not args.source:
            raise ConfigError("Register requires --asset-id and --source")
        print_result(register(root, args.asset_id, args.source))
    elif args.action == "reprocess":
        if not args.job_id:
            raise ConfigError("Image reprocessing requires --job-id")
        result = reprocess_image(root, args.job_id)
        print_result(result)
        return int(not result.get("ok", False))
    elif args.action == "recover":
        if not args.job_id or not args.source or not args.receipt:
            raise ConfigError("Image recovery requires --job-id, --source and --receipt")
        print_result(recover_image(root, args.job_id, args.source.resolve(), load_json(args.receipt)))
    elif args.action == "batch":
        if not args.manifest:
            raise ConfigError("Image batch requires --manifest")
        manifest = load_json(args.manifest)
        items = manifest.get("images")
        if not isinstance(items, list):
            raise ConfigError("Image batch manifest must be an object with an images list")
        prepared_items = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("references", []), list):
                raise ConfigError("Each image manifest entry must contain references as a list")
            references = [(root / Path(reference)).resolve() for reference in item.get("references", [])]
            prepared_items.append({**item, "references": references})
        path = user_config_path(args.config)
        result = generate_images(root, read_config(path, ready=True), store_root=path.parent, items=prepared_items)
        print_result(result)
        return int(not result.get("ok", False))
    else:
        if not args.job_id or not args.prompt_file:
            raise ConfigError("Image generation requires --job-id and --prompt-file")
        path = user_config_path(args.config)
        print_result(generate_image(root, read_config(path, ready=True), store_root=path.parent,
            job_id=args.job_id, prompt=args.prompt_file.read_text(encoding="utf-8-sig"),
            references=[(root / p).resolve() for p in args.reference], binding_id=args.binding, size=args.size,
            quality=args.quality, retry=args.retry, reason=args.reason))
    return 0
