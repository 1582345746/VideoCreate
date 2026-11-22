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
    parser.add_argument("action", choices=["init", "validate", "audit", "compile", "preview", "route", "schema"])
    parser.add_argument("project", nargs="?", type=Path)
    parser.add_argument("--output", type=Path, help="Output path for plan schema or advisory audit")
    parser.add_argument("--example", choices=["smart-car"])
    from .planning.profiles import FLOWS, PROFILES
    parser.add_argument("--profile", choices=sorted(PROFILES))
    parser.add_argument("--flow", choices=FLOWS, help="Choose one of the six production workflows")
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
        if args.example and (args.profile or args.flow):
            raise ConfigError("Choose the worked example or a production flow/profile")
        if args.flow:
            from .planning.profiles import create_flow
            bundle = create_flow(args.flow, title=args.title, topic=args.topic, seconds=args.seconds,
                                 aspect_ratio=args.aspect_ratio, profile=args.profile)
            args.profile = bundle['brief'].get('workflow_profile')
        elif args.profile:
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
            "next": "Use production import-clip/import-image to register local footage/static holds, then plan validate and timeline render"
                if args.profile=='edit-only' else 'Import local clips and author generated shots/jobs in the same timeline; generation selection applies only to provider jobs'
                if args.profile=='mixed-video' else 'Author generation-plan.image_jobs, then plan validate/compile and production images-run'
                if args.profile in {'image-only','gif-only'} else 'Use production gif-video/gif-frames to create a local GIF without provider configuration'
                if args.profile=='gif-local' else "Author brief/story/director/generation-plan/timeline, then plan validate and plan preview", "paid_creates": 0})
        return 0
    bundle = load_project(root)
    from . import image_production
    if image_production.is_image(bundle) and args.action in {'route','compile','preview'}:
        checked=validate_plan(bundle,root)
        if not checked['ok']:raise ConfigError('; '.join(checked['errors']))
        if args.action=='preview':
            if args.video:raise ConfigError('Pure image/GIF preview uses actual image files; no video cards are generated')
            result=image_production.page(root,bundle)
        else:
            path=user_config_path(args.config)
            result=image_production.compile_plan(root,bundle,read_config(path) if bundle['generation-plan'].get('image_jobs') else {},path.parent,job_ids=args.job,binding_override=args.binding)
        print_result(result);return 0
    if args.action == "audit":
        from .planning.creative_audit import audit
        result = audit(bundle)
        if args.output:
            atomic_json(args.output.resolve(), result)
        print_result(result)
        return 0
    if args.action == "route":
        if bundle['brief'].get('workflow_profile') in {'edit-only','mixed-video'} and not bundle['generation-plan']['jobs']:
            check=validate_plan(bundle,root)
            print_result({**check,'jobs':[],'local_sources':bundle['generation-plan'].get('local_sources',[]),
                'route':'local-editing','provider_configuration_required':False})
            return int(not check['ok'])
        from .routing import recommend
        path = user_config_path(args.config)
        print_result(recommend(bundle, read_config(path), store_root=path.parent, root=root))
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
    if bundle['brief'].get('workflow_profile') in {'edit-only','mixed-video'} and not bundle['generation-plan']['jobs']:
        print_result({'ok':True,'jobs':[],'local_sources':bundle['generation-plan'].get('local_sources',[]),
            'verification':'local-editing-no-generation','paid_creates':0})
        return 0
    path = user_config_path(args.config)
    config = read_config(path)
    from .media_references import selection_request
    from .planning.request_preview import describe_inputs
    from .runtime.budget import estimate_details
    rows = []
    selected_ids = {job["id"] for job in bundle["generation-plan"]["jobs"]}
    if args.job and set(args.job) - selected_ids:
        raise ConfigError("Unknown selected job")
    for job in bundle["generation-plan"]["jobs"]:
        if args.job and job["id"] not in args.job:
            continue
        mid = job.get("model", config["defaults"]["video_model"])
        route = config["routes"].get(mid, {})
        bid = args.binding or job.get("binding_id") or route.get("preferred_binding")
        item = config["bindings"].get(bid)
        if not item or item["model"] != mid:
            raise ConfigError("Compile binding must reference the job's model")
        compiled = compile_job(bundle, job, max_bytes=capabilities(config, item)["max_prompt_bytes"], root=root)
        binding = configured_binding(config, bid)
        inputs = selection_request(root, bundle, job)
        if binding.adapter in {"xingapi-video-v2", "newapi-json-v2"} and job.get("references") and not inputs.get("media_references"):
            raise ConfigError("Version two requires explicit reference kinds; register or attach typed references")
        parameters = {"operation": job["operation"], **inputs}
        request = validate_request(binding, {**parameters, "prompt": compiled["prompt"]})
        if not request["ok"]:
            raise ConfigError(job["id"] + ": " + "; ".join(request["errors"]))
        destination = root / "jobs" / job["id"] / "compiled.preview.json"
        overview = describe_inputs(root, bundle, job, inputs)
        overview["quote"] = estimate_details(binding, job["seconds"], config["budget"]["currency"], parameters=parameters)
        overview["warnings"] = request["warnings"]
        atomic_json(destination, {**compiled, "request_preview": overview, "binding_id": bid, "remote_model": item["remote_model"]})
        rows.append({"job_id": job["id"], "binding_id": bid, "enabled": item["enabled"],
            "remote_model": item["remote_model"], "compiled": str(destination), "utf8_bytes": compiled["utf8_bytes"],
            "request_preview": overview})
    print_result({"ok": True, "jobs": rows, "local_sources":bundle['generation-plan'].get('local_sources',[]),
        "planned_video_jobs": len(rows), "verification": "offline-compiled-only", "paid_creates": 0})
    return 0


