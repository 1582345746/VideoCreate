# -*- coding: utf-8 -*-
"""Validate docs/prototype and preserve existing source; optionally build a docs-only ZIP."""
import argparse
import collections
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs'
HERE = Path(__file__).resolve().parent
BUNDLE = DOCS / 'VideoCreate-WebConfig-Handoff-20261113.zip'
TEXTS = [
    DOCS/'20261113-f-drive-migration.zh-CN.md',
    DOCS/'20261113-web-provider-config-design.zh-CN.md',
    DOCS/'20261113-complete-development-checklist.zh-CN.md',
    DOCS/'20261113-new-chat-handoff.zh-CN.md',
    DOCS/'20261113-new-chat-start.zh-CN.md',
    DOCS/'20261113-cleanup-record.zh-CN.md',
]
EXTRA = [
    DOCS/'20261113-development-checklist.json',
    DOCS/'20261113-cleanup-summary.json',
    DOCS/'20261113-cleanup-protection-verification.json',
    DOCS/'20261113-dev43-acceptance.zh-CN.md',
    DOCS/'20261112-provider-management-and-production-roadmap.zh-CN.md',
    DOCS/'20261112-development-progress.zh-CN.md',
]
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def verify():
    errors = []
    preserved = json.loads((HERE/'handoff-preservation-baseline.json').read_text(encoding='utf-8'))
    for row in preserved['preexisting_product_changes']:
        p = ROOT/row['path']
        if not p.is_file() or digest(p) != row['sha256']:
            errors.append({'kind':'changed-existing-product-file','file':row['path']})
    config = preserved['production_config']
    config_unchanged = digest(Path(config['path'])) == config['sha256']
    if not config_unchanged:
        errors.append({'kind':'production-config-changed'})
    checklist = json.loads((DOCS/'20261113-development-checklist.json').read_text(encoding='utf-8'))
    ids = [w['id'] for w in checklist['work_packages']]
    assert len(ids) == len(set(ids)) == 73
    counts = dict(collections.Counter(w['status'] for w in checklist['work_packages']))
    assert counts == {'partial':60,'implemented-offline':11,'planned':2}
    web = checklist['web_subitems']
    assert len(web) == 22 and len({w['id'] for w in web}) == 22
    assert all(set(w['maps']) <= set(ids) for w in web)
    baseline = json.loads(subprocess.check_output(['git','show',preserved['head']+':videocreate/assets/module-catalog.json'],cwd=ROOT))
    original = {w['id']:w for w in baseline['work_packages']}
    for w in checklist['work_packages']:
        assert all(w[k] == original[w['id']][k] for k in ('priority','status','requirement'))
        for p in w['source_paths']:
            if not (ROOT/p).exists():errors.append({'kind':'missing-code-path','file':p})
        for t in w['existing_test_index']:
            if not (ROOT/'tests'/t).is_file():errors.append({'kind':'missing-test','file':t})
    links = 0
    for p in TEXTS:
        text = p.read_text(encoding='utf-8')
        assert '\ufffd' not in text
        for target in re.findall(r'\]\(([^)]+)\)', text):
            target = target.strip('<>')
            if re.match(r'^[a-zA-Z]+://|^#',target):continue
            name = unquote(target.split('#')[0])
            if not (p.parent/name).exists():errors.append({'kind':'broken-doc-link','file':p.name,'target':name})
            links += 1
    html = (HERE/'provider-config-web.html').read_text(encoding='utf-8')
    assert '<script src=' not in html and 'fetch(' not in html and 'localStorage' not in html
    code = re.search(r'<script>([\s\S]*?)</script>',html).group(1)
    with tempfile.TemporaryDirectory(prefix='vc-handoff-js-') as temp:
        js = Path(temp)/'prototype.js'
        js.write_text(code,encoding='utf-8')
        subprocess.run(['node','--check',str(js)],check=True,capture_output=True)
    browser = json.loads((HERE/'provider-config-prototype-verification.json').read_text(encoding='utf-8'))
    assert browser['ok'] and browser['checks_count'] == 10
    assert browser['browser_errors'] == browser['external_requests'] == []
    assert browser['production_config_reads'] == browser['production_config_writes'] == browser['provider_creates'] == 0
    protection = json.loads((DOCS/'20261113-cleanup-protection-verification.json').read_text(encoding='utf-8'))
    assert protection['ok'] and protection['project_files'] == 5466
    assert protection['projects_bytes_and_paths_unchanged'] and protection['installed_skill_bytes_and_paths_unchanged']
    assert protection['configuration_and_credential_files_bytes_unchanged']
    return {'ok':not errors,'date':'2026-11-13','scope':'docs-and-fixture-prototype-only',
            'original_work_packages':73,'baseline_status_counts':counts,'web_subitems':22,
            'markdown_local_links_checked':links,'prototype_browser_flow_groups':10,
            'prototype_browser_errors':0,'prototype_external_requests':0,
            'prototype_javascript_syntax':'pass','preexisting_product_files_unchanged':11,
            'production_config_bytes_unchanged':config_unchanged,
            'cleanup_protection_verified':True,'protected_project_files':5466,
            'production_web_implemented':False,'paid_creates':0,'errors':errors}

