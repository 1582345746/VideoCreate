"""Native local catalog manager. UI edits the same JSON service used by the CLI."""
from __future__ import annotations

import copy
import json
import tkinter as tk
from . import manager_lifecycle as ui
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

from .config import management as service
from .config.schema import ADAPTERS, validate_config
from .config.storage import ConfigError, load_json, parse_json, user_config_path


class Manager:
    def __init__(self, window, path):
        self.window, self.path = window, Path(path).resolve()
        self.window.title('VideoCreate · 上游与模型管理')
        self.window.geometry('1240x780')
        self.window.minsize(1020, 660)
        style = ttk.Style(window)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('Treeview', rowheight=34)
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 19, 'bold'))
        style.configure('Muted.TLabel', foreground='#64748b')
        style.configure('Accent.TButton', padding=(14, 7))
        self.dirty = False
        self.record = service.load(self.path)
        if not self.record['editable']:
            raise ConfigError('; '.join(self.record['errors']))
        self.value = service.migrate(self.record['config'])
        self.dirty = self.value != self.record['config']
        self.search = ui.StringVar(window)
        self.favorites_only = ui.BooleanVar(window)
        self.kind_filter = ui.StringVar(window, value='全部类型')
        self.family_filter = ui.StringVar(window, value='全部家族')
        self.sort_order = ui.StringVar(window, value='配置顺序')
        self.current_upstream = None
        self.task_scenario = None
        self.task_exclusions = False
        self.task_report = None
        self.status = ui.StringVar(window)
        self.build()
        self.refresh()
        self.window.protocol('WM_DELETE_WINDOW', self.close)

    def build(self):
        outer = ttk.Frame(self.window, padding=20)
        outer.pack(fill='both', expand=True)
        top = ttk.Frame(outer)
        top.pack(fill='x')
        ttk.Label(top, text='上游与模型', style='Title.TLabel').pack(side='left')
        ttk.Button(top, text='保存配置', style='Accent.TButton', command=self.save).pack(side='right')
        ttk.Button(top, text='重新载入', command=self.reload).pack(side='right', padx=8)
        ttk.Button(top, text='恢复备份', command=self.restore).pack(side='right')
        ttk.Label(outer, text=str(self.path), style='Muted.TLabel').pack(anchor='w', pady=(5, 16))
        main = ttk.Panedwindow(outer, orient='horizontal')
        main.pack(fill='both', expand=True)
        left = ttk.Frame(main, padding=(0, 0, 15, 0))
        main.add(left, weight=1)
        ttk.Label(left, text='服务与账户').pack(anchor='w', pady=(0, 8))
        ttk.Button(left, text='查看共享账户配额', command=self.quota_panel).pack(fill='x', pady=(0, 8))
        self.providers = ttk.Treeview(left, show='tree', selectmode='browse', height=15)
        self.providers.pack(fill='both', expand=True)
        self.providers.bind('<<TreeviewSelect>>', self.select_upstream)
        for title, action in [('新增上游', lambda: self.edit_upstream()), ('编辑上游', self.edit_selected_upstream),
                              ('复制为新上游', lambda: self.edit_upstream(copy_from=self.current_upstream)),
                              ('管理凭据', self.credential), ('归档 / 恢复上游', self.archive_upstream),
                              ('只读检查 / 导入目录', self.discover), ('查看已保存目录', lambda:self.discover(refresh=False)),
                              ('新建制作项目', self.new_project), ('项目与任务', self.project_panel),
                              ('角色与素材库', self.library_panel), ('迁移旧剪辑计划', self.legacy_edit_panel)]:
            ttk.Button(left, text=title, command=action).pack(fill='x', pady=(7, 0))
        ttk.Button(left, text='本机素材与 HTTPS 直链', command=self.media_panel).pack(fill='x', pady=(7, 0))
        right = ttk.Frame(main)
        main.add(right, weight=5)
        bar = ttk.Frame(right)
        bar.pack(fill='x', pady=(0, 8))
        ttk.Entry(bar, textvariable=self.search).pack(side='left', fill='x', expand=True)
        ttk.Checkbutton(bar, text='收藏', variable=self.favorites_only, command=self.refresh_models).pack(side='left', padx=8)
        ttk.Button(bar, text='新增型号', command=lambda: self.edit_binding()).pack(side='right', padx=(8, 0))
        self.search.trace_add('write', lambda *_: self.refresh_models())
        taskbar=ttk.Frame(right);taskbar.pack(fill='x',pady=(0,8))
        ttk.Button(taskbar,text='按任务筛选',command=self.task_filter).pack(side='left')
        ttk.Button(taskbar,text='清除任务筛选',command=self.clear_task_filter).pack(side='left',padx=8)
        self.task_note=ui.StringVar(self.window,value='可按操作、时长、分辨率、画幅和参考数量筛选；不提交生成。')
        ttk.Label(taskbar,textvariable=self.task_note,wraplength=650,style='Muted.TLabel').pack(side='left')
        filters = ttk.Frame(right)
        filters.pack(fill='x', pady=(0,8))
        for label,var,choices,width in [('媒体',self.kind_filter,['全部类型','视频','图片'],10),
                ('家族',self.family_filter,['全部家族',*sorted({m['family'] for m in self.value['models'].values()})],16),
                ('排序',self.sort_order,['配置顺序','名称','上游','家族'],12)]:
            ttk.Label(filters,text=label).pack(side='left',padx=(0,5))
            field=ttk.Combobox(filters,textvariable=var,values=choices,state='readonly',width=width)
            field.pack(side='left',padx=(0,12))
            field.bind('<<ComboboxSelected>>',lambda _:self.refresh_models())
            if label=='家族':self.family_choices=field
        ttk.Label(filters,text='Ctrl / Shift 可选 2–4 个型号比较',style='Muted.TLabel').pack(side='left')
        columns = ('upstream', 'model', 'state', 'price', 'notes')
        self.models = ttk.Treeview(right, columns=columns, show='headings', selectmode='extended', height=10)
        for col, title, width in zip(columns, ['上游', '型号', '接入状态', '价格', '备注'], [140, 210, 110, 130, 270]):
            self.models.heading(col, text=title)
            self.models.column(col, width=width, minwidth=70)
        self.models.pack(fill='both', expand=True)
        self.models.bind('<<TreeviewSelect>>', self.show_details)
        self.models.bind('<Double-1>', lambda _: self.edit_selected_binding())
        actions = ttk.Frame(right)
        actions.pack(fill='x', pady=8)
        for title, action in [('编辑型号', self.edit_selected_binding), ('收藏 / 取消', self.favorite),
                              ('归档 / 恢复型号', self.archive_binding), ('设为以后默认', self.default_binding),
                              ('比较所选', self.compare), ('逐操作实测', self.evidence_panel)]:
            ttk.Button(actions, text=title, command=action).pack(side='left', padx=(0, 7))
        self.detail = tk.Text(right, height=12, wrap='word', font=('Microsoft YaHei UI', 10),
                              background='#f4f7fb', foreground='#27354a', borderwidth=0, padx=14, pady=12)
        self.detail.pack(fill='both', expand=True)
        self.detail.configure(state='disabled')
        ttk.Label(outer, textvariable=self.status, style='Muted.TLabel').pack(anchor='w', pady=(12, 0))

    def error(self, exc):
        messagebox.showerror('未完成操作', str(exc), parent=self.window)

    def changed(self):
        self.dirty = True
        self.refresh()

    def refresh(self):
        self.providers.delete(*self.providers.get_children())
        self.providers.insert('', 'end', iid='__all', text='全部上游')
        for uid, u in self.value['upstreams'].items():
            self.providers.insert('', 'end', iid=uid, text=u.get('display_name', uid) + (' · 已归档' if u.get('archived') else ''))
        self.providers.selection_set(self.current_upstream or '__all')
        families = ['全部家族',*sorted({m['family'] for m in self.value['models'].values()})]
        self.family_choices.configure(values=families)
        if self.family_filter.get() not in families:self.family_filter.set('全部家族')
        self.refresh_models()
        self.status.set(('有未保存修改  ·  ' if self.dirty else '已保存  ·  ') +
            f"配置 v{self.value['schema_version']} / 修订 {self.record['revision']}  ·  保存和查看不会生成媒体")

    def select_upstream(self, _=None):
        chosen = self.providers.selection()
        if chosen:
            self.current_upstream = None if chosen[0] == '__all' else chosen[0]
            self.refresh_models()

    def refresh_models(self):
        if not hasattr(self, 'models'):
            return
        selected = self.models.selection()
        self.models.delete(*self.models.get_children())
        from .catalog.presentation import rows
        filters=dict(upstream=self.current_upstream,
            kind={'视频':'video','图片':'image'}.get(self.kind_filter.get()),
            family=None if self.family_filter.get()=='全部家族' else self.family_filter.get(),
            query=self.search.get(),favorites=self.favorites_only.get(),
            order={'配置顺序':'configured','名称':'name','上游':'upstream','家族':'family'}[self.sort_order.get()])
        if self.task_scenario is not None:
            from .catalog.suitability import query
            self.task_report=query(self.value,self.task_scenario,**filters)
            visible=[row for row in self.task_report['bindings'] if self.task_exclusions or row['task_fit']['matches']]
            n=self.task_report['counts']
            self.task_note.set(f"参数范围相符 {n['parameters-match']} · 不符合 {n['excluded']} · 未核实 {n['unverified']}；尚需正式选型与预检。")
        else:
            visible=rows(self.value,**filters);self.task_report=None
            self.task_note.set('可按操作、时长、分辨率、画幅和参考数量筛选；不提交生成。')
        for row in visible:
            state=row['state_text']
            if 'task_fit' in row:state={'parameters-match':'参数范围相符','excluded':'不符合任务','unverified':'尚未核实'}[row['task_fit']['status']]+' · '+state
            self.models.insert('', 'end', iid=row['id'], values=(row['upstream_name'],
                ('★ ' if row['favorite'] else '') + row['display_name'], state,
                row['price_text'].replace('\n',' · '), row['notes'].replace('\n', ' ')))
        self.models.selection_set([bid for bid in selected if self.models.exists(bid)])
        self.show_details()

    def selected_binding(self):
        items = self.models.selection()
        if len(items)>1:
            self.error('此操作只处理一个型号。请先单选；并排查看请使用“比较所选”。')
            return None
        return items[0] if items else None

    def show_details(self, _=None):
        selected = self.models.selection()
        from .catalog.presentation import card
        data = card(self.value, selected[0]) if len(selected)==1 else None
        if data and self.task_report:
            row=next((row for row in self.task_report['bindings'] if row['id']==selected[0]),None)
            if row:
                fit=row['task_fit']
                data['fields']['本次任务筛选']='；'.join(fit['reasons']+fit['unknowns']) or '已填写参数与数量范围相符；尚未检查实际素材、提示词、凭据和完整请求。'
                if fit['warnings']:data['fields']['参数说明']='；'.join(fit['warnings'])
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', '\n\n'.join(key+'：'+value for key,value in data['fields'].items()) if data else
            ('已选择 '+str(len(selected))+' 个型号。点击“比较所选”查看报价与参数对照。' if selected else '选择型号可查看参数、报价、备注与来源。'))
        self.detail.configure(state='disabled')

    def task_filter(self):
        from .manager_task_filter import TaskFilterPanel
        return TaskFilterPanel(self).win

    def clear_task_filter(self):
        self.task_scenario=None;self.task_exclusions=False;self.refresh_models()

    def save(self):
        try:
            errors = validate_config(self.value)
            if errors:
                raise ConfigError('; '.join(errors))
            paths = service.changed_paths(self.record['config'], self.value)
            if paths and not messagebox.askyesno('保存差异', '\n'.join(paths[:20]) +
                    (f'\n另有 {len(paths) - 20} 项' if len(paths) > 20 else '') + '\n\n保存这些修改？', parent=self.window):
                return False
            result = service.save(self.path, self.value, expected_token=self.record['token'], reason='local manager edit')
            self.record = service.load(self.path)
            self.value = copy.deepcopy(self.record['config'])
            self.dirty = False
            self.refresh()
            if result.get('warning'):
                messagebox.showwarning('保存提示', result['warning'], parent=self.window)
            return True
        except (ConfigError, OSError, ValueError) as exc:
            self.error(exc)
            return False

    def reload(self, *, discard_forms=False):
        from .manager_drafts import confirm_close, guards
        if not discard_forms and not confirm_close(self.window, scope='configuration'):return
        if self.dirty and not messagebox.askyesno('重新载入', '丢弃当前未保存的修改并读取磁盘配置？', parent=self.window):
            return
        try:
            record = service.load(self.path)
            if record['errors']:
                raise ConfigError('; '.join(record['errors']))
            for guard in guards(self.window):
                if guard.scope == 'configuration':guard.window.destroy()
            self.record = record
            self.value = service.migrate(record['config'])
            self.dirty = self.value != record['config']
            self.refresh()
        except (ConfigError, OSError, ValueError) as exc:
            self.error(exc)

    def restore(self):
        if self.dirty:
            self.error('请先保存或重新载入，避免丢失未保存的修改。')
            return
        from .manager_drafts import confirm_close
        if not confirm_close(self.window, scope='configuration'):return
        backup = filedialog.askopenfilename(parent=self.window, title='选择配置备份',
            initialdir=self.path.parent / 'backups', filetypes=[('JSON', '*.json')])
        if backup:
            try:
                service.restore(self.path, backup, expected_token=self.record['token'])
                self.reload(discard_forms=True)
            except (ConfigError, OSError, ValueError) as exc:
                self.error(exc)

    def dialog(self, title):
        win = tk.Toplevel(self.window)
        win.title(title)
        win.geometry('790x650')
        win.transient(self.window)
        win.grab_set()
        book = ttk.Notebook(win)
        book.pack(fill='both', expand=True, padx=18, pady=14)
        basic = ttk.Frame(book, padding=16)
        book.add(basic, text='基本信息')
        return win, book, basic

    @staticmethod
    def field(frame, row, label, value='', values=None, readonly=False, secret=False):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 14), pady=7)
        var = ui.StringVar(frame, value=str(value))
        if values is not None:
            widget = ttk.Combobox(frame, textvariable=var, values=values, state='readonly')
        else:
            widget = ttk.Entry(frame, textvariable=var, show='●' if secret else '')
            if readonly:
                widget.configure(state='readonly')
        widget.grid(row=row, column=1, sticky='ew', pady=7)
        frame.columnconfigure(1, weight=1)
        return var

    @staticmethod
    def json_tab(book, title, value):
        frame = ttk.Frame(book, padding=10)
        book.add(frame, text=title)
        editor = tk.Text(frame, wrap='word', font=('Consolas', 10), undo=True)
        editor.pack(fill='both', expand=True)
        editor.insert('1.0', json.dumps(value, ensure_ascii=False, indent=2))
        return editor

    @staticmethod
    def read_object(editor):
        text = editor.get('1.0', 'end').strip()
        try:
            result = parse_json(text or '{}')
        except json.JSONDecodeError as exc:
            raise ConfigError(f'JSON 格式错误，第 {exc.lineno} 行，第 {exc.colno} 列') from None
        if not isinstance(result, dict):
            raise ConfigError('此页需要 JSON 对象')
        return result

    def edit_selected_upstream(self):
        if self.current_upstream:
            self.edit_upstream(self.current_upstream)

    def edit_upstream(self, uid=None, copy_from=None):
        original = copy.deepcopy(self.value['upstreams'].get(uid or copy_from, {}))
        if copy_from:
            original.pop('archived', None)
        win, book, basic = self.dialog('编辑上游' if uid else '新增上游')
        fields = {}
        for i, (key, label, default) in enumerate([
            ('id', '稳定标识', uid or ''), ('display_name', '显示名称', original.get('display_name', '')),
            ('base_url', 'API 地址', original.get('base_url', 'https://')),
            ('account_id', '账户标识', original.get('account_id', uid or '')),
            ('max_concurrent_submissions', '同时提交数', original.get('max_concurrent_submissions', 2)),
            ('request_timeout_seconds', '请求超时（秒）', original.get('request_timeout_seconds', 120)),
            ('documentation_url', '文档链接', original.get('documentation_url', ''))]):
            fields[key] = self.field(basic, i, label, default, readonly=bool(uid and key in {'id', 'base_url', 'account_id'}))
        auth = original.get('auth', {'type': 'bearer', 'env': 'VIDEOCREATE_NEW_PROVIDER_KEY'})
        mode = self.field(basic, 7, '凭据来源', 'secret_ref' if 'secret_ref' in auth else 'env' if 'env' in auth else 'existing',
                          values=['secret_ref', 'env', 'existing'])
        ref = self.field(basic, 8, '凭据引用 / 环境变量', auth.get('secret_ref', auth.get('env', '')))
        from .manager_forms import Fields
        notes = Fields(book, '备注', {'notes': original.get('notes', ''), 'capacity_group': original.get('capacity_group', '')},
            [('notes','说明与备注','multiline'), ('capacity_group','共享并发容量组（可空）','text')],
            '同一账户标识或相同容量组的入口共用最严格限制；包含已归档入口。')
        quotas = Fields(book, '配额', original.get('quotas', {}),
            [('max_remote_inflight','远端在途任务上限','integer'),
             ('create_rpm','每分钟创建准入数','integer'), ('poll_rpm','每分钟查询请求数','integer'),
             ('download_rpm','每分钟下载请求数','integer')],
            '留空表示未配置。只统计同一配置目录中登记的 v3 项目；其他机器和外部客户端不计入。'
            '未知提交持续占用在途名额；本地停止等待不会释放。创建准入数可能包含后续被本地预算拒绝的请求，不能当作账单。')
        ttk.Label(basic, text='先建立上游，再用“管理凭据”录入密钥。更换地址或账户请新增上游。',
                  style='Muted.TLabel', wraplength=600).grid(row=9, column=0, columnspan=2, sticky='w', pady=12)
        def apply():
            try:
                identity = fields['id'].get().strip()
                if not uid and identity in self.value['upstreams']:
                    raise ConfigError('标识已经存在')
                item = {**original, **{k: v.get().strip() for k, v in fields.items() if k != 'id'},
                        **notes.read()}
                for k in ('max_concurrent_submissions', 'request_timeout_seconds'):
                    item[k] = int(item[k])
                limits = quotas.read()
                if limits:
                    item['quotas'] = limits
                else:
                    item.pop('quotas', None)
                if mode.get() != 'existing':
                    item['auth'] = {'type': 'bearer', mode.get(): ref.get().strip()}
                elif 'auth' not in item:
                    raise ConfigError('新增上游请选择环境变量或加密凭据引用')
                candidate = service.upsert(self.value, 'upstreams', identity, item)
                errors = validate_config(candidate)
                if errors:
                    raise ConfigError('; '.join(errors))
                self.value = candidate
                self.current_upstream = identity
                self.changed()
                win.destroy()
            except (ConfigError, OSError, ValueError) as exc:
                self.error(exc)
        ttk.Button(win, text='应用到待保存配置', command=apply).pack(pady=(0, 15))
        from .manager_drafts import DraftGuard
        DraftGuard(win, label='上游设置（尚未应用到待保存配置）', scope='configuration')

    def edit_selected_binding(self):
        bid = self.selected_binding()
        if bid:
            self.edit_binding(bid)

    def edit_binding(self, bid=None):
        original = copy.deepcopy(self.value['bindings'].get(bid, {}))
        win, book, basic = self.dialog('编辑型号' if bid else '新增型号')
        fields = {}
        entries = [
            ('id', '接入标识', bid or ''), ('upstream', '上游', original.get('upstream', self.current_upstream or '')),
            ('model', '内部型号标识', original.get('model', '')), ('remote_model', '远端型号（原样）', original.get('remote_model', '')),
            ('display_name', '显示名称', original.get('display_name', '')),
            ('family', '模型家族', self.value['models'].get(original.get('model'), {}).get('family', 'seedance')),
            ('kind', '媒体类型', self.value['models'].get(original.get('model'), {}).get('kind', 'video')),
            ('adapter', '接口协议', original.get('adapter', 'unconfigured')),
            ('operations', '操作（逗号分隔）', ','.join(original.get('operations', []))),
        ]
        for i, (key, label, default) in enumerate(entries):
            choices = list(self.value['upstreams']) if key == 'upstream' else ['video', 'image'] if key == 'kind' else ['unconfigured', *ADAPTERS] if key == 'adapter' else None
            fields[key] = self.field(basic, i, label, default, values=choices,
                                      readonly=bool(bid and key in {'id', 'model'}))
        enabled = ui.BooleanVar(basic, value=original.get('enabled', False))
        ttk.Checkbutton(basic, text='启用此型号（协议与参数必须配置完整）', variable=enabled).grid(row=9, column=0, columnspan=2, sticky='w', pady=10)
        from .manager_forms import Fields, DECLARED, CAPABILITIES, MEDIA_REFERENCE_LIMITS
        from .manager_pricing import Prices
        notes = Fields(book, '备注与来源', {'notes': original.get('notes', ''),
            'tags': original.get('tags', []), 'documentation_url': original.get('documentation_url', ''),
            'sort_order': original.get('sort_order', 0)},
            [('notes','说明与备注','multiline'),('tags','标签（逗号分隔）','list'),
             ('documentation_url','文档链接','text'),('sort_order','排序数值（小值在前）','integer')],
            '备注用于展示和选型，不会自动改变接口行为或要求重新生成。')
        declared = Fields(book, '供应商声明', original.get('declared_capabilities', {}), DECLARED,
            '声明仅供选型参考。未知留空；填写声明不会让接口自动支持视频或音频参考。')
        cap_values = copy.deepcopy(original.get('capability_overrides', {}))
        media_values = cap_values.pop('media_reference_limits', {})
        caps = Fields(book, '执行参数', cap_values, CAPABILITIES,
            '仅填写已核实的接口约束。其他字段在高级页；最终仍由共用校验器和 adapter 预检。')
        media_caps = Fields(book, '多媒体限制', media_values, MEDIA_REFERENCE_LIMITS,
            '仅适用星光 v2。未知不是无限；勾选已确认的素材组合，明确音频参考能否与声音生成同时使用。'
            '未使用的素材类型数量填 0。')
        options = self.json_tab(book, '协议选项', original.get('adapter_options', {}))
        prices = Prices(book, {k: original[k] for k in ('pricing', 'listed_pricing') if k in original})
        def apply():
            try:
                f = {k: v.get().strip() for k, v in fields.items()}
                candidate = copy.deepcopy(self.value)
                if not bid:
                    candidate = service.add_binding(candidate, identity=f['id'], upstream=f['upstream'], model=f['model'],
                        remote_model=f['remote_model'], family=f['family'], kind=f['kind'], display_name=f['display_name'])
                elif self.value['models'][f['model']]['kind'] != f['kind']:
                    raise ConfigError('已有型号不能改变媒体类型，请新增型号')
                item = {**original, **{k: f[k] for k in ('upstream', 'model', 'remote_model', 'display_name', 'adapter')},
                    'operations': [x.strip() for x in f['operations'].split(',') if x.strip()],
                    'enabled': enabled.get(), 'setup_status': 'configured' if f['adapter'] != 'unconfigured' else 'draft',
                    **notes.read(), 'declared_capabilities': declared.read(),
                    'capability_overrides': caps.read(), 'adapter_options': self.read_object(options)}
                typed_limits = media_caps.read()
                if typed_limits:
                    item['capability_overrides']['media_reference_limits'] = typed_limits
                for key in ('pricing', 'listed_pricing'):
                    item.pop(key, None)
                item.update(prices.read())
                candidate['bindings'][f['id']] = item
                errors = validate_config(candidate)
                if errors:
                    raise ConfigError('; '.join(errors))
                self.value = candidate
                self.changed()
                win.destroy()
            except (ConfigError, OSError, ValueError) as exc:
                self.error(exc)
        ttk.Button(win, text='应用到待保存配置', command=apply).pack(pady=(0, 15))
        from .manager_drafts import DraftGuard
        DraftGuard(win, label='型号、参数与价格（尚未应用到待保存配置）', scope='configuration')

    def credential(self):
        uid = self.current_upstream
        if not uid:
            self.error('先选择一个上游')
            return
        original = self.value['upstreams'][uid]
        win, _, frame = self.dialog('本机加密凭据')
        account = self.field(frame, 0, '账户存储标识', uid.replace('.', '-'))
        version = self.field(frame, 1, '新版本标识', 'v2')
        key = self.field(frame, 2, 'API 密钥', '', secret=True)
        ttk.Label(frame, text='密钥加密保存到本机。已有版本保留用于恢复；更换账户请新增上游。',
                  style='Muted.TLabel', wraplength=550).grid(row=3, column=0, columnspan=2, pady=15)
        def apply():
            try:
                from .config.secrets import store_credential
                auth = store_credential(self.path.parent, account.get(), key.get(), version=version.get())
                original['auth'] = auth
                original['credential_version'] = version.get()
                key.set('')
                self.changed()
                win.destroy()
            except (ConfigError, OSError, ValueError) as exc:
                self.error(exc)
        ttk.Button(win, text='加密保存并应用引用', command=apply).pack(pady=15)
        from .manager_drafts import DraftGuard
        DraftGuard(win, label='本机凭据（尚未加密保存或应用）', scope='configuration')

    def favorite(self):
        bid = self.selected_binding()
        if bid:
            b = self.value['bindings'][bid]
            b['favorite'] = not b.get('favorite', False)
            self.changed()

    def archive_upstream(self):
        if self.current_upstream:
            self.value = service.archive(self.value, 'upstreams', self.current_upstream,
                not self.value['upstreams'][self.current_upstream].get('archived', False))
            self.changed()

    def archive_binding(self):
        bid = self.selected_binding()
        if bid:
            self.value = service.archive(self.value, 'bindings', bid,
                not self.value['bindings'][bid].get('archived', False))
            self.changed()

    def compare(self):
        from .manager_comparison import open_panel
        try:
            return open_panel(self,list(self.models.selection()))
        except (ConfigError,OSError,ValueError) as exc:self.error(exc)

    def evidence_panel(self):
        bid = self.selected_binding()
        if not bid:return
        try:
            from .catalog.presentation import card
            data = card(self.value,bid,store_root=self.path.parent)
            win,book,basic = self.dialog('逐操作实测记录')
            book.tab(0,text='观察范围')
            ttk.Label(basic,text=data['name'],font=('Microsoft YaHei UI',14,'bold')).pack(anchor='w')
            ttk.Label(basic,text=data['fields']['逐操作实测'],wraplength=690,justify='left').pack(anchor='w',pady=15)
            ttk.Label(basic,text='目录、合同、生成小样和内容质量分别记录。旧价格、备注或默认修改不会让原任务改换路线。',wraplength=690).pack(anchor='w')
            editor=self.json_tab(book,'记录详情',data['evidence'])
            editor.configure(state='disabled')
            return win
        except (ConfigError,OSError,ValueError) as exc:self.error(exc)

    def discover(self, *, refresh=True):
        if not self.current_upstream:
            self.error('先选择一个上游');return
        from .manager_catalog import CatalogPanel
        return CatalogPanel(self,self.current_upstream,refresh=refresh).win

    def legacy_edit_panel(self):
        from .manager_legacy_edit import open_form
        return open_form(self)

    def new_project(self):
        from .manager_authoring import open_new
        def completed(result):
            from .manager_projects import open_panel
            open_panel(self,Path(result['project']))
        open_new(self,completed=completed)

    def project_panel(self):
        folder = filedialog.askdirectory(parent=self.window, title='选择包含 project.json 的 v3 项目')
        if not folder:
            return
        try:
            from .manager_projects import open_panel
            open_panel(self, Path(folder))
        except (ConfigError, OSError, ValueError) as exc:
            self.error(exc)

    def quota_panel(self):
        if not self.current_upstream:
            self.error(ConfigError('请先选择一个上游'))
            return
        try:
            from .runtime.quotas import status
            # Runtime limits follow saved configuration, never unsaved form edits.
            value = service.load(self.path)['config']
            report = status(self.path.parent, value, self.current_upstream)
            win, book, page = self.dialog('共享账户配额（本机已登记项目）')
            book.tab(0, text='配额状态')
            text = tk.Text(page, wrap='word', font=('Microsoft YaHei UI',10))
            text.pack(fill='both',expand=True)
            limits = report['limits']
            text.insert('1.0', '使用已保存配置。只统计本配置目录中的已登记 v3 项目。\n'
                f"远端在途：{report['remote_inflight']} / {limits.get('max_remote_inflight','未配置')}\n"
                '未知提交没有自动过期；缺失项目保留已观察到的占用。其他机器、外部客户端不在统计范围。\n'
                '创建准入数可能包含被后续本地预算拦截的请求，不能据此计算实付。\n\n'
                + json.dumps(report,ensure_ascii=False,indent=2))
            text.configure(state='disabled')
            win.quota_result = report
            return win
        except (ConfigError,OSError,ValueError) as exc:
            self.error(exc)

    def library_panel(self):
        from .manager_library import open_panel
        try:
            open_panel(self)
        except (ConfigError, OSError, ValueError) as exc:
            self.error(exc)

    def media_panel(self):
        from .manager_media import open_panel
        try:
            return open_panel(self)
        except (ConfigError, OSError, ValueError) as exc:
            self.error(exc)

    def default_binding(self):
        bid = self.selected_binding()
        if not bid:
            return
        b = self.value['bindings'][bid]
        if not b['enabled'] or b.get('archived') or b['adapter'] == 'unconfigured':
            self.error('请先完成接入并启用该型号')
            return
        kind = self.value['models'][b['model']]['kind']
        self.value['defaults'][kind + '_model'] = b['model']
        self.value['routes'][b['model']]['preferred_binding'] = bid
        self.value['routes'][b['model']]['policy'] = 'fixed'
        auto = messagebox.askyesno('以后默认选择', '新项目未指定时直接沿用该组合？\n选择“否”会把它作为推荐项，仍先让用户选择。', parent=self.window)
        self.value.setdefault('selection', {})[kind] = {'when_unspecified': 'use-default' if auto else 'ask', 'remember_scope': 'project'}
        self.changed()

    def close(self):
        from .manager_drafts import confirm_close
        if not confirm_close(self.window):return
        if self.dirty:
            answer = messagebox.askyesnocancel('未保存修改', '保存配置后关闭？', parent=self.window)
            if answer is None or answer and not self.save():
                return
        self.window.destroy()


