import copy
import io
import json
import tempfile
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.catalog import discovery, observations as o
from videocreate.cli import main
from videocreate.config import management as m
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json, load_json


class CatalogObservationTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.path=self.root/'config.json'
        self.value=m.migrate(config());self.uid='primary-sub2api'
        atomic_json(self.path,self.value);self.original=self.path.read_bytes()
        self.local=next(b['remote_model'] for b in self.value['bindings'].values() if b['upstream']==self.uid)

    def record(self,ids):return o.record(self.value,self.uid,ids,store_root=self.root)

    def fetch(self,body):
        response=mock.MagicMock();response.__enter__.return_value.read.return_value=body
        with mock.patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=response
            result=discovery.models(self.value,self.uid,store_root=self.root)
        request=opener.return_value.open.call_args[0][0]
        self.assertEqual(request.get_method(),'GET')
        self.assertEqual(request.full_url,'https://provider.example.test/v1/models')
        return result

    def cli(self,*args):
        output=io.StringIO()
        with redirect_stdout(output):
            status=main(['providers',*args,'--config',str(self.path)])
        return status,json.loads(output.getvalue())

    def test_first_observation_is_not_a_removal_baseline(self):
        report=self.record(['Seedance-V','seedance-v','Seedance-V',' model / exact '])
        self.assertEqual(report['ids'],['Seedance-V','seedance-v',' model / exact '])
        self.assertIsNone(report['changes']['added_since_previous'])
        self.assertIsNone(report['changes']['not_in_latest_since_previous'])
        self.assertFalse(report['baseline_available'])
        self.assertEqual(report['changes']['new_to_configuration'],report['ids'])
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_second_observation_exposes_disappeared_names_without_local_bindings(self):
        first=self.record([self.local,'never-imported','stable'])
        second=self.record(['stable','new'])
        self.assertEqual(second['changes']['added_since_previous'],['new'])
        self.assertEqual(set(second['changes']['not_in_latest_since_previous']),{self.local,'never-imported'})
        absent=next(row for row in second['rows'] if row['remote_model']=='never-imported')
        self.assertEqual(absent['change'],'not-in-latest')
        self.assertEqual(absent['local_bindings'],[]);self.assertFalse(absent['importable'])
        self.assertEqual(second['previous_observation'],first['observation']['observation_hash'])
        self.assertEqual(o.show(self.value,self.uid,store_root=self.root),{**second,'network_requests':0})

    def test_empty_complete_catalog_keeps_local_configuration(self):
        self.record([self.local]);report=self.fetch(b'{"data":[]}')
        self.assertEqual(report['ids'],[])
        self.assertIn(self.local,report['changes']['local_not_in_observation'])
        self.assertIn(self.local,report['changes']['not_in_latest_since_previous'])
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_exact_source_time_hash_and_no_full_response_persisted(self):
        report=self.fetch(json.dumps({'data':[{'id':'Remote-V','secret_metadata':'not-saved'}]}).encode())
        packet=load_json(Path(report['evidence']))
        self.assertEqual(packet['evidence_kind'],'catalog-only')
        self.assertNotIn('secret_metadata',Path(report['evidence']).read_text())
        self.assertEqual(o.checked(packet,o.identity(self.value,self.uid)),packet)
        self.assertEqual(report['network_requests'],1);self.assertEqual(report['paid_creates'],0)

    def test_malformed_response_never_replaces_valid_baseline(self):
        previous=self.record(['keep'])
        bodies=[b'{"data":[{"id":"x"},{}]}',b'{"data":["x"]}',b'{"data":{}}',b'[]',
            b'{"data":[{"id":null}]}',b'{"data":[{"id":5}]}',b'{"data":[{"id":""}]}',
            b'{"data":[],"data":[{"id":"x"}]}',b'{"data":[{"id":"x","id":"y"}]}',
            b'{"data":[],"unknown":NaN}',b'\xff',b'not-json',b'{"data":[{"id":"\\ud800"}]}']
        for raw in bodies:
            with self.subTest(raw=raw),self.assertRaises(ConfigError):self.fetch(raw)
        self.assertEqual(o.show(self.value,self.uid,store_root=self.root)['observation'],previous['observation'])
        self.assertEqual(len(list(Path(previous['evidence']).parent.glob('*.json'))),1)

    def test_oversized_response_rejected_without_observation(self):
        with self.assertRaisesRegex(ConfigError,'size limit'):self.fetch(b' '*(4*1024*1024+1))
        self.assertEqual(o.show(self.value,self.uid,store_root=self.root)['status'],'no-observation')

    def test_reflected_active_credential_never_enters_result_or_disk(self):
        key='credential-for-reflection-test'
        with mock.patch('videocreate.catalog.discovery.resolve_key',return_value=key):
            with self.assertRaises(ConfigError) as error:self.fetch(json.dumps({'data':[{'id':'prefix-'+key}]}).encode())
        self.assertNotIn(key,str(error.exception))
        self.assertFalse((self.root/'runtime/catalog-observations').exists())

    def test_http_and_transport_failures_preserve_history_and_hide_remote_body(self):
        previous=self.record(['keep'])
        for error in (urllib.error.HTTPError('https://provider.test',503,'secret-remote-error',{},None),OSError('secret-remote-error')):
            with mock.patch('urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect=error
                with self.assertRaises(ConfigError) as caught:discovery.models(self.value,self.uid,store_root=self.root)
                self.assertNotIn('secret-remote-error',str(caught.exception))
        self.assertEqual(o.show(self.value,self.uid,store_root=self.root)['observation'],previous['observation'])

    def test_catalog_redirect_does_not_forward_credentials(self):
        request=mock.Mock()
        self.assertIsNone(discovery.NoRedirect().redirect_request(request,None,302,'redirect',{},'https://other.test'))

    def test_scope_isolated_by_upstream_address_and_account(self):
        previous=self.record(['original'])
        for field,value in [('base_url','https://different.test/v1'),('account_id','other-account')]:
            changed=copy.deepcopy(self.value);changed['upstreams'][self.uid][field]=value
            self.assertEqual(o.show(changed,self.uid,store_root=self.root)['status'],'no-observation')
            with self.assertRaises(ConfigError):o.show(changed,self.uid,store_root=self.root,file=previous['evidence'])
        other=copy.deepcopy(self.value);other['upstreams']['another']=copy.deepcopy(other['upstreams'][self.uid])
        self.assertEqual(o.show(other,'another',store_root=self.root)['status'],'no-observation')

    def test_same_account_credential_rotation_and_trailing_slash_keep_history(self):
        first=self.record(['before'])
        changed=copy.deepcopy(self.value)
        changed['upstreams'][self.uid]['auth']={'api_key':'rotated-value'}
        changed['upstreams'][self.uid]['base_url']+='/'
        report=o.record(changed,self.uid,['after'],store_root=self.root)
        self.assertEqual(report['previous_observation'],first['observation']['observation_hash'])

    def test_corrupt_unknown_and_renamed_observations_are_ignored_not_deleted(self):
        first=self.record(['keep']);folder=Path(first['evidence']).parent
        (folder/'broken.json').write_bytes(b'\xff')
        newer=copy.deepcopy(first['observation']);newer['schema_version']=99;newer.pop('observation_hash')
        newer['observation_hash']=m.fingerprint(newer);atomic_json(folder/(newer['observation_hash']+'.json'),newer)
        atomic_json(folder/'wrong-name.json',first['observation'])
        corrupt=copy.deepcopy(first['observation']);corrupt['ids']=['changed-without-hash'];atomic_json(folder/'corrupt.json',corrupt)
        report=o.show(self.value,self.uid,store_root=self.root)
        self.assertEqual(report['unreadable_observations'],4)
        self.assertEqual(report['ids'],['keep']);self.assertEqual(len(list(folder.glob('*.json'))),5)

    def test_altered_observation_is_rejected_for_explicit_use_and_import(self):
        first=self.record(['keep']);packet=load_json(Path(first['evidence']));packet['ids']=['altered']
        atomic_json(Path(first['evidence']),packet)
        with self.assertRaises(ConfigError):o.show(self.value,self.uid,store_root=self.root,file=first['evidence'])
        with self.assertRaises(ConfigError):discovery.import_models(self.value,self.uid,['altered'],observation=packet)

    def test_offline_cache_does_not_read_credentials_or_old_unscoped_cache(self):
        legacy=self.root/'runtime/catalogs/primary-sub2api.json';atomic_json(legacy,{'ids':['old-unscoped']})
        original=legacy.read_bytes()
        with mock.patch('urllib.request.build_opener',side_effect=AssertionError('No network')),\
             mock.patch('videocreate.catalog.discovery.resolve_key',side_effect=AssertionError('No key')):
            self.assertEqual(o.show(self.value,self.uid,store_root=self.root)['status'],'no-observation')
            self.record(['scoped']);report=o.show(self.value,self.uid,store_root=self.root)
            self.assertEqual(report['ids'],['scoped']);self.assertEqual(report['network_requests'],0)
        self.assertEqual(legacy.read_bytes(),original)

    def test_explicit_historical_observation_compares_its_own_predecessor(self):
        a=self.record(['a']);b=self.record(['b']);self.record(['c'])
        report=o.show(self.value,self.uid,store_root=self.root,file=b['evidence'])
        self.assertEqual(report['previous_observation'],a['observation']['observation_hash'])
        self.assertEqual(report['changes']['added_since_previous'],['b'])

    def test_import_source_is_recorded_without_enabling_drafts_or_touching_existing(self):
        original=copy.deepcopy(self.value);report=self.record([self.local,'Seedance-V'])
        changed,added=discovery.import_models(self.value,self.uid,report['ids'],observation=report['observation'])
        self.assertEqual(validate_config(changed),[]);self.assertEqual(len(added),1)
        for bid,binding in original['bindings'].items():self.assertEqual(changed['bindings'][bid],binding)
        draft=changed['bindings'][added[0]]
        self.assertFalse(draft['enabled']);self.assertEqual(draft['adapter'],'unconfigured')
        self.assertEqual(draft['setup_status'],'draft');self.assertEqual(draft['remote_model'],'Seedance-V')
        source=draft['declared_capabilities']['source']
        self.assertEqual(source['url'],report['url']);self.assertEqual(source['observed_at'],report['observed_at'])
        self.assertIn(report['observation']['observation_hash'],source['notes'])
        self.assertEqual(self.value,original);self.assertEqual(self.path.read_bytes(),self.original)

    def test_import_skips_existing_exact_id_preserving_notes_prices_and_limits(self):
        report=self.record(['New-V']);value,added=discovery.import_models(self.value,self.uid,report['ids'])
        binding=value['bindings'][added[0]];binding.update(notes='my notes',enabled=False,pricing={'currency':'USD','per_request':1})
        original=copy.deepcopy(value)
        changed,added=discovery.import_models(value,self.uid,report['ids'],observation=report['observation'])
        self.assertEqual(changed,original);self.assertEqual(added,[])

    def test_import_keeps_case_distinct_and_never_merges_across_upstreams(self):
        value,added=discovery.import_models(self.value,self.uid,['Remote-V','remote-v','Remote-V'])
        self.assertEqual(len(added),2)
        value,other=discovery.import_models(value,'backup-newapi',['Remote-V'])
        self.assertEqual(len(other),1);self.assertNotIn(other[0],added)

    def test_import_rejects_unobserved_ids_and_different_account(self):
        report=self.record(['known'])
        with self.assertRaises(ConfigError):discovery.import_models(self.value,self.uid,['other'],observation=report['observation'])
        changed=copy.deepcopy(self.value);changed['upstreams'][self.uid]['account_id']='other'
        with self.assertRaises(ConfigError):discovery.import_models(changed,self.uid,['known'],observation=report['observation'])

    def test_invalid_ids_are_rejected_before_import_or_record(self):
        for ids in ('not-a-list',[None],['\n'],['\ud800'],['x'*1025],['x']*10001):
            with self.subTest(ids=str(ids)[:40]):
                with self.assertRaises(ConfigError):self.record(ids)
                with self.assertRaises(ConfigError):discovery.import_models(self.value,self.uid,ids)

    def test_concurrent_observations_have_an_intact_serial_history(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            reports=list(pool.map(self.record,[[str(i)] for i in range(5)]))
        self.assertEqual(sum(not r['baseline_available'] for r in reports),1)
        hashes={r['observation']['observation_hash'] for r in reports}
        self.assertEqual(len(hashes),5)
        self.assertEqual(o.show(self.value,self.uid,store_root=self.root)['unreadable_observations'],0)
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_cli_cached_show_has_no_network_or_key_reads(self):
        self.record(['cached'])
        with mock.patch('urllib.request.build_opener',side_effect=AssertionError('No network')),\
             mock.patch('videocreate.catalog.discovery.resolve_key',side_effect=AssertionError('No key')):
            status,result=self.cli('catalog-show','--upstream',self.uid)
        self.assertEqual(status,0);self.assertEqual(result['ids'],['cached'])
        self.assertEqual(result['network_requests'],result['paid_creates'])

    def test_cli_raw_packet_and_report_preview_and_token_bound_apply(self):
        report=self.record(['new-from-catalog']);source=self.root/'report.json';atomic_json(source,report)
        for file in (source,Path(report['evidence'])):
            status,preview=self.cli('import-models','--upstream',self.uid,'--kind','video','--file',str(file))
            self.assertEqual(status,0);self.assertFalse(preview['applied'])
            self.assertEqual(preview['catalog_source']['observation_hash'],report['observation']['observation_hash'])
            self.assertEqual(self.path.read_bytes(),self.original)
        status,result=self.cli('import-models','--upstream',self.uid,'--kind','video','--file',str(source),'--apply','--token',m.fingerprint(self.value))
        self.assertEqual(status,0);self.assertEqual(len(result['added']),1)
        saved=load_json(self.path);self.assertFalse(saved['bindings'][result['added'][0]]['enabled'])
        self.assertIn('source',saved['bindings'][result['added'][0]]['declared_capabilities'])
        status,error=self.cli('import-models','--upstream',self.uid,'--kind','video','--file',str(source),'--apply','--token',m.fingerprint(self.value))
        self.assertNotEqual(status,0);self.assertEqual(load_json(self.path),saved)

    def test_cli_manual_import_remains_supported_without_catalog_claim(self):
        file=self.root/'manual.json';atomic_json(file,{'ids':['manual']})
        status,result=self.cli('import-models','--upstream',self.uid,'--kind','image','--file',str(file))
        self.assertEqual(status,0);self.assertIsNone(result['catalog_source'])
        self.assertEqual(self.path.read_bytes(),self.original)


if __name__=='__main__':unittest.main()
