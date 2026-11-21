"""Exercise the portable kit outside its build tree, using only F-drive fixtures."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / '_local') or output.exists():
        raise ValueError('Choose a fresh directory within workspace _local')
    build_root = args.kit.resolve()
    build = json.loads((build_root / 'kit-build.json').read_text(encoding='utf-8'))
    archive_path = build_root / build['archive']['filename']
    if digest(archive_path) != build['archive']['sha256']:
        raise ValueError('Kit archive integrity failed')
    output.mkdir(parents=True)
    extracted = output / '仓库外 解压 空格 & 路径'
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if any(not (extracted / n).resolve().is_relative_to(extracted) for n in names):
            raise ValueError('Invalid kit ZIP path')
        archive.extractall(extracted)
    kit = extracted / 'VideoCreate-dev44-offline-win-cp39'
    script = kit / 'run-offline.py'
    runner = [str(args.python.resolve()), '-B', '-X', 'utf8', str(script)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
               TEMP=str(output), TMP=str(output))
    checks = []
    with (output / 'commands.log').open('w', encoding='utf-8') as log:
        def run(arguments, expected=0):
            result = subprocess.run([*runner, *map(str, arguments)], cwd=output, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', timeout=300)
            log.write(result.stdout + '\n[exit_code] ' + str(result.returncode) + '\n')
            log.flush()
            if result.returncode != expected:
                raise RuntimeError('Kit verification failed; inspect commands.log')
            return result

        run(['--verify-only'])
        checks.append('ZIP extracted outside build tree: all hashes verified')
        # Three real CLI failures must occur before an output environment exists.
        candidate = kit / 'candidate.json'
        original = candidate.read_bytes()
        target = output / 'must-not-create'
        try:
            candidate.write_bytes(original + b'\n')
            run(['--work-dir', target], expected=1)
            assert not target.exists()
        finally:
            candidate.write_bytes(original)
        checks.append('tampered candidate metadata rejected before environment creation')
        wheel = next((kit / 'wheelhouse').glob('*.whl'))
        saved_wheel = output / wheel.name
        shutil.move(str(wheel), str(saved_wheel))
        try:
            run(['--work-dir', target], expected=1)
            assert not target.exists()
        finally:
            shutil.move(str(saved_wheel), str(wheel))
        checks.append('missing dependency rejected before environment creation')
        extra = kit / 'unexpected.txt'
        try:
            extra.write_text('synthetic extra file', encoding='utf-8')
            run(['--work-dir', target], expected=1)
            assert not target.exists()
        finally:
            extra.unlink()
        checks.append('unlisted file rejected before environment creation')
        preserved = output / 'existing-output'
        preserved.mkdir()
        sentinel = preserved / 'sentinel.txt'
        sentinel.write_bytes(b'existing F-drive bytes')
        run(['--work-dir', preserved], expected=1)
        assert sentinel.read_bytes() == b'existing F-drive bytes' and len(list(preserved.iterdir())) == 1
        checks.append('existing output rejected without adding or changing files')
        run(['--work-dir', kit / 'unsafe-output'], expected=1)
        assert not (kit / 'unsafe-output').exists()
        checks.append('output inside the kit rejected')
        special = output / 'percent%output'
        run(['--work-dir', special], expected=1)
        assert not special.exists()
        checks.append('CMD expansion characters rejected before environment creation')

        spec = importlib.util.spec_from_file_location('portable_acceptance', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(module.sysconfig, 'get_platform', return_value='win32'), \
                mock.patch.object(module.sys, 'argv', [str(script), '--work-dir', str(target)]), \
                contextlib.redirect_stderr(io.StringIO()):
            assert module.main() == 1 and not target.exists()
        checks.append('unsupported 32-bit runtime rejected before environment creation')

        for index, names in enumerate((['../escape.txt'], ['videocreate/CON.txt'],
                                        ['videocreate/item.txt', 'videocreate/ITEM.txt'],
                                        ['videocreate/file.txt:stream'], ['videocreate/link'])):
            bad_zip = output / ('malformed-' + str(index) + '.zip')
            with zipfile.ZipFile(bad_zip, 'x') as archive:
                for name in names:
                    info = zipfile.ZipInfo(name)
                    if name.endswith('/link'):
                        info.create_system = 3
                        info.external_attr = (0o120777 << 16)
                    archive.writestr(info, b'synthetic')
            destination = output / ('must-not-extract-' + str(index))
            try:
                module.extract_skill(bad_zip, destination)
            except ValueError:
                assert not destination.exists()
            else:
                raise AssertionError('Malformed archive was accepted')
        checks.append('traversal/device/case-collision/ADS/symlink archives rejected before extraction')
        untouched = output / 'unrelated-synthetic-data'
        untouched.mkdir()
        unrelated = untouched / 'keep.txt'
        unrelated.write_bytes(b'not a production config or secret')
        # Poison inherited settings to make reliance on workstation configuration
        # fail visibly. The portable runner must override these settings itself.
        pip_config = output / 'unrelated-pip.ini'
        pip_config.write_text('[global]\nfind-links = https://offline-pip.invalid/wheels\n', encoding='utf-8')
        env.update(PIP_FIND_LINKS='https://offline-pip.invalid/wheels', PIP_INDEX_URL='https://offline-pip.invalid/simple',
                   PIP_CONFIG_FILE=str(pip_config), VIDEOCREATE_CONFIG_DIR=str(untouched), GVS_CONFIG_DIR=str(untouched))
        run(['--work-dir', output / '自动验收 工作 空格 & 路径'])
        result_path = output / '自动验收 工作 空格 & 路径/result.json'
        result = json.loads(result_path.read_text(encoding='utf-8'))
        assert result['ok'] and len(result['launchers']) == 4
        assert all(row['listener_closed'] for row in result['launchers'])
        assert result['kit_manifest_sha256'] == build['kit_manifest_sha256']
        assert unrelated.read_bytes() == b'not a production config or secret' and len(list(untouched.iterdir())) == 1
        checks.append('full offline install and four launchers pass with poisoned inherited pip/config settings')
        run(['--verify-only'])
        checks.append('extracted kit remains byte-identical after acceptance')
    report = {'ok': True, 'candidate': build['candidate_receipt'], 'checks': checks,
        'kit_build': str(build_root.relative_to(ROOT) / 'kit-build.json'),
        'kit_archive_sha256': build['archive']['sha256'], 'portable_result': str(result_path.relative_to(ROOT)),
        'portable_result_sha256': digest(result_path), 'unique_Python_tests_added': 0,
        'logical_browser_groups_added': 0, 'human_acceptance': False, 'clean_windows_host': False,
        'installed_stable_replaced': False, 'paid_creates': 0}
    (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