def jobs_command(argv: list[str]) -> int:
    from .cli import print_result, read_config
    from .runtime.state import read_state
    from .runtime.budget import summary
    parser = argparse.ArgumentParser(prog="videocreate jobs")
    parser.add_argument("action", choices=["run", "resume", "prepare", "execute", "status", "cancel-local", "resolve", "settle", "candidates", "select"])
    parser.add_argument("project", type=Path)
    parser.add_argument("--job", action="append")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--poll-timeout", type=int, default=900)
    parser.add_argument("--retry", choices=["network", "content", "replan"])
    parser.add_argument("--reason", default="")
    parser.add_argument("--attempt")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument('--binding', help='Explicit one-time binding for selected new attempts')
    parser.add_argument('--model', help='Canonical model; ask for an upstream if ambiguous')
    parser.add_argument('--upstream', help='Upstream instance; ask for a model if ambiguous')
    parser.add_argument('--mode', choices=['run', 'resume', 'content', 'replan'])
    parser.add_argument('--new-requests', type=int)
    parser.add_argument('--token')
    args = parser.parse_args(argv)
    if args.action == 'resume' and (args.binding or args.model or args.upstream or args.retry):
        raise ConfigError('Resume uses original known tasks; omit new routes and retry kinds')
    if args.action not in {'prepare', 'execute'} and any(v is not None for v in (args.mode, args.new_requests, args.token)):
        raise ConfigError('--mode/--new-requests/--token belong to prepare/execute')
    root = args.project.resolve()
    bundle=load_project(root)
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
    if args.action in {'run', 'resume'} and not bundle['generation-plan']['jobs']:
        if args.job or args.binding or args.model or args.upstream or args.retry:
            raise ConfigError('No planned provider video jobs; local sources are not model task IDs')
        check=validate_plan(bundle,root)
        print_result({**check,'jobs':[],'local_sources':bundle['generation-plan'].get('local_sources',[]),
            'provider_configuration_required':False,'budget':summary(read_state(root))})
        return int(not check['ok'])
    config_path = user_config_path(args.config)
    config = read_config(config_path)
    if args.action in {'prepare', 'execute'}:
        from . import generation_actions
        if args.model or args.upstream or args.retry:
            raise ConfigError('Prepare/execute use --mode and exact --binding, or the numbered selection')
        arguments = {'job_ids': args.job, 'mode': args.mode or 'run', 'reason': args.reason,
            'bindings': {jid: args.binding for jid in args.job or []} if args.binding else None,
            'max_new_requests': args.new_requests if args.new_requests is not None else 1, 'poll_timeout': args.poll_timeout}
        if args.action == 'prepare':
            if args.token:
                raise ConfigError('--token is consumed by execute')
            result = generation_actions.preview(root, config_path, **arguments)
        else:
            result = generation_actions.execute(root, config_path, expected_token=args.token, **arguments)
        print_result(result)
        return int(not result.get('ok', False))
    if args.action == "resolve":
        if not args.receipt:
            raise ConfigError("Resolution needs a structured --receipt; absence from logs does not prove non-reception")
        from .runtime.reconcile import reconcile
        print_result(reconcile(root, config, load_json(args.receipt), store_root=config_path.parent))
        return 0
    from .runtime.jobs import generate
    overrides = None
    if args.binding or args.model or args.upstream:
        from .selection import video_overrides
        overrides = video_overrides(root, config, job_ids=args.job, model=args.model,
            upstream=args.upstream, binding=args.binding, store_root=config_path.parent, retry=args.retry)
    def progress(value):
        print(json.dumps(value, ensure_ascii=False), file=sys.stderr, flush=True)
    result = generate(root, config, store_root=config_path.parent, job_ids=args.job,
        poll_timeout=args.poll_timeout, retry=args.retry, reason=args.reason, progress=progress, binding_override=overrides,
        allow_create=args.action != 'resume')
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


