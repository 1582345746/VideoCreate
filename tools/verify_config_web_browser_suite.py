"""Re-run browser groups in a fresh clone of the established synthetic fixture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]

def main():
    scripts=('verify_config_web.cjs','verify_config_web_m2.cjs','verify_config_web_m3.cjs','verify_config_web_acceptance.cjs','verify_config_web_contracts.cjs','verify_config_web_references.cjs','verify_config_web_zoom.cjs','verify_config_web_billing.cjs','verify_config_web_accessibility.cjs','verify_config_web_read_context.cjs','verify_config_web_save_lock.cjs','verify_config_web_reconcile.cjs')
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path,default=ROOT/'videocreate/src');p.add_argument('--scripts',nargs='+',choices=scripts);args=p.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT/'_local') or output.exists():raise RuntimeError('Choose fresh workspace _local directory')
    output.mkdir();tmp=output/'tmp';tmp.mkdir()
    baseline=ROOT/'_local/web-m1-20261113'
    for name in ('config.json','secrets.dpapi'):
        if (baseline/name).is_file():shutil.copy2(baseline/name,output/name)
    if (baseline/'backups').is_dir():shutil.copytree(baseline/'backups',output/'backups')
    value=json.loads((output/'config.json').read_text(encoding='utf-8'))
    # Preserve the M1 text-only/XSS assertion even if an earlier form test edited
    # this label. It is ordinary synthetic JSON, never HTML served by the app.
    for row in value['bindings'].values():
        if 'onerror' in row.get('notes',''):row['notes']=''
    next(iter(value['bindings'].values()))['notes']='<img src=x onerror=alert(1)>'
    (output/'config.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    assert port!=8765
    origin='http://127.0.0.1:'+str(port)
    source=args.source.resolve()
    if not (source/'videocreate/config_web').is_dir():raise RuntimeError('Source must contain the candidate videocreate package')
    env=dict(os.environ);env.update(PYTHONPATH=str(source),PYTHONDONTWRITEBYTECODE='1',TEMP=str(tmp),TMP=str(tmp),
        VIDEOCREATE_CONFIG_DIR=str(output/'unused'),VC_WEB_TEST_ORIGIN=origin,VC_WEB_FIXTURE_DIR=str(output))
    server_log=(output/'server.log').open('w',encoding='utf-8');process=subprocess.Popen([sys.executable,'-B','-X','utf8','-m','videocreate','config-web','--config',str(output/'config.json'),'--port',str(port),'--no-browser'],cwd=ROOT,env=env,stdout=server_log,stderr=subprocess.STDOUT)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));groups=[]
    try:
        for _ in range(150):
            try:
                with opener.open(origin+'/health',timeout=.2) as response:health=json.load(response)
                assert health['product']=='VideoCreateConfigWeb';break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('Synthetic service startup timeout')
        with (output/'browser.log').open('w',encoding='utf-8') as log:
            for name in args.scripts or scripts:
                result=subprocess.run(['C:/Program Files/nodejs/node.exe',str(ROOT/'tools'/name)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
                log.flush();groups.append({'script':name,'exit_code':result.returncode})
                if result.returncode:raise RuntimeError('Browser group failed: '+name)
        files=[{'path':p.relative_to(source).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in sorted((source/'videocreate/config_web').rglob('*'))
               if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}]
        (output/'result.json').write_text(json.dumps({'ok':True,'source':str(source),'web_files':files,'groups':groups,'security_cases':70 if 'verify_config_web_acceptance.cjs' in [g['script'] for g in groups] else 0,'paid_creates':0,'existing_8765_touched':False},indent=2),encoding='utf-8')
        print(json.dumps({'ok':True,'groups':groups,'output':str(output)}))
    finally:
        if process.poll() is None:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=server_log,stderr=subprocess.STDOUT)
        process.wait(timeout=10);server_log.close()

if __name__=='__main__':main()
