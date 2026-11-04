from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config.schema import configuration_schema, validate_config
from .config.storage import ConfigError, atomic_json, load_json, redact_config, user_config_path


def skill_root() -> Path:
    packaged = Path(__file__).resolve().parent / "_skill"
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[2]


def print_result(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def read_config(path: Path, *, ready: bool = False) -> dict[str, Any]:
    config = load_json(path)
    errors = validate_config(config, ready=ready, store_root=path.parent)
    if errors:
        raise ConfigError("; ".join(errors))
    return config


def configuration_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="videocreate config")
    parser.add_argument("action", choices=["init", "open", "validate", "show", "effective", "schema", "migrate", "migrate-project", "import"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--redacted", action="store_true", help="Output is always redacted")
    parser.add_argument("--ready", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace", action="store_true", help="Explicitly replace configuration on stdin import")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--job")
    parser.add_argument("--binding")
    args = parser.parse_args(argv)
    path = user_config_path(args.config)
    if args.action == "migrate-project":
        if not args.project:
            raise ConfigError("Legacy project adoption requires --project")
        from .migrations.project_v2 import adopt
        print_result(adopt(args.project, apply=args.apply))
        return 0
    if args.action == "import":
        import tempfile
        if path.exists() and not args.replace:
            raise ConfigError("Configuration already exists; --replace is required to import a replacement")
        # Use the same duplicate-key/NaN/JSON diagnostics as file editing.
        with tempfile.TemporaryDirectory(prefix="videocreate-private-import-") as temp:
            temporary = Path(temp) / "config.json"
            fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(sys.stdin.read())
            config = read_config(temporary)
        atomic_json(path, config)
        print_result({"ok": True, "config": str(path), "credential_values": "never-printed", "network_requests": 0})
        return 0
    if args.action == "schema":
        print_result(configuration_schema())
        return 0
    if args.action == "migrate":
        from .migrations.config_v2 import migrate_config
        print_result({"ok": True, **migrate_config(args.source, args.destination, apply=args.apply)})
        return 0
    if args.action == "init":
        if path.exists():
            print_result({"ok": True, "created": False, "config": str(path), "preserved": True})
            return 0
        template = load_json(skill_root() / "assets/config/videocreate.config.example.json")
        schema_path = path.parent / "videocreate.config.schema.json"
        template["$schema"] = str(schema_path)
        atomic_json(schema_path, configuration_schema())
        atomic_json(path, template)
        print_result({"ok": True, "created": True, "config": str(path), "status": "setup_required",
                      "next": "Fill upstream URL/auth, exact remote_model, enable bindings, then run config validate --ready"})
        return 0
    if args.action == "open":
        if not path.is_file():
            raise ConfigError("Configuration does not exist; run config init")
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print_result({"ok": True, "config": str(path)})
        return 0
    config = load_json(path)
    errors = validate_config(config, ready=args.ready, store_root=path.parent)
    if args.action == "effective":
        if errors:
            raise ConfigError("; ".join(errors))
        from .config.effective import effective
        from .planning.project import load_project
        if args.job and not args.project:
            raise ConfigError("--job requires --project")
        print_result(effective(config, path, bundle=load_project(args.project.resolve()) if args.project else None,
                               job_id=args.job, binding_id=args.binding))
    elif args.action == "show":
        print_result({"ok": not errors, "config": str(path), "values": redact_config(config), "errors": errors})
    else:
        print_result({"ok": not errors, "config": str(path), "errors": errors, "network_requests": 0})
    return int(bool(errors))


def doctor_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="videocreate doctor")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--read-only", action="store_true", help="Query provider model catalogs; never creates media")
    args = parser.parse_args(argv)
    path = user_config_path(args.config)
    config = read_config(path)
    import shutil
    from .catalog.bindings import ADAPTER_ALIASES
    from .config.storage import resolve_key, safe_error
    rows = []
    for bid, binding in config["bindings"].items():
        upstream = config["upstreams"][binding["upstream"]]
        key = resolve_key(upstream["auth"], store_root=path.parent)
        row = {"binding": bid, "enabled": binding["enabled"], "model": binding["model"],
               "adapter": binding["adapter"], "credential_available": bool(key), "status": "configured"}
        if not binding["enabled"]:
            row["status"] = "disabled"
        elif not key:
            row["status"] = "setup_required"
        elif args.read_only:
            try:
                engine = legacy_engine()
                if config["models"][binding["model"]]["kind"] == "image":
                    client = engine.Sub2ApiImageClient(upstream["base_url"], key, binding["remote_model"])
                else:
                    from .config.bridge import engine_settings
                    client = engine.select_video_client(engine_settings(config, store_root=path.parent), bid, model=binding["model"])
                models = client.list_models()
                seen = binding["remote_model"] in models
                row["status"] = "catalog_seen" if seen else "catalog_not_seen"
                from .catalog.bindings import configured_binding
                from .catalog.evidence import record
                import hashlib
                import uuid
                evidence_path = path.parent / "binding-evidence" / "catalog-responses" / (uuid.uuid4().hex + ".json")
                atomic_json(evidence_path, {"binding": bid, "models": models, "paid_creates": 0})
                snapshot = configured_binding(config, bid)
                row["catalog_receipt"] = record(path.parent, snapshot, {
                    "stage": "catalog", "result": "pass" if seen else "fail",
                    "binding_fingerprint": snapshot.snapshot()["fingerprint"], "operation": binding["operations"][0],
                    "reviewer_id": "videocreate-doctor", "method": "read-only-model-list", "checks": {"exact_remote_model_seen": seen},
                    "evidence": [{"path": str(evidence_path), "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest()}]})["receipt"]
            except Exception as error:
                row.update(status="read_only_check_failed", error=safe_error(error, [key]))
        rows.append(row)
    setup_errors = validate_config(config, ready=True, store_root=path.parent)
    print_result({"ok": not setup_errors, "status": "setup_required" if setup_errors else "ready_for_authorized_attempt",
                  "config": str(path), "setup_errors": setup_errors, "version": __version__, "ffmpeg": bool(shutil.which("ffmpeg")),
                  "ffprobe": bool(shutil.which("ffprobe")), "bindings": rows, "paid_creates": 0,
                  "note": "Catalog presence does not verify generation, reference semantics or output quality"})
    return int(bool(setup_errors))


def legacy_engine():
    scripts = skill_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import videocreate_engine
    return videocreate_engine


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if not argv or argv in (["--help"], ["-h"]):
            print("VideoCreate " + __version__ + "\n\n"
                  "Commands: config, doctor, capabilities, workflow, plan, assets, jobs, timeline, review, reference, education, series, version\n"
                  "Start: config init; config open; config validate --ready\n"
                  "Offline preview: plan init PROJECT --example smart-car; plan preview PROJECT --video\n"
                  "Each command accepts --help. Existing project commands remain available; use legacy COMMAND to select the retained engine explicitly.")
            return 0
        if argv[0] == "legacy":
            return legacy_engine().main(argv[1:])
        if argv and argv[0] == "version":
            print_result({"ok": True, "product": "VideoCreate", "version": __version__})
            return 0
        if argv and argv[0] == "config":
            return configuration_command(argv[1:])
        if argv and argv[0] in {"reference", "education", "series"}:
            from . import production_commands
            return getattr(production_commands, argv[0] + "_command")(argv[1:])
        if argv and argv[0] in {"plan", "jobs", "timeline", "review", "assets", "capabilities", "workflow"}:
            from . import commands
            return getattr(commands, argv[0] + "_command")(argv[1:])
        if argv and argv[0] == "doctor":
            if not user_config_path().exists() and "--config" not in argv:
                print_result({"ok": False, "status": "setup_required", "config": str(user_config_path()),
                              "next": "Run config init, then edit the returned JSON file", "paid_creates": 0})
                return 1
            return doctor_command(argv[1:])
        engine = legacy_engine()
        return engine.main(argv)
    except (ConfigError, OSError, ValueError) as error:
        from .config.storage import safe_error
        print_result({"ok": False, "error": safe_error(error)})
        return 1
