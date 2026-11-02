#!/usr/bin/env python3
"""Standalone skill entrypoint; no package installation is required."""
from pathlib import Path
import sys
import importlib.util

_source = Path(__file__).resolve().parents[1] / "src"
if __name__ == "videocreate":
    # Legacy callers put scripts/ first on sys.path. Do not let this launcher
    # shadow the real package when a sibling module imports videocreate.
    _spec = importlib.util.spec_from_file_location("videocreate", _source / "videocreate/__init__.py",
                                                submodule_search_locations=[str(_source / "videocreate")])
    _package = importlib.util.module_from_spec(_spec)
    sys.modules[__name__] = _package
    _spec.loader.exec_module(_package)
elif __name__ == "__main__":
    sys.path.insert(0, str(_source))
    from videocreate.cli import main
    raise SystemExit(main())
