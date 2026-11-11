"""Animation CLI: no implicit paid generation during story authoring."""
import argparse
from pathlib import Path
from ..cli import print_result, read_config
from ..config.storage import ConfigError, atomic_json, load_json, user_config_path
from . import examples, pipeline, project, themes


def animation_command(argv):
    parser = argparse.ArgumentParser(prog="videocreate animation")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("themes")
    schema = sub.add_parser("schema")
    schema.add_argument("--output", type=Path)
    init = sub.add_parser("init")
    init.add_argument("project", type=Path)
    init.add_argument("--title", default="未命名动画")
    init.add_argument("--theme", default="lulu-lumei")
    init.add_argument("--theme-file", type=Path)
    series_init = sub.add_parser("series-init")
    series_init.add_argument("project", type=Path)
    series_init.add_argument("--title", default="独立动画短剧")
    series_init.add_argument("--theme", default="lulu-lumei")
    series_init.add_argument("--episodes", type=int, default=20)
    episode = sub.add_parser("episode")
    episode.add_argument("project", type=Path)
    episode.add_argument("--episode", type=int, required=True)
    episode.add_argument("--file", type=Path, required=True, help="Authored animation.authoring.json")
    episode.add_argument("--model")
    episode.add_argument("--binding")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("project", type=Path)
    inspect.add_argument("sources", type=Path, nargs="+")
    inspect.add_argument("--purpose", choices=["story", "character", "art"], default="story")
    inspect.add_argument("--max-frames", type=int, default=16)
    for name in ("study", "adapt"):
        author = sub.add_parser(name)
        author.add_argument("project", type=Path)
        author.add_argument("--file", type=Path, required=True, help="JSON containing study/outline/adaptation; use animation schema")
    for name in ("plan", "example"):
        command = sub.add_parser(name)
        command.add_argument("project", type=Path)
        command.add_argument("--model")
        command.add_argument("--binding")
        if name == "example":
            command.add_argument("--theme", default="lulu-lumei", choices=["lulu-lumei", "cloud-couriers"])
            command.add_argument("--scenario", default="reaction", choices=["reaction", "dialogue", "contact"])
    for name in ("validate", "status"):
        command = sub.add_parser(name)
        command.add_argument("project", type=Path)
    preview = sub.add_parser("preview", help="Locally edit completed pilot shots without changing the full plan")
    preview.add_argument("project", type=Path)
    preview.add_argument("--edit-file", type=Path)
    preview.add_argument("--output-name", default="animation-pilot.mp4")
    frames = sub.add_parser("keyframes")
    frames.add_argument("project", type=Path)
    frames.add_argument("--shot", action="append")
    frames.add_argument("--generate", action="store_true")
    frames.add_argument("--model")
    frames.add_argument("--binding")
    frames.add_argument("--config", type=Path)
    frames.add_argument("--retry", choices=["content", "replan"])
    frames.add_argument("--reason", default="")
    select = sub.add_parser("select")
    select.add_argument("project", type=Path)
    select.add_argument("--shot", required=True)
    select.add_argument("--image", type=Path, required=True)
    select.add_argument("--observation", type=Path, required=True)
    select.add_argument("--include-guidance", action="store_true", help="Only for video bindings with declared additional-image support")
    reference = sub.add_parser("reference")
    reference.add_argument("project", type=Path)
    reference.add_argument("--character", required=True)
    reference.add_argument("--source", type=Path, required=True)
    reference.add_argument("--crop", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    run = sub.add_parser("run")
    run.add_argument("project", type=Path)
    run.add_argument("--stage", choices=["pilot", "full"], default="pilot")
    run.add_argument("--job", action="append")
    run.add_argument("--config", type=Path)
    run.add_argument("--poll-timeout", type=int, default=900)
    run.add_argument("--retry", choices=["network", "content", "replan"])
    run.add_argument("--reason", default="")
    voice = sub.add_parser("voice")
    voice.add_argument("project", type=Path)
    voice.add_argument("--shot", required=True)
    voice.add_argument("--line", type=int, default=0)
    voice.add_argument("--file", type=Path, required=True)
    voice.add_argument("--voice-id")
    voice.add_argument("--reviewer", required=True)
    voice.add_argument("--notes", required=True)
    synthesize = sub.add_parser("synthesize")
    synthesize.add_argument("project", type=Path)
    synthesize.add_argument("--shot", required=True)
    synthesize.add_argument("--line", type=int, default=0)
    synthesize.add_argument("--service-url")
    synthesize.add_argument("--voice-id")
    synthesize.add_argument("--instruct", default="")
    cast = sub.add_parser("voice-cast", help="Configure versioned local preset voices for a project or animation series")
    cast.add_argument("project", type=Path)
    cast.add_argument("--file", type=Path)
    cast.add_argument("--reason", default="")
    cast.add_argument("--check-service", action="store_true")
    library_add = sub.add_parser("library-add", help="Register an interaction from playback-reviewed source footage")
    library_add.add_argument("project", type=Path)
    library_add.add_argument("--library", type=Path, required=True)
    library_add.add_argument("--id", required=True)
    library_add.add_argument("--job", required=True)
    library_add.add_argument("--start", type=float, required=True)
    library_add.add_argument("--end", type=float, required=True)
    library_add.add_argument("--description", required=True)
    library_add.add_argument("--opening-conditions", required=True)
    library_add.add_argument("--contact", action="store_true")
    library_add.add_argument("--output-name", default="preview.mp4", help="Output name used by the existing playback reviews")
    library_list = sub.add_parser("library-list", help="List local interactions and recheck their source reviews")
    library_list.add_argument("project", type=Path)
    review = sub.add_parser("review")
    review.add_argument("project", type=Path)
    review.add_argument("--file", type=Path)
    review.add_argument("--output-name", default="preview.mp4")
    review.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.action == "themes":
        result = {"ok": True, "themes": themes.catalog(), "paid_creates": 0}
    elif args.action == "schema":
        from .schema import animation_schema
        result = {"$schema": "https://json-schema.org/draft/2020-12/schema", **animation_schema()}
        if args.output:
            atomic_json(args.output, result)
            result = {"ok": True, "schema": str(args.output.resolve()), "paid_creates": 0}
    else:
        root = args.project.resolve()
        if args.action == "init":
            result = project.initialize(root, title=args.title, theme=args.theme, theme_file=args.theme_file)
        elif args.action == "series-init":
            from . import series
            result = series.initialize(root, title=args.title, theme=args.theme, episodes=args.episodes)
        elif args.action == "episode":
            from . import series
            result = series.prepare(root, args.episode, args.file.resolve(), model=args.model, binding=args.binding)
        elif args.action == "inspect":
            result = project.inspect(root, args.sources, purpose=args.purpose, max_frames=args.max_frames)
        elif args.action in {"study", "adapt"}:
            result = project.author(root, load_json(args.file))
        elif args.action == "example":
            result = examples.create(root, theme=args.theme, scenario=args.scenario, model=args.model, binding=args.binding)
        elif args.action == "plan":
            result = project.plan(root, model=args.model, binding=args.binding)
        elif args.action == "validate":
            from ..planning.project import load_project, validate_plan
            result = validate_plan(load_project(root), root) if (root / "project.json").exists() else project.validate_document(project.read(root), root, ready=True)
        elif args.action == "status":
            result = pipeline.status(root)
        elif args.action == "preview":
            from . import previews
            result = previews.render(root, edits=load_json(args.edit_file) if args.edit_file else None, output_name=args.output_name)
        elif args.action == "select":
            result = pipeline.select_frame(root, args.shot, args.image.resolve(), load_json(args.observation), include_guidance=args.include_guidance)
        elif args.action == "reference":
            from .references import register
            result = register(root, args.character, args.source.resolve(), crop=args.crop)
        elif args.action == "voice":
            result = pipeline.import_voice(root, args.shot, args.line, args.file.resolve(), voice_id=args.voice_id, reviewer=args.reviewer, notes=args.notes)
        elif args.action == "voice-cast":
            from .voice_cast import configure, describe
            result = configure(root, load_json(args.file), reason=args.reason) if args.file else describe(root, check_service=args.check_service)
        elif args.action in {"library-add", "library-list"}:
            from . import library
            result = library.catalog(root) if args.action == "library-list" else library.add(root, args.library.resolve(),
                item_id=args.id, job_id=args.job, start=args.start, end=args.end, description=args.description,
                opening_conditions=args.opening_conditions, contact=args.contact, output_name=args.output_name)
        elif args.action == "synthesize":
            from .voices import synthesize
            result = synthesize(root, args.shot, args.line, service_url=args.service_url, voice_id=args.voice_id, instruct=args.instruct)
        elif args.action == "review":
            result = pipeline.review(root, load_json(args.file) if args.file else None, output_name=args.output_name)
            if args.output:
                atomic_json(args.output, result.get("template", result))
        else:
            config_path = user_config_path(args.config)
            config = read_config(config_path) if args.action == "run" or args.generate else None
            if args.action == "keyframes":
                result = pipeline.keyframes(root, shot_ids=args.shot, config=config, store_root=config_path.parent,
                    generate=args.generate, model=args.model, binding=args.binding, retry=args.retry, reason=args.reason)
            else:
                result = pipeline.run(root, config, store_root=config_path.parent, stage=args.stage, job_ids=args.job,
                    poll_timeout=args.poll_timeout, retry=args.retry, reason=args.reason)
    print_result(result)
    return int(result.get("ok") is False)
