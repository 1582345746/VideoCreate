"""Repair corrupt configuration bytes without creating work or losing evidence."""
import concurrent.futures
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.config import management as m, repair
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.management_commands import providers_command


class ConfigurationRepairTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.path=self.root/'config.json'
        self.value=m.migrate(config());self.text=json.dumps(self.value,ensure_ascii=False)
        self.raw=b'\xef\xbb\xbf{"schema_version":4,"api_key":"private-repair-fixture",\r\n}'
        self.path.write_bytes(self.raw)

    def describe(self,text=None,baseline=None):
        return repair.preview(self.path,text or self.text,
            source_token=repair.inspect(self.path)['source_token'],baseline=baseline)

    def apply(self,preview=None,**options):
        p=preview or self.describe()
        return repair.apply(self.path,self.text,source_token=p['source_token'],
            preview_token=p['preview_token'],**options)

    def test_inspection_and_preview_are_read_only_and_redacted(self):
        with mock.patch('urllib.request.urlopen',side_effect=AssertionError('offline')):
            inspected=repair.inspect(self.path);p=self.describe()
        self.assertEqual(inspected['status'],'syntax-error');self.assertTrue(inspected['can_repair'])
        self.assertFalse(p['original_structure_verified']);self.assertEqual(p['network_requests'],0)
        self.assertEqual(list(self.root.iterdir()),[self.path]);self.assertEqual(self.path.read_bytes(),self.raw)
        for secret in ('private-repair-fixture','test-only-value'):
            self.assertNotIn(secret,json.dumps([inspected,p]))

    def test_exact_bom_and_crlf_original_is_backed_up_before_valid_repair(self):
        p=self.describe();result=self.apply(p)
        self.assertEqual(Path(result['original_backup']).read_bytes(),self.raw)
        self.assertEqual(validate_config(load_json(self.path)),[])
        self.assertEqual(load_json(self.path)['revision'],1)
        history=list((self.root/'config-history').glob('*.json'));self.assertEqual(len(history),1)
        self.assertNotIn('private-repair-fixture',history[0].read_text())

    def test_schema_invalid_current_is_repairable(self):
        value=copy.deepcopy(self.value);value['revision']='broken';atomic_json(self.path,value)
        p=self.describe();self.assertEqual(p['source_status'],'schema-error')
        self.assertTrue(p['original_structure_verified']);self.apply(p)
        self.assertEqual(validate_config(load_json(self.path)),[])

    def test_non_utf8_original_is_preserved_exactly(self):
        raw=b'\xff\xfe\x00\xa1';self.path.write_bytes(raw)
        self.assertEqual(repair.inspect(self.path)['status'],'syntax-error')
        result=self.apply();self.assertEqual(Path(result['original_backup']).read_bytes(),raw)

    def test_duplicate_fields_and_nan_are_repairable_sources_but_rejected_drafts(self):
        for raw in ('{"schema_version":4,"x":1,"x":2}','{"schema_version":4,"x":NaN}'):
            with self.subTest(raw=raw):
                self.path.write_text(raw,encoding='utf-8');self.assertEqual(repair.inspect(self.path)['status'],'syntax-error')
                with self.assertRaises(ConfigError):self.describe(raw)
                self.assertEqual(self.path.read_text(encoding='utf-8'),raw)

    def test_unsupported_version_including_broken_tail_is_read_only(self):
        for raw in ('{"schema_version":99}', '{"schema_version":99,"tail":',
                    '{"schema_version":"4","tail":', '{"schema_version":4.0,"tail":',
                    '{"schema_version":3,"schema_version":99,}'):
            with self.subTest(raw=raw):
                self.path.write_text(raw,encoding='utf-8');state=repair.inspect(self.path)
                self.assertEqual(state['status'],'read-only');self.assertFalse(state['can_repair'])
                with self.assertRaises(ConfigError):self.describe()

    def test_nested_or_quoted_version_does_not_override_root(self):
        raw='{"schema_version":4,"nested":{"schema_version":99},"note":"schema_version",}'
        self.path.write_text(raw,encoding='utf-8')
        self.assertEqual(repair.inspect(self.path)['status'],'syntax-error')
        self.describe()

    def test_valid_config_cannot_use_repair_instead_of_normal_save(self):
        atomic_json(self.path,self.value)
        self.assertEqual(repair.inspect(self.path)['status'],'valid')
        with self.assertRaisesRegex(ConfigError,'normal save'):self.describe()

    def test_changed_source_bytes_reject_preview_and_apply(self):
        p=self.describe();self.path.write_bytes(self.raw+b' ')
        with self.assertRaisesRegex(ConfigError,'bytes changed'):self.apply(p)
        with self.assertRaisesRegex(ConfigError,'bytes changed'):
            repair.preview(self.path,self.text,source_token=p['source_token'])
        self.assertFalse((self.root/'backups').exists())

    def test_changed_draft_even_whitespace_requires_new_preview(self):
        p=self.describe()
        with self.assertRaisesRegex(ConfigError,'draft or baseline changed'):
            repair.apply(self.path,self.text+' ',source_token=p['source_token'],preview_token=p['preview_token'])
        self.assertEqual(self.path.read_bytes(),self.raw)

    def test_schema_invalid_candidate_cannot_write_backup_or_configuration(self):
        value=copy.deepcopy(self.value);value['defaults']['unknown']='private-repair-fixture'
        with self.assertRaises(ConfigError) as exc:self.describe(json.dumps(value))
        self.assertNotIn('private-repair-fixture',str(exc.exception))
        self.assertFalse((self.root/'backups').exists());self.assertEqual(self.path.read_bytes(),self.raw)

    def baseline(self):
        baseline=self.root/'backups'/'previous.json';atomic_json(baseline,self.value);return baseline

    def test_inspection_lists_only_valid_supported_backups(self):
        baseline=self.baseline();(baseline.parent/'bad.json').write_text('{}')
        atomic_json(baseline.parent/'future.json',{'schema_version':99})
        rows=repair.inspect(self.path)['backups'];self.assertEqual([r['path'] for r in rows],[str(baseline.resolve())])
        self.assertEqual(rows[0]['sha256'],repair.sha(baseline.read_bytes()))

    def test_changed_baseline_bytes_requires_new_preview(self):
        baseline=self.baseline();p=self.describe(baseline=baseline)
        baseline.write_bytes(baseline.read_bytes()+b' ')
        with self.assertRaisesRegex(ConfigError,'draft or baseline changed'):self.apply(p,baseline=baseline)
        self.assertEqual(self.path.read_bytes(),self.raw)

    def test_baseline_must_be_separate_and_valid(self):
        for baseline in (self.path,self.root/'bad.json'):
            if baseline!=self.path:baseline.write_text('{}')
            with self.subTest(path=str(baseline)),self.assertRaises(ConfigError):self.describe(baseline=baseline)

    def test_readable_later_identities_are_retained_when_using_old_baseline(self):
        baseline=self.baseline();current=copy.deepcopy(self.value)
        current['upstreams']['later']=copy.deepcopy(next(iter(current['upstreams'].values())))
        current['upstreams']['later']['account_id']='later-account'
        current['models']['later-model']={'kind':'video','family':'custom','display_name':'Later'}
        binding=copy.deepcopy(current['bindings']['grok-on-sub2api'])
        binding.update(upstream='later',model='later-model')
        current['bindings']['later-binding']=binding
        current['routes']['later-model']={'policy':'fixed','preferred_binding':'later-binding','candidates':['later-binding']}
        current['revision']='broken';atomic_json(self.path,current)
        p=self.describe(baseline=baseline);self.apply(p,baseline=baseline);fixed=load_json(self.path)
        self.assertTrue(fixed['upstreams']['later']['archived']);self.assertTrue(fixed['models']['later-model']['archived'])
        self.assertTrue(fixed['bindings']['later-binding']['archived']);self.assertFalse(fixed['bindings']['later-binding']['enabled'])
        self.assertIn('later-model',fixed['routes']);self.assertEqual(len(p['preserved_entries']),4)

    def test_known_address_and_account_cannot_be_reassigned(self):
        current=copy.deepcopy(self.value);current['revision']='broken';atomic_json(self.path,current)
        for field,replacement in [('base_url','https://different.example/v1'),('account_id','another-account')]:
            candidate=copy.deepcopy(self.value);candidate['upstreams']['primary-sub2api'][field]=replacement
            with self.subTest(field=field),self.assertRaisesRegex(ConfigError,'known upstream'):self.describe(json.dumps(candidate))

    def test_baseline_cannot_override_disagreeing_known_current_identity(self):
        baseline=self.baseline();current=copy.deepcopy(self.value);current['revision']='broken'
        current['upstreams']['primary-sub2api']['account_id']='newer-account';atomic_json(self.path,current)
        with self.assertRaisesRegex(ConfigError,'disagree'):self.describe(baseline=baseline)

    def test_unreadable_identity_has_explicit_report_boundary(self):
        current=copy.deepcopy(self.value);current['upstreams']['primary-sub2api']['base_url']=42
        atomic_json(self.path,current);p=self.describe()
        self.assertIn('$.upstreams.primary-sub2api',p['unverified_identity_paths'])
        self.assertNotIn('primary-sub2api',p['protected_upstream_ids'])
        self.apply(p)

    def test_unusable_missing_catalog_entry_must_be_explicitly_repaired(self):
        current=copy.deepcopy(self.value);current['models']['damaged']=False;atomic_json(self.path,current)
        with self.assertRaisesRegex(ConfigError,'explicitly repaired'):self.describe()

    def test_invalid_url_is_unverified_and_can_be_corrected(self):
        for address in ('https://','https://example.test:broken/v1','https://user:secret@example.test/v1'):
            current=copy.deepcopy(self.value);current['upstreams']['primary-sub2api']['base_url']=address
            atomic_json(self.path,current);p=self.describe()
            self.assertIn('$.upstreams.primary-sub2api',p['unverified_identity_paths'])
            self.apply(p)

    def test_exact_existing_original_backup_can_be_reused(self):
        p=self.describe();backup=Path(p['original_backup']);backup.parent.mkdir();backup.write_bytes(self.raw)
        result=self.apply(p);self.assertEqual(result['original_backup'],str(backup))

    def test_conflicting_backup_path_refuses_overwrite(self):
        p=self.describe();backup=Path(p['original_backup']);backup.parent.mkdir();backup.write_bytes(b'other')
        with self.assertRaisesRegex(ConfigError,'different bytes'):self.apply(p)
        self.assertEqual(self.path.read_bytes(),self.raw);self.assertEqual(backup.read_bytes(),b'other')

    def test_atomic_replace_failure_keeps_original_and_exact_backup(self):
        p=self.describe()
        with mock.patch.object(repair,'atomic_json',side_effect=OSError('disk unavailable')),self.assertRaises(OSError):self.apply(p)
        self.assertEqual(self.path.read_bytes(),self.raw);self.assertEqual(Path(p['original_backup']).read_bytes(),self.raw)

    def test_history_failure_reports_committed_repair_and_backup(self):
        actual=repair.atomic_json
        def write(path,value):
            if path.parent.name=='config-history':raise OSError('history unavailable')
            actual(path,value)
        with mock.patch.object(repair,'atomic_json',side_effect=write):result=self.apply()
        self.assertTrue(result['ok']);self.assertIn('history write failed',result['warning'])
        self.assertEqual(validate_config(load_json(self.path)),[])
        self.assertEqual(Path(result['original_backup']).read_bytes(),self.raw)

    def test_concurrent_apply_commits_once_and_preserves_unrelated_files(self):
        protected=[self.root/'secrets.dpapi',self.root/'project'/'state.json']
        for p in protected:p.parent.mkdir(exist_ok=True);p.write_bytes(b'untouched-evidence')
        p=self.describe()
        def attempt(_):
            try:self.apply(p);return True
            except ConfigError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
        self.assertEqual(sorted(results),[False,True]);self.assertEqual(load_json(self.path)['revision'],1)
        self.assertTrue(all(p.read_bytes()==b'untouched-evidence' for p in protected))

    def test_revision_exceeds_current_and_selected_baseline(self):
        baseline=self.baseline();value=load_json(baseline);value['revision']=8;atomic_json(baseline,value)
        p=self.describe(baseline=baseline);self.apply(p,baseline=baseline)
        self.assertEqual(load_json(self.path)['revision'],9)

    def test_cli_can_inspect_preview_and_repair_a_broken_configuration(self):
        draft=self.root/'draft.json';draft.write_text(self.text,encoding='utf-8')
        def command(*args):
            output=io.StringIO()
            with redirect_stdout(output):self.assertEqual(providers_command([*args,'--config',str(self.path)]),0)
            self.assertNotIn('test-only-value',output.getvalue());return json.loads(output.getvalue())
        state=command('repair-inspect');p=command('repair-preview','--file',str(draft),'--token',state['source_token'])
        result=command('repair-apply','--file',str(draft),'--token',state['source_token'],'--preview-token',p['preview_token'])
        self.assertTrue(result['ok']);self.assertEqual(validate_config(load_json(self.path)),[])

    def test_cli_rejects_missing_preview_and_misapplied_repair_flags(self):
        draft=self.root/'draft.json';draft.write_text(self.text,encoding='utf-8')
        for args in (['repair-apply','--file',str(draft),'--token',repair.sha(self.raw)],
                     ['repair-inspect','--file',str(draft)],['list','--baseline',str(draft)]):
            with self.subTest(args=args),self.assertRaises(ConfigError):providers_command([*args,'--config',str(self.path)])


if __name__=='__main__':unittest.main()