def models_command(argv: list[str]) -> int:
    from .cli import print_result, read_config
    from .runtime.health import cooling_down
    parser = argparse.ArgumentParser(prog="videocreate models")
    parser.add_argument("action", choices=["list", "explain-image"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--family")
    parser.add_argument("--model")
    parser.add_argument("--binding")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--reference", type=Path, action="append", default=[])
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", default="auto")
    parser.add_argument("--output-format", default="png", choices=["png", "jpeg", "webp", "gif"])
    args = parser.parse_args(argv)
    path = user_config_path(args.config)
    config = read_config(path)
    if args.action == "explain-image":
        from .assets import _select_image_route
        model, candidates, selection = _select_image_route(config, requested_model=args.model,
            binding_id=args.binding, prompt=args.prompt_file.read_text(encoding="utf-8-sig") if args.prompt_file else "Image route preview",
            references=[p.resolve() for p in args.reference], size=args.size, quality=args.quality,
            output_format=args.output_format, store_root=path.parent)
        print_result({"ok": True, "model": model, "selection": selection,
            "bindings": [{"id": b.id, "upstream": b.upstream_id, "pricing": b.options.get("pricing", "unknown")}
                         for b in candidates], "paid_creates": 0})
        return 0
    families = {}
    for mid, model in config["models"].items():
        if args.family and model["family"] != args.family or args.model and mid != args.model:
            continue
        bindings = []
        for bid, item in config["bindings"].items():
            if item["model"] != mid:
                continue
            upstream = config["upstreams"][item["upstream"]]
            binding = configured_binding(config, bid)
            bindings.append({"id": bid, "platform": upstream.get("platform", "custom"),
                "instance": item["upstream"], "base_url": upstream["base_url"], "adapter": item["adapter"],
                "remote_model": item["remote_model"], "enabled": item["enabled"],
                "setup_status": item.get("setup_status", "configured"), "operations": item["operations"],
                "cooling_down": cooling_down(path.parent, binding), "capabilities": binding.capabilities})
        families.setdefault(model["family"], {}).setdefault(model["kind"], {})[mid] = {
            "display_name": model.get("display_name", mid), "route": config["routes"].get(mid), "bindings": bindings}
    print_result({"ok": True, "families": families, "paid_creates": 0})
    return 0


def timeline_command(argv: list[str]) -> int:
    from .cli import print_result
    from .runtime.state import read_state
    from .timeline.model import mapping, validate_timeline
    from .timeline.render import AUDIO_OUTPUTS, render
    parser = argparse.ArgumentParser(prog="videocreate timeline")
    parser.add_argument("action", choices=["validate", "map", "render"])
    parser.add_argument("project", type=Path)
    parser.add_argument("--output-name", default="preview.mp4")
    parser.add_argument("--events", type=Path, help="Map authored reference and target event windows into the current edit")
    parser.add_argument("--audio-output", choices=AUDIO_OUTPUTS, help="Audio delivery for this local render")
    args = parser.parse_args(argv)
    if args.events and args.action != "map":
        raise ConfigError("--events applies to timeline map")
    if args.audio_output and args.action != "render":
        raise ConfigError("--audio-output applies to timeline render")
    root = args.project.resolve()
    bundle = load_project(root)
    errors = validate_timeline(bundle["timeline"])
    if args.action == "validate" or errors:
        print_result({"ok": not errors, "errors": errors, "paid_creates": 0})
        return int(bool(errors))
    if args.action == "map":
        if args.events:
            from .timeline.events import event_map
            print_result({"ok": True, **event_map(root, bundle, load_json(args.events))})
        else:
            print_result({"ok": True, **mapping(bundle["timeline"]), "paid_creates": 0})
        return 0
    print_result(render(root, bundle, read_state(root), output_name=args.output_name, audio_output=args.audio_output))
    return 0


def review_command(argv: list[str]) -> int:
    from .cli import print_result
    from .runtime.state import read_state
    from .review.receipts import apply, inbox, review_image, summary, template
    parser = argparse.ArgumentParser(prog="videocreate review")
    parser.add_argument("action", choices=["template", "apply", "status", "packet", "inbox", "image", "gif", "page", "compare", "compare-apply"])
    parser.add_argument("project", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--output-name", default="preview.mp4")
    comparison_inputs = parser.add_mutually_exclusive_group()
    comparison_inputs.add_argument("--spec", type=Path, help="Versioned event comparison with source and candidate intervals")
    comparison_inputs.add_argument("--events", type=Path, help="Compare mapped source events to the verified final edit")
    parser.add_argument("--pending-only", action="store_true")
    parser.add_argument("--job")
    parser.add_argument("--gif")
    parser.add_argument("--status", choices=["pass", "fail"])
    parser.add_argument("--reviewer")
    parser.add_argument("--observation")
    parser.add_argument("--temporal-observation", action="store_true", help="Reviewer observed full animation playback")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    from . import image_production
    if args.events and args.action not in {'compare', 'compare-apply'}:
        raise ConfigError('--events applies to review compare and compare-apply')
    if args.action == 'inbox':
        result=inbox(root, pending_only=args.pending_only)
        bundle=load_project(root) if (root/'project.json').is_file() else None
        if bundle and image_production.is_image(bundle):
            from . import local_gifs
            result['local_gifs']=[r for r in local_gifs.rows(root,bundle) if not args.pending_only or r['content_status']!='reviewed']
        print_result(result)
        return 0
    bundle = load_project(root)
    if args.action in {'compare', 'compare-apply'}:
        from .review.comparison import export_comparison, record_observations
        if not args.spec and not args.events:
            raise ConfigError('Event comparison requires --spec or --events')
        spec = load_json(args.spec or args.events)
        options = {'mapped': bool(args.events), 'output_name': args.output_name}
        if args.action == 'compare-apply':
            if not args.receipt:
                raise ConfigError('Import event observations with --receipt')
            result = record_observations(root, bundle, spec, load_json(args.receipt), **options)
        else:
            result = export_comparison(root, bundle, spec, **options)
        print_result(result)
        return 0
    if image_production.is_image(bundle) and args.action in {'template','apply','packet'}:
        raise ConfigError('Pure image/GIF review uses review page/inbox/image/status; video-layer receipts do not apply')
    if args.action == "packet":
        from .review.packet import packet
        print_result(packet(root, bundle, output_name=args.output_name))
    elif args.action == 'gif':
        from . import local_gifs
        if not args.gif or not args.status or not args.reviewer or not args.observation:
            raise ConfigError('Local GIF review needs --gif, --status, --reviewer and --observation')
        print_result(local_gifs.review(root,gif_id=args.gif,status=args.status,reviewer_id=args.reviewer,
            observation=args.observation,temporal_observation=args.temporal_observation))
    elif args.action == "image":
        if not args.job or not args.status or not args.reviewer or not args.observation:
            raise ConfigError("Image review needs --job, --status, --reviewer and --observation")
        print_result(review_image(root, job_id=args.job, status=args.status,
            reviewer_id=args.reviewer, observation=args.observation, temporal_observation=args.temporal_observation))
    elif args.action == 'page':
        from . import image_production
        if image_production.is_image(bundle):
            print_result(image_production.page(root,bundle))
        else:
            from .review.page import export
            print_result(export(root, output_name=args.output_name))
    elif args.action == "template":
        path = root / "reviews" / "content-review.template.json"
        atomic_json(path, template(root, bundle, output_name=args.output_name))
        print_result({"ok": True, "template": str(path), "status": "unverified"})
    elif args.action == "apply":
        if not args.receipt:
            raise ConfigError("--receipt required")
        print_result(apply(root, bundle, load_json(args.receipt)))
    else:
        from . import image_production
        if image_production.is_image(bundle):
            from . import local_gifs
            print_result({'ok':True,**image_production.review_summary([*image_production.rows(root,bundle,read_state(root)),*local_gifs.rows(root,bundle)])})
        else:
            print_result({"ok": True, **summary(root, bundle, output_name=args.output_name)})
    return 0


def assets_command(argv: list[str]) -> int:
    from .cli import print_result, read_config
    from .assets import generate_image, generate_images, register, recover_image, reprocess_image
    parser = argparse.ArgumentParser(prog="videocreate assets")
    parser.add_argument("action", choices=["register", "stage-reference", "board", "image", "batch", "recover", "reprocess", "handoff"])
    parser.add_argument("project", type=Path)
    parser.add_argument("--asset-id")
    parser.add_argument("--asset-kind",choices=['character','scene','prop','voice'])
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
    parser.add_argument("--model", help="Canonical image model; defaults to config.defaults.image_model")
    parser.add_argument("--output-format", choices=["png", "jpeg", "webp", "gif"], default="png")
    parser.add_argument("--retry", choices=["content", "replan"])
    parser.add_argument("--reason", default="")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    root = args.project.resolve()
    load_project(root)
    if args.action=='stage-reference':
        if not args.source or not args.asset_kind:raise ConfigError('Reference staging needs --source and --asset-kind')
        from .project_assets import stage_reference
        print_result(stage_reference(root,args.source,kind=args.asset_kind))
    elif args.action=='board':
        if not args.asset_id:raise ConfigError('Comparison board needs --asset-id')
        from .project_assets import board
        print_result(board(root,args.asset_id))
    elif args.action == "handoff":
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
        path = user_config_path(args.config)
        result = reprocess_image(root, args.job_id,
            config=read_config(path) if args.config or path.is_file() else None, store_root=path.parent)
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
        result = generate_images(root, read_config(path), store_root=path.parent, items=prepared_items)
        print_result(result)
        return int(not result.get("ok", False))
    else:
        if not args.job_id or not args.prompt_file:
            raise ConfigError("Image generation requires --job-id and --prompt-file")
        path = user_config_path(args.config)
        print_result(generate_image(root, read_config(path), store_root=path.parent,
            job_id=args.job_id, prompt=args.prompt_file.read_text(encoding="utf-8-sig"),
            references=[(root / p).resolve() for p in args.reference], binding_id=args.binding, size=args.size,
            quality=args.quality, output_format=args.output_format, model=args.model,
            retry=args.retry, reason=args.reason))
    return 0


def media_command(argv: list[str]) -> int:
    from .cli import print_result
    from .media.gif import export_video_to_gif, export_frames_to_gif, extract_frame, probe_image
    parser = argparse.ArgumentParser(prog="videocreate media")
    parser.add_argument("action", choices=["inspect", "export-gif", "frames-gif", "extract-frame"])
    parser.add_argument("target", type=Path, help="Image path for inspect; v3 project directory for export-gif")
    parser.add_argument("--source", type=Path, help="Source video for export-gif")
    parser.add_argument("--job-id", help="Unique generated-media ID for export-gif")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--duration", type=float, default=3)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--loop", type=int, default=0, help="0 loops forever; -1 plays once")
    parser.add_argument("--frame", action="append", type=Path, default=[], help="Ordered static frame for frames-gif")
    parser.add_argument("--at", type=float, default=0, help="Timestamp for explicit still-frame extraction")
    args = parser.parse_args(argv)
    if args.action == "inspect":
        print_result({"ok": True, **probe_image(args.target.resolve()), "paid_creates": 0})
        return 0
    root = args.target.resolve()
    load_project(root)
    if not args.job_id:
        raise ConfigError("Media conversion requires --job-id")
    if args.action == "frames-gif":
        print_result(export_frames_to_gif(root, frames=[p.resolve() for p in args.frame], job_id=args.job_id,
            fps=args.fps, width=args.width, loop=args.loop))
        return 0
    if not args.source:
        raise ConfigError("Media conversion requires --source")
    if args.action == "extract-frame":
        print_result(extract_frame(root, source=args.source.resolve(), job_id=args.job_id, at=args.at))
        return 0
    print_result(export_video_to_gif(root, source=args.source.resolve(), job_id=args.job_id,
        start=args.start, duration=args.duration, fps=args.fps, width=args.width, loop=args.loop))
    return 0