def launch(path=None):
    root = tk.Tk()
    try:
        path = user_config_path(path)
        if not path.exists():
            from .cli import skill_root
            from .config.storage import atomic_json
            atomic_json(path, service.migrate(load_json(skill_root() / 'assets/config/videocreate.config.example.json')))
        from .config import repair
        if repair.inspect(path)['status']!='valid':
            from .manager_repair import RepairPanel
            def recovered(_):
                panel.dispose();Manager(root,path)
            panel=RepairPanel(root,path,completed=recovered)
        else:
            Manager(root, path)
        root.mainloop()
    except Exception as exc:
        messagebox.showerror('VideoCreate', str(exc), parent=root)
        root.destroy()
        return 1
    return 0


def main():
    import argparse
    import sys
    parser = argparse.ArgumentParser(prog='VideoCreateManager')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--media-server-run', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--smoke-report', type=Path, help='Load UI offscreen, report row counts, then exit without saving or network')
    args = parser.parse_args()
    # A desktop host may virtualize LOCALAPPDATA. The local installer pins the
    # resolved authoritative file so a later Explorer launch opens the same data.
    settings = Path(sys.executable).parent / 'manager.settings.json'
    if args.config is None and getattr(sys, 'frozen', False) and settings.exists():
        location = load_json(settings).get('config_path')
        if not isinstance(location, str) or not Path(location).is_absolute():
            raise ConfigError('Installed manager settings require an absolute configuration path')
        args.config = Path(location)
    if args.media_server_run:
        from .media_server_commands import command
        return command(['run', '--config', str(user_config_path(args.config))])
    if args.smoke_report:
        from .config.storage import atomic_json
        root = tk.Tk()
        root.withdraw()
        try:
            manager = Manager(root, user_config_path(args.config))
            original_value=copy.deepcopy(manager.value)
            original_dirty=manager.dirty
            original_rows=set(manager.models.get_children())
            task_window=manager.task_filter();task_window.withdraw()
            task_form=task_window.task_filter_panel
            task_form.fields['seconds'].set('5');task_form.fields['resolution'].set('720p')
            task_form.fields['aspect_ratio'].set('16:9');task_form.check_counts.set(True)
            task_form.preview()
            if not task_form.pending:raise ConfigError('Task catalog filter did not preview')
            task_form.apply()
            expected={row['id'] for row in manager.task_report['bindings'] if row['task_fit']['matches']}
            if set(manager.models.get_children())!=expected:raise ConfigError('Task filter rows disagree with the shared service')
            task_window=manager.task_filter();task_window.withdraw();task_form=task_window.task_filter_panel
            task_form.excluded.set(True);task_form.preview();task_form.apply()
            if set(manager.models.get_children())!=original_rows:raise ConfigError('Task filter omitted excluded explanation rows')
            manager.clear_task_filter()
            if manager.value!=original_value or manager.dirty!=original_dirty or set(manager.models.get_children())!=original_rows:
                raise ConfigError('Task catalog filter changed configuration or failed to restore the view')
            # Exercise the packaged comparison and price-form modules too;
            # row counts alone do not prove the new UI is distributable.
            identities = list(manager.models.get_children())[:2]
            comparison_count = 0
            if len(identities) == 2:
                from .manager_comparison import open_panel
                panel = open_panel(manager, identities)
                panel.withdraw()
                comparison_count = len(panel.comparison_result['cards'])
                panel.destroy()
            from .manager_pricing import Prices
            book = ttk.Notebook(root)
            original = manager.value['bindings'][identities[0]] if identities else {}
            price_form = Prices(book, {k: original[k] for k in ('pricing','listed_pricing') if k in original})
            price_value = price_form.read()
            draft_guards_exercised = bool(identities and manager.value['upstreams'])
            if draft_guards_exercised:
                # Exercise the actual config forms without applying or saving drafts.
                upstream_id = next(iter(manager.value['upstreams']))
                original_upstream = manager.current_upstream
                def last_dialog():
                    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
                manager.edit_upstream(upstream_id)
                draft_window = last_dialog()
                if draft_window.draft_guard.dirty():raise ConfigError('Untouched upstream form is dirty')
                def children(parent):
                    for child in parent.winfo_children():
                        yield child
                        yield from children(child)
                field = next(w for w in children(draft_window) if isinstance(w, ttk.Entry) and not w.instate(['readonly']))
                initial_text=field.get();field.insert('end',' synthetic draft')
                if not draft_window.draft_guard.dirty():raise ConfigError('Unapplied upstream draft was not detected')
                field.delete(0,'end');field.insert(0,initial_text)
                draft_window.draft_guard.close()
                if draft_window.winfo_exists():raise ConfigError('Unchanged config form did not close')
                manager.edit_binding(identities[0]);draft_window=last_dialog()
                if draft_window.draft_guard.dirty():raise ConfigError('Untouched binding form is dirty')
                draft_window.draft_guard.close()
                manager.current_upstream=upstream_id;manager.credential();draft_window=last_dialog()
                if draft_window.draft_guard.dirty():raise ConfigError('Untouched credential form is dirty')
                draft_window.draft_guard.close();manager.current_upstream=original_upstream
                draft_window=price_form.edit()
                if draft_window.draft_guard.dirty():raise ConfigError('Untouched price form is dirty')
                draft_window.draft_guard.close()
            from .runtime.quotas import status as quota_status
            quota_reports = [quota_status(manager.path.parent, manager.value, uid)
                for uid in manager.value['upstreams']]
            import tempfile
            from .planning.profiles import create
            from .planning.project import save_bundle
            from .manager_projects import open_panel as project_panel
            from .local_sources import import_clip
            from .manager_authoring import open_new,open_editor
            local_controls = {}
            def inspect_controls(panel, profile):
                def widgets(parent):
                    for child in parent.winfo_children():
                        yield child
                        yield from widgets(child)
                labels = {w.cget('text') for w in widgets(panel) if isinstance(w, ttk.Button)}
                expected_render = profile not in {'image-only', 'gif-only', 'gif-local'}
                verified = ('制作流程与检查点' in labels and '继续制作' in labels and '导出交付清单' in labels and ('渲染当前时间线' in labels) == expected_render)
                if not verified:
                    raise ConfigError('Packaged local project controls are incomplete: ' + profile)
                expected_still = profile in {'edit-only', 'mixed-video'}
                if ('导入静态图片' in labels) != expected_still:
                    raise ConfigError('Packaged static import controls do not match the project profile')
                local_controls[profile] = {'render': expected_render, 'delivery': True, 'continue': True,
                    'static_image_import': expected_still, 'production_policy': True}
            with tempfile.TemporaryDirectory(prefix='videocreate-manager-smoke-') as temporary:
                # Catalog history/import smoke uses an isolated synthetic config,
                # never the user's observations, credentials or draft models.
                import time
                from .cli import skill_root
                from .catalog import observations
                catalog_path=Path(temporary)/'catalog/config.json'
                catalog_value=service.migrate(load_json(skill_root()/'assets/config/videocreate.config.example.json'))
                atomic_json(catalog_path,catalog_value);catalog_bytes=catalog_path.read_bytes()
                catalog_upstream=next(iter(catalog_value['upstreams']))
                observations.record(catalog_value,catalog_upstream,['smoke-gone','smoke-stable'],store_root=catalog_path.parent)
                observations.record(catalog_value,catalog_upstream,['smoke-stable','smoke-new'],store_root=catalog_path.parent)
                catalog_root=tk.Toplevel(root);catalog_root.withdraw()
                catalog_manager=Manager(catalog_root,catalog_path);catalog_manager.current_upstream=catalog_upstream
                catalog_window=catalog_manager.discover(refresh=False);catalog_window.withdraw();catalog_form=catalog_window.catalog_panel
                deadline=time.monotonic()+10
                while catalog_form.background.busy and time.monotonic()<deadline:root.update();time.sleep(.005)
                if not catalog_form.result or catalog_form.result['network_requests']:
                    raise ConfigError('Cached catalog form did not load offline')
                catalog_form.view.set('相比上次未再出现')
                if list(catalog_form.items.values())!=['smoke-gone']:
                    raise ConfigError('Catalog form lost disappeared, unconfigured model names')
                catalog_form.view.set('相比上次新增')
                if list(catalog_form.items.values())!=['smoke-new']:
                    raise ConfigError('Catalog form did not show the exact new model ID')
                catalog_form.tree.selection_set(next(iter(catalog_form.items)))
                catalog_form.apply()
                draft=next((b for b in catalog_manager.value['bindings'].values() if b['remote_model']=='smoke-new'),None)
                if (not draft or draft['enabled'] or draft['adapter']!='unconfigured' or
                        draft['declared_capabilities']['source']['kind']!='catalog' or not catalog_manager.dirty
                        or catalog_path.read_bytes()!=catalog_bytes):
                    raise ConfigError('Catalog import did not remain a source-bound, unsaved disabled draft')
                catalog_root.destroy()
                project = Path(temporary) / 'edit-only'
                save_bundle(project, create('edit-only', title='Offline import panel smoke'))
                panel = project_panel(manager, project)
                inspect_controls(panel, 'edit-only')
                panel.withdraw()
                root.update_idletasks()
                panel.destroy()
                from .manager_stills import open_form as still_form
                dialog = still_form(manager, project, source=Path(temporary)/'synthetic-static.png')
                dialog.withdraw();root.update_idletasks();dialog.destroy()
                dialog=open_editor(manager,project,'timeline')
                dialog.withdraw();root.update_idletasks();dialog.destroy()
                for profile in ('image-only','gif-only','gif-local','mixed-video'):
                    pure = Path(temporary) / profile
                    save_bundle(pure,create(profile,title='Offline pure media panel',topic='Synthetic offline prompt'))
                    panel = project_panel(manager,pure)
                    inspect_controls(panel, profile)
                    panel.withdraw()
                    root.update_idletasks()
                    panel.destroy()
                    dialog=open_editor(manager,pure,'generation-plan')
                    dialog.withdraw();root.update_idletasks();dialog.destroy()
                    if profile=='gif-local':
                        from .manager_gifs import open_form as gif_form
                        for is_frames in (False,True):
                            dialog=gif_form(manager,pure,frames=is_frames,paths=[Path(temporary)/'synthetic-input.png'])
                            dialog.withdraw()
                            root.update_idletasks()
                            dialog.destroy()
                dialog=open_new(manager);dialog.withdraw();root.update_idletasks();dialog.destroy()
                from .planning.examples import smart_car
                authored=Path(temporary)/'authoring'
                save_bundle(authored,smart_car())
                panel = project_panel(manager, authored)
                inspect_controls(panel, 'video')
                panel.withdraw();root.update_idletasks();panel.destroy()
                from .production_continue import describe
                from .manager_continuation import open_inspection
                from .manager_tasks import open_panel as execution_panel
                task_window = execution_panel(manager, authored)
                task_window.withdraw();root.update_idletasks();task_window.destroy()
                from .manager_policy import open_panel as policy_panel
                import time
                policy_window = policy_panel(manager, authored);policy_window.withdraw()
                policy_deadline = time.monotonic() + 10
                while policy_window.policy_panel.busy and time.monotonic() < policy_deadline:
                    root.update();time.sleep(.01)
                if not policy_window.policy_panel.snapshot:
                    raise ConfigError('Production policy panel did not load its shared offline service')
                policy_window.destroy()
                dialog = open_inspection(manager, authored, describe(authored),
                    edit_layer=lambda *args, **kwargs: None, completed=lambda value: None)
                dialog.withdraw();root.update_idletasks();dialog.destroy()
                for layer in ('brief','story','director','generation-plan','timeline'):
                    dialog=open_editor(manager,authored,layer)
                    if layer=='timeline':
                        form=dialog.authoring_timeline
                        form.transitions.add();form.draw()
                        if not form.graph_data['ok'] or len(form.graph_data.get('transitions',[]))!=1:
                            raise ConfigError('Packaged transition form did not produce a valid overlap preview')
                        from .manager_timeline import set_field
                        set_field(form.finishing,'filters','warm,sharpen')
                        set_field(form.finishing,'loudness.target_lufs','-18')
                        set_field(form.finishing,'subtitle_render.burn','是')
                        set_field(form.finishing,'subtitle_render.style','clean')
                        form.draw()
                        if (not form.graph_data['ok'] or form.read()['format_version']!=3
                                or form.graph_data['finishing']['loudness']!={'target_lufs':-18}):
                            raise ConfigError('Packaged finishing controls did not produce a valid format 3 preview')
                        set_field(form.finishing,'fade_seconds','.2')
                        set_field(form.finishing,'mix_limiter','否')
                        set_field(form.segments.editor,'source_gain_db','-6')
                        form.draw()
                        if not form.graph_data['ok'] or form.read()['format_version']!=4:
                            raise ConfigError('Packaged format 4 controls did not preview')
                    dialog.withdraw();root.update_idletasks();dialog.destroy()
                dialog=open_editor(manager,authored,'director',assets_only=True)
                dialog.withdraw();root.update_idletasks();dialog.destroy()
                from .manager_legacy_edit import open_form as migration_form
                dialog=migration_form(manager,source=authored)
                dialog.withdraw();root.update_idletasks();dialog.destroy()
                from .config import repair
                from .manager_repair import RepairPanel
                broken=Path(temporary)/'damaged.json'
                broken_raw=b'{"schema_version":4,"damaged":}'
                broken.write_bytes(broken_raw)
                recovery=tk.Toplevel(root);recovery.withdraw();recovered=[]
                def repaired(value):
                    repair_panel.dispose();recovered.append(Manager(recovery,broken))
                repair_panel=RepairPanel(recovery,broken,completed=repaired)
                from .cli import skill_root
                draft=json.dumps(service.migrate(load_json(skill_root()/'assets/config/videocreate.config.example.json')))
                repair_panel.editor.insert('1.0',draft);root.update()
                repair_panel.preview()
                deadline=time.monotonic()+10
                while repair_panel.call.busy and time.monotonic()<deadline:root.update();time.sleep(.005)
                if not repair_panel.pending:raise ConfigError('Configuration repair did not preview')
                original_backup=Path(repair_panel.pending['original_backup'])
                repair_panel.apply()
                deadline=time.monotonic()+10
                while repair_panel.call.busy and time.monotonic()<deadline:root.update();time.sleep(.005)
                if not recovered or original_backup.read_bytes()!=broken_raw:
                    raise ConfigError('Configuration repair did not return to the manager with its exact backup')
                recovery.destroy()
                broken.write_text('{"schema_version":99,"damaged":',encoding='utf-8')
                recovery=tk.Toplevel(root);recovery.withdraw();repair_panel=RepairPanel(recovery,broken)
                if repair_panel.snapshot['can_repair'] or not all(button.instate(['disabled']) for button in repair_panel.buttons.values()):
                    raise ConfigError('Newer configuration repair was not read-only')
                recovery.destroy()
            # Exercise real Tcl teardown in the packaged runtime too.
            owner = ttk.Frame(root)
            probe = ui.StringVar(owner, value='lifecycle smoke')
            command = probe.trace_add('write', lambda *_: None)
            name = str(probe);owner.destroy()
            if (probe._tk is not None or root.tk.call('info', 'exists', name)
                    or root.tk.call('info', 'commands', command)):
                raise ConfigError('Closed UI variables or trace commands remain live')
            from .manager_media import open_panel as media_panel
            media_window = media_panel(manager);media_window.withdraw()
            root.update_idletasks();media_window.destroy()
            import gc
            import threading
            collector = threading.Thread(target=gc.collect)
            collector.start();collector.join(10)
            if collector.is_alive():
                raise ConfigError('Worker garbage collection did not finish')
            ui.reap_interpreters()
            root.update_idletasks()
            atomic_json(args.smoke_report, {'ok': True, 'upstreams': len(manager.value['upstreams']),
                'bindings': len(manager.models.get_children()), 'config_version': manager.value['schema_version'],
                'comparison_count': comparison_count, 'conditional_tiers': len(price_value.get('pricing',{}).get('tiers',[])),
                'comparison_and_pricing_forms_created': True,
                'task_catalog_filter_preview_apply_clear': True,
                'task_catalog_filter_exclusions_and_config_preserved': True,
                'catalog_observation_cached_changes_exercised': True,
                'catalog_source_bound_unsaved_draft_exercised': True,
                'configuration_draft_guards_exercised': draft_guards_exercised,
                'nested_price_draft_guard_exercised': draft_guards_exercised,
                'configuration_repair_preview_apply_and_return': True,
                'configuration_repair_exact_original_backup': True,
                'configuration_repair_future_version_read_only': True,
                'quota_module_loaded': True, 'quota_upstreams': len(quota_reports),
                'edit_only_panel_created': True, 'local_source_module_loaded': callable(import_clip),
                'image_and_gif_panels_created': True,
                'local_gif_panel_created': True,
                'local_gif_conversion_forms_created': True,
                'mixed_video_panel_created': True,
                'authoring_forms_created': True,
                'screenplay_forms_created': True,
                'project_asset_forms_created': True,
                'generation_job_forms_created': True,
                'timeline_forms_created': True,
                'timeline_transition_form_previewed': True,
                'timeline_finishing_form_previewed': True,
                'timeline_format4_controls_previewed': True,
                'legacy_edit_migration_form_created': True,
                'local_project_action_controls': local_controls,
                'continuation_inspection_form_created': True,
                'generation_execution_panel_created': True,
                'static_image_import_form_created': True,
                'production_policy_panel_loaded': True,
                'lifecycle_scope_tcl_cleanup': True,
                'lifecycle_worker_gc': True,
                'lifecycle_media_panel_close': True,
                'network_requests': 0, 'saved': False, 'visual_review': 'not-performed'})
        finally:
            root.destroy()
        return 0
    return launch(args.config)


if __name__ == '__main__':
    raise SystemExit(main())
