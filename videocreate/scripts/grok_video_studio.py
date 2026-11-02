"""Deprecated v2 entrypoint retained for one migration cycle."""
import sys
import videocreate_engine as _engine

if __name__ == "__main__":
    raise SystemExit(_engine.main())
sys.modules[__name__] = _engine
