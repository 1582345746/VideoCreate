"""Read-only browser acceptance on existing data, with F-only writes and no keys.

Runs the real app factory rather than the launcher: the launcher intentionally
registers an instance beside the config, which this inspection must not write.
This does not test launcher registration or grant generation acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def inventory(folder):
    rows = {}
    for current, dirs, names in os.walk(folder, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(current) / d).is_symlink()]
        for name in names:
            path = Path(current) / name
            if path.is_file() and not path.is_symlink():
                relative = path.relative_to(folder).as_posix()
                try:
                    rows[relative] = sha(path)
                except PermissionError:
                    # The existing 8765 process owns this Windows byte lock.
                    # Never release it or silently exempt another private file.
                    if relative != 'local-media/server-lock/.videocreate-state.lock':
                        raise
                    stat = path.stat()
                    rows[relative] = {'verification': 'metadata-only-active-media-lock',
                                      'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    return rows


def tree_hash(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode('utf-8')).hexdigest()


def worker(args):
    """Guard production code before imports; no product safety switches added."""
    from unittest import mock
    import threading
    attempts = {'outside_workspace_writes': 0, 'external_network': 0, 'key_resolution': 0, 'subprocess': 0}
    root = ROOT.resolve()
    if not args.output.is_relative_to(root / '_local') or args.port == 8765:
        raise RuntimeError('Worker requires an isolated F evidence directory and configuration port')
    def record_attempt(category):
        attempts[category] += 1
        (args.output / 'server-guards.json').write_text(json.dumps(attempts, indent=2), encoding='utf-8')
    def writable(path):
        if isinstance(path, int):
            return
        target = Path(os.fsdecode(path)).resolve()
        if not target.is_relative_to(root):
            record_attempt('outside_workspace_writes')
            raise RuntimeError('Read-only data acceptance forbids writes outside the F workspace')
    def guard(event, values):
        if event == 'open':
            mode, flags = values[1], values[2]
            if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                writable(values[0])
        elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime', 'os.truncate'}:
            writable(values[0])
        elif event in {'os.rename', 'os.link', 'os.symlink'}:
            writable(values[0]); writable(values[1])
        elif event in {'socket.connect', 'socket.getaddrinfo', 'socket.bind'}:
            address = values[0] if event == 'socket.getaddrinfo' else values[1]
            host = address[0] if isinstance(address, tuple) else address
            if host not in {'127.0.0.1', 'localhost', '::1', None}:
                record_attempt('external_network')
                raise RuntimeError('Only loopback allowed during read-only data acceptance')
        elif event == 'subprocess.Popen':
            record_attempt('subprocess')
            raise RuntimeError('No subprocesses in read-only data service')
    def no_key(*args, **kwargs):
        record_attempt('key_resolution')
        raise RuntimeError('No credential resolution in read-only data acceptance')
    sys.addaudithook(guard)
    sys.path.insert(0, str(args.source))
    import uvicorn
    from videocreate.config import storage, secrets
    forbidden_codes = {storage.resolve_key.__code__, storage.private_store.__code__, secrets.unprotect.__code__}
    def profile(frame, event, arg):
        if event == 'call' and frame.f_code in forbidden_codes:
            no_key()
    # Function-code guards also catch aliases imported before the mocks; worker
    # threads inherit them. No auth backend may fall through to an environment,
    # plaintext return or DPAPI merely because it held an earlier function alias.
    sys.setprofile(profile); threading.setprofile(profile)
    with mock.patch.object(storage, 'resolve_key', no_key), \
         mock.patch.object(storage, 'private_store', no_key), \
         mock.patch.object(secrets, 'unprotect', no_key):
        from videocreate.config_web.app import create_app
        from videocreate.config_web.service import ConfigService
        app = create_app(args.config, port=args.port, read_only=True)
        summary = ConfigService(args.config).summary()
        assert summary['status'] == 'valid' and not summary['editable']
        (args.output / 'server-summary.json').write_text(json.dumps({
            'config_path': summary['config_path'], 'token': summary['token'],
            'version': summary['version'], 'revision': summary['revision'], 'counts': summary['counts'],
            'read_only': True}, indent=2), encoding='utf-8')
        (args.output / 'server-guards.json').write_text(json.dumps(attempts, indent=2), encoding='utf-8')
        try:
            uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port,
                access_log=False, log_level='critical', server_header=False)).run()
        finally:
            (args.output / 'server-guards.json').write_text(json.dumps(attempts, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--source', type=Path, default=ROOT / 'videocreate/src')
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    args.source = args.source.resolve(); args.output = args.output.resolve()
    if args.worker:
        return worker(args)
    if not args.output.is_relative_to(ROOT / '_local') or args.output.exists():
        raise RuntimeError('Choose a fresh evidence directory in workspace _local')
    if not (args.source / 'videocreate/config_web').is_dir():
        raise RuntimeError('Source must contain the Web candidate package')
    sys.path.insert(0, str(args.source))
    from videocreate.config.storage import user_config_path
    config = user_config_path(args.config).resolve()
    if not config.is_file():
        raise RuntimeError('Existing valid configuration required; do not initialize data for this inspection')
    args.output.mkdir(); (args.output / 'tmp').mkdir()
    original = inventory(config.parent)
    before = sha(config)
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    assert port != 8765
    origin = 'http://127.0.0.1:' + str(port)
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE='1', TEMP=str(args.output / 'tmp'), TMP=str(args.output / 'tmp'),
               PYTHONPATH=str(args.source), VC_WEB_TEST_ORIGIN=origin,
               VC_WEB_FIXTURE_DIR=str(args.output), VC_WEB_EXISTING_CONFIG=str(config))
    # Only the spawned app factory runs against the real path. No instance
    # marker, migrations, credential transactions or generated files are used.
    server_log = (args.output / 'server.log').open('w', encoding='utf-8')
    process = subprocess.Popen([sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()),
        '--worker', '--output', str(args.output), '--source', str(args.source), '--config', str(config), '--port', str(port)],
        cwd=ROOT, env=env, stdout=server_log, stderr=subprocess.STDOUT)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    ok = False
    try:
        for _ in range(150):
            if process.poll() is not None:
                raise RuntimeError('Read-only data service exited; inspect server.log')
            try:
                with opener.open(origin + '/health', timeout=.2) as response:
                    health = json.load(response)
                assert health['product'] == 'VideoCreateConfigWeb' and health['mode'] == 'read-only'
                break
            except OSError:
                time.sleep(.05)
        else:
            raise RuntimeError('Read-only data service startup timeout')
        with (args.output / 'browser.log').open('w', encoding='utf-8') as log:
            result = subprocess.run(['C:/Program Files/nodejs/node.exe', str(ROOT / 'tools/verify_config_web_readonly_data.cjs')],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        if result.returncode:
            raise RuntimeError('Read-only existing-data browser acceptance failed; inspect browser.log')
        ok = True
    finally:
        # Terminate only this owned app-factory process; no source-data writes
        # were permitted. Guard violations are persisted when they occur,
        # before rejection, so Windows TerminateProcess cannot skip that record.
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10); server_log.close()
        after = inventory(config.parent)
        unchanged = original == after and before == sha(config)
        metadata_only = [name for name, value in original.items() if isinstance(value, dict)]
        preserved = {'ok': unchanged, 'files_checked': len(original), 'files_hashed': len(original) - len(metadata_only),
            'metadata_only_active_locks': metadata_only, 'tree_sha256_before': tree_hash(original),
            'tree_sha256_after': tree_hash(after), 'config_sha256_before': before, 'config_sha256_after': sha(config),
            'created_files': len(after.keys() - original.keys()), 'removed_files': len(original.keys() - after.keys()),
            'changed_files': sum(original[n] != after[n] for n in original.keys() & after.keys()),
            'real_credentials_decrypted': False, 'configuration_directory_written': False}
        (args.output / 'data-preservation.json').write_text(json.dumps(preserved, indent=2), encoding='utf-8')
        if not unchanged:
            raise RuntimeError('Existing-data directory changed during acceptance; inspect aggregate preservation evidence')
    browser = json.loads((args.output / 'browser/result.json').read_text(encoding='utf-8'))
    guards = json.loads((args.output / 'server-guards.json').read_text(encoding='utf-8'))
    if any(guards.values()):
        raise RuntimeError('Read-only acceptance guard rejected an attempted action; inspect server-guards.json')
    report = {'ok': ok and browser['ok'], 'scope': 'existing configuration, real read-only app, no launcher registration',
        'source': str(args.source), 'config_path': str(config), 'read_only': True, 'browser': browser,
        'data_preservation': preserved, 'guards': guards, 'inspection_service_stopped': True, 'existing_8765_touched': False,
        'launcher_registration_tested': False, 'human_acceptance': False, 'clean_Windows_host': False,
        'real_credentials_decrypted': False, 'paid_creates': 0}
    (args.output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in {'browser', 'config_path', 'source', 'data_preservation'}}, indent=2))


if __name__ == '__main__':
    main()
