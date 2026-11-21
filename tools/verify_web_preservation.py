"""Read-only verification of real files; hashes only, no credential resolution."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args()
    sys.path.insert(0,str(ROOT/'videocreate/src'))
    from videocreate.config_web.service import ConfigService
    before=json.loads((ROOT/'_local/web-baseline-20261113/preservation-before.json').read_text(encoding='utf-8'))
    external=[]
    for row in json.loads((ROOT/'_local/migration-20261113/environment-baseline.json').read_text(encoding='utf-8'))['files']:
        p=Path(row['path'])
        external.append({'path':row['path'],'unchanged':p.is_file() and digest(p)==row['sha256']})
    authority=[]
    for name,sha in before['external'].items():
        p=Path(name);authority.append({'path':str(p),'sha256':digest(p),'unchanged':digest(p)==sha})
    protected=[]
    for name,sha in before['product'].items():
        p=ROOT/name;protected.append({'path':name,'present':p.is_file(),'unchanged':p.is_file() and digest(p)==sha})
    dirty=[{'path':name,'present':(ROOT/name).is_file(),'unchanged':(ROOT/name).is_file() and digest(ROOT/name)==sha}
           for name,sha in before['dirty'].items()]
    original=json.loads((ROOT/'_local/migration-20261113/source-file-manifest.json').read_text(encoding='utf-8'))
    projects=[row for row in original if row['path'].replace('\\','/').startswith('projects/')]
    changed=[row['path'] for row in projects if not (ROOT/row['path']).is_file() or digest(ROOT/row['path'])!=row['sha256']]
    ports=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',
        "@(Get-NetTCPConnection -State Listen -LocalPort 8765 | Select-Object LocalAddress,LocalPort,OwningProcess) | ConvertTo-Json -Compress"],text=True))
    if isinstance(ports,dict):ports=[ports]
    summary=ConfigService().summary()
    report={'type':'web-development-preservation','authority':authority,
            'installed_and_external_files_checked':len(external),'installed_and_external_unchanged':all(row['unchanged'] for row in external),
            'external_changes':[row for row in external if not row['unchanged']],
            'protected_dev44_files':protected,'all_preexisting_dirty_files_present':all(row['present'] for row in dirty),
            'preexisting_dirty_files_checked':len(dirty),'intentionally_extended_preexisting_files':[r['path'] for r in dirty if not r['unchanged']],
            'original_project_files_checked':len(projects),'original_project_files_unchanged':not changed,
            'changed_original_project_paths':changed,'media_8765':ports,
            'media_same_pid_2176':any(r['OwningProcess']==2176 and r['LocalAddress']=='127.0.0.1' for r in ports),
            'real_config_read_only_summary':{key:summary.get(key) for key in ('config_path','status','schema_version','revision','counts')},
            'real_credentials_decrypted':False,'paid_creates':0}
    output=args.output.resolve() if args.output else ROOT/'_local/web-validation-20261113/preservation-final.json'
    if not output.is_relative_to(ROOT/'_local'):raise RuntimeError('Evidence output must be inside workspace _local')
    if args.output and output.exists():raise RuntimeError('Choose new evidence file')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert all(row['unchanged'] for row in authority) and report['installed_and_external_unchanged']
    assert report['all_preexisting_dirty_files_present'] and not changed and report['media_same_pid_2176']
    print(json.dumps({key:value for key,value in report.items() if key not in {'protected_dev44_files','authority'}},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
