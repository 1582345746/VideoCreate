"""Include the retained execution resources in standalone wheel installs."""
from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildSkill(build_py):
    def run(self):
        super().run()
        source = Path(__file__).parent / "videocreate"
        target = Path(self.build_lib) / "videocreate" / "_skill"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "SKILL.md", target / "SKILL.md")
        for name in ("scripts", "assets", "references", "agents"):
            shutil.copytree(source / name, target / name, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))


setup(cmdclass={"build_py": BuildSkill})
