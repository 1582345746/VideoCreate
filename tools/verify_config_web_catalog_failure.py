"""Browser proof that a failing catalog does not hide independent known documents."""
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

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source',type=Path,default=ROOT/'videocreate/src')
    args=parser.parse_args();output=args.output.resolve();source=args.source.resolve()
    if not output.is_relative_to(ROOT/'_local') or output.exists():
        raise RuntimeError('Choose a fresh evidence directory inside workspace _local')
    if not source.is_relative_to(ROOT) or not (source/'videocreate/config_web/checks.py').is_file():
        raise RuntimeError('Expected a retained workspace source tree')
    output.mkdir();temporary=output/'tmp';temporary.mkdir()
    sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'tests')]
    from test_v3_config import config
    from videocreate.config import management as m
    value=m.migrate(config());uids=list(value['upstreams'])
    matched,unknown=uids[:2]
    value['upstreams'][matched].update(base_url='https://xingapi.top/v1',display_name='已有文档的隔离上游')
    value['upstreams'][unknown].update(base_url='https://unknown.example.test/v1',display_name='没有文档的隔离上游')
    for upstream in value['upstreams'].values():upstream['auth']={'type':'bearer','api_key':'catalog-failure-private-fixture-key'}
    for identity, remote, kind in (('draft-exact', 'seedance2.5-V', 'video'),
                                   ('draft-case', 'seedance2.5-v', 'video'),
                                   ('draft-image', 'Unknown-image', 'image')):
        value=m.add_binding(value,identity=identity,upstream=matched,model=identity,
                            remote_model=remote,family='unknown',kind=kind)
        value['bindings'][identity]['declared_capabilities']={
            'summary':'声明不能补成合同', 'source':{'kind':'catalog'}, 'resolutions':['720p']}
    (output/'config.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'scenario.json').write_text('{"mode":"404"}',encoding='utf-8')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    assert port!=8765
    origin='http://127.0.0.1:'+str(port)
    # This injection belongs only to the disposable server process. No product
    # debug endpoints, arbitrary proxy URL or paid-call switch are introduced.
    server=output/'server.py'
    server.write_text(
        'import json,os,sys\nfrom pathlib import Path\n'
        'folder=Path(os.environ["VC_WEB_FIXTURE_DIR"])\n'
        'def guard(event,args):\n'
        '    if event in {"socket.connect","socket.getaddrinfo"}:\n'
        '        address=args[1] if event=="socket.connect" else args[0]\n'
        '        host=address[0] if isinstance(address,tuple) else address\n'
        '        if host not in {"127.0.0.1","localhost","::1",None}:\n'
        '            with (folder/"external-attempts.jsonl").open("a",encoding="utf-8") as log:log.write("{}\\n")\n'
        '            raise RuntimeError("External access forbidden in catalog failure verification")\n'
        'sys.addaudithook(guard)\n'
        'from videocreate.config.storage import ConfigError\n'
        'from videocreate.catalog import discovery\n'
        'def failure(*args,**kwargs):\n'
        '    mode=json.loads((folder/"scenario.json").read_text(encoding="utf-8"))["mode"]\n'
        '    with (folder/"discovery-calls.jsonl").open("a",encoding="utf-8") as log:log.write(json.dumps({"mode":mode})+"\\n")\n'
        '    message={"timeout":"read failed","credentials":"credential unavailable"}.get(mode,"HTTP "+mode)\n'
        '    raise ConfigError(message+" catalog-failure-private-fixture-key catalog-failure-private-exception")\n'
        'discovery.models=failure\n'
        'from videocreate.config_web.launcher import launch\n'
        'launch(folder/"config.json",port=int(os.environ["VC_WEB_TEST_PORT"]),browser=False,read_only=False)\n',encoding='utf-8')
    env=dict(os.environ);env.update(PYTHONPATH=str(source),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',
        TEMP=str(temporary),TMP=str(temporary),VIDEOCREATE_CONFIG_DIR=str(output/'unused'),GVS_CONFIG_DIR=str(output/'legacy'),
        VC_WEB_FIXTURE_DIR=str(output),VC_WEB_TEST_ORIGIN=origin,VC_WEB_TEST_PORT=str(port),
        VC_WEB_MATCHED_UPSTREAM=matched,VC_WEB_UNKNOWN_UPSTREAM=unknown)
    server_log=(output/'server.log').open('w',encoding='utf-8')
    process=subprocess.Popen([sys.executable,'-B','-X','utf8',server],cwd=output,env=env,
                             stdin=subprocess.DEVNULL,stdout=server_log,stderr=subprocess.STDOUT)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));completed=False
    try:
        for _ in range(150):
            try:
                with opener.open(origin+'/health',timeout=.2) as response:health=json.load(response)
                assert health['product']=='VideoCreateConfigWeb';break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('Synthetic app startup timeout')
        with (output/'browser.log').open('w',encoding='utf-8') as log:
            result=subprocess.run(['C:/Program Files/nodejs/node.exe',ROOT/'tools/verify_config_web_catalog_failure.cjs'],
                                  cwd=output,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        if result.returncode:raise RuntimeError('Catalog failure browser verification failed; inspect browser.log')
        browser=json.loads((output/'browser/result.json').read_text(encoding='utf-8'))
        attempts=output/'external-attempts.jsonl'
        assert not attempts.exists() or not attempts.read_bytes()
        calls=(output/'discovery-calls.jsonl').read_text(encoding='utf-8').splitlines()
        assert len(calls)==browser['discovery_calls']==7
        completed=True
    finally:
        if process.poll() is None:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=server_log,stderr=subprocess.STDOUT,check=True)
        process.wait(timeout=10);server_log.close()
        with socket.socket() as probe:assert probe.connect_ex(('127.0.0.1',port))!=0
        if not completed:
            (output/'failure.json').write_text(json.dumps({'ok':False,'synthetic_service_stopped':True,
                'source':str(source),'paid_creates':0,'existing_8765_touched':False},indent=2),encoding='utf-8')
    # All writers are closed before producing the source/log evidence inventory.
    report={'ok':True,'source':str(source.relative_to(ROOT)),
            'checks_source_sha256':hashlib.sha256((source/'videocreate/config_web/checks.py').read_bytes()).hexdigest(),
            'browser':browser,'discovery':'in-process injected failures; no actual provider GET or credential resolution',
            'external_network_attempts':0,'synthetic_service_stopped':True,'existing_8765_touched':False,'paid_creates':0}
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
