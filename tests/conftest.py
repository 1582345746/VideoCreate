import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = [str(ROOT / "videocreate" / "src"), str(ROOT / "tests")]
inherited = os.environ.get("PYTHONPATH")
if inherited:
    SOURCE_PATHS.append(inherited)
os.environ["PYTHONPATH"] = os.pathsep.join(SOURCE_PATHS)
