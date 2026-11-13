"""Production policy and plan checkpoints through the shared offline service."""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import production, production_policy
from .config.storage import safe_error

MODES = {'逐步核对策划阶段': 'assisted', '按现有授权推进，保留所选检查点': 'auto-within-authorization'}
PROGRESSION = {'not-applicable': '本项目不适用', 'checked-current-version': '当前版本已核对',
    'review-required': '需核对计划', 'automatic-without-approval': '可继续，计划未核对',
    'existing-runtime-and-review': '沿用执行与实际审核'}


def _work(channel, operation, root, options):
    try:
        function = {'load': production_policy.describe, 'preview': production_policy.preview,
            'save': production_policy.save, 'inspect': production_policy.inspect_stage}[operation]
        channel.put((True, function(root, **options)))
    except Exception as exc:
        channel.put((False, safe_error(exc)))


class PolicyPanel:
    def __init__(self, manager, root, completed):
        self.manager, self.root, self.completed = manager, Path(root), completed
        self.snapshot = self.preview_result = None
        self.busy, self.scheduled = False, None
        win, book, basic = manager.dialog('制作流程与检查点')
        self.win = win
        win.geometry('900x760')
        book.pack_forget()
        footer = ttk.Frame(win, padding=12);footer.pack(side='bottom', fill='x')
        book.pack(fill='both', expand=True, padx=18, pady=14)
        ttk.Label(basic, text=str(root), wraplength=800).pack(anchor='w', pady=6)
        ttk.Label(basic, text='逐步核对会停在尚未核对的策划阶段。自动推进只保留勾选的策划检查点；'
            '略过的计划仍是未核对状态。生成预算、原任务恢复和实际审片继续使用原有规则。',
            wraplength=800).pack(anchor='w', pady=6)
        self.mode = tk.StringVar(win)
        self.selector = ttk.Combobox(basic, textvariable=self.mode, values=list(MODES), state='readonly', width=48)
        self.selector.pack(anchor='w', pady=6)
        self.selector.bind('<<ComboboxSelected>>', self.changed)
        gatebox = ttk.LabelFrame(basic, text='自动推进时仍需核对的策划阶段', padding=8);gatebox.pack(fill='x', pady=5)
        self.gates, self.checks = {}, []
        for index, stage in enumerate(production.AUTHORING):
            value = tk.BooleanVar(win)
            button = ttk.Checkbutton(gatebox, text=production.NAMES[stage], variable=value, command=self.changed)
            button.grid(row=index // 3, column=index % 3, sticky='w', padx=14, pady=3)
            self.gates[stage] = value;self.checks.append(button)
        ttk.Label(basic, text='本次设置依据').pack(anchor='w')
        self.reason = tk.StringVar(win)
        self.reason_entry = ttk.Entry(basic, textvariable=self.reason);self.reason_entry.pack(fill='x', pady=5)
        self.reason.trace_add('write', self.changed)
        stageframe = ttk.Frame(book, padding=8);book.add(stageframe, text='阶段与下一步')
        self.tree = ttk.Treeview(stageframe, columns=('name', 'status', 'progression'), show='headings', height=11)
        for column, title, width in [('name', '阶段', 140), ('status', '实际状态', 130), ('progression', '推进方式', 330)]:
            self.tree.heading(column, text=title);self.tree.column(column, width=width)
        self.tree.pack(fill='both', expand=True)
        self.summary = tk.StringVar(win)
        ttk.Label(stageframe, textvariable=self.summary, wraplength=790).pack(anchor='w', pady=8)
        self.details = manager.json_tab(book, '预览与任务详情', {})
        self.details.configure(state='disabled')
        self.message = tk.StringVar(win, value='正在读取当前流程、计划与任务。')
        ttk.Label(footer, textvariable=self.message, wraplength=850).pack(anchor='w', pady=4)
        controls = ttk.Frame(footer);controls.pack(fill='x')
        self.buttons = {}
        for text, action in [('重新载入', self.reload), ('预览策略变化', self.preview),
                ('保存已预览策略', self.save), ('核对选中策划阶段', self.inspect)]:
            button = ttk.Button(controls, text=text, command=action);button.pack(side='left', padx=4)
            self.buttons[text] = button
        ttk.Button(controls, text='关闭', command=win.destroy).pack(side='right', padx=4)
        win.bind('<Destroy>', self.destroyed, add='+')
        self.reload()

    def destroyed(self, event):
        if event.widget == self.win and self.scheduled is not None:
            self.win.after_cancel(self.scheduled);self.scheduled = None

    def enabled(self):
        loaded = self.snapshot is not None and not self.busy
        for key, button in self.buttons.items():
            available = not self.busy if key == '重新载入' else loaded
            if key == '保存已预览策略':available = loaded and self.preview_result is not None
            button.configure(state='normal' if available else 'disabled')
        self.selector.configure(state='readonly' if loaded else 'disabled')
        self.reason_entry.configure(state='normal' if loaded else 'disabled')
        automatic = MODES.get(self.mode.get()) == 'auto-within-authorization'
        for button in self.checks:button.configure(state='normal' if loaded and automatic else 'disabled')

    def changed(self, *_):
        self.preview_result = None
        self.enabled()

    def display(self, value):
        from .manager_projects import STATUS
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in value['stages']:
            self.tree.insert('', 'end', iid=row['id'], values=(row['name'], STATUS.get(row['status'], row['status']),
                PROGRESSION[row['progression']]))
        if selected and self.tree.exists(selected[0]):self.tree.selection_set(selected[0])
        else:self.tree.selection_set(value['stages'][0]['id'])
        next_step = value['next'] or {'name': '查看交付清单'}
        self.summary.set('按此策略的下一步：' + next_step['name'] + '。实际审片状态：' + value['review']['status'])
        self.details.configure(state='normal');self.details.delete('1.0', 'end')
        import json
        self.details.insert('1.0', json.dumps(value, ensure_ascii=False, indent=2));self.details.configure(state='disabled')

    def start(self, operation, options):
        if self.busy:return
        self.busy = True;self.enabled()
        self.message.set({'load': '正在读取流程。', 'preview': '正在预览阶段与下一步变化。',
            'save': '正在重新核对版本并保存流程设置。', 'inspect': '正在读取选中阶段的实际计划内容。'}[operation])
        channel = queue.Queue()
        threading.Thread(target=_work, args=(channel, operation, self.root, options), daemon=False).start()

        def finish():
            self.scheduled = None
            if not self.win.winfo_exists():return
            try:ok, result = channel.get_nowait()
            except queue.Empty:
                self.scheduled = self.win.after(80, finish);return
            self.busy = False
            if not ok:
                self.preview_result = None;self.message.set('操作未完成：' + str(result));self.manager.error(result)
            elif operation == 'load':
                self.snapshot = result;self.preview_result = None
                self.mode.set(next(label for label, mode in MODES.items() if mode == result['policy']))
                for stage, value in self.gates.items():value.set(stage in result['required_authoring_stages'])
                self.reason.set('');self.display(result);self.message.set('已载入当前流程。修改后先预览，再保存。')
            elif operation == 'preview':
                self.preview_result = result;self.display(result['after'])
                before = (result['before']['next'] or {}).get('name', '查看交付清单')
                after = (result['after']['next'] or {}).get('name', '查看交付清单')
                self.message.set('预览：' + before + ' → ' + after + '；保存只更新流程设置。')
            elif operation == 'save':
                self.preview_result = None;self.message.set('流程设置已保存；尚未执行生成或批准媒体。')
                self.completed(result)
                self.reload();return
            else:
                from .manager_continuation import open_inspection
                def edit_layer(layer, **kwargs):
                    from .manager_authoring import open_editor
                    open_editor(self.manager, self.root, layer, completed=lambda _: self.reload() if self.win.winfo_exists() else None, **kwargs)
                open_inspection(self.manager, self.root, result, edit_layer=edit_layer,
                    completed=lambda _: self.reload() if self.win.winfo_exists() else None)
                self.message.set('已打开当前版本的阶段内容；登记结论只核对计划。')
            self.enabled()
        self.scheduled = self.win.after(80, finish)

    def reload(self):
        self.start('load', {})

    def options(self):
        return {'mode': MODES.get(self.mode.get()), 'required_stages': [s for s, value in self.gates.items() if value.get()],
            'reason': self.reason.get(), 'source_token': self.snapshot['source_token']}

    def preview(self):
        if self.snapshot and not self.busy:self.start('preview', self.options())

    def save(self):
        if self.snapshot and self.preview_result and not self.busy:
            self.start('save', {**self.options(), 'preview_token': self.preview_result['preview_token']})

    def inspect(self):
        if self.snapshot and not self.busy and self.tree.selection():
            self.start('inspect', {'stage': self.tree.selection()[0], 'source_token': self.snapshot['source_token']})


def open_panel(manager, root, *, completed=lambda result: None):
    panel = PolicyPanel(manager, root, completed)
    panel.win.policy_panel = panel
    return panel.win