def make_bundle(report):
    files = TEXTS + EXTRA + [p for p in HERE.iterdir() if p.suffix in {'.html','.png','.json','.cjs','.py'} and p.name != 'handoff-manifest.json']
    files = sorted(set(files))
    assert all(p.is_file() for p in files)
    for p in files:
        if re.search(rb'sk-[A-Za-z0-9]{20,}',p.read_bytes()):
            raise AssertionError('Secret-shaped value in document (value withheld): '+p.name)
        assert p.suffix not in {'.dpapi','.pyc'}
    manifest = {'date':'2026-11-13','kind':'documentation-and-demo-only',
                'workspace_source_required':True,'contains_runtime_config':False,
                'contains_credentials':False,'contains_real_media_or_task_receipts':False,
                'files':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)} for p in files]}
    (HERE/'handoff-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    readme = ('VideoCreate Web Config Handoff / 2026-11-13\n\n'
              'Open docs/prototypes/provider-config-web.html for the interactive fixture prototype.\n'
              'Read docs/20261113-f-drive-migration.zh-CN.md first.\n'
              'Then read docs/20261113-new-chat-handoff.zh-CN.md.\n'
              'Read docs/20261113-new-chat-start.zh-CN.md for a new-chat prompt.\n'
              'This archive contains documentation and demo fixtures only.\n'
              f'Continue development in the existing {ROOT.as_posix()} workspace.\n'
              'Product source, ignored acceptance/projects/dist folders, runtime config and credentials are not bundled.\n'
              'Source links point back to that workspace. This is not an installed Web application.\n')
    with zipfile.ZipFile(BUNDLE,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('README.md',readme)
        for p in files+[HERE/'handoff-manifest.json']:
            archive.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(BUNDLE) as archive:
        assert archive.testzip() is None
        for p in files:
            assert hashlib.sha256(archive.read(p.relative_to(ROOT).as_posix())).hexdigest() == digest(p)
    return {'file':BUNDLE.name,'bytes':BUNDLE.stat().st_size,'sha256':digest(BUNDLE),
            'entries':len(files)+2,'crc_and_exact_file_hashes':'pass','secret_shape_scan':'pass'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--build-bundle',action='store_true')
    args=parser.parse_args()
    report=verify()
    out=HERE/'handoff-verification.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.build_bundle and report['ok']:
        # Keep the inner verification report deterministic; external receipt holds ZIP hash.
        report['bundle']=make_bundle(report)
        (DOCS/'20261113-handoff-bundle-receipt.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return int(not report['ok'])

if __name__=='__main__':
    raise SystemExit(main())
