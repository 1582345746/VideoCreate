import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate import diagnostics as d
from videocreate.catalog import observations,evidence
from videocreate.catalog.bindings import configured_binding
from videocreate.cli import main
from videocreate.config.management import migrate,fingerprint
from videocreate.config.storage import ConfigError,atomic_json,load_json


class ProviderDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.path=self.root/'config.json';self.output=self.root/'diagnostics.json'
        self.value=migrate(config());self.uid='primary-sub2api';self.bid='grok-on-sub2api'
        self.secret='inline-secret-canary';self.value['upstreams'][self.uid]['auth']['api_key']=self.secret
        self.value['upstreams'][self.uid].update(notes='private-upstream-note',account_id='private-account-id',credential_version='private-key-version')
        self.value['upstreams'][self.uid]['base_url']='https://provider.example.test/private-path-canary'
        self.value['bindings'][self.bid].update(notes='private-binding-note',documentation_url='https://docs.test/?signature=private-signature')
        atomic_json(self.path,self.value);self.original=self.path.read_bytes()

    def preview(self,**kwargs):return d.preview(self.path,**kwargs)

    def export(self,pending,**kwargs):return d.export(self.path,pending,self.output,token=pending['preview_token'],**kwargs)

    def cli(self,*args):
        text=io.StringIO()
        with redirect_stdout(text):status=main(['providers',*args,'--config',str(self.path)])
        return status,json.loads(text.getvalue())

    def receipt(self,result='pass',operation='text-to-video'):
        binding=configured_binding(self.value,self.bid);source=self.root/('private-receipt-'+operation+'-'+result)
        source.write_bytes(b'actual-local-evidence')
        return evidence.record(self.root,binding,{'stage':'smoke','result':result,'operation':operation,
            'binding_fingerprint':binding.snapshot()['fingerprint'],'reviewer_id':'private-reviewer',
            'method':'offline-fixture','checks':{'downloaded':result=='pass'},'attempt_id':'private-attempt','task_id':'private-task',
            'evidence':[{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]})

    def test_anonymous_report_omits_credentials_identifiers_free_text_paths_and_urls(self):
        report=self.preview()['report'];text=json.dumps(report)
        for forbidden in (self.secret,self.uid,self.bid,'private-upstream-note','private-account-id','private-key-version',
                'private-binding-note','private-signature','private-path-canary','provider.example.test',str(self.root)):
            self.assertNotIn(forbidden,text)
        self.assertEqual(report['configuration']['status'],'valid')
        self.assertEqual(report['disclosure'],'anonymous');self.assertEqual(report['paid_creates'],0)
        self.assertEqual(report['external_credential_reads'],0)
        self.assertIn('redact',report['inline_credential_handling'])
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_optional_identifiers_only_include_model_ids_and_host_with_inline_secrets_scrubbed(self):
        self.value['bindings'][self.bid]['remote_model']='Model-'+self.secret
        atomic_json(self.path,self.value);report=self.preview(include_identifiers=True)['report'];text=json.dumps(report)
        row=next(row for row in report['bindings'] if row.get('identifiers',{}).get('id')==self.bid)
        self.assertEqual(row['identifiers']['remote_model'],'Model-[redacted]')
        self.assertIn('provider.example.test',text);self.assertNotIn('private-path-canary',text)
        self.assertNotIn(self.secret,text);self.assertNotIn('private-account-id',text);self.assertNotIn('private-binding-note',text)

    def test_preview_and_export_never_resolve_env_or_encrypted_credentials_or_network(self):
        self.value['upstreams'][self.uid]['auth']={'type':'bearer','env':'PRIVATE_ENV_NAME'}
        self.value['upstreams']['backup-newapi']['auth']={'type':'bearer','secret_ref':'private.secret.ref'}
        atomic_json(self.path,self.value)
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('No key')) as key,\
             mock.patch('videocreate.config.storage.private_store',side_effect=AssertionError('No DPAPI')) as store,\
             mock.patch('urllib.request.build_opener',side_effect=AssertionError('No network')) as network:
            pending=self.preview();self.export(pending);key.assert_not_called();store.assert_not_called();network.assert_not_called()
        text=self.output.read_text();self.assertNotIn('PRIVATE_ENV_NAME',text);self.assertNotIn('private.secret.ref',text)
        modes={row['credential']['mode'] for row in pending['report']['upstreams']}
        self.assertIn('environment',modes);self.assertIn('encrypted-reference',modes)

    def test_scope_keeps_route_relations_and_excludes_other_identifiers(self):
        report=self.preview(upstream=self.uid,include_identifiers=True)['report']
        self.assertEqual(len(report['upstreams']),1)
        self.assertTrue(all(row['upstream_ref']==report['upstreams'][0]['ref'] for row in report['bindings']))
        self.assertNotIn('backup-newapi',json.dumps(report))
        self.assertEqual(report['counts']['bindings'],sum(b['upstream']==self.uid for b in self.value['bindings'].values()))
        refs={row['ref'] for row in report['bindings']}
        self.assertTrue(all(set(r['candidates'])<=refs for r in report['routes']))

    def test_cached_catalog_counts_do_not_leak_remote_names_or_evidence_paths(self):
        observations.record(self.value,self.uid,['private-remote-a','private-remote-b'],store_root=self.root)
        observations.record(self.value,self.uid,['private-remote-b','private-remote-c'],store_root=self.root)
        report=self.preview(upstream=self.uid)['report'];catalog=report['upstreams'][0]['catalog']
        self.assertEqual(catalog['model_count'],2);self.assertEqual(catalog['changes']['added_since_previous'],1)
        self.assertEqual(catalog['changes']['not_in_latest_since_previous'],1)
        self.assertNotIn('private-remote',json.dumps(report));self.assertNotIn('catalog-observations',json.dumps(report))

    def test_missing_corrupt_observations_remain_unknown(self):
        report=self.preview(upstream=self.uid)['report'];self.assertEqual(report['upstreams'][0]['catalog']['status'],'not-observed')
        observations.record(self.value,self.uid,['private-remote'],store_root=self.root)
        folder=observations.folder(self.root,observations.identity(self.value,self.uid));(folder/'corrupt.json').write_text('{}')
        report=self.preview(upstream=self.uid)['report'];self.assertEqual(report['upstreams'][0]['catalog']['ignored_observations'],1)

    def test_operation_evidence_counts_keep_failure_and_expired_evidence_separate(self):
        passed=self.receipt('pass');self.receipt('fail','image-to-video')
        report=self.preview()['report'];row=next(r for r in report['bindings'] if r['ref']=='binding-001')
        self.assertEqual(row['evidence']['text-to-video']['stages']['smoke']['status'],'reported_pass')
        self.assertEqual(row['evidence']['image-to-video']['stages']['smoke']['status'],'fail')
        self.assertEqual(row['evidence']['text-to-video']['stages']['quality']['status'],'unverified')
        text=json.dumps(report)
        for secret in ('private-task','private-attempt','private-reviewer','private-receipt',str(self.root)):self.assertNotIn(secret,text)
        Path(load_json(Path(passed['receipt']))['evidence'][0]['path']).write_bytes(b'changed')
        changed=self.preview()['report']['bindings'][0]['evidence']['text-to-video']
        self.assertEqual(changed['stages']['smoke']['status'],'unverified');self.assertEqual(changed['stale_receipt_count'],1)

    def test_malformed_receipt_result_does_not_become_a_passing_diagnostic(self):
        saved=self.receipt();path=Path(saved['receipt']);value=load_json(path);value['result']='unexpected';atomic_json(path,value)
        row=self.preview()['report']['bindings'][0]['evidence']['text-to-video']
        self.assertEqual(row['stages']['smoke']['status'],'unverified');self.assertEqual(row['stale_receipt_count'],1)

    def test_tampered_failing_checks_or_missing_reviewer_cannot_keep_passing_receipt(self):
        saved=self.receipt();path=Path(saved['receipt']);original=load_json(path)
        for delta in ({'checks':{'downloaded':False}},{'checks':{}},{'reviewer_id':''},{'task_id':''}):
            value={**original,**delta};atomic_json(path,value)
            status=evidence.status(self.root,configured_binding(self.value,self.bid),operation='text-to-video')
            self.assertEqual(status['stages']['smoke']['status'],'unverified');self.assertEqual(len(status['stale_receipts']),1)

    def test_immutable_new_export_matches_exact_preview_and_preserves_protected_files(self):
        protected=self.root/'secrets.dpapi';protected.write_bytes(b'private-encrypted-evidence')
        pending=self.preview();result=self.export(pending)
        self.assertEqual(load_json(self.output),pending['report'])
        self.assertEqual(result['report_sha256'],hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertNotIn('preview_token',self.output.read_text());self.assertNotIn('source_token',self.output.read_text())
        self.assertEqual(protected.read_bytes(),b'private-encrypted-evidence');self.assertEqual(self.path.read_bytes(),self.original)
        self.assertFalse(list(self.root.glob('.videocreate-diagnostic-*.tmp')))

    def test_existing_output_is_never_overwritten(self):
        self.output.write_bytes(b'existing-user-file');pending=self.preview()
        with self.assertRaisesRegex(ConfigError,'already exists'):self.export(pending)
        self.assertEqual(self.output.read_bytes(),b'existing-user-file')

    def test_output_cannot_be_configuration_or_non_json(self):
        pending=self.preview()
        for output in (self.path,self.root/'unsafe.txt'):
            with self.assertRaises(ConfigError):d.export(self.path,pending,output,token=pending['preview_token'])
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_export_rejects_changed_configuration_including_notes(self):
        pending=self.preview();self.value['upstreams'][self.uid]['notes']='changed';atomic_json(self.path,self.value)
        with self.assertRaisesRegex(ConfigError,'changed'):self.export(pending)
        self.assertFalse(self.output.exists())

    def test_export_rejects_new_catalog_or_evidence_after_preview(self):
        pending=self.preview();observations.record(self.value,self.uid,['new'],store_root=self.root)
        with self.assertRaisesRegex(ConfigError,'changed'):self.export(pending)
        pending=self.preview();self.receipt()
        with self.assertRaisesRegex(ConfigError,'changed'):self.export(pending)
        self.assertFalse(self.output.exists())

    def test_export_rejects_tampered_preview_or_wrong_token(self):
        pending=self.preview();changed=copy.deepcopy(pending);changed['report']['paid_creates']=99
        with self.assertRaises(ConfigError):self.export(changed)
        with self.assertRaises(ConfigError):d.export(self.path,pending,self.output,token='wrong-token')
        changed=copy.deepcopy(pending);changed['report']['leaked']='private';changed['preview_token']=fingerprint({k:v for k,v in changed.items() if k!='preview_token'})
        with self.assertRaises(ConfigError):self.export(changed)
        self.assertFalse(self.output.exists())

    def test_configuration_changed_during_collect_is_rejected_before_publication(self):
        pending=self.preview();original=d._build
        def build(*args,**kwargs):
            result=original(*args,**kwargs);self.path.write_bytes(self.original+b' ');return result
        with mock.patch('videocreate.diagnostics._build',side_effect=build),self.assertRaisesRegex(ConfigError,'changed'):self.export(pending)
        self.assertFalse(self.output.exists())

    def test_missing_unreadable_invalid_and_newer_configs_export_minimal_status_without_content(self):
        for raw,expected in [(None,'missing'),(b'private-invalid-secret','unreadable'),(b'\xff','unreadable'),
                (b'{"schema_version":4,"private":"inline-secret"}','invalid'),(b'{"schema_version":99,"private":"inline-secret"}','invalid')]:
            if raw is None:self.path.unlink(missing_ok=True)
            else:self.path.write_bytes(raw)
            pending=self.preview();report=pending['report'];self.assertEqual(report['configuration']['status'],expected)
            self.assertNotIn('inline-secret',json.dumps(report));self.assertNotIn('private-invalid-secret',json.dumps(report))
            self.assertEqual(report['upstreams'],[]);self.assertEqual(report['bindings'],[])
            if self.output.exists():self.output.unlink()
            self.export(pending);self.assertEqual(load_json(self.output),report)
            self.assertEqual(self.path.read_bytes() if self.path.exists() else None,raw)

    def test_custom_parameter_labels_are_omitted_while_numeric_contract_bounds_remain(self):
        caps=self.value['bindings'][self.bid]['capability_overrides']
        caps['resolutions']=['720p','private-resolution-secret'];caps['conditions']=[{'when':{'resolution':'private-resolution-secret'},'max_seconds':4}]
        atomic_json(self.path,self.value);report=self.preview()['report'];row=report['bindings'][0]
        self.assertEqual(row['limits']['resolutions'],['720p']);self.assertEqual(row['limits']['resolutions_omitted_count'],1)
        self.assertEqual(row['limits']['conditions'][0]['max_seconds'],4)
        self.assertNotIn('private-resolution-secret',json.dumps(report))

    def test_unknown_scope_and_invalid_options_raise_generic_errors(self):
        for kwargs in ({'upstream':'missing-private-id'},{'upstream':[]},{'include_identifiers':'yes'}):
            with self.assertRaises(ConfigError) as error:self.preview(**kwargs)
            self.assertNotIn('missing-private-id',str(error.exception))

    def test_cli_preview_and_export_use_same_report_and_token(self):
        status,pending=self.cli('diagnostics','--upstream',self.uid)
        self.assertEqual(status,0);file=self.root/'preview.json';atomic_json(file,pending)
        status,result=self.cli('diagnostics-export','--file',str(file),'--output',str(self.output),'--token',pending['preview_token'])
        self.assertEqual(status,0);self.assertEqual(result['status'],'exported')
        self.assertEqual(load_json(self.output),pending['report']);self.assertEqual(self.path.read_bytes(),self.original)

    def test_cli_diagnoses_broken_json_before_normal_configuration_load(self):
        self.path.write_text('{"schema_version":4,"secret":"private",}',encoding='utf-8')
        status,pending=self.cli('diagnostics');self.assertEqual(status,0)
        self.assertEqual(pending['report']['configuration']['status'],'unreadable');self.assertNotIn('private',json.dumps(pending))

    def test_cli_rejects_ignored_diagnostic_mutation_or_disclosure_flags(self):
        for args in [('diagnostics','--apply'),('diagnostics-export','--include-identifiers'),('list','--include-identifiers'),
                ('diagnostics','--output',str(self.output))]:
            status,error=self.cli(*args);self.assertNotEqual(status,0);self.assertFalse(error['ok'])
        self.assertFalse(self.output.exists());self.assertEqual(self.path.read_bytes(),self.original)


if __name__=='__main__':unittest.main()
