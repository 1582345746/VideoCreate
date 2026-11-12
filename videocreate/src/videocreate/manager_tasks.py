"""Explicit generation, recovery and numbered route choices in the desktop UI."""
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from . import generation_actions, production, selection
from .config.storage import ConfigError, load_json, safe_error

MODES = {'生成或继续': 'run', '仅恢复原任务': 'resume', '重做内容': 'content', '按新计划重做': 'replan'}


def _worker(channel, operation, root, config_path, arguments):
    """A worker retains plain values and a queue, never Tk widgets."""
    try:
        if operation == 'preview':
            value = generation_actions.preview(root, config_path, **arguments)
        elif operation == 'execute':
            value = generation_actions.execute(root, config_path,
                progress=lambda event: channel.put(('progress', event)), **arguments)
        elif operation == 'choose':
            from .cli import read_config
            value = selection.choose(root, read_config(config_path), store_root=config_path.parent,
                **{k:v for k,v in arguments.items() if k != 'job_id'})
        else:
            from .cli import read_config
            from .runtime.reconcile import reconcile
            from .runtime.settlement import settle
            receipt = load_json(arguments['file'])
            value = reconcile(root, read_config(config_path), receipt, store_root=config_path.parent) if operation == 'reconcile' else settle(root, receipt)
        channel.put(('done', value))
    except selection.SelectionRequired as exc:
        channel.put(('selection', exc.payload))
    except Exception as exc:
        channel.put(('error', safe_error(exc)))


