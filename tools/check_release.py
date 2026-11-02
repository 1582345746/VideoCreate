"""Offline release contents check. Diagnostics never print matching secret values."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


def check(entries):
    errors, count = [], 0
    for name, data in entries:
        count += 1
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if any(p in {"projects", "analysis-frames", "__pycache__", ".git", ".env"} or p.endswith(".egg-info") for p in parts):
            errors.append({"file": name, "reason": "private project or build/cache directory"})
        if name.endswith((".pyc", ".pyo", ".dpapi")) or parts[-1] in {"config.json", "videocreate.config.json", "secrets.json"}:
            errors.append({"file": name, "reason": "private/runtime file"})
        if "grok-video-studio" in parts:
            errors.append({"file": name, "reason": "old discoverable skill directory"})
        if re.search(rb"sk-[A-Za-z0-9]{20,}", data):
            errors.append({"file": name, "reason": "API-key-shaped literal (value withheld)"})
    return {"ok": not errors, "files_checked": count, "errors": errors, "network_requests": 0}


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--directory", type=Path)
    group.add_argument("--archive", type=Path)
    group.add_argument("--archive-directory", type=Path)
    args = parser.parse_args()
    if args.archive_directory:
        archives = sorted([*args.archive_directory.glob("*.whl"), *args.archive_directory.glob("*.zip")])
        if not archives:
            result = {"ok": False, "errors": ["No archives found"]}
        else:
            rows = []
            for path in archives:
                with zipfile.ZipFile(path) as archive:
                    rows.append({"archive": path.name, **check((i.filename, archive.read(i)) for i in archive.infolist() if not i.is_dir())})
            result = {"ok": all(row["ok"] for row in rows), "archives": rows}
    elif args.archive:
        with zipfile.ZipFile(args.archive) as archive:
            result = check((i.filename, archive.read(i)) for i in archive.infolist() if not i.is_dir())
    else:
        result = check((p.relative_to(args.directory).as_posix(), p.read_bytes()) for p in args.directory.rglob("*") if p.is_file())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(not result["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
