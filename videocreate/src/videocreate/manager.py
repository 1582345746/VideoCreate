"""Native local catalog manager. UI edits the same JSON service used by the CLI."""
from __future__ import annotations

import copy
import json
import tkinter as tk
import queue
import threading
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
        self.search = tk.StringVar()
        self.favorites_only = tk.BooleanVar()
        self.current_upstream = None
        self.status = tk.StringVar()
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
        self.providers = ttk.Treeview(left, show='tree', selectmode='browse', height=15)
        self.providers.pack(fill='both', expand=True)
        self.providers.bind('<<TreeviewSelect>>', self.select_upstream)
        for title, action in [('新增上游', lambda: self.edit_upstream()), ('编辑上游', self.edit_selected_upstream),
                              ('复制为新上游', lambda: self.edit_upstream(copy_from=self.current_upstream)),
                              ('管理凭据', self.credential), ('归档 / 恢复上游', self.archive_upstream),
                              ('只读检查 / 导入目录', self.discover), ('项目与任务', self.project_panel),
                              ('角色与素材库', self.library_panel)]:
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
        columns = ('upstream', 'model', 'state', 'price', 'notes')
        self.models = ttk.Treeview(right, columns=columns, show='headings', selectmode='browse', height=10)
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
                              ('比较型号', self.compare)]:
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
        term = self.search.get().casefold().strip()
        for row in service.catalog(self.value, upstream=self.current_upstream):
            if self.favorites_only.get() and not row['favorite']:
                continue
            if term and term not in ' '.join(str(row[k]) for k in ('display_name', 'remote_model', 'family', 'notes', 'upstream_name')).casefold():
                continue
            price = row.get('pricing')
            if price:
                parts = []
                for key, unit in [('per_request', '次'), ('per_second', '秒')]:
                    if key in price:
                        parts.append(str(price[key]) + '/' + unit)
                price_text = price['currency'] + ' ' + '+'.join(parts)
                if price.get('status') == 'unverified':
                    price_text += ' 待核实'
            elif row.get('listed_pricing'):
                p = row['listed_pricing']
                price_text = str(p.get('display_symbol', p.get('currency') or '')) + str(p.get('amount', '?')) + ' 声明价'
            else:
                price_text = '未录入'
            status = '已归档' if row['archived'] else '待接入' if row['adapter'] == 'unconfigured' or row['setup_status'] == 'draft' else '已启用' if row['enabled'] else '已禁用'
            self.models.insert('', 'end', iid=row['id'], values=(row['upstream_name'],
                ('★ ' if row['favorite'] else '') + row['display_name'], status, price_text, row['notes'].replace('\n', ' ')))
        if selected and self.models.exists(selected[0]):
            self.models.selection_set(selected[0])

    def selected_binding(self):
        items = self.models.selection()
        return items[0] if items else None

    def show_details(self, _=None):
        bid = self.selected_binding()
        if not bid:
            return
        b = self.value['bindings'][bid]
        data = {'型号': b['remote_model'], '接入标识': bid, '备注': b.get('notes', ''),
                '操作': b['operations'], '供应商声明': b.get('declared_capabilities', {}),
                '实际参数约束': b.get('capability_overrides', {}), '报价说明': b.get('listed_pricing', {}),
                '预算计价': b.get('pricing', {}), '说明': '已启用仅表示允许调用；实际质量请查看对应任务审核。'}
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', json.dumps(data, ensure_ascii=False, indent=2))
        self.detail.configure(state='disabled')

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

    def reload(self):
        if self.dirty and not messagebox.askyesno('重新载入', '丢弃当前未保存的修改并读取磁盘配置？', parent=self.window):
            return
        try:
            record = service.load(self.path)
            if record['errors']:
                raise ConfigError('; '.join(record['errors']))
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
        backup = filedialog.askopenfilename(parent=self.window, title='选择配置备份',
            initialdir=self.path.parent / 'backups', filetypes=[('JSON', '*.json')])
        if backup:
            try:
                service.restore(self.path, backup, expected_token=self.record['token'])
                self.reload()
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
        var = tk.StringVar(value=str(value))
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
            [('notes','说明与备注','text'), ('capacity_group','共享并发容量组（可空）','text')],
            '同一账户的多个入口可填写相同容量组；共用最严格的同时提交数。')
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
        enabled = tk.BooleanVar(value=original.get('enabled', False))
        ttk.Checkbutton(basic, text='启用此型号（协议与参数必须配置完整）', variable=enabled).grid(row=9, column=0, columnspan=2, sticky='w', pady=10)
        from .manager_forms import Fields, DECLARED, CAPABILITIES, PRICES, MEDIA_REFERENCE_LIMITS
        notes = Fields(book, '备注与来源', {'notes': original.get('notes', ''),
            'tags': original.get('tags', []), 'documentation_url': original.get('documentation_url', ''),
            'sort_order': original.get('sort_order', 0)},
            [('notes','说明与备注','text'),('tags','标签（逗号分隔）','list'),
             ('documentation_url','文档链接','text'),('sort_order','排序数值（小值在前）','integer')],
            '备注用于展示和选型，不会自动改变接口行为或要求重新生成。')
        declared = Fields(book, '供应商声明', original.get('declared_capabilities', {}), DECLARED,
            '声明仅供选型参考。未知留空；填写声明不会让接口自动支持视频或音频参考。')
        cap_values = copy.deepcopy(original.get('capability_overrides', {}))
        media_values = cap_values.pop('media_reference_limits', {})
        caps = Fields(book, '执行参数', cap_values, CAPABILITIES,
            '仅填写已核实的接口约束。其他字段在高级页；最终仍由共用校验器和 adapter 预检。')
        media_caps = Fields(book, '多媒体限制', media_values, MEDIA_REFERENCE_LIMITS,
            '仅适用星光 v2。未知不是无限；高级页还需明确 allowed_combinations（类型组合数组）和 '
            'audio_reference_with_generated_audio（布尔值）。未使用的素材类型数量填 0。')
        options = self.json_tab(book, '协议选项', original.get('adapter_options', {}))
        prices = Fields(book, '价格', {k: original[k] for k in ('pricing', 'listed_pricing') if k in original}, PRICES,
            '展示价与预算价分开。未知币种不推算；每次与每秒价格同时填写会相加。')
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
        win, book, _ = self.dialog('当前列表型号比较')
        book.forget(0)
        columns = ['upstream_name', 'remote_model', 'setup_status', 'operations',
                   'declared_capabilities', 'capability_overrides', 'pricing', 'listed_pricing']
        data = [{k: row.get(k) for k in columns} for row in service.catalog(self.value, upstream=self.current_upstream)
                if self.models.exists(row['id'])]
        editor = self.json_tab(book, '比较详情', {'models': data})
        editor.configure(state='disabled')

    def discover(self):
        uid = self.current_upstream
        if not uid:
            self.error('先选择一个上游')
            return
        config = copy.deepcopy(self.value)
        token = service.fingerprint(config)
        win, book, basic = self.dialog('只读模型目录')
        ttk.Label(basic, text='只读取 /models；不会提交生成。导入条目保存为禁用草稿。', wraplength=650).pack(anchor='w')
        listing = tk.Listbox(basic, selectmode='extended', font=('Microsoft YaHei UI', 10))
        listing.pack(fill='both', expand=True, pady=12)
        note = tk.StringVar(value='正在读取…')
        ttk.Label(basic, textvariable=note, wraplength=650).pack(anchor='w')
        choices = ttk.Frame(win, padding=12)
        choices.pack(fill='x')
        kind = tk.StringVar(value='video')
        ttk.Combobox(choices, textvariable=kind, values=['video', 'image'], state='readonly', width=10).pack(side='left')
        family = tk.StringVar(value='custom')
        ttk.Label(choices, text='家族').pack(side='left', padx=8)
        ttk.Entry(choices, textvariable=family, width=18).pack(side='left')
        packets = queue.Queue()
        def work():
            try:
                from .catalog.discovery import models
                packets.put((True, models(config, uid, store_root=self.path.parent)))
            except (ConfigError, OSError, ValueError) as exc:
                packets.put((False, str(exc)))
        def receive():
            if not win.winfo_exists():
                return
            try:
                ok, result = packets.get_nowait()
            except queue.Empty:
                win.after(100, receive)
                return
            if not ok:
                note.set(result)
                return
            for remote in result['ids']:
                listing.insert('end', remote)
            known = {b['remote_model'] for b in config['bindings'].values() if b['upstream'] == uid}
            missing = known - set(result['ids'])
            note.set(f"读到 {len(result['ids'])} 个型号；{len(missing)} 个本地型号未出现在目录（保留）。选择型号后导入草稿。")
            apply_button.configure(state='normal')
        def apply():
            try:
                if token != service.fingerprint(self.value):
                    raise ConfigError('配置已变更，请关闭后重新检查目录')
                ids = [listing.get(i) for i in listing.curselection()]
                if not ids:
                    raise ConfigError('请选择需要导入的型号')
                from .catalog.discovery import import_models
                self.value, added = import_models(self.value, uid, ids, kind=kind.get(), family=family.get().strip() or 'custom')
                self.changed()
                note.set(f'已加入 {len(added)} 个草稿，请关闭窗口并保存配置。')
                apply_button.configure(state='disabled')
            except (ConfigError, OSError, ValueError) as exc:
                self.error(exc)
        apply_button = ttk.Button(choices, text='导入所选为草稿', command=apply, state='disabled')
        apply_button.pack(side='right')
        threading.Thread(target=work, daemon=True).start()
        win.after(100, receive)

    def project_panel(self):
        folder = filedialog.askdirectory(parent=self.window, title='选择包含 project.json 的 v3 项目')
        if not folder:
            return
        try:
            from .manager_projects import open_panel
            open_panel(self, Path(folder))
        except (ConfigError, OSError, ValueError) as exc:
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
        record = service.load(path)
        if not record['editable']:
            from .config.storage import redact_config
            root.title('VideoCreate · 配置只读检查')
            root.geometry('1000x720')
            ttk.Label(root, text='当前配置版本或字段无法编辑。原文件未改动。', padding=16).pack(anchor='w')
            ttk.Label(root, text=str(path), padding=8).pack(anchor='w')
            view = tk.Text(root, wrap='word', font=('Consolas', 10))
            view.pack(fill='both', expand=True, padx=12, pady=12)
            view.insert('1.0', '\n'.join(record['errors']) + '\n\n' + json.dumps(redact_config(record['config']),ensure_ascii=False,indent=2))
            view.configure(state='disabled')
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
            root.update_idletasks()
            atomic_json(args.smoke_report, {'ok': True, 'upstreams': len(manager.value['upstreams']),
                'bindings': len(manager.models.get_children()), 'config_version': manager.value['schema_version'],
                'network_requests': 0, 'saved': False, 'visual_review': 'not-performed'})
        finally:
            root.destroy()
        return 0
    return launch(args.config)


if __name__ == '__main__':
    raise SystemExit(main())