class TaskPanel:
    def __init__(self, manager, root, *, completed=None):
        self.manager, self.root = manager, Path(root).resolve()
        self.config_path = Path(manager.path).resolve()
        self.completed = completed
        self.win, book, page = manager.dialog('生成任务执行与恢复')
        self.win.geometry('1040x760')
        book.pack_forget()
        footer = ttk.Frame(self.win, padding=12);footer.pack(side='bottom', fill='x')
        book.pack(fill='both', expand=True, padx=18, pady=14)
        ttk.Label(page, text='使用磁盘上已保存的配置和计划。选中任务后预检；依赖也会列出。实际生成可能收费，恢复模式禁止新建。', wraplength=940).pack(anchor='w', pady=6)
        self.tree = ttk.Treeview(page, columns=('job', 'status', 'route', 'action', 'price', 'content'), show='headings', height=8, selectmode='extended')
        for key, label, width in [('job','任务',140),('status','状态',120),('route','原接入 / 计划接入',300),
                ('action','本次操作',90),('price','本次创建报价',150),('content','内容审核',120)]:
            self.tree.heading(key, text=label);self.tree.column(key, width=width)
        self.tree.pack(fill='both', expand=True)
        form = ttk.Frame(page);form.pack(fill='x', pady=12)
        self.mode = tk.StringVar(self.win, value='生成或继续')
        self.new_requests = tk.StringVar(self.win, value='1')
        self.timeout = tk.StringVar(self.win, value='900')
        self.reason = tk.StringVar(self.win)
        self.binding = tk.StringVar(self.win)
        fields = [('操作', self.mode, tuple(MODES)), ('本次最多新增请求', self.new_requests, None),
            ('本次等待上限（秒）', self.timeout, None), ('重做原因', self.reason, None)]
        for index, (label, variable, values) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=index, column=0, sticky='w', pady=4)
            widget = ttk.Combobox(form, textvariable=variable, values=values, state='readonly') if values else ttk.Entry(form, textvariable=variable)
            widget.grid(row=index, column=1, sticky='ew', padx=12, pady=4)
        ttk.Label(form, text='本次接入（留空按任务/项目选择）').grid(row=4, column=0, sticky='w')
        values = ('', *load_json(self.config_path).get('bindings', {}))
        ttk.Combobox(form, textvariable=self.binding, values=values, state='readonly').grid(row=4,column=1,sticky='ew',padx=12)
        form.columnconfigure(1, weight=1)
        self.details = manager.json_tab(book, '预检与执行记录', {})
        self.note = tk.StringVar(self.win)
        ttk.Label(footer, textvariable=self.note, wraplength=980).pack(anchor='w', pady=5)
        row = ttk.Frame(footer);row.pack(fill='x')
        self.buttons = []
        for label, command in [('刷新任务', self.refresh), ('预检所选任务', self.preview), ('执行预检方案', self.execute), ('清除本次接入', self.clear_bindings)]:
            button = ttk.Button(row, text=label, command=command);button.pack(side='left',padx=5);self.buttons.append(button)
        self.execute_button = self.buttons[2]
        receipts = ttk.Frame(footer);receipts.pack(fill='x', pady=8)
        for label, operation in [('导入未知提交对账回执','reconcile'), ('导入实际账单回执','settle')]:
            button = ttk.Button(receipts, text=label, command=lambda op=operation:self.receipt(op))
            button.pack(side='left', padx=5);self.buttons.append(button)
        self.busy, self.token, self.overrides, self.scheduled = False, None, {}, None
        self.win.bind('<Destroy>', self.destroyed, add='+')
        self.refresh()

    def destroyed(self, event):
        if event.widget == self.win and self.scheduled is not None:
            self.win.after_cancel(self.scheduled);self.scheduled = None

    def display(self, value):
        self.details.configure(state='normal');self.details.delete('1.0','end')
        self.details.insert('1.0', json.dumps(value, ensure_ascii=False, indent=2));self.details.configure(state='disabled')

    def refresh(self):
        if self.busy:
            return
        try:
            self.token = None;self.execute_button.configure(state='disabled')
            current = production.status(self.root)
            bundle = production.load_project(self.root)
            planned = {j['id']:j for j in [*bundle['generation-plan']['jobs'], *bundle['generation-plan'].get('image_jobs', [])]}
            selected = set(self.tree.selection());self.tree.delete(*self.tree.get_children())
            for row in current['jobs']:
                jid = row['job_id']
                self.tree.insert('', 'end', iid=jid, values=(jid, row['status'], row.get('binding') or planned.get(jid, {}).get('binding_id', '未选定'), '', '预检后显示', row['content_status']))
            self.tree.selection_set(*(jid for jid in selected if self.tree.exists(jid)))
            self.note.set('预检不创建媒体；参考素材可能需要 HTTPS 校验。停止等待或关闭窗口不取消远端任务，可稍后恢复原任务。')
        except (ConfigError, OSError, ValueError) as exc:
            self.manager.error(exc)

    def clear_bindings(self):
        self.overrides = {};self.binding.set('');self.token = None;self.execute_button.configure(state='disabled')
        self.note.set('已清除本窗口的临时接入；已保存项目选择仍有效。')

    def arguments(self):
        ids = list(self.tree.selection())
        bundle = production.load_project(self.root)
        planned = {j['id']:j for j in [*bundle['generation-plan']['jobs'], *bundle['generation-plan'].get('image_jobs', [])]}
        ordered = generation_actions._ordered(planned, ids) if all(j in planned for j in ids) else ids
        overrides = {k:v for k,v in self.overrides.items() if k in ordered}
        if self.binding.get():
            overrides.update({jid:self.binding.get() for jid in ids})
        return {'job_ids': ids, 'mode': MODES[self.mode.get()], 'reason': self.reason.get().strip(),
            'bindings': overrides, 'max_new_requests': int(self.new_requests.get()), 'poll_timeout': int(self.timeout.get())}

    def preview(self):
        try:
            self.start('preview', self.arguments())
        except (ConfigError, ValueError) as exc:
            self.manager.error(exc)

    def execute(self):
        try:
            if not self.token:
                raise ConfigError('请先预检当前所选任务。')
            self.start('execute', {**self.arguments(), 'expected_token':self.token})
        except (ConfigError, ValueError) as exc:
            self.manager.error(exc)

    def receipt(self, operation):
        path = filedialog.askopenfilename(parent=self.win, title='选择实际证据回执', filetypes=[('JSON','*.json')])
        if path:
            self.start(operation, {'file':Path(path)})

    def start(self, operation, arguments):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:button.configure(state='disabled')
        self.note.set('正在'+('预检所选任务和依赖；不创建媒体。' if operation=='preview' else '执行明确操作；原任务与账本将持续保存。'))
        channel = queue.Queue()
        threading.Thread(target=_worker, args=(channel, operation, self.root, self.config_path, arguments), daemon=False).start()
        def receive():
            self.scheduled = None
            if not self.win.winfo_exists():return
            while True:
                try:kind, value = channel.get_nowait()
                except queue.Empty:
                    self.scheduled = self.win.after(100, receive);return
                if kind == 'progress':
                    if value.get('job_id') and self.tree.exists(value['job_id']):
                        self.tree.set(value['job_id'], 'status', value.get('status') or value.get('phase', ''))
                    self.note.set('当前进度：'+json.dumps(value, ensure_ascii=False));continue
                self.busy = False
                for button in self.buttons:button.configure(state='normal')
                self.execute_button.configure(state='disabled')
                if kind == 'error':
                    self.refresh();self.note.set('操作未完成：'+str(value));self.manager.error(value);return
                if kind == 'selection':
                    self.token = None;self.display(value);self.select_route(value);return
                if operation == 'preview':
                    for job in value['jobs']:
                        price = job['price']
                        quote = '未知' if price['estimate'] is None else str(price['estimate'])+' '+str(price['currency'])
                        if job['action'] != 'create':quote = '本次不创建'
                        self.tree.set(job['job_id'], 'route', job['binding'])
                        self.tree.set(job['job_id'], 'action', {'create':'新建','resume':'恢复原任务','skip':'复用完成项','reprocess':'重取原结果'}[job['action']])
                        self.tree.set(job['job_id'], 'price', quote)
                    self.token = value['token'];self.execute_button.configure(state='normal')
                    self.note.set(f"预检完成：所选及依赖共 {len(value['jobs'])} 项，预计新增 {value['new_requests']} 次请求；请查看路线、费用和原任务号后执行。")
                elif operation == 'choose':
                    if value['scope'] == 'once':self.overrides[arguments['job_id']] = value['binding_id']
                    self.token = None;self.note.set('接入已选定，请重新预检当前任务。')
                else:
                    self.refresh();self.note.set('操作已结束；实际完成或失败见记录，生成内容仍需审片。')
                    if self.completed:self.completed(value)
                self.display(value);return
        self.scheduled = self.win.after(100, receive)

    def select_route(self, packet):
        win, book, page = self.manager.dialog('选择缺失的上游与型号')
        ttk.Label(page, text='当前任务：'+packet['job_id']+'；编号绑定本次候选列表。', wraplength=680).pack(anchor='w',pady=8)
        self.manager.json_tab(book, '候选与排除原因', packet)
        tree = ttk.Treeview(page, columns=('number','upstream','model','notes'), show='headings', height=10)
        for key, label, width in [('number','序号',50),('upstream','上游',150),('model','型号',200),('notes','备注',280)]:
            tree.heading(key,text=label);tree.column(key,width=width)
        for row in packet['choices']:
            tree.insert('', 'end', iid=str(row['number']), values=(row['number'],row['upstream_id'],row['remote_model'],row.get('notes','')))
        tree.pack(fill='both',expand=True)
        scope = tk.StringVar(win, value='仅本次')
        ttk.Combobox(page, textvariable=scope, values=('仅本次','当前项目'), state='readonly').pack(anchor='w',pady=8)
        def choose():
            ids = tree.selection()
            if len(ids) != 1:
                self.manager.error('请选择一个有效序号。');return
            args = {'selection_id':packet['selection_id'], 'number':int(ids[0]),
                'scope':'once' if scope.get()=='仅本次' else 'project', 'job_id':packet['job_id']}
            win.destroy();self.win.grab_set();self.start('choose', args)
        ttk.Button(page, text='使用所选序号', command=choose).pack(anchor='w',pady=8)


def open_panel(manager, root, *, completed=None):
    panel = TaskPanel(manager, root, completed=completed)
    panel.win.task_panel = panel
    return panel.win
