"""Standalone, synthetic-only Windows CPython 3.9 x64 acceptance runner."""
import argparse
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import sys
import sysconfig
import time
import urllib.request
import zipfile

sys.dont_write_bytecode = True
KIT = Path(__file__).resolve().parent


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def safe_relative(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or path.is_absolute()
            or any(part in {'', '.', '..'} for part in name.split('/'))):
        raise ValueError('Invalid relative package path')
    return path


def verify_kit():
    manifest = json.loads((KIT / 'kit-manifest.json').read_text(encoding='utf-8'))
    if manifest['format'] != 1 or manifest['target'] != 'win-cp39-amd64':
        raise ValueError('Unsupported kit format or target')
    expected, folded = set(), set()
    for row in manifest['files']:
        name = str(safe_relative(row['path']))
        if name == 'kit-manifest.json' or name.casefold() in folded:
            raise ValueError('Duplicate or reserved manifest path')
        path = KIT.joinpath(*PurePosixPath(name).parts)
        if (path.is_symlink() or not path.resolve().is_relative_to(KIT)
                or not path.is_file() or path.stat().st_size != row['bytes']
                or digest(path) != row['sha256']):
            raise ValueError('Kit integrity check failed: ' + name)
        expected.add(name)
        folded.add(name.casefold())
    actual = {p.relative_to(KIT).as_posix() for p in KIT.rglob('*') if p.is_file()}
    if actual != expected | {'kit-manifest.json'}:
        raise ValueError('Kit contains missing or unlisted files')
    return manifest


