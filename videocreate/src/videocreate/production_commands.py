"""Production authoring entry points; no implicit network or generation requests."""
import argparse
from pathlib import Path
from .config.storage import ConfigError, load_json
from .cli import print_result


def reference_command(argv):
    from . import references
    parser = argparse.ArgumentParser(prog="videocreate reference")
    sub = parser.add_subparsers(dest="action", required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("source", type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    analyze.add_argument("--max-frames", type=int, default=24)
    analyze.add_argument("--crop", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"),
                         help="Analyze an observed content rectangle in source pixels; preserve original source")
    profile = sub.add_parser("profile")
    profile.add_argument("report", type=Path)
    profile.add_argument("--observations", type=Path)
    attach = sub.add_parser("attach")
    attach.add_argument("project", type=Path)
    attach.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.action == "analyze":
        result = references.analyze(args.source.resolve(), args.output.resolve(), max_frames=args.max_frames, crop=args.crop)
    elif args.action == "profile":
        result = references.profile(args.report.resolve(), load_json(args.observations) if args.observations else None)
    else:
        result = references.attach(args.project.resolve(), args.profile.resolve())
    print_result(result)
    return 0


def education_command(argv):
    from . import education
    from .planning.project import load_project
    parser = argparse.ArgumentParser(prog="videocreate education")
    sub = parser.add_subparsers(dest="action", required=True)
    source = sub.add_parser("source")
    source.add_argument("project", type=Path)
    for key in ("source-id", "url", "title", "publisher"):
        source.add_argument("--" + key, required=True)
    source.add_argument("--file", required=True, type=Path)
    validate = sub.add_parser("validate")
    validate.add_argument("project", type=Path)
    validate.add_argument("--ready", action="store_true")
    export = sub.add_parser("export")
    export.add_argument("project", type=Path)
    export.add_argument("--apply", action="store_true")
    narration = sub.add_parser("narration")
    narration.add_argument("project", type=Path)
    narration.add_argument("--file", required=True, type=Path)
    drawing = sub.add_parser("map")
    drawing.add_argument("source", type=Path)
    drawing.add_argument("--output", required=True, type=Path)
    drawing.add_argument("--source-url", required=True)
    args = parser.parse_args(argv)
    if args.action == "map":
        result = education.draw_map(args.source.resolve(), args.output.resolve(), source_url=args.source_url)
    else:
        root = args.project.resolve()
        if args.action == "source":
            result = education.add_source(root, args.source_id, args.file.resolve(), url=args.url, title=args.title, publisher=args.publisher)
        elif args.action == "validate":
            result = education.validate_research(load_project(root), root=root, ready=args.ready)
        elif args.action == "export":
            result = education.export(root, apply=args.apply)
        else:
            result = education.import_narration(root, args.file.resolve())
    print_result(result)
    return int(not result["ok"])


def series_command(argv):
    from . import series
    parser = argparse.ArgumentParser(prog="videocreate series")
    parser.add_argument("action", choices=["init", "prepare", "check", "accept"])
    parser.add_argument("project", type=Path, help="Series root, or episode root for check")
    parser.add_argument("--title", default="未命名系列")
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--mode", choices=["serial", "independent"], default="serial")
    parser.add_argument("--episode", type=int)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--output-name", default="preview.mp4")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    if args.action == "init":
        result = series.initialize(root, args.title, args.episodes, mode=args.mode)
    elif args.action == "check":
        from .planning.project import load_project
        series.check_episode_context(root, load_project(root))
        result = {"ok": True, "paid_creates": 0, "content": "not_reviewed_by_context_check"}
    else:
        if not args.episode or (args.action == "accept" and not args.observation):
            raise ConfigError("Requires --episode, and --observation for accept")
        result = series.prepare(root, args.episode, args.seconds) if args.action == "prepare" else series.accept(root, args.episode, load_json(args.observation), args.output_name)
    print_result(result)
    return 0
