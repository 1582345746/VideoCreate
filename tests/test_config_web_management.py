"""Web recovery, defaults and document/catalog integration with isolated data."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.catalog import observations, contracts
from videocreate.config import management as m, repair
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.config_web.changes import Changes
from videocreate.config_web.checks import Checks
from videocreate.config_web.errors import WebError
from videocreate.config_web.service import ConfigService


class WebManagementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'config.json'
        self.value = m.migrate(config()); atomic_json(self.path, self.value)
        self.service = ConfigService(self.path, read_only=False)
        self.changes = Changes(self.service)
        self.uid = next(iter(self.value['upstreams']))

    def preview(self, operation, values, identity=None, token=None):
        return self.changes.preview({'operation': operation, 'values': values, 'id': identity,
            'expected_token': token or m.load(self.path)['token']}, session='one')

    def commit(self, preview):
        return self.changes.commit({'preview_token': preview['preview_token']}, session='one')

    def backup(self):
        identity = m.fingerprint(self.value)
        atomic_json(self.path.parent / 'backups' / ('config-' + identity + '.json'), self.value)
        return identity

    def test_only_matching_valid_backup_ids_are_listed_without_paths_or_old_keys(self):
        identity = self.backup()
        atomic_json(self.path.parent/'backups'/'other-config.json', self.value)
        atomic_json(self.path.parent/'backups'/('config-'+'0'*64+'.json'), self.value)
        report = self.changes.backups.inspect()
        self.assertEqual([b['id'] for b in report['backups']], [identity])
        self.assertNotIn('test-only-value', json.dumps(report))
        self.assertNotIn('auth', json.dumps(report))
        for bad in ['../config', str(self.path), 'x'*64, '0'*64]:
            with self.assertRaises((WebError, ConfigError)):
                self.preview('config.restore', {'backup_id': bad})

    def test_restore_retains_later_identities_archived_and_old_task_snapshots(self):
        identity = self.backup()
        later = copy.deepcopy(self.value)
        later['upstreams']['later-account'] = copy.deepcopy(later['upstreams'][self.uid])
        m.save(self.path, later, expected_token=m.fingerprint(self.value))
        result = self.commit(self.preview('config.restore', {'backup_id': identity}))
        self.assertTrue(result['ok'])
        value = load_json(self.path)
        self.assertTrue(value['upstreams']['later-account']['archived'])
        self.assertEqual(value['upstreams'][self.uid], self.value['upstreams'][self.uid])

    def test_backup_changed_after_preview_cannot_commit(self):
        identity = self.backup()
        p = self.preview('config.restore', {'backup_id': identity})
        target, _ = self.changes.backups.get(identity)
        target.write_text('{}', encoding='utf-8')
        original = self.path.read_bytes()
        with self.assertRaises(WebError): self.commit(p)
        self.assertEqual(self.path.read_bytes(), original)

    def test_corrupt_original_never_reaches_browser_and_exact_bytes_are_preserved(self):
        identity = self.backup()
        raw = b'\xef\xbb\xbf{"schema_version":4,"key":"private-corrupt-key",\r\n}'
        self.path.write_bytes(raw)
        report = self.changes.backups.inspect()
        self.assertTrue(report['can_repair'])
        p = self.preview('config.repair', {'backup_id': identity}, token=report['source_token'])
        self.assertNotIn('private-corrupt-key', json.dumps([report, p]))
        self.assertFalse(p['original_structure_verified'])
        self.commit(p)
        original = self.path.parent/'backups'/('config-damaged-'+repair.sha(raw)+'.raw')
        self.assertEqual(original.read_bytes(), raw)
        self.assertEqual(load_json(self.path)['revision'], 1)

    def test_repair_source_change_and_future_schema_do_not_write(self):
        identity = self.backup()
        self.path.write_text('{"schema_version":4,}', encoding='utf-8')
        source = self.changes.backups.inspect()['source_token']
        p = self.preview('config.repair', {'backup_id': identity}, token=source)
        self.path.write_text('{"schema_version":99,}', encoding='utf-8')
        with self.assertRaises(WebError): self.commit(p)
        self.assertFalse(self.changes.backups.inspect()['can_repair'])
        with self.assertRaises(ConfigError): self.preview('config.repair', {'backup_id': identity}, token=repair.sha(self.path.read_bytes()))

    def test_repair_lost_response_reconciles_without_replacing_again(self):
        identity = self.backup(); self.path.write_text('{"schema_version":4,}', encoding='utf-8')
        p = self.preview('config.repair', {'backup_id': identity}, token=repair.sha(self.path.read_bytes()))
        real = repair.apply
        def lost(*args, **kw):
            real(*args, **kw); raise OSError('lost response')
        with mock.patch('videocreate.config_web.changes.repair.apply', side_effect=lost):
            with self.assertRaises(OSError): self.commit(p)
        saved = self.path.read_bytes()
        restarted = Changes(self.service)
        self.assertEqual(restarted.status({'preview_token':p['preview_token']})['status'], 'committed')
        with mock.patch('videocreate.config_web.changes.repair.apply', side_effect=AssertionError('No replay')):
            result = restarted.commit({'preview_token':p['preview_token']}, session='new')
        self.assertTrue(result['recovered']); self.assertEqual(self.path.read_bytes(), saved)

    def test_configurations_in_same_folder_do_not_share_receipts(self):
        p = self.preview('upstream.update', {'name':'changed'}, self.uid); self.commit(p)
        other = ConfigService(self.path.with_name('second.json'), read_only=False)
        self.assertEqual(Changes(other).status({'preview_token':p['preview_token']})['status'], 'not-submitted')

    def test_independent_defaults_and_disabled_draft_exclusion(self):
        image = next(bid for bid, b in self.value['bindings'].items() if self.value['models'][b['model']]['kind']=='image')
        video = next(bid for bid, b in self.value['bindings'].items() if self.value['models'][b['model']]['kind']=='video')
        p = self.preview('defaults.update', {'image': {'binding':image,'policy':'use-default'},
                                             'video': {'binding':video,'policy':'ask'}})
        self.commit(p)
        choices = self.service.catalog()['defaults']
        self.assertEqual(choices['image'], {'binding':image, 'policy':'use-default'})
        self.assertEqual(choices['video'], {'binding':video, 'policy':'ask'})
        with self.assertRaises(WebError): self.preview('defaults.update', {'video':{'binding':image,'policy':'ask'}})
        self.commit(self.preview('binding.update', {'enabled':False}, image))
        with self.assertRaises(WebError): self.preview('defaults.update', {'image':{'binding':image,'policy':'use-default'}})
        self.assertFalse(next(b for b in self.service.catalog()['bindings'] if b['id']==image)['default_eligible'])

    def test_optional_price_claim_clears_to_unknown_without_changing_binding_identity(self):
        identity = next(iter(self.value['bindings']))
        original = copy.deepcopy(self.value['bindings'][identity])
        self.commit(self.preview('binding.update', {'listed_pricing':{'unit':'second','amount':0.25,'currency':'USD'},
                                                   'pricing':{'currency':'USD','per_second':0.2}}, identity))
        self.commit(self.preview('binding.update', {'listed_pricing':None,'pricing':None}, identity))
        saved = load_json(self.path)['bindings'][identity]
        self.assertNotIn('listed_pricing', saved); self.assertNotIn('pricing', saved)
        for key in ('upstream','model','remote_model','adapter','operations','enabled'):
            self.assertEqual(saved[key],original[key])
        row = next(b for b in self.service.catalog()['bindings'] if b['id']==identity)
        self.assertEqual(row['price_text'], '未录入')
        from videocreate.catalog.bindings import configured_binding
        from videocreate.runtime.budget import estimate
        self.assertIsNone(estimate(configured_binding(load_json(self.path), identity), 5, 'USD'))

    def test_null_nonoptional_field_is_still_rejected_without_writing(self):
        before = self.path.read_bytes()
        for key in ('enabled','remote_model','adapter','operations','notes'):
            with self.assertRaises(WebError):
                self.preview('binding.update', {key:None}, next(iter(self.value['bindings'])))
        self.assertEqual(self.path.read_bytes(),before)

    def test_web_price_tiers_keep_units_rounding_unknown_and_expiry_contracts(self):
        from videocreate.catalog.bindings import configured_binding
        from videocreate.runtime.budget import estimate
        identity = next(bid for bid,b in self.value['bindings'].items() if 'text-to-video' in b['operations'])
        pricing = {'currency':'CNY','status':'confirmed','minimum_seconds':5,'round_seconds':2,
                   'tiers':[{'when':{'resolution':'720p'},'per_second':0.2},
                            {'when':{'resolution':'1080p'},'per_second':0.4}]}
        def rate(prices, currency='CNY', parameters=None):
            self.commit(self.preview('binding.update', {'pricing':prices}, identity))
            return estimate(configured_binding(load_json(self.path),identity),3,currency,parameters=parameters)
        self.assertAlmostEqual(rate(pricing, parameters={'resolution':'720p'}),1.2)
        self.assertIsNone(rate(pricing,currency='USD',parameters={'resolution':'720p'}))
        self.assertIsNone(rate(pricing))
        ambiguous = copy.deepcopy(pricing); ambiguous['tiers'].append(copy.deepcopy(ambiguous['tiers'][0]))
        self.assertIsNone(rate(ambiguous, parameters={'resolution':'720p'}))
        expired = {**pricing,'valid_until':'2000-01-01T00:00:00+00:00'}
        self.assertIsNone(rate(expired, parameters={'resolution':'720p'}))
        self.assertIsNone(rate({**pricing,'status':'unverified'}, parameters={'resolution':'720p'}))

    def test_prepared_callback_failure_leaves_config_and_backups_untouched(self):
        old = self.path.read_bytes(); candidate = copy.deepcopy(self.value); candidate['defaults']['resolution']='1080p'
        with self.assertRaises(OSError):
            m.save(self.path, candidate, expected_token=m.fingerprint(self.value),
                   on_prepared=mock.Mock(side_effect=OSError('journal full')))
        self.assertEqual(self.path.read_bytes(), old)
        self.assertFalse((self.path.parent/'backups').exists())

    def test_cached_catalog_is_local_import_is_disabled_exact_and_idempotent(self):
        observed = observations.record(self.value, self.uid, ['Exact / CASE-V'], store_root=self.path.parent)
        with mock.patch('urllib.request.build_opener', side_effect=AssertionError('no network')):
            report = Checks(self.service).read({'upstream':self.uid})
            p = self.preview('catalog.import', {'ids':['Exact / CASE-V'],'kind':'video',
                'observation_id':report['observation_id']}, self.uid)
            self.commit(p)
            self.commit(self.preview('catalog.import', {'ids':['Exact / CASE-V'],'kind':'video',
                'observation_id':report['observation_id']}, self.uid))
        added = [b for b in load_json(self.path)['bindings'].values() if b['remote_model']=='Exact / CASE-V']
        self.assertEqual(len(added), 1); self.assertFalse(added[0]['enabled'])
        self.assertEqual(added[0]['adapter'], 'unconfigured')
        self.assertNotIn('account_id', json.dumps(report)); self.assertNotIn('test-only-value', json.dumps(report))

    def test_catalog_check_failures_are_safe_and_never_undo_saved_config(self):
        original = self.path.read_bytes()
        for message, status in [('HTTP 404','not-supported'),('HTTP 401','unauthorized'),('HTTP 302','redirect-blocked'),('read failed','read-failed')]:
            with mock.patch('videocreate.config_web.checks.discovery.models', side_effect=ConfigError(message+' private-error')):
                report = Checks(self.service).read({'upstream':self.uid}, refresh=True)
            self.assertEqual(report['status'], status); self.assertNotIn('private-error', json.dumps(report))
        self.assertEqual(self.path.read_bytes(), original)

    def test_imported_drafts_explain_missing_contract_without_inheriting_claims(self):
        expected = {'video': ['protocol', 'operations', 'duration', 'resolutions', 'aspect_ratios'],
                    'image': ['protocol', 'operations', 'image_sizes', 'output_formats']}
        for kind, codes in expected.items():
            remote = 'Exact / CASE-' + kind
            observations.record(load_json(self.path), self.uid, [remote], store_root=self.path.parent)
            with mock.patch('urllib.request.build_opener', side_effect=AssertionError('No network')), \
                 mock.patch('videocreate.config.storage.resolve_key', side_effect=AssertionError('No key lookup')):
                report = Checks(self.service).read({'upstream': self.uid})
                self.commit(self.preview('catalog.import', {'ids': [remote], 'kind': kind,
                    'observation_id': report['observation_id']}, self.uid))
                row = next(b for b in self.service.catalog()['bindings'] if b['remote_model'] == remote)
                self.commit(self.preview('binding.update', {'declared_capabilities': {
                    'summary': 'All sizes and references advertised', 'source': {'kind': 'screenshot'},
                    'resolutions': ['720p'], 'duration': {'maximum': 30}}}, row['id']))
                before = self.path.read_bytes()
                row = next(b for b in self.service.catalog()['bindings'] if b['id'] == row['id'])
            self.assertEqual([g['code'] for g in row['setup_gaps']], codes)
            self.assertTrue(all(g['message'] for g in row['setup_gaps']))
            self.assertFalse(row['enabled']); self.assertFalse(row['default_eligible'])
            self.assertEqual(row['adapter'], 'unconfigured'); self.assertEqual(row['operations'], [])
            self.assertNotIn('capability_overrides', row)
            self.assertEqual(self.path.read_bytes(), before)

    def test_draft_guidance_tracks_explicit_fields_and_exact_document_scope(self):
        self.value['upstreams'][self.uid]['base_url'] = 'https://xingapi.top/v1'
        for remote in ('seedance2.5-V', 'seedance2.5-v'):
            self.value = m.add_binding(self.value, identity=remote, model=remote, upstream=self.uid,
                                      remote_model=remote, family='seedance', kind='video')
        atomic_json(self.path, self.value)
        self.commit(self.preview('binding.update', {'adapter': 'xingapi-video-v1',
            'operations': ['text-to-video'], 'capability_overrides': {
                'duration': {'minimum': 5, 'maximum': 30, 'step': 1}, 'resolutions': ['720p']}}, 'seedance2.5-v'))
        row = next(b for b in self.service.catalog()['bindings'] if b['id'] == 'seedance2.5-v')
        self.assertEqual([g['code'] for g in row['setup_gaps']], ['aspect_ratios'])
        self.commit(self.preview('binding.update', {'capability_overrides': {
            **row['capability_overrides'], 'aspect_ratios': ['9:16']}}, row['id']))
        row = next(b for b in self.service.catalog()['bindings'] if b['id'] == row['id'])
        self.assertEqual([g['code'] for g in row['setup_gaps']], ['review'])
        self.assertFalse(row['default_eligible'])
        lowercase_before = load_json(self.path)['bindings']['seedance2.5-v']
        recipe = contracts.available(load_json(self.path), self.uid)[0]
        self.commit(self.preview('contract.apply', {'contract_id': recipe['id'], 'revision': recipe['revision']}, self.uid))
        packet = self.service.catalog()
        documented = next(b for b in packet['bindings'] if b['id'] == 'seedance2.5-V')
        self.assertEqual(documented['setup_gaps'], [])
        self.assertEqual(documented['operations'], ['text-to-video'])
        self.assertTrue(documented['default_eligible'])
        self.assertEqual(load_json(self.path)['bindings']['seedance2.5-v'], lowercase_before)

    def test_disabled_typed_operations_explain_unknown_reference_contract(self):
        self.value = m.add_binding(self.value, identity='typed', model='typed', upstream=self.uid,
                                  remote_model='typed', family='unknown', kind='video')
        binding = self.value['bindings']['typed']
        binding.update(adapter='xingapi-video-v2', operations=['reference-to-video'], setup_status='configured')
        atomic_json(self.path, self.value); before = self.path.read_bytes()
        row = next(b for b in self.service.catalog()['bindings'] if b['id'] == 'typed')
        self.assertEqual([g['code'] for g in row['setup_gaps']], ['reference_limits'])
        with self.assertRaises(WebError):
            self.preview('binding.update', {'enabled': True}, 'typed')
        self.assertFalse(row['default_eligible']); self.assertEqual(self.path.read_bytes(), before)

    def test_catalog_failures_keep_known_contracts_without_requiring_an_observation(self):
        self.value['upstreams'][self.uid]['base_url']='https://xingapi.top/v1'
        atomic_json(self.path,self.value);original=self.path.read_bytes()
        expected=contracts.available(self.value,self.uid)
        for message in ('HTTP 401','HTTP 403','HTTP 404','HTTP 302','read failed','credential unavailable'):
            with self.subTest(message=message), mock.patch(
                    'videocreate.config_web.checks.discovery.models',side_effect=ConfigError(message+' private-error')) as fetch:
                report=Checks(self.service).read({'upstream':self.uid},refresh=True)
                self.assertEqual(report.get('contracts'),expected)
                self.assertEqual(report.get('rows'),[])
                self.assertNotIn('observation_id',report)
                self.assertNotIn('private-error',json.dumps(report))
                self.assertFalse(report['config_changed']);self.assertEqual(report['paid_creates'],0)
                fetch.assert_called_once()
                self.assertEqual(self.path.read_bytes(),original)
        # Applying the existing precise document remains an independent offline transaction.
        with mock.patch('videocreate.config_web.checks.discovery.models',side_effect=AssertionError('no extra check')):
            self.commit(self.preview('contract.apply',{'contract_id':expected[0]['id'],'revision':expected[0]['revision']},self.uid))
        saved=load_json(self.path)
        binding=next(b for b in saved['bindings'].values() if b['remote_model']=='seedance2.5-V')
        self.assertEqual(binding['operations'],['text-to-video'])
        self.assertEqual(binding['adapter'],'xingapi-video-v1')
        self.assertTrue(binding['enabled'])

    def test_catalog_failure_rechecks_identity_and_archive_before_offering_contracts(self):
        self.value['upstreams'][self.uid]['base_url']='https://xingapi.top/v1'
        for change in ('address','account','missing','missing-file','invalid-json','future-version','archived','display-name'):
            with self.subTest(change=change):
                atomic_json(self.path,self.value)
                def failed_read(*args,**kwargs):
                    after=copy.deepcopy(self.value)
                    if change=='address':after['upstreams'][self.uid]['base_url']='https://other.example.test/v1'
                    elif change=='account':after['upstreams'][self.uid]['account_id']='different-account'
                    elif change=='missing':after['upstreams'].pop(self.uid)
                    elif change=='future-version':after['schema_version']=99
                    elif change=='archived':
                        after['upstreams'][self.uid]['archived']=True
                        for binding in after['bindings'].values():
                            if binding['upstream']==self.uid:binding['enabled']=False
                    elif change=='display-name':after['upstreams'][self.uid]['display_name']='另一个显示名称'
                    if change=='missing-file':self.path.unlink()
                    elif change=='invalid-json':self.path.write_text('{',encoding='utf-8')
                    else:atomic_json(self.path,after)
                    raise ConfigError('HTTP 404 private-error')
                with mock.patch('videocreate.config_web.checks.discovery.models',side_effect=failed_read):
                    if change in {'archived','display-name'}:
                        report=Checks(self.service).read({'upstream':self.uid},refresh=True)
                        self.assertEqual(report.get('contracts'),[] if change=='archived' else contracts.available(self.value,self.uid))
                    else:
                        with self.assertRaises(WebError) as raised:
                            Checks(self.service).read({'upstream':self.uid},refresh=True)
                        self.assertEqual(raised.exception.status,409)
                        self.assertEqual(raised.exception.code,'catalog_source_changed')

    def test_known_document_can_be_applied_without_catalog_and_cli_reads_same_file(self):
        self.value['upstreams'][self.uid]['base_url']='https://xingapi.top/v1'; atomic_json(self.path, self.value)
        with mock.patch('urllib.request.build_opener', side_effect=AssertionError('no network')):
            available = contracts.available(self.value, self.uid)
            self.commit(self.preview('contract.apply', {'contract_id':available[0]['id'],'revision':'1'}, self.uid))
        current = m.load(self.path)['config']
        binding = next(b for b in current['bindings'].values() if b['remote_model']=='seedance2.5-V')
        self.assertEqual(binding['operations'], ['text-to-video']); self.assertTrue(binding['enabled'])
        self.assertEqual(binding['adapter'], 'xingapi-video-v1')
        self.assertNotIn('reference-to-video', binding['operations'])
        self.assertEqual(contracts.available(self.value, 'missing'), [])
        with self.assertRaises(ConfigError): contracts.apply(self.value, self.uid, available[0]['id'], 'old')

    def test_explicit_catalog_get_uses_only_saved_endpoint_and_never_follows_redirect(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        requests=[];mode=['ok']
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path,self.headers.get('Authorization')))
                if mode[0]=='redirect':
                    self.send_response(302);self.send_header('Location','http://127.0.0.1:'+str(self.server.server_port)+'/must-not-fetch');self.end_headers();return
                payload=json.dumps({'data':[{'id':'seedance2.5-V'}]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        self.value['upstreams'][self.uid]['base_url']='http://127.0.0.1:'+str(server.server_port)+'/v1'
        atomic_json(self.path,self.value);original=self.path.read_bytes()
        checks=Checks(self.service)
        checks.read({'upstream':self.uid});self.assertEqual(requests,[])
        result=checks.read({'upstream':self.uid},refresh=True)
        self.assertEqual(requests,[('/v1/models','Bearer test-only-value')])
        self.assertEqual(result['rows'][0]['remote_model'],'seedance2.5-V')
        mode[0]='redirect';result=checks.read({'upstream':self.uid},refresh=True)
        self.assertEqual(result['status'],'redirect-blocked');self.assertEqual(len(requests),2)
        self.assertEqual(self.path.read_bytes(),original)


if __name__ == '__main__': unittest.main()
