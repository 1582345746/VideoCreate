"""Lost-browser discovery and real process races, using synthetic drafts only."""
import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

import test_config_web_drafts as fixture
from videocreate.config.storage import atomic_json, load_json
from videocreate.config_web.drafts import Drafts
from videocreate.config_web.errors import WebError
from videocreate.config_web.service import ConfigService


class DraftConcurrencyTests(unittest.TestCase):
    setUp = fixture.WebFormDraftTests.setUp
    save = fixture.WebFormDraftTests.save
    binding = fixture.WebFormDraftTests.binding
    defaults = fixture.WebFormDraftTests.defaults
    def test_discovery_is_metadata_only_paginated_and_config_scoped(self):
        before = self.path.read_bytes()
        saved = [self.save(self.binding()), self.save(self.defaults()), self.save({
            'mode':'create','id':'','url':'https://private-draft.test/v1','name':'PRIVATE-NAME','notes':'PRIVATE-NOTE'})]
        restarted = Drafts(ConfigService(self.path))
        first = restarted.list({'limit':2}, session='new-browser')
        second = restarted.list({'limit':2,'cursor':first['next_cursor']}, session='new-browser')
        rows = first['drafts'] + second['drafts']
        self.assertEqual(len(rows),3); self.assertIsNone(second['next_cursor'])
        self.assertEqual({r['draft_token'] for r in rows},{r['draft_token'] for r in saved})
        self.assertEqual({r['kind'] for r in rows},{'upstream','defaults','binding'})
        for row in rows:
            self.assertEqual(set(row),{'draft_token','draft_version','kind','updated_at','expires_at','status'})
            self.assertEqual(row['status'],'available')
        encoded = json.dumps(rows)
        for forbidden in ('PRIVATE-', 'private-draft', '未保存中文', 'owner', 'source_token', str(self.path), 'form'):
            self.assertNotIn(forbidden, encoded)
        foreign = Drafts(ConfigService(self.path.with_name('another.json')))
        self.assertEqual(foreign.list({},session='new')['drafts'],[])
        self.assertEqual(self.path.read_bytes(),before)
        for bad in ({'limit':True},{'limit':51},{'cursor':'../config'},{'path':str(self.path)}):
            with self.assertRaises(WebError): restarted.list(bad,session='new')

    def test_stale_save_claim_discard_and_resurrection_are_rejected(self):
        before = self.path.read_bytes(); initial = self.save(self.binding())
        token, version = initial['draft_token'], initial['draft_version']
        claim = self.drafts.load({'draft_token':token,'claim':True,'expected_version':version},session='one')
        self.assertNotEqual(version,claim['draft_version'])  # Same cookie still changes version.
        latest = self.drafts.path(token).read_bytes()
        calls = [lambda:self.save(self.binding(),token=token,version=version),
                 lambda:self.drafts.load({'draft_token':token,'claim':True,'expected_version':version},session='one'),
                 lambda:self.drafts.discard({'draft_token':token,'expected_version':version},session='one'),
                 lambda:self.save(self.binding(),token=token)]
        for call in calls:
            with self.assertRaises(WebError) as caught: call()
            self.assertEqual(caught.exception.code,'draft_conflict'); self.assertEqual(caught.exception.status,409)
            self.assertEqual(self.drafts.path(token).read_bytes(),latest)
        self.drafts.discard({'draft_token':token,'expected_version':claim['draft_version']},session='one')
        with self.assertRaises(WebError) as caught: self.save(self.binding(),token=token,version=claim['draft_version'])
        self.assertEqual(caught.exception.code,'draft_conflict'); self.assertFalse(self.drafts.path(token).exists())
        self.assertTrue(self.drafts.discard({'draft_token':token,'expected_version':version},session='one')['discarded'])
        self.assertEqual(self.path.read_bytes(),before)

    def test_damaged_expired_and_future_drafts_preserved_until_exact_discard(self):
        result = self.save(self.binding()); token = result['draft_token']; target = self.drafts.path(token)
        original = load_json(target)
        cases = [(b'{"auth":"PRIVATE-DAMAGE",','unavailable'),
                 (b'x'*(512*1024+1),'unavailable'),
                 (json.dumps({**original,'expires_at':0}).encode(),'expired'),
                 (json.dumps({**original,'form_version':99}).encode(),'unsupported'),
                 (json.dumps({**original,'form_version':[]}).encode(),'unsupported'),
                 (json.dumps({**original,'omitted_sections':[{}]}).encode(),'unavailable')]
        for raw,status in cases:
            with self.subTest(status=status,size=len(raw)):
                target.write_bytes(raw)
                row = self.drafts.list({},session='new')['drafts'][0]
                self.assertEqual(row['status'],status); self.assertEqual(row['kind'],'unknown')
                self.assertEqual(row['draft_version'],hashlib.sha256(raw).hexdigest())
                self.assertNotIn('PRIVATE-DAMAGE',json.dumps(row))
                with self.assertRaises(WebError): self.drafts.load({'draft_token':token},session='new')
                with self.assertRaises(WebError): self.drafts.discard({'draft_token':token,'expected_version':result['draft_version']},session='new')
                self.assertEqual(target.read_bytes(),raw)
                self.drafts.discard({'draft_token':token,'expected_version':row['draft_version']},session='new')
                self.assertFalse(target.exists())

    def test_read_only_can_discover_and_read_but_cannot_claim_or_discard(self):
        result = self.save(self.defaults()); before = self.drafts.path(result['draft_token']).read_bytes()
        readonly = Drafts(ConfigService(self.path))
        row = readonly.list({},session='new')['drafts'][0]
        self.assertEqual(readonly.load({'draft_token':row['draft_token']},session='new')['form'],self.defaults())
        for operation in ('claim','discard'):
            packet = {'draft_token':row['draft_token'],'expected_version':row['draft_version']}
            with self.assertRaises(WebError) as caught:
                if operation == 'claim': readonly.load({**packet,'claim':True},session='new')
                else: readonly.discard(packet,session='new')
            self.assertEqual(caught.exception.status,403)
        self.assertEqual(self.drafts.path(result['draft_token']).read_bytes(),before)

    def test_two_real_processes_have_one_winner_without_configuration_writes(self):
        result = self.save(self.defaults()); before = self.path.read_bytes()
        worker = '''import json,sys,time
from pathlib import Path
from videocreate.config_web.drafts import Drafts
from videocreate.config_web.service import ConfigService
from videocreate.config_web.errors import WebError
p,token,version,source,label,ready,gate=sys.argv[1:]
d=Drafts(ConfigService(Path(p),read_only=False))
Path(ready).write_text('ready');deadline=time.monotonic()+15
while not Path(gate).exists():
    if time.monotonic()>deadline:raise RuntimeError('Barrier timeout')
    time.sleep(.01)
try:
    r=d.save({'draft_token':token,'expected_version':version,'source_token':source,'form':{'kind':'defaults','image':{'binding':label,'policy':'ask'},'video':{'binding':'','policy':'ask'}}},session='one')
    print(json.dumps({'status':200,'label':label,'version':r['draft_version']}))
except WebError as e:print(json.dumps({'status':e.status,'code':e.code,'label':label}))
'''
        processes = []
        gate = self.path.parent/'go'
        try:
            for label in ('writer-a','writer-b'):
                args = [sys.executable,'-B','-X','utf8','-c',worker,str(self.path),result['draft_token'],result['draft_version'],self.source,label,str(self.path.parent/label),str(gate)]
                processes.append(subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ)))
            deadline = time.monotonic()+10
            while not all((self.path.parent/name).exists() for name in ('writer-a','writer-b')):
                self.assertLess(time.monotonic(),deadline,'Child process barrier timed out'); time.sleep(.01)
            gate.write_text('go')
            reports=[]
            for process in processes:
                stdout,stderr=process.communicate(timeout=20)
                self.assertEqual(process.returncode,0,stderr); self.assertEqual(stderr,'')
                reports.append(json.loads(stdout))
            self.assertEqual(sorted(r['status'] for r in reports),[200,409])
            winner=next(r for r in reports if r['status']==200)
            self.assertEqual(next(r for r in reports if r['status']==409)['code'],'draft_conflict')
            final=self.drafts.load({'draft_token':result['draft_token']},session='one')
            self.assertEqual(final['form']['image']['binding'],winner['label'])
            self.assertEqual(final['draft_version'],winner['version']); self.assertEqual(self.path.read_bytes(),before)
        finally:
            for process in processes:
                if process.poll() is None: process.kill(); process.communicate(timeout=5)


if __name__ == '__main__': unittest.main()
