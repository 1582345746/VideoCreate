"""Exercise candidate maintenance without touching the installed skill or user data."""
import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile


ROOT = Path(__file__).resolve().parents[1]
GUIDE = 'references/config-web-installation.md'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): digest(p)
            for p in sorted(root.rglob('*')) if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--stable-wheel', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    local = (ROOT / '_local').resolve()
    candidate, stable, output = (p.resolve() for p in
                                 (args.candidate, args.stable_wheel, args.output))
    if not all(p.is_relative_to(local) and p != local for p in (candidate, stable, output)):
        raise RuntimeError('All evidence, fixtures and artifacts must stay under workspace _local')
    if output.exists():
        raise RuntimeError('Choose a fresh lifecycle evidence directory')
    report = json.loads((candidate / 'candidate-build.json').read_text(encoding='utf-8'))
    if report['status'] != 'unreleased-web-candidate' or report['version'] != '3.0.0.dev44':
        raise RuntimeError('Expected an explicitly unreleased dev44 candidate')
    artifacts = candidate / 'artifacts'
    paths = []
    for row in report['artifacts']:
        path = (artifacts / row['filename']).resolve()
        if path.parent != artifacts or digest(path) != row['sha256'] or path.stat().st_size != row['bytes']:
            raise RuntimeError('Candidate artifact identity mismatch')
        paths.append(path)
    wheel, archive = (next(p for p in paths if p.suffix == suffix) for suffix in ('.whl', '.zip'))
    with zipfile.ZipFile(stable) as package:
        metadata = [n for n in package.namelist() if n.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise RuntimeError('Expected one retained wheel metadata entry')
        headers = BytesParser().parsebytes(package.read(metadata[0]), headersonly=True)
        if headers['Name'] != 'videocreate' or headers['Version'] != '3.0.0.dev43':
            raise RuntimeError('Expected an independently built retained dev43 wheel')
    guide_bytes = (ROOT / 'videocreate' / GUIDE).read_bytes()
    for path, prefix in ((wheel, 'videocreate/_skill/'), (archive, 'videocreate/')):
        with zipfile.ZipFile(path) as package:
            if package.read(prefix + GUIDE) != guide_bytes:
                raise RuntimeError('Maintenance guide is missing or differs in the artifact')

    output.mkdir(parents=True)
    started = time.monotonic()
    cwd = output / '仓库外 空格 & 工作目录'; cwd.mkdir()
    temporary = output / 'tmp'; temporary.mkdir()
    data = output / '用户数据 空格 & 保留'; data.mkdir()
    config_dir = data / '配置'
    config = config_dir / 'videocreate.config.json'
    guard = output / 'offline-guard'; guard.mkdir()
    attempts = output / 'external-network-attempts.jsonl'
    # Child Python processes (including pip) fail closed on any network use.
    # No real credential operations or local HTTP server are needed here.
    (guard / 'sitecustomize.py').write_text(
        "import os,socket\n"
        "def deny(*args,**kwargs):\n"
        "    with open(os.environ['VC_LIFECYCLE_NETWORK_LOG'],'a',encoding='utf-8') as stream:\n"
        "        stream.write('{\"network_attempt_blocked\":true}\\n')\n"
        "    raise RuntimeError('Lifecycle verification forbids all network access')\n"
        "socket.socket.connect=deny\nsocket.socket.connect_ex=deny\n"
        "socket.socket.sendto=deny\nsocket.create_connection=deny\nsocket.getaddrinfo=deny\n",
        encoding='utf-8')
    env = dict(os.environ)
    env.update(PYTHONPATH=str(guard), PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8', TEMP=str(temporary), TMP=str(temporary),
               PIP_CACHE_DIR=str(ROOT / '_local/pip-cache'), PIP_NO_INDEX='1',
               PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_CONFIG_FILE=os.devnull,
               VIDEOCREATE_CONFIG_DIR=str(config_dir), GVS_CONFIG_DIR=str(data / 'legacy'),
               VC_LIFECYCLE_NETWORK_LOG=str(attempts))
    # Keep the Python distribution's required DLL paths; exclude only Node/npm.
    env['PATH'] = os.pathsep.join(p for p in os.get_exec_path() if p and not any(
        (Path(p) / name).is_file() for name in ('node.exe', 'node.cmd', 'npm.cmd', 'npm.exe')))
    assert shutil.which('node', path=env['PATH']) is None
    assert shutil.which('npm', path=env['PATH']) is None
    checks = []
    with (output / 'commands.log').open('w', encoding='utf-8') as log:
        def run(command, expected=0):
            command = [str(x) for x in command]
            log.write('[command] ' + json.dumps(command, ensure_ascii=False) + '\n'); log.flush()
            result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    encoding='utf-8', timeout=180)
            log.write(result.stdout + '\n[exit_code] ' + str(result.returncode) + '\n'); log.flush()
            if result.returncode != expected:
                raise RuntimeError('Lifecycle command failed; see commands.log')
            return result.stdout

        venv = output / '专用 Python 环境 & 空格'
        run([args.python, '-m', 'venv', venv])
        python = venv / 'Scripts/python.exe'
        entry = venv / 'Scripts/videocreate.exe'
        web_entry = venv / 'Scripts/videocreate-config-web.exe'
        def install(path):
            run([python, '-m', 'pip', 'install', '--no-index', '--no-deps', '--force-reinstall', path])

        install(wheel)
        # Guard installation is checked explicitly, rather than assumed.
        assert run([python, '-c', 'import sitecustomize; print(sitecustomize.__file__)']).strip() == str(guard / 'sitecustomize.py')
        assert run([python, '-c',
                    'import socket,sitecustomize; print(all(function is sitecustomize.deny for function in '
                    '(socket.socket.connect,socket.socket.connect_ex,socket.socket.sendto,'
                    'socket.create_connection,socket.getaddrinfo)))']).strip() == 'True'
        run([python, '-m', 'videocreate', 'config', 'init', '--config', config])
        value = json.loads(config.read_text(encoding='utf-8'))
        for upstream in value['upstreams'].values():
            upstream['auth'] = {'type': 'bearer', 'secret_ref': 'provider_accounts.fixture.v1'}
        config.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Opaque preservation sentinels intentionally are not valid DPAPI blobs.
        # Unexpected credential resolution would fail; no decrypt command is used.
        opaque = b'fixture-only opaque credential preservation sentinel\x00\x01\xff'
        fixtures = {
            '配置/secrets.dpapi': opaque,
            '配置/backups/secrets-fixture.dpapi': opaque + b'old',
            '配置/backups/config-fixture.json': config.read_bytes(),
            '配置/config-history/fixture.json': b'{"fixture_only":true}\n',
            '配置/runtime/config-web/fixture/drafts/nonsecret.json': b'{"notes":"fixture draft"}\n',
            '配置/runtime/manager-drafts/fixture/snapshot.dpapi': opaque + b'draft',
            '配置/catalog/fixture.json': b'{"fixture_only":true}\n',
            '项目/tasks/task-fixture.json': b'{"fixture_only":true,"status":"submission_unknown"}\n',
            '项目/budget.jsonl': b'{"fixture_only":true,"reservation":"unknown"}\n',
            '项目/已有样片.mp4': b'fixture-only media byte sentinel; not a playable sample\x00',
            '组件/model-fixture.bin': b'fixture-only model byte sentinel\x00',
        }
        for name, payload in fixtures.items():
            path = data / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
        baseline = inventory(data)
        def preserved(stage):
            current = inventory(data)
            assert current == baseline, 'Synthetic user data changed at ' + stage
            checks.append({'stage': stage, 'files': len(current), 'paths_and_bytes_unchanged': True})

        def validate(prefix=None, path=config, expected=0):
            return json.loads(run([*(prefix or [python, '-m', 'videocreate']),
                                   'config', 'validate', '--config', path], expected))

        # A normal configuration may move between versions, without initializing again.
        for path, version, stage in ((stable, 'dev43', 'baseline-dev43'),
                                      (wheel, 'dev44', 'upgrade-dev44'),
                                      (wheel, 'dev44', 'same-version-reinstall')):
            install(path)
            assert version in run([python, '-m', 'videocreate', 'version'])
            assert validate()['ok']
            preserved(stage)

        # A newer optional field must make the old version refuse, without changing it.
        newer = output / 'newer-config.json'
        newer_value = json.loads(config.read_text(encoding='utf-8'))
        newer_value['bindings']['image-primary']['pricing'] = {'currency': 'USD', 'per_image': 0.04}
        newer.write_text(json.dumps(newer_value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        newer_hash = digest(newer)
        assert validate(path=newer)['ok']
        install(stable)
        assert validate()['ok'] and 'dev43' in run([python, '-m', 'videocreate', 'version'])
        rejected = validate(path=newer, expected=1)
        assert not rejected['ok'] and any('per_image' in text for text in rejected['errors'])
        assert digest(newer) == newer_hash
        preserved('rollback-dev43-new-field-rejected')
        install(wheel)
        assert validate(path=newer)['ok'] and digest(newer) == newer_hash
        preserved('return-dev44-new-field-retained')

        run([python, '-m', 'pip', 'uninstall', '--yes', 'videocreate'])
        assert run([python, '-c', "import importlib.util; print(importlib.util.find_spec('videocreate') is None)"]).strip() == 'True'
        assert not entry.exists() and not web_entry.exists()
        preserved('wheel-uninstalled')

        # Use the ZIP with no wheel installed, then quarantine precisely this copy.
        extracted = output / 'ZIP 解压 & 空格'; extracted.mkdir()
        with zipfile.ZipFile(archive) as package:
            for item in package.infolist():
                target = (extracted / item.filename).resolve()
                assert target.is_relative_to(extracted)
                assert item.filename.startswith('videocreate/')
            package.extractall(extracted)
        skill = extracted / 'videocreate'
        assert not (extracted / 'install.ps1').exists()
        assert (skill / GUIDE).read_bytes() == guide_bytes
        zip_prefix = [python, skill / 'scripts/videocreate.py']
        assert 'dev44' in run([*zip_prefix, 'version']) and validate(zip_prefix)['ok']
        preserved('zip-without-wheel')
        skill_manifest = inventory(skill)
        quarantine = extracted / 'videocreate.removed'
        # Both resolved targets are fresh fixture descendants, never user paths.
        assert skill.resolve().is_relative_to(output) and quarantine.resolve().is_relative_to(output)
        assert skill.parent == quarantine.parent and not quarantine.exists()
        skill.rename(quarantine)
        assert not skill.exists() and inventory(quarantine) == skill_manifest
        assert (quarantine / GUIDE).read_bytes() == guide_bytes
        preserved('zip-quarantined')

        install(wheel)
        assert validate()['ok'] and validate(path=newer)['ok'] and digest(newer) == newer_hash
        assert 'dev44' in run([python, '-m', 'videocreate', 'version'])
        preserved('wheel-reinstalled')
        run([python, '-m', 'pip', 'check'])
        assert not attempts.exists() or not attempts.read_bytes()
        result = {'ok': True, 'status': 'unreleased-candidate-maintenance-verified',
                  'candidate': str(candidate.relative_to(ROOT)),
                  'artifacts': report['artifacts'],
                  'stable_wheel': {'path': str(stable.relative_to(ROOT)), 'sha256': digest(stable)},
                  'guide': {'path': 'videocreate/' + GUIDE, 'sha256': hashlib.sha256(guide_bytes).hexdigest(),
                            'wheel_and_zip_bytes_match': True},
                  'checks': checks, 'preserved_files': baseline, 'preservation_checks': len(checks),
                  'same_version_reinstall': True, 'wheel_uninstall_removes_import_and_entrypoints': True,
                  'ZIP_works_without_wheel': True, 'ZIP_quarantine_keeps_all_program_bytes': True,
                  'new_field_dev43_rejected_without_mutation': True, 'new_field_dev44_reinstall_readable': True,
                  'network_guard_verified': True, 'external_network_attempts': 0, 'paid_creates': 0,
                  'installed_stable_replaced': False, 'real_credentials_used': False,
                  'credential_fixture': 'Opaque byte-preservation sentinel; not a valid DPAPI credential',
                  'fixture_media_played_or_regenerated': False, 'clean_windows_machine': 'not-performed',
                  'runtime_node_npm_on_PATH': False, 'seconds': round(time.monotonic() - started, 3)}
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in {'preserved_files', 'artifacts'}},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
