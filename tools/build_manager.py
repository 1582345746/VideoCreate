"""Build a portable Windows manager from source; never include a user's config."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import shutil
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('dist/manager'))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    # A launcher beside scripts/videocreate.py shadows the actual package during analysis.
    launcher = repo / 'build' / 'manager_entry.py'
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text('from videocreate.manager import main\nraise SystemExit(main())\n', encoding='utf-8')
    resources = repo / 'build' / 'manager-resources'
    if resources.exists():
        if not resources.resolve().is_relative_to(repo / 'build'):
            raise RuntimeError('Invalid build resource path')
        shutil.rmtree(resources)
    for name in ('assets', 'scripts'):
        shutil.copytree(repo / 'videocreate' / name, resources / name,
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
        '--name', 'VideoCreateManager', '--paths', str(repo / 'videocreate/src'),
        '--distpath', str(output), '--workpath', str(repo / 'build/manager-work'),
        '--specpath', str(repo / 'build'),
        '--add-data', str(resources / 'assets') + ';videocreate/_skill/assets',
        '--add-data', str(resources / 'scripts') + ';videocreate/_skill/scripts',
        str(launcher)]
    subprocess.run(command, cwd=repo, check=True)
    folder = output / 'VideoCreateManager'
    executable = folder / 'VideoCreateManager.exe'
    archive_path = output / 'VideoCreateManager-Windows-x64.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(output))
    report = {'ok': True, 'executable': str(executable), 'archive': str(archive_path),
        'exe_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        'archive_sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        'archive_bytes': archive_path.stat().st_size,
        'installed_bytes': sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()),
        'signed': False, 'python_required_on_target': False,
        'note': 'Keep the whole portable directory. Built with bundled Tcl/Tk; clean-machine test is separate.'}
    (output / 'manager-build.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
