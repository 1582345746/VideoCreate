"""Build isolated, explicitly unreleased wheel/skill candidates, preserving stable installs."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
IGNORED_DIRECTORIES={'__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','node_modules','.git','local-cast'}


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files(directory):
    for folder, children, files in os.walk(directory):
        children[:] = sorted(name for name in children
            if name not in IGNORED_DIRECTORIES and not name.endswith('.egg-info'))
        for name in sorted(files):
            if not name.endswith(('.pyc','.pyo')) and name != '20261123-seven-video-generation-handoff.zh-CN.md':
                yield Path(folder)/name


def build_inputs(root):
    paths=[root/name for name in ('pyproject.toml','setup.py','MANIFEST.in','README.md',
        'tools/build_web_candidate.py','tools/check_release.py')]
    for name in ('videocreate','requirements','web/provider-config'):
        paths.extend(source_files(root/name))
    return {p.relative_to(root).as_posix():file_hash(p) for p in sorted(paths)}


def verify_published_schema(root, expected):
    """Reject a stale/missing release asset before doing frontend or packaging work."""
    name='videocreate/assets/schemas/videocreate.config.schema.json'
    try:
        raw=(root/name).read_bytes()
        published=json.loads(raw.decode('utf-8-sig'))
    except (OSError,UnicodeError,ValueError):
        raise RuntimeError('Published configuration schema is missing or invalid; synchronize it from the runtime before building') from None
    # Python equality considers False == 0; JSON Schema does not interchange
    # booleans and numeric bounds. Compare the parsed JSON with its types intact.
    if json.dumps(published,sort_keys=True)!=json.dumps(expected,sort_keys=True):
        raise RuntimeError('Published configuration schema differs from the runtime; synchronize it before building')
    return {'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'matches_runtime':True,
            'checked_before_frontend_and_packaging':True,'asset_modified':False}


def verify_frontend(root, output):
    """Rebuild without touching the static files that users and archives consume."""
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    if not npm:
        raise RuntimeError('Candidate builds require Node/npm; packaged Web runtime does not')
    rebuilt=output/'verified-static'
    env=dict(os.environ);env.update(TEMP=str(output/'tmp'),TMP=str(output/'tmp'),
        NPM_CONFIG_CACHE=str(root/'_local/npm-cache'),NPM_CONFIG_UPDATE_NOTIFIER='false')
    (output/'tmp').mkdir(exist_ok=True)
    with (output/'frontend-build.log').open('w',encoding='utf-8') as log:
        subprocess.run([npm,'run','build','--','--outDir',str(rebuilt),'--emptyOutDir'],
            cwd=root/'web/provider-config',env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    saved=root/'videocreate/src/videocreate/config_web/static'
    expected={p.relative_to(saved).as_posix():file_hash(p) for p in source_files(saved)}
    actual={p.relative_to(rebuilt).as_posix():file_hash(p) for p in source_files(rebuilt)}
    if not actual or actual!=expected:
        raise RuntimeError('Bundled frontend is stale or incomplete; rebuild it before creating a candidate')
    return {'typecheck_and_rebuild':'passed','bundled_files_match':True,
            'static_files':[{'path':name,'sha256':sha} for name,sha in sorted(actual.items())],
            'workspace_static_modified':False,'log':'frontend-build.log'}


def verify_inputs_unchanged(root, before):
    if build_inputs(root)!=before:
        raise RuntimeError('Build inputs changed during validation/build; retain this attempt and build a new candidate')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to((ROOT/'_local').resolve()) or output.exists():
        raise RuntimeError('Choose a new candidate directory inside this workspace _local folder')
    output.mkdir(parents=True)
    inputs=build_inputs(ROOT)
    sys.path.insert(0,str(ROOT/'videocreate/src'))
    from videocreate.config.schema import configuration_schema
    schema=verify_published_schema(ROOT,configuration_schema())
    frontend=verify_frontend(ROOT,output)
    verify_inputs_unchanged(ROOT,inputs)
    source=output/'source';source.mkdir()
    for name in ('pyproject.toml','setup.py','MANIFEST.in','README.md'):
        shutil.copy2(ROOT/name,source/name)
    shutil.copytree(ROOT/'videocreate',source/'videocreate',ignore=shutil.ignore_patterns('local-cast','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','*.pyc','*.pyo','*.egg-info','20261123-seven-video-generation-handoff.zh-CN.md'))
    shutil.copytree(ROOT/'requirements',source/'requirements')
    from videocreate import __version__
    from check_release import check
    staged=source/'videocreate'
    safety=check((str(f.relative_to(source)),f.read_bytes()) for f in staged.rglob('*') if f.is_file())
    if not safety['ok']:raise RuntimeError('Candidate content check failed; values withheld')
    packaged_sources=[{'path':f.relative_to(source).as_posix(),'sha256':file_hash(f)}
                  for f in sorted(staged.rglob('*')) if f.is_file()]
    if any(inputs.get(row['path'])!=row['sha256'] for row in packaged_sources):
        raise RuntimeError('Staged source differs from the validated build inputs')
    wheel_dir=output/'artifacts';wheel_dir.mkdir()
    env=dict(os.environ);env.update(PIP_CACHE_DIR=str(ROOT/'_local/pip-cache'),PYTHONDONTWRITEBYTECODE='1')
    subprocess.run([sys.executable,'-m','build','--wheel','--no-isolation','--outdir',str(wheel_dir)],cwd=source,env=env,check=True)
    archive=wheel_dir/('VideoCreate-'+__version__+'-web-candidate.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for file in sorted(staged.rglob('*')):
            if file.is_file() and not any(part.endswith('.egg-info') or part=='__pycache__' for part in file.parts):
                z.write(file,file.relative_to(source).as_posix())
    rows=[]
    for file in sorted(wheel_dir.iterdir()):
        with zipfile.ZipFile(file) as z:
            result=check((i.filename,z.read(i)) for i in z.infolist() if not i.is_dir())
            names=set(z.namelist())
            static=[n for n in names if '/config_web/static/' in n]
            if not static or not any(n.endswith('static/index.html') for n in static):raise RuntimeError('Bundled Web resources missing')
        if not result['ok']:raise RuntimeError('Archive safety check failed; values withheld')
        rows.append({'filename':file.name,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'bytes':file.stat().st_size,
                     'static_resources':len(static),'safety':result})
    verify_inputs_unchanged(ROOT,inputs)
    report={'version':__version__,'status':'unreleased-web-candidate','installed_stable_replaced':False,
            'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
            'artifacts':rows,'source_files':packaged_sources,'paid_creates':0,
            'frontend_rebuild':frontend,'published_config_schema':schema,'build_inputs_unchanged':True,
            'build_environment':{'python':sys.version.split()[0],
                'setuptools':importlib.metadata.version('setuptools'),'build':importlib.metadata.version('build'),
                'node':subprocess.check_output([shutil.which('node'),'--version'],text=True).strip(),
                'npm':subprocess.check_output([shutil.which('npm.cmd' if os.name=='nt' else 'npm'),'--version'],text=True).strip()},
            'build_inputs':[{'path':name,'sha256':sha} for name,sha in sorted(inputs.items())]}
    (output/'candidate-build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
