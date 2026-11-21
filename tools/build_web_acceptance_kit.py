"""Collect frozen candidates and a complete, hashed offline Windows wheelhouse."""
import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def normalized(name):
    return re.sub('[-_.]+', '-', name).lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--wheelhouse', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    wheelhouse = args.wheelhouse.resolve()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / '_local') or output.exists():
        raise ValueError('Choose a new output directory within workspace _local')
    report_path = candidate / 'candidate-build.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if (report['status'] != 'unreleased-web-candidate' or report['installed_stable_replaced']
            or report['version'] != '3.0.0.dev44' or not report['build_inputs_unchanged']
            or not report['frontend_rebuild']['bundled_files_match'] or report['paid_creates']):
        raise ValueError('Expected a verified, explicitly unreleased dev44 candidate')
    from build_web_candidate import build_inputs
    if build_inputs(ROOT) != {row['path']: row['sha256'] for row in report['build_inputs']}:
        raise ValueError('Candidate build inputs differ from the current source')
    for row in report['artifacts']:
        if Path(row['filename']).name != row['filename']:
            raise ValueError('Invalid artifact filename')
        path = candidate / 'artifacts' / row['filename']
        if path.stat().st_size != row['bytes'] or digest(path) != row['sha256'] or not row['safety']['ok']:
            raise ValueError('Candidate artifact integrity failed')
    wheels = [r for r in report['artifacts'] if r['filename'].endswith('.whl')]
    skills = [r for r in report['artifacts'] if r['filename'].endswith('.zip')]
    if len(wheels) != 1 or len(skills) != 1 or len(report['artifacts']) != 2:
        raise ValueError('Expected exactly one wheel and one skill ZIP')
    lock = ROOT / 'requirements/web-py39.lock.txt'
    if lock.read_bytes() != (ROOT / 'videocreate/assets/web-py39.lock.txt').read_bytes():
        raise ValueError('Dependency locks differ')
    pins = {}
    for line in lock.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([0-9][A-Za-z0-9_.]*)', line.strip())
        if not match or normalized(match[1]) in pins:
            raise ValueError('Dependency lock must contain unique exact version pins')
        pins[normalized(match[1])] = match[2]
    if len(pins) != 15:
        raise ValueError('Unexpected dependency closure; review the kit target before updating')
    dependencies = {}
    for path in sorted(wheelhouse.glob('*.whl')):
        with zipfile.ZipFile(path) as archive:
            metadata = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            if len(metadata) != 1:
                raise ValueError('Invalid wheel metadata')
            package = BytesParser().parsebytes(archive.read(metadata[0]))
        name = normalized(package['Name'])
        if name not in pins or package['Version'] != pins[name] or name in dependencies:
            raise ValueError('Wheelhouse must match the exact lock without duplicates/extras')
        if not path.name.endswith(('-py3-none-any.whl', '-py2.py3-none-any.whl', '-cp39-cp39-win_amd64.whl')):
            raise ValueError('Wheel target does not match Windows CPython 3.9 x64')
        dependencies[name] = {'path': path, 'sha256': digest(path), 'version': package['Version']}
    if dependencies.keys() != pins.keys():
        raise ValueError('Offline wheelhouse is incomplete')

    # Check all archive contents, rather than trusting the old content summary.
    from check_release import check
    safety = []
    archives = [candidate / 'artifacts' / row['filename'] for row in report['artifacts']]
    archives += [row['path'] for row in dependencies.values()]
    for path in archives:
        with zipfile.ZipFile(path) as archive:
            result = check((row.filename, archive.read(row)) for row in archive.infolist() if not row.is_dir())
        if not result['ok']:
            raise ValueError('Archive content scan failed (values withheld): ' + path.name)
        safety.append({'filename': path.name, **result})

    output.mkdir(parents=True)
    kit = output / 'VideoCreate-dev44-offline-win-cp39'
    kit.mkdir()
    (kit / 'artifacts').mkdir()
    (kit / 'wheelhouse').mkdir()
    for name in ('run-offline.py', 'README.zh-CN.md', 'ACCEPTANCE.zh-CN.md'):
        shutil.copyfile(ROOT / 'tools/web_acceptance_kit' / name, kit / name)
    for row in report['artifacts']:
        shutil.copyfile(candidate / 'artifacts' / row['filename'], kit / 'artifacts' / row['filename'])
    lines = ['# Windows x64 CPython 3.9 only. Offline wheel hashes; no index or sdists.']
    for name, row in sorted(dependencies.items()):
        shutil.copyfile(row['path'], kit / 'wheelhouse' / row['path'].name)
        lines.append(name + '==' + row['version'] + ' --hash=sha256:' + row['sha256'])
    (kit / 'requirements-win-cp39.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    write_json(kit / 'candidate.json', {
        'version': report['version'], 'status': report['status'], 'head': report['head'],
        'candidate_receipt_sha256': digest(report_path),
        'wheel': 'artifacts/' + wheels[0]['filename'], 'skill_zip': 'artifacts/' + skills[0]['filename'],
        'artifacts': report['artifacts'], 'source_build_inputs': len(report['build_inputs']),
        'packaged_skill_files': len(report['source_files']), 'installed_stable_replaced': False,
    })
    files = [{'path': p.relative_to(kit).as_posix(), 'bytes': p.stat().st_size, 'sha256': digest(p)}
             for p in sorted(kit.rglob('*')) if p.is_file()]
    write_json(kit / 'kit-manifest.json', {'format': 1, 'target': 'win-cp39-amd64',
        'candidate_version': report['version'], 'status': 'unreleased-acceptance-kit',
        'python_runtime_bundled': False, 'files': files})
    own_scan = check((p.relative_to(kit).as_posix(), p.read_bytes()) for p in kit.rglob('*') if p.is_file())
    if not own_scan['ok']:
        raise ValueError('Kit content scan failed (values withheld)')
    archive_path = output / (kit.name + '.zip')
    with zipfile.ZipFile(archive_path, 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(kit.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(output).as_posix())
    # Hash copied bytes too: the manifest must represent the frozen artifacts,
    # not a source that changed during copying.
    for row in report['artifacts']:
        if digest(kit / 'artifacts' / row['filename']) != row['sha256']:
            raise ValueError('Candidate changed during packaging')
    for row in dependencies.values():
        if digest(kit / 'wheelhouse' / row['path'].name) != row['sha256']:
            raise ValueError('Dependency changed during packaging')
    if build_inputs(ROOT) != {row['path']: row['sha256'] for row in report['build_inputs']}:
        raise ValueError('Candidate inputs changed during packaging')
    result = {'ok': True, 'status': 'unreleased-acceptance-kit', 'candidate_rebuilt': False,
        'candidate_receipt': report_path.relative_to(ROOT).as_posix(), 'candidate_receipt_sha256': digest(report_path),
        'source_build_inputs_unchanged': len(report['build_inputs']), 'packaged_skill_files_unchanged': len(report['source_files']),
        'target': 'win-cp39-amd64', 'locked_dependency_wheels': len(dependencies),
        'kit_manifest_sha256': digest(kit / 'kit-manifest.json'), 'kit_files': len(files),
        'archive': {'filename': archive_path.name, 'bytes': archive_path.stat().st_size, 'sha256': digest(archive_path)},
        'content_scan': own_scan, 'nested_archive_scans': safety, 'runtime_bundled': False,
        'human_acceptance': False, 'clean_windows_host': False, 'installed_stable_replaced': False, 'paid_creates': 0}
    write_json(output / 'kit-build.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in {'nested_archive_scans', 'content_scan'}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