def extract_skill(archive_path, target):
    # Validate every member before writing any member. Windows aliases, links,
    # ADS and traversal must not turn a disposable extraction into an overwrite.
    with zipfile.ZipFile(archive_path) as archive:
        seen = set()
        for member in archive.infolist():
            name = member.filename.rstrip('/')
            relative = safe_relative(name)
            if relative.parts[0] != 'videocreate' or name.casefold() in seen:
                raise ValueError('Unexpected or duplicate skill archive path')
            if ((member.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError('Skill archive contains a symbolic link')
            for part in relative.parts:
                if part.endswith((' ', '.')) or part.split('.')[0].upper() in {
                    'CON', 'PRN', 'AUX', 'NUL',
                    *('COM' + str(n) for n in range(1, 10)),
                    *('LPT' + str(n) for n in range(1, 10)),
                }:
                    raise ValueError('Skill archive contains a Windows alias')
            seen.add(name.casefold())
        target.mkdir()
        archive.extractall(target)


def cmd_line(arguments):
    # Windows cmd requires an extra outer pair around quoted command arguments.
    # Reject cmd expansion characters; never interpolate user text into code.
    if any(any(c in str(arg) for c in '"%!\r\n') for arg in arguments):
        raise ValueError('CMD acceptance paths cannot contain quotes, %, ! or newlines')
    executable = Path(os.environ['SystemRoot']) / 'System32/cmd.exe'
    return '"' + str(executable) + '" /d /s /c "' + ' '.join(
        '"' + str(arg) + '"' for arg in arguments) + '"'


def run_acceptance(work, manifest):
    work.mkdir(parents=True)  # Caller rejects existing directories, including empty ones.
    tmp = work / 'tmp'
    tmp.mkdir()
    cwd = work / '工作目录 空格 & 路径'
    cwd.mkdir()
    venv = work / 'Python 环境 空格 & 路径'
    config = work / '合成配置 空格 & 路径/videocreate.config.json'
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in {'PYTHONPATH', 'PYTHONHOME'} and not key.upper().startswith('PIP_')}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               TEMP=str(tmp), TMP=str(tmp), PIP_CONFIG_FILE=os.devnull,
               PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1',
               VIDEOCREATE_CONFIG_DIR=str(config.parent), GVS_CONFIG_DIR=str(work / 'unused-legacy'))
    env.pop('VIDEOCREATE_OFFLINE_ACCEPTANCE_UNUSED_KEY', None)
    # Preserve the selected Python's DLL search directories (Conda in particular),
    # while making accidental Node/npm runtime dependencies observable.
    env['PATH'] = os.pathsep.join(directory for directory in os.get_exec_path(env)
        if directory and not any((Path(directory) / name).is_file()
            for name in ('node.exe', 'node.cmd', 'npm.cmd', 'npm.exe')))
    if shutil.which('node', path=env['PATH']) or shutil.which('npm', path=env['PATH']):
        raise ValueError('Could not remove Node/npm from acceptance PATH')

    with (work / 'commands.log').open('w', encoding='utf-8') as log:
        def run(command, expected=0):
            result = subprocess.run([str(arg) for arg in command], cwd=cwd, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', timeout=180)
            log.write(result.stdout + '\n[exit_code] ' + str(result.returncode) + '\n')
            log.flush()
            if result.returncode != expected:
                raise RuntimeError('Command failed; inspect commands.log')
            return result.stdout

        run([sys.executable, '-B', '-m', 'venv', venv])
        python = venv / 'Scripts/python.exe'
        env['PATH'] = str(python.parent) + os.pathsep + env['PATH']
        # The offline pip subprocess rejects every socket connect/DNS attempt,
        # including a hidden remote find-links value in the host's pip settings.
        pip_guard = work / 'pip-offline.py'
        pip_guard.write_text(
            'import runpy, sys\n'
            'def guard(event, args):\n'
            '    if event in {"socket.connect", "socket.getaddrinfo"}:\n'
            '        raise RuntimeError("Network is forbidden during offline installation")\n'
            'sys.addaudithook(guard)\n'
            'runpy.run_module("pip", run_name="__main__")\n', encoding='utf-8')
        pip = [python, '-B', pip_guard, '--disable-pip-version-check', '--no-input']
        run([*pip, 'install', '--no-index', '--no-deps', '--no-cache-dir', '--only-binary', ':all:',
             '--require-hashes', '--find-links', KIT / 'wheelhouse', '-r', KIT / 'requirements-win-cp39.txt'])
        candidate = json.loads((KIT / 'candidate.json').read_text(encoding='utf-8'))
        wheel = KIT / candidate['wheel']
        archive = KIT / candidate['skill_zip']
        run([*pip, 'install', '--no-index', '--no-deps', '--no-cache-dir', wheel])
        run([*pip, 'check'])
        if json.loads(run([python, '-m', 'videocreate', 'version']))['version'] != candidate['version']:
            raise RuntimeError('Installed candidate version mismatch')
        run([python, '-c',
            'import json; from videocreate.cli import skill_root; '
            'from videocreate.config.schema import configuration_schema; '
            'assert json.loads((skill_root()/"assets/schemas/videocreate.config.schema.json").read_text(encoding="utf-8"))==configuration_schema(); '
            'print("Installed published schema matches runtime")'])

        run([python, '-m', 'videocreate', 'config', 'init', '--config', config])
        fixture = json.loads(config.read_text(encoding='utf-8'))
        for index, upstream in enumerate(fixture['upstreams'].values()):
            upstream['base_url'] = 'https://offline-' + str(index) + '.invalid/v1'
            upstream['auth'] = {'type': 'bearer', 'env': 'VIDEOCREATE_OFFLINE_ACCEPTANCE_UNUSED_KEY'}
        config.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        run([python, '-m', 'videocreate', 'config', 'validate', '--config', config])
        original = config.read_bytes()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        checks = []

        def smoke(prefix, label, extra, cli_prefix):
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0))
                port = reserve.getsockname()[1]
            if port == 8765:
                raise RuntimeError('Refusing the reserved media port')
            args = [*prefix, *extra, '--config', config, '--port', str(port), '--no-browser', '--read-only']
            if label in {'zip-powershell', 'zip-cmd'}:
                args = [*prefix, '-Python', python, '-Config', config, '-Port', str(port), '-NoBrowser', '-ReadOnly']
            command = cmd_line(args) if label == 'zip-cmd' else [str(arg) for arg in args]
            origin = 'http://127.0.0.1:' + str(port)
            with (work / (label + '.log')).open('w', encoding='utf-8') as server_log:
                process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                    stdout=server_log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                try:
                    for _ in range(300):
                        if process.poll() is not None:
                            raise RuntimeError(label + ' exited before readiness')
                        try:
                            with opener.open(origin + '/health', timeout=.2) as response:
                                health = json.load(response)
                            break
                        except OSError:
                            time.sleep(.1)
                    else:
                        raise RuntimeError(label + ' readiness timed out')
                    if (health['product'] != 'VideoCreateConfigWeb' or health['version'] != candidate['version']
                            or health['mode'] != 'read-only'):
                        raise RuntimeError(label + ' service identity mismatch')
                    with opener.open(origin, timeout=3) as response:
                        html = response.read().decode('utf-8')
                    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
                    if not assets or any(not value.startswith('/assets/') or '..' in value for value in assets):
                        raise RuntimeError('Missing or invalid bundled static resources')
                    for resource in assets:
                        with opener.open(origin + resource, timeout=3) as response:
                            if not response.read():
                                raise RuntimeError('Empty static resource')
                    request = urllib.request.Request(origin + '/api/config/summary', headers={'X-VC-Client': '1'})
                    with opener.open(request, timeout=3) as response:
                        summary = json.load(response)
                    if (Path(summary['config_path']).resolve() != config or summary['status'] != 'valid'
                            or summary['mode'] != 'read-only' or config.read_bytes() != original):
                        raise RuntimeError('Synthetic configuration or read-only mode mismatch')
                    run([*cli_prefix, 'config-web', '--config', config, '--port', str(port), '--no-browser', '--read-only'])
                    with opener.open(origin + '/health', timeout=3) as response:
                        if json.load(response) != health:
                            raise RuntimeError('Same-instance reuse changed identity')
                finally:
                    # Only this exact owned process tree. Never stop by name or port.
                    if process.poll() is None:
                        subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/taskkill.exe'),
                            '/PID', str(process.pid), '/T', '/F'], stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT, timeout=15)
                    process.wait(timeout=15)
                for _ in range(40):
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.1):
                            pass
                    except OSError:
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError(label + ' left a listener behind')
            checks.append({'entry': label, 'port': port, 'static_resources': len(assets),
                           'same_instance_reused': True, 'read_only': True, 'listener_closed': True})

        smoke([venv / 'Scripts/videocreate-config-web.exe'], 'wheel-console', [], [python, '-m', 'videocreate'])
        run([*pip, 'uninstall', '--yes', 'videocreate'])
        if run([python, '-c', 'import importlib.util; print(importlib.util.find_spec("videocreate") is None)']).strip() != 'True':
            raise RuntimeError('Wheel still present before ZIP acceptance')
        extracted = work / '技能解压目录 空格 & 路径'
        extract_skill(archive, extracted)
        skill = extracted / 'videocreate'
        cli = [python, skill / 'scripts/videocreate.py']
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        smoke([powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', skill / 'scripts/config-web.ps1'],
              'zip-powershell', [], cli)
        smoke([skill / 'scripts/Start-ConfigWeb.cmd'], 'zip-cmd', [], cli)
        smoke(cli, 'zip-python', ['config-web'], cli)
        run([*pip, 'install', '--no-index', '--no-deps', '--no-cache-dir', wheel])
        run([*pip, 'check'])
        if config.read_bytes() != original:
            raise RuntimeError('Synthetic configuration changed')
        return {'ok': True, 'candidate_version': candidate['version'], 'candidate_status': 'unreleased',
                'kit_manifest_sha256': digest(KIT / 'kit-manifest.json'), 'kit_files_verified': len(manifest['files']),
                'python': sys.version.split()[0], 'python_platform': sysconfig.get_platform(),
                'windows_version': list(sys.getwindowsversion()[:3]), 'work_directory': str(work),
                'locked_dependency_wheels': 15, 'offline_pip_network_guard': True,
                'published_schema_matches_runtime': True, 'runtime_node_on_path': False,
                'launchers': checks, 'zip_wheel_absent': True, 'synthetic_configuration_preserved': True,
                'real_config_used': False, 'real_credentials_decrypted': False,
                'installed_stable_replaced': False, 'existing_8765_touched': False, 'paid_creates': 0,
                'clean_windows_host': 'not-established-by-runner', 'human_acceptance': 'not-performed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, help='New, nonexistent directory on F:; outside the extracted kit')
    parser.add_argument('--verify-only', action='store_true', help='Verify kit bytes; create no environment or files')
    args = parser.parse_args()
    work = None
    created = False
    try:
        manifest = verify_kit()
        if args.verify_only:
            print(json.dumps({'ok': True, 'files_verified': len(manifest['files']), 'runtime_tested': False}))
            return 0
        if (os.name != 'nt' or sys.implementation.name != 'cpython' or sys.version_info[:2] != (3, 9)
                or sysconfig.get_platform() != 'win-amd64'):
            raise ValueError('This wheelhouse requires Windows x64 CPython 3.9; no runtime is bundled')
        if not args.work_dir or not args.work_dir.is_absolute():
            raise ValueError('Provide an absolute --work-dir on F:')
        work = args.work_dir.resolve()
        if work.drive.upper() != 'F:' or work == KIT or work.is_relative_to(KIT) or KIT.is_relative_to(work) or work.exists():
            raise ValueError('Choose a new F: directory outside the kit; existing directories are never reused')
        if any(c in str(work) + str(KIT) for c in '"%!\r\n'):
            raise ValueError('CMD acceptance paths cannot contain quotes, %, ! or newlines')
        # Set ownership only after an exclusive mkdir succeeds, before the runner
        # creates anything else. Failures never write into preexisting directories.
        work.mkdir(parents=True)
        created = True
        result = run_acceptance_in_created(work, manifest)
        (work / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        failure = {'ok': False, 'error_type': type(error).__name__, 'error': str(error), 'candidate_status': 'unreleased'}
        if created:
            (work / 'failure.json').write_text(json.dumps(failure, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(failure, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


def run_acceptance_in_created(work, manifest):
    # run_acceptance expects to create its root exclusively. The outer function
    # already owns it, so use a child for all commands and keep top-level receipts.
    return run_acceptance(work / 'run', manifest)


if __name__ == '__main__':
    raise SystemExit(main())
