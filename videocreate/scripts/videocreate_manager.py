"""GUI launcher usable both from the skill checkout and a frozen distribution."""
from pathlib import Path
import sys

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from videocreate.manager import main

if __name__ == '__main__':
    raise SystemExit(main())
