import copy
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from test_v3_config import config
from test_typed_media_generation import media_limits
from videocreate.config.management import migrate
from videocreate.config.storage import atomic_json,ConfigError
from videocreate.manager import Manager
from videocreate.manager_forms import Fields, MEDIA_REFERENCE_LIMITS
from videocreate.manager_pricing import Prices
from tkinter import ttk


class ManagerCatalogUITests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.root.update_idletasks()
        def cleanup():
            self.root.update_idletasks();self.root.destroy()
        self.addCleanup(cleanup)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'config.json'
        self.config=migrate(config());atomic_json(self.path,self.config)
        self.book=ttk.Notebook(self.root)

    def test_media_limits_round_trip_booleans_combinations_and_advanced_bounds(self):
        original=media_limits()
        original['audio_reference_with_generated_audio']=False
        original['video']['maximum_width']=1920
        form=Fields(self.book,'media',original,MEDIA_REFERENCE_LIMITS)
        self.assertEqual(form.read(),original)
        for name,var,kind in form.fields:
            if name=='audio_reference_with_generated_audio':var.set('是')
            if name=='allowed_combinations':
                for combo,selected in var.choices:selected.set(set(combo)=={'image','video'})
        updated=form.read()
        self.assertIs(updated['audio_reference_with_generated_audio'],True)
        self.assertEqual(updated['allowed_combinations'],[['image','video']])
        self.assertEqual(updated['video']['maximum_width'],1920)
        empty=Fields(self.book,'empty',{},MEDIA_REFERENCE_LIMITS)
        self.assertEqual(empty.read(),{})

    def test_tier_form_preserves_zero_rates_rounding_source_and_specific_conditions(self):
        value={'pricing':{'currency':'USD','status':'confirmed','minimum_seconds':5,'round_seconds':5,
            'source':{'kind':'catalog','observed_at':'2026-11-13'},
            'tiers':[{'when':{'operation':'text-to-video','resolution':'720p'},'per_request':0},
                     {'when':{'resolution':'1080p','minimum_seconds':5,'maximum_seconds':15},'per_second':.299}]},
            'listed_pricing':{'currency':None,'unit':'request','amount':4.9,'notes':'供应商原价'}}
        form=Prices(self.book,value)
        # Optional null currency is represented by an empty input and omitted.
        expected=copy.deepcopy(value);expected['listed_pricing'].pop('currency')
        self.assertEqual(form.read(),expected)
        self.assertIn('0/次',form.table.item('0','values')[1])
        form.table.selection_set('1');form.remove_selected()
        self.assertEqual(len(form.read()['pricing']['tiers']),1)
        for rates in ({'per_request':'0'},{'per_second':'.22','minimum_seconds':'5','maximum_seconds':'30'}):
            self.assertIn('when',Prices.tier(rates))
        for rates in ({'per_request':'nan'},{'per_second':'-1'},{'per_request':'1','minimum_seconds':'10','maximum_seconds':'5'},{}):
            with self.assertRaises(ConfigError):Prices.tier(rates)

    def test_image_prices_survive_common_fields_and_tier_editor_reopen(self):
        value={'pricing':{'currency':'USD','per_request':.01,'per_image':.04,
            'tiers':[{'when':{'operation':'image-edit'},'per_image':.06}]}}
        form=Prices(self.book,value)
        self.assertEqual(form.read(),value)
        self.assertIn('.06/张',form.table.item('0','values')[1])
        win=form.edit(0);win.withdraw()
        for button in win.winfo_children()[0].winfo_children():
            if isinstance(button,ttk.Button) and button.cget('text')=='应用档位':button.invoke();break
        else:self.fail('Missing tier apply button')
        self.assertEqual(form.read(),value)

    def test_manager_displays_tier_price_and_filters_without_changing_config(self):
        self.config['bindings']['grok-on-sub2api']['pricing']={'currency':'USD','tiers':[
            {'when':{'operation':'text-to-video','resolution':'720p'},'per_request':4.9}]}
        atomic_json(self.path,self.config);before=self.path.read_bytes()
        manager=Manager(self.root,self.path)
        self.assertIn('USD 4.9/次',manager.models.item('grok-on-sub2api','values')[3])
        manager.kind_filter.set('图片');manager.refresh_models()
        self.assertTrue(all(manager.value['models'][manager.value['bindings'][bid]['model']]['kind']=='image' for bid in manager.models.get_children()))
        manager.kind_filter.set('全部类型');manager.family_filter.set('grok');manager.refresh_models()
        self.assertTrue(manager.models.get_children())
        self.assertTrue(all(manager.value['models'][manager.value['bindings'][bid]['model']]['family']=='grok' for bid in manager.models.get_children()))
        self.assertEqual(self.path.read_bytes(),before)

    def test_multiple_selection_compares_only_selected_and_single_mutations_refuse_it(self):
        manager=Manager(self.root,self.path)
        selected=['grok-on-sub2api','grok-on-newapi']
        manager.models.selection_set(selected)
        selected=list(manager.models.selection())
        before=copy.deepcopy(manager.value)
        with mock.patch.object(manager,'error') as error:
            manager.favorite()
            error.assert_called_once()
        self.assertEqual(manager.value,before)
        window=manager.compare();window.withdraw();self.root.update_idletasks()
        self.assertEqual([c['id'] for c in window.comparison_result['cards']],selected)
        self.assertEqual(window.comparison_result['paid_creates'],0)
        manager.refresh_models()
        self.assertEqual(list(manager.models.selection()),selected)
        window.destroy()

    def test_multiline_notes_remain_multiline_and_do_not_touch_disk(self):
        form=Fields(self.book,'notes',{'notes':'第一段\n第二段'},[('notes','备注','multiline')])
        self.assertEqual(form.read(),{'notes':'第一段\n第二段'})
        form.fields[0][1].insert('end','\n第三段')
        self.assertEqual(form.read()['notes'],'第一段\n第二段\n第三段')

    def test_upstream_quota_form_applies_typed_values_without_saving(self):
        manager=Manager(self.root,self.path)
        before=self.path.read_bytes(); created={}
        def fields(book,title,*args,**kwargs):
            created[title]=Fields(book,title,*args,**kwargs)
            return created[title]
        with mock.patch('videocreate.manager_forms.Fields',side_effect=fields), mock.patch.object(manager,'error') as error:
            manager.edit_upstream('primary-sub2api')
            form=created['配额']
            for name,var,kind in form.fields:
                if name=='create_rpm':var.set('2')
                if name=='max_remote_inflight':var.set('3')
            def widgets(root):
                for child in root.winfo_children():
                    yield child
                    yield from widgets(child)
            button=next(w for w in widgets(self.root) if isinstance(w,ttk.Button) and w.cget('text')=='应用到待保存配置')
            button.invoke();error.assert_not_called()
        self.assertEqual(manager.value['upstreams']['primary-sub2api']['quotas'],{'create_rpm':2,'max_remote_inflight':3})
        self.assertTrue(manager.dirty)
        self.assertEqual(self.path.read_bytes(),before)

    def test_quota_panel_uses_saved_policy_without_network_or_config_writes(self):
        self.config['upstreams']['primary-sub2api']['quotas']={'create_rpm':2}
        atomic_json(self.path,self.config);before=self.path.read_bytes()
        manager=Manager(self.root,self.path);manager.current_upstream='primary-sub2api'
        manager.value['upstreams']['primary-sub2api']['quotas']['create_rpm']=99
        with mock.patch('urllib.request.urlopen') as network:
            window=manager.quota_panel();window.withdraw()
            self.assertEqual(window.quota_result['limits']['create_rpm'],2)
            self.assertEqual(window.quota_result['network_requests'],0)
            network.assert_not_called();window.destroy()
        self.assertEqual(self.path.read_bytes(),before)


if __name__=='__main__':unittest.main()
