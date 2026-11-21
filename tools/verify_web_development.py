"""Whole-source offline regression with isolated config roots and loopback only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def worker(kind, output):
    import tempfile
    import unittest
    sys.path[:0] = [str(ROOT/'videocreate/src'), str(ROOT/'tests')]
    tempfile.tempdir = str(output/'tmp')
    attempts = []
    if kind == 'core':
        # Core media tests require the established Pillow/FFmpeg runtime; the
        # optional minimal Web venv intentionally need not provide Pillow.
        try:
            from PIL import Image
        except ImportError:
            raise RuntimeError('Core regression needs Pillow; use the established full Python environment, not the minimal Web venv') from None
        Image.new('RGB',(1,1))
    def guard(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = args[1] if event == 'socket.connect' else args[0]
            host = address[0] if isinstance(address, tuple) else address
            if host not in {'localhost','127.0.0.1','::1',None}:
                attempts.append(event)
                raise RuntimeError('Regression allows loopback only; external network blocked')
    sys.addaudithook(guard)
    modules = [p.stem for p in sorted((ROOT/'tests').glob('test_*.py'))
               if p.stem.startswith('test_config_web') == (kind == 'web')]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in modules)
    start = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'group':kind,'python':sys.executable,'python_version':sys.version.split()[0],
              'modules':modules,'tests':result.testsRun,
              'failures':[t.id() for t,_ in result.failures], 'errors':[t.id() for t,_ in result.errors],
              'skips':[t.id() for t,_ in result.skipped], 'external_network_attempts_blocked':len(attempts),
              'seconds':round(time.monotonic()-start,3), 'paid_creates':0}
    (output/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return 0 if result.wasSuccessful() and not attempts else 1


def main():
    p=argparse.ArgumentParser();p.add_argument('kind',choices=['core','web']);p.add_argument('--output',type=Path,required=True);p.add_argument('--worker',action='store_true')
    args=p.parse_args();output=args.output.resolve()
    if not output.is_relative_to(ROOT/'_local'):
        raise RuntimeError('Regression evidence must stay inside workspace _local')
    if not args.worker and output.exists():
        raise RuntimeError('Choose a fresh evidence directory; previous results are retained')
    (output/'tmp').mkdir(parents=True,exist_ok=True)
    if args.worker:return worker(args.kind,output)
    env=dict(os.environ);env.update(PYTHONDONTWRITEBYTECODE='1',TEMP=str(output/'tmp'),TMP=str(output/'tmp'),
        VIDEOCREATE_CONFIG_DIR=str(output/'isolated-config'),GVS_CONFIG_DIR=str(output/'isolated-legacy'),
        PYTHONPATH=os.pathsep.join([str(ROOT/'videocreate/src'),str(ROOT/'tests')]))
    with (output/'tests.log').open('w',encoding='utf-8') as stream:
        result=subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),args.kind,'--output',str(output),'--worker'],
                              cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    if (output/'result.json').is_file():print((output/'result.json').read_text(encoding='utf-8'))
    else:print('Regression interrupted; inspect '+str(output/'tests.log'))
    return result.returncode


if __name__=='__main__':raise SystemExit(main())
