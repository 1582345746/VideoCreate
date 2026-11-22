"""Verify candidate installs in a temporary runtime outside the source checkout."""
import argparse
import hashlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEV43_COMMIT = 'aed9f160ed8d07007ab5b2ef3950706ce0d3a207'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--media-wheelhouse', type=Path, help='Also exercise the installed cast sheet CLI with offline Pillow wheels')
    args = parser.parse_args()
    # Installation commands intentionally run outside the repository. Resolve
    # the candidate before changing cwd so relative CLI paths remain usable.
    args.candidate = args.candidate.resolve()
    if args.media_wheelhouse:
        args.media_wheelhouse = args.media_wheelhouse.resolve()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'_local') or output.exists():
        raise RuntimeError('Choose a new verification directory within workspace _local')
    with tempfile.TemporaryDirectory(prefix='videocreate-candidate-') as temporary:
        runtime = Path(temporary).resolve()
        if runtime.is_relative_to(ROOT):
            raise RuntimeError('Set TEMP to a directory outside the source checkout')
        verify(args, output, runtime)


def verify(args, output, runtime):
    output.mkdir(parents=True)
    tmp = output/'tmp'; tmp.mkdir()
    cwd = runtime/'仓库外 工作目录 & 路径'; cwd.mkdir()
    config_dir=runtime/'配置目录 空格 & 路径'
    venv=runtime/'Python 环境 空格 & 路径'
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8', TEMP=str(tmp), TMP=str(tmp),
               PIP_CACHE_DIR=str(ROOT/'_local/pip-cache'),
               VIDEOCREATE_CONFIG_DIR=str(config_dir), GVS_CONFIG_DIR=str(output/'legacy'))
    log = (output/'commands.log').open('w', encoding='utf-8')

    def run(command, *, expected=0):
        result = subprocess.run(command if isinstance(command,str) else [str(x) for x in command], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        log.write(result.stdout);log.write('\n[exit_code] '+str(result.returncode)+'\n');log.flush()
        if result.returncode != expected:
            raise RuntimeError('Isolated command failed; inspect commands.log')
        return result.stdout

    report = json.loads((args.candidate/'candidate-build.json').read_text(encoding='utf-8'))
    artifacts = args.candidate/'artifacts'
    for row in report['artifacts']:
        assert hashlib.sha256((artifacts/row['filename']).read_bytes()).hexdigest() == row['sha256']
    candidate = next(artifacts.glob('*.whl'))
    skill_zip = next(artifacts.glob('*.zip'))

    # Rebuild the immutable committed dev43 source for a genuine isolated
    # 43 -> 44 -> 43 -> 44 package transition, without touching the installation.
    stable = output/'stable-source'; stable.mkdir()
    payload = subprocess.check_output(['git', 'archive', DEV43_COMMIT, '--', 'pyproject.toml', 'setup.py', 'MANIFEST.in', 'README.md', 'videocreate'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        for item in archive.getmembers():
            target = (stable/item.name).resolve()
            if not target.is_relative_to(stable) or not (item.isdir() or item.isfile()):
                raise RuntimeError('Unexpected baseline archive member')
            if item.isdir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(item).read())
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'build', '--wheel', '--no-isolation', '--outdir', str(output/'stable-wheel')],
                            cwd=stable, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode: raise RuntimeError('Baseline build failed')
    old = next((output/'stable-wheel').glob('*.whl'))
    run([args.python, '-m', 'venv', venv])
    python = venv/'Scripts/python.exe'
    entry = venv/'Scripts/videocreate.exe'
    web_entry = venv/'Scripts/videocreate-config-web.exe'
    system_root=Path(os.environ['SystemRoot'])
    # Keep this Python distribution's DLL search paths (notably Conda SSL).
    # Remove Node/npm directories rather than replacing the whole runtime PATH.
    env['PATH']=os.pathsep.join([str(python.parent),*(directory for directory in os.get_exec_path()
        if directory and not any((Path(directory)/name).is_file()
            for name in ('node.exe','node.cmd','npm.cmd','npm.exe')))])
    assert shutil.which('node',path=env['PATH']) is None
    assert shutil.which('npm',path=env['PATH']) is None
    run([python, '-m', 'pip', 'install', '--no-index', '--no-deps', old])
    assert 'dev43' in run([python, '-m', 'videocreate', 'version'])
    run([python, '-m', 'pip', 'install', '--no-index', '--no-deps', candidate])
    assert 'dev44' in run([entry, 'version'])
    assert 'config-web' in run([python, '-m', 'videocreate', '--help'])
    missing = run([python, '-m', 'videocreate', 'config-web', '--no-browser'], expected=1)
    assert 'Web dependencies are missing' in missing and 'Traceback' not in missing
    missing_console=run([web_entry,'--no-browser'],expected=1)
    assert 'Web dependencies are missing' in missing_console and 'Traceback' not in missing_console
    run([python, '-m', 'pip', 'install', '--no-index', '--find-links', ROOT/'_local/web-wheelhouse', '-r', ROOT/'requirements/web-py39.lock.txt'])
    run([python, '-m', 'pip', 'check'])
    limited_env=dict(env)
    limited_env['PATH']=os.pathsep.join(str(p) for p in (python.parent,system_root/'System32',system_root,
                                                        system_root/'System32/WindowsPowerShell/v1.0'))
    probe=subprocess.run([str(python),'-c','import fastapi,uvicorn'],cwd=cwd,env=limited_env,
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8')
    runtime_diagnostic={'restricted_DLL_path_import_failure':probe.returncode!=0,
                        'normal_runtime_PATH_retained':True}
    if probe.returncode:
        # A Conda-based venv can lose _ssl when its DLL paths are removed.
        # Verify the installed console reports that known failure without a stack.
        diagnostic=subprocess.run([str(web_entry),'--no-browser'],cwd=cwd,env=limited_env,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8')
        log.write(diagnostic.stdout);log.flush()
        assert diagnostic.returncode==1 and 'Web runtime could not load' in diagnostic.stdout
        assert 'Traceback' not in diagnostic.stdout and '_ssl' not in diagnostic.stdout
        runtime_diagnostic['structured_console_error_without_traceback']=True

    # CLI initialization is explicitly limited to this synthetic candidate root.
    config = config_dir/'videocreate.config.json'
    run([python, '-m', 'videocreate', 'config', 'init', '--config', config])
    original = config.read_bytes()

    # Exercise the new CLI from the installed wheel, outside the repository.
    # This separate synthetic file must not alter the Web smoke config.
    identity_config=output/'identity-config.json'
    fixture=json.loads(original)
    for uid in ('primary-sub2api','backup-newapi'):
        fixture['upstreams'][uid]['display_name']='候选同名账户'
    for bid,remote in (('grok-on-sub2api','Candidate Exact V'),('grok-on-newapi','Candidate exact v')):
        fixture['bindings'][bid].update(display_name='候选视频接入',remote_model=remote)
    identity_config.write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    identity_before=identity_config.read_bytes()
    def identify(*terms):
        result=json.loads(run([entry,'providers','identify','--config',identity_config,'--kind','video',*terms]))
        assert result['readiness']=='not-checked' and not result['credentials_checked']
        assert not result['selection_changed'] and result['network_requests']==result['paid_creates']==0
        assert identity_config.read_bytes()==identity_before and config.read_bytes()==original
        return result
    ambiguous=identify('--upstream-name','候选同名账户','--model-name','候选视频接入')
    assert ambiguous['status']=='ambiguous' and ambiguous['needs_choice']==['upstream']
    exact=identify('--model-name','Candidate Exact V')
    assert exact['status']=='identified' and exact['matches'][0]['binding_id']=='grok-on-sub2api'
    pinned=identify('--upstream','primary-sub2api','--model-name','候选视频接入')
    assert pinned['status']=='identified' and pinned['matches'][0]['binding_id']=='grok-on-sub2api'
    assert identify('--model-name','candidate exact v')['status']=='no_matches'
    for terms in (('--upstream-name','候选同名账户'),()):assert identify(*terms)['status']=='ambiguous'
    identity_checks={'synthetic_config_preserved':True,'duplicate_saved_names':'ambiguous',
        'exact_remote_case':'identified','explicit_canonical_pin':'identified',
        'wrong_case':'no_matches','upstream_only_and_unspecified':'ambiguous',
        'readiness':'not-checked','credentials_checked':False,'network_requests':0,'paid_creates':0}
    # New optional image units must never be silently discarded by dev43.
    image_config=output/'image-price-config.json'
    fixture=json.loads(original)
    fixture['bindings']['image-primary']['pricing']={'currency':'USD','per_request':.01,'per_image':.04}
    image_other=next(bid for bid,b in fixture['bindings'].items()
        if bid!='image-primary' and fixture['models'][b['model']]['kind']=='image')
    image_config.write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    image_before=image_config.read_bytes()
    image_scenario=output/'image-scenario.json'
    image_scenario.write_text('{"operation":"text-to-image"}\n',encoding='utf-8')
    def image_quote():
        run([python,'-c',
            'import json; from videocreate.cli import skill_root; from videocreate.config.schema import configuration_schema; '
            'published=json.loads((skill_root()/"assets/schemas/videocreate.config.schema.json").read_text(encoding="utf-8")); '
            'assert published==configuration_schema(); print("Installed published schema matches runtime")'])
        assert json.loads(run([entry,'config','validate','--config',image_config]))['ok']
        filtered=json.loads(run([entry,'providers','filter','--config',image_config,
            '--scenario-file',image_scenario,'--include-excluded']))
        quote=next(row['task_fit']['quote'] for row in filtered['bindings'] if row['id']=='image-primary')
        assert quote['amount']==.05 and quote['calculation']['billed_images']==1
        assert quote['actual_payment']=='unknown'
        compared=json.loads(run([entry,'providers','compare','--config',image_config,
            '--operation','text-to-image','--binding','image-primary','--binding',image_other]))
        assert compared['cards'][0]['quote']['amount']==.05
        assert image_config.read_bytes()==image_before
    image_quote()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    launcher_checks=[]
    def web_smoke(command, label, *, cli_prefix=None):
        server_log = (output/(label+'.log')).open('w', encoding='utf-8')
        process = subprocess.Popen(command if isinstance(command,str) else [str(x) for x in command], cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=server_log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
        origin = 'http://127.0.0.1:'+str(port)
        try:
            for _ in range(160):
                try:
                    with opener.open(origin+'/health', timeout=.2) as response: health = json.load(response)
                    break
                except OSError:
                    if process.poll() is not None: raise RuntimeError(label+' exited')
                    time.sleep(.05)
            else: raise RuntimeError(label+' startup timed out')
            assert health['product']=='VideoCreateConfigWeb' and health['version']=='3.0.0.dev44'
            assert health['mode']=='read-only'
            with opener.open(origin, timeout=2) as response: html=response.read().decode()
            assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
            assert assets
            for resource in assets:
                with opener.open(origin+resource, timeout=2) as response: assert response.read()
            request=urllib.request.Request(origin+'/api/config/summary',headers={'X-VC-Client':'1'})
            with opener.open(request,timeout=2) as response:summary=json.load(response)
            assert Path(summary['config_path'])==config and summary['status']=='valid' and summary['mode']=='read-only'
            reuse = run([*(cli_prefix or [python,'-m','videocreate']), 'config-web', '--config', config,
                         '--port', str(port), '--no-browser', '--read-only'])
            assert 'Traceback' not in reuse
            with opener.open(origin+'/health',timeout=2) as response:assert json.load(response)==health
            assert config.read_bytes()==original
        finally:
            # Windows venv shims have children. Stop this exact test tree only.
            if process.poll() is None:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=log, stderr=subprocess.STDOUT)
            process.wait(timeout=10); server_log.close()
        for _ in range(20):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1):pass
            except OSError:break
            time.sleep(.05)
        else:raise RuntimeError(label+' left its test listener running')
        launcher_checks.append({'entry':label,'config_path_exact':True,'read_only':True,
            'static_resources':len(assets),'same_instance_reused':True,'config_bytes_preserved':True,
            'test_listener_closed':True,'runtime_node_on_path':False})

    web_smoke([web_entry, '--config', config, '--port', str(port), '--no-browser', '--read-only'], 'wheel-entry')
    # The ZIP must work without the wheel masking missing source or resources.
    run([python,'-m','pip','uninstall','--yes','videocreate'])
    assert run([python,'-c',"import importlib.util;print(importlib.util.find_spec('videocreate') is None)"]).strip()=='True'
    extracted = runtime/'技能解压目录 空格 & 路径'; extracted.mkdir()
    with zipfile.ZipFile(skill_zip) as archive:
        for name in archive.namelist():
            assert (extracted/name).resolve().is_relative_to(extracted)
        archive.extractall(extracted)
    zip_cli=[python,extracted/'videocreate/scripts/videocreate.py']
    web_smoke(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
               extracted/'videocreate/scripts/config-web.ps1', '-Python', python, '-Config', config,
               '-Port', str(port), '-NoBrowser', '-ReadOnly'], 'zip-powershell',cli_prefix=zip_cli)
    # cmd /s strips an outer quote pair. Quote every controlled argument and
    # keep that extra pair so Unicode paths containing spaces and & stay data.
    cmd_args=[extracted/'videocreate/scripts/Start-ConfigWeb.cmd','-Python',python,'-Config',config,
              '-Port',str(port),'-NoBrowser','-ReadOnly']
    def cmd_line(arguments):
        assert all(not any(char in str(arg) for char in '\"%!\r\n') for arg in arguments)
        return '"'+str(system_root/'System32/cmd.exe')+'" /d /s /c "'+' '.join('"'+str(arg)+'"' for arg in arguments)+'"'
    command=cmd_line(cmd_args)
    web_smoke(command,'zip-cmd',cli_prefix=zip_cli)
    web_smoke([*zip_cli,'config-web','--config',config,'--port',str(port),'--no-browser','--read-only'],
              'zip-python',cli_prefix=zip_cli)
    for command in (
        ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
         extracted/'videocreate/scripts/config-web.ps1','-Python',python,'-Config',config,
         '-Port','8765','-NoBrowser','-ReadOnly'],
        cmd_line([extracted/'videocreate/scripts/Start-ConfigWeb.cmd','-Python',python,'-Config',config,
                  '-Port','8765','-NoBrowser','-ReadOnly'])):
        rejection=run(command,expected=1)
        assert 'dedicated configuration port' in rejection and 'Traceback' not in rejection
    for artifact, version in ((old,'dev43'),(candidate,'dev44')):
        run([python, '-m', 'pip', 'install', '--no-index', '--no-deps', '--force-reinstall', artifact])
        assert version in run([python, '-m', 'videocreate', 'version'])
        assert config.read_bytes()==original
        if version=='dev43':
            rejected=json.loads(run([python,'-m','videocreate','config','validate','--config',image_config],expected=1))
            assert not rejected['ok'] and any('per_image' in error for error in rejected['errors'])
            assert image_config.read_bytes()==image_before
        else:image_quote()
    run([python, '-m', 'pip', 'check'])
    cast_check = None
    media_check = None
    if args.media_wheelhouse:
        project = cwd/'双人排练'
        run([entry, 'plan', 'init', project, '--title', 'Two character rehearsal'])
        card_file = project/'director.json'
        director = json.loads(card_file.read_text(encoding='utf-8'))
        layout_file = project/'layout.json'
        cells = []
        for shade in ('red', 'blue'):
            run(['ffmpeg', '-v','error', '-f','lavfi', '-i','color=c='+shade+':s=16x16',
                 '-frames:v','1', project/(shade+'.png')])
            director['assets'].append({'id':shade,'kind':'character','description':shade,
                                       'references':[shade+'.png']})
            cells.append({'asset_id':shade})
        card_file.write_text(json.dumps(director),encoding='utf-8')
        layout_file.write_text(json.dumps({'columns':2,'cells':cells}),encoding='utf-8')
        make_sheet = [entry,'media-ref','cast-sheet',project,'--spec',layout_file]
        missing = run(make_sheet,expected=1)
        assert 'Pillow' in missing and 'Traceback' not in missing
        run([python,'-m','pip','install','--no-index','--find-links',args.media_wheelhouse,
             f'videocreate[media]=={report["version"]}'])
        sheet = json.loads(run(make_sheet))
        assert sheet['cells'] == 2 and sheet['paid_creates'] == 0
        path = project/sheet['reference']['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sheet['reference']['sha256']
        measured = json.loads(run(['ffprobe','-v','error','-show_streams','-of','json',path]))['streams'][0]
        assert (measured['width'],measured['height']) == (768,512)
        run([python,'-m','pip','check'])
        cast_check = {'pillow_version':run([python,'-c','import PIL; print(PIL.__version__)']).strip(),
                      'missing_dependency_diagnostic':True, 'cells':2, 'dimensions':[768,512],
                      'sha256':sheet['reference']['sha256']}
        edit_project = cwd/'动作时间与声音版本'
        run([entry,'plan','init',edit_project,'--profile','edit-only'])
        original_video = edit_project/'original.mp4'
        run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=24:d=2',
             '-c:v','libx264','-pix_fmt','yuv420p',original_video])
        run([entry,'production','import-clip',edit_project,'--source',original_video,'--source-id','dance',
             '--start','0','--end','1','--mute'])
        edit_path = edit_project/'timeline.json'
        edit = json.loads(edit_path.read_text(encoding='utf-8'))
        first = edit['segments'][0]
        edit.update(width=64,height=64,fps='24',
                    segments=[{**first,'id':'fast','rate':2}, {**first,'id':'repeat'}])
        edit['audio_tracks'] = []
        for role, frequency in (('dialogue',440),('music',880)):
            sound = edit_project/(role+'.wav')
            run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={frequency}:duration=1.5',sound])
            edit['audio_tracks'].append({'id':role,'kind':role,'path':sound.name,
                'source_in':0,'source_out':1.5,'timeline_start':0})
        edit_path.write_text(json.dumps(edit),encoding='utf-8')
        spec = {'schema_version':1,'source':{'path':original_video.name,
                'sha256':hashlib.sha256(original_video.read_bytes()).hexdigest()},
                'target_job':'dance','tolerance_seconds':1/24,
                'events':[{'id':'beat','source':[0,1],'target':[0,1],'reason':'Speed change and reprise'}]}
        event_file = edit_project/'events.json'
        event_file.write_text(json.dumps(spec),encoding='utf-8')
        mapped = json.loads(run([entry,'timeline','map',edit_project,'--events',event_file]))
        assert [r['timeline'] for r in mapped['events'][0]['occurrences']] == [[0,.5],[.5,1.5]]
        variants = []
        for mode in ('silent','dialogue','music','dialogue-music'):
            value = json.loads(run([entry,'timeline','render',edit_project,
                '--output-name',mode+'.mp4','--audio-output',mode]))
            assert value['media']['has_audio'] == (mode != 'silent')
            assert value['media']['frame_count'] == '36' and value['paid_creates'] == 0
            variants.append({'mode':mode,'sha256':value['sha256'],'media':value['media'],
                             'audio_delivery':value['audio_delivery']})
        page = json.loads(run([entry,'review','compare',edit_project,'--events',event_file,
                               '--output-name','silent.mp4']))
        assert page['events'] == 2 and not page['candidate_has_audio_stream']
        review = json.loads(run([entry,'review','status',edit_project,'--output-name','silent.mp4']))
        assert review['status'] == 'review_pending'
        media_check = {'events':2,'timeline_windows':[[0,.5],[.5,1.5]],'variants':variants,
                       'mapped_review':'review_pending','paid_creates':0}
        study = json.loads(run([entry,'reference','analyze',original_video,'--output',edit_project/'study',
                               '--max-frames','3']))
        source_events = edit_project/'source-events.json'
        run([entry,'reference','events',study['report'],'--output',source_events])
        source_frame=Path(study['report']).parent/'source-frame.jpg'
        run(['ffmpeg','-v','error','-ss','0.25','-i',original_video,'-frames:v','1',source_frame])
        observed = {'reviewer_id':'','observations':[],'participants':[],
                    'events':[{'id':'opening','category':'hook','start':0,'end':1,'participants':[],
                               'evidence_ids':['fixture-frame'],'notes':'Unverified opening source event',
                               'status':'unverified','must_preserve':True}],
                    'evidence':[{'id':'fixture-frame','path':source_frame.relative_to(Path(study['report']).parent).as_posix(),
                        'sha256':hashlib.sha256(source_frame.read_bytes()).hexdigest(),
                        'source_sha256':hashlib.sha256(original_video.read_bytes()).hexdigest(),'at_seconds':0.25}]}
        source_events.write_text(json.dumps(observed),encoding='utf-8')
        draft = json.loads(run([entry,'reference','events',study['report'],'--output',source_events]))
        assert draft['created'] is False and json.loads(source_events.read_text(encoding='utf-8'))['evidence'] == observed['evidence']
        profile = json.loads(run([entry,'reference','profile',study['report'],'--observations',source_events]))
        profile_file = Path(profile['profile'])
        attached = json.loads(run([entry,'reference','attach',edit_project,'--profile',profile_file]))
        attached_profile = edit_project/attached['path']
        old_profile = attached_profile.read_bytes()
        spec.update(schema_version=2, source_profile={'path':attached['path'],
                    'sha256':hashlib.sha256(old_profile).hexdigest()})
        spec['events'][0].update(source_event_id='opening')
        event_file.write_text(json.dumps(spec),encoding='utf-8')
        mapped = json.loads(run([entry,'timeline','map',edit_project,'--events',event_file]))
        assert not mapped['source_event_issues']
        assert mapped['source_profile']['event_coverage']['temporal']['observed_event_seconds'] == 0
        page = json.loads(run([entry,'review','compare',edit_project,'--events',event_file,
                               '--output-name','silent.mp4']))
        compared = json.loads((Path(page['page']).parent/'comparison.json').read_text(encoding='utf-8'))
        assert compared['events'][0]['source_event_id'] == 'opening'
        assert len(compared['timing']['source_profile']['events']) == 1
        frame=compared['timing']['source_profile']['evidence'][0]
        assert hashlib.sha256((edit_project/frame['path']).read_bytes()).hexdigest()==frame['sha256']
        assert compared['source_events'][0]['evidence_ids']==['fixture-frame']
        page_html=Path(page['page']).read_text(encoding='utf-8')
        assert ('"path": "'+frame['path']+'"') in page_html
        playwright_root='C:/Users/FBX/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'
        runtime_node_root = None
        for node_root in ('C:/Users/FBX/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules',
                          'E:/MyFiles/MarineAI/node_global/node_modules'):
            if (Path(node_root)/'playwright/package.json').is_file():
                runtime_node_root=Path(node_root);break
        runtime_chrome=next((p for p in ('C:/Program Files/Google/Chrome/Application/chrome.exe',
            'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe') if Path(p).is_file()),None)
        node=shutil.which('node')
        if (node and runtime_node_root and runtime_chrome
                and os.environ.get('VC_SKIP_EVENT_BROWSER_TEST') != '1'):
            browser_script=output/'verify-event-frames.cjs'
            env['NODE_PATH']=str(runtime_node_root)
            browser_script.write_text("""
const fs=require('fs'),{chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER});
const page=await browser.newPage();const failures=[];page.on('pageerror',e=>failures.push(String(e)));
await page.goto(process.env.VC_EVENT_PAGE);await page.waitForTimeout(500);
const initial=await page.evaluate(()=>({rows:document.querySelectorAll('#sourceRows tr').length,
images:[...document.querySelectorAll('#eventFrames img')].map(i=>({complete:i.complete,width:i.naturalWidth})),
status:document.querySelector('#status').value,coverage:document.querySelector('#sourceCoverage').textContent}));
if(initial.rows!==1||initial.images.length!==1||!initial.images[0].width)throw Error(JSON.stringify(initial));
await page.selectOption('#event','event-1-use-1');await page.click('#sourceRows button:first-of-type');
await page.selectOption('#event','event-1-use-2');await page.locator('#seek').fill('50');
await page.waitForTimeout(200);
const final=await page.evaluate(()=>({rows:document.querySelectorAll('#sourceRows tr').length,
selected:document.querySelector('#event').selectedOptions[0].value,
images:[...document.querySelectorAll('#eventFrames img')].map(i=>i.naturalWidth),
source:document.querySelector('#source').currentTime,candidate:document.querySelector('#candidate').currentTime,
status:document.querySelector('#status').value}));
if(final.rows!==1||final.selected!=='event-1-use-2'||final.images[0]===0||final.status!=='unverified'
||Math.abs(final.source-.75)>.05||Math.abs(final.candidate-.5)>.05)throw Error(JSON.stringify(final));
if(failures.length)throw Error(failures.join('\\n'));
fs.writeFileSync(process.env.VC_EVENT_EVIDENCE,JSON.stringify({initial,final},null,2));
await browser.close()})().catch(e=>{console.error(e);process.exitCode=1});
""",encoding='utf-8')
            browser_log=(output/'event-frame-browser.log').open('w',encoding='utf-8')
            browser_env=dict(env,VC_BROWSER=runtime_chrome,VC_EVENT_PAGE=Path(page['page']).as_uri(),
                             VC_EVENT_EVIDENCE=str(output/'event-frame-browser.json'))
            browser_run=subprocess.run([node,str(browser_script)],cwd=cwd,env=browser_env,
                stdout=browser_log,stderr=subprocess.STDOUT,timeout=90)
            browser_log.close()
            if browser_run.returncode:
                raise RuntimeError('Review-page frame check failed; inspect event-frame-browser.log')
            media_check['source_event_browser']=json.loads((output/'event-frame-browser.json').read_text(encoding='utf-8'))
        else:
            media_check['source_event_browser']='browser-unavailable'
        observed['events'][0]['notes'] = 'Revised source event awaiting playback'
        source_events.write_text(json.dumps(observed),encoding='utf-8')
        revision = json.loads(run([entry,'reference','profile',study['report'],'--observations',source_events]))
        assert attached_profile.read_bytes() == old_profile and revision['profile'] != str(profile_file)
        media_check['source_event_profile'] = {'events':1,'observed_motion_seconds':0,
                                               'evidence_images':1,'immutable_revision':True,'mapped_occurrences':page['events']}
    report = {'ok':True,'candidate_version':'3.0.0.dev44','status':'unreleased',
              'checks':['artifact SHA-256','clean Python 3.9 venv','CLI-only missing-Web diagnostic',
                        'offline locked runtime install','pip check','outside-repo console entry/static resources',
                        'outside-repo installed CLI identity lookup',
                        'installed CLI requested-image quote and dev43 rejects new rate without changing bytes',
                        'same-instance reuse','ZIP Python/PowerShell/CMD launchers without installed wheel',
                        'Unicode/space/ampersand working/config/Python/ZIP paths','runtime PATH without Node/npm',
                        'dev43 -> dev44 -> dev43 -> dev44'],
              'configuration_preserved':True,'installed_stable_replaced':False,'paid_creates':0,
              'runtime_outside_source_checkout': True, 'runtime_directory':str(runtime),
              'cast_sheet_check':cast_check,
              'local_media_check':media_check,
              'catalog_identity':identity_checks,
              'image_pricing':{'requested_images':1,'per_request':.01,'per_image':.04,'estimate':.05,
                  'actual_payment':'unknown','dev44_before_after_rollback':'passed',
                  'installed_published_schema_matches_runtime':True,
                  'dev43_new_field':'rejected','synthetic_config_preserved':True},
              'launchers':launcher_checks,'zip_installed_wheel_absent':True,
              'runtime_dependency_diagnostic':runtime_diagnostic,
              'PowerShell_CMD_invalid_port_exit_code':1,
              'clean_windows_machine':'not-performed'}
    (output/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    log.close(); print(json.dumps(report,indent=2))


if __name__=='__main__': main()
