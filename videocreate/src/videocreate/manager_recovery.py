"""Encrypted, opt-in-layout recovery of pending configuration and raw forms."""
import copy
import os
import tkinter as tk
from tkinter import ttk, messagebox

from . import manager_lifecycle as ui
from .config.drafts import DraftStore
from .config.management import fingerprint, migrate
from .config.schema import validate_config
from .config.storage import ConfigError


def controls(window):
    result = []
    def walk(parent, path=()):
        for index, child in enumerate(parent.winfo_children()):
            if isinstance(child, tk.Toplevel):continue
            key = (*path, index)
            if isinstance(child, (ttk.Entry, tk.Entry, ttk.Combobox, ttk.Spinbox, tk.Spinbox)):
                if not child.cget('show'):
                    result.append((list(key), child.winfo_class(), child.get()))
            elif isinstance(child, tk.Text) and str(child.cget('state')) != 'disabled':
                result.append((list(key), child.winfo_class(), child.get('1.0', 'end-1c')))
            elif isinstance(child, (ttk.Checkbutton, ttk.Radiobutton)):
                result.append((list(key), child.winfo_class(), str(child.getvar(child.cget('variable')))))
            walk(child, key)
    walk(window)
    return result


def apply_controls(window, saved):
    current = controls(window)
    if [(p, k) for p, k, v in current] != [(p, k) for p, k, v in saved]:
        raise ConfigError('Recovery form layout changed; encrypted snapshot retained')
    for (path, kind, value), (_, _, original) in zip(saved, current):
        if not isinstance(value, str):raise ConfigError('Invalid raw form value')
        widget = window
        for index in path:widget = widget.winfo_children()[index]
        if isinstance(widget, tk.Text):widget.delete('1.0', 'end');widget.insert('1.0', value)
        elif isinstance(widget, ttk.Combobox):widget.set(value)
        elif isinstance(widget, (ttk.Checkbutton, ttk.Radiobutton)):widget.setvar(widget.cget('variable'), value)
        elif str(widget.cget('state')) in {'readonly', 'disabled'}:
            if value != original:raise ConfigError('An immutable recovery field does not match the configuration')
        else:widget.delete(0, 'end');widget.insert(0, value)


def children(window):
    result = []
    for child in window.winfo_children():
        if isinstance(child, tk.Toplevel):
            if hasattr(child, 'recovery_descriptor'):result.append(child)
        else:result.extend(children(child))
    return result


def capture(window):
    nested = [item for child in children(window) if (item := capture(child)) is not None]
    if not window.draft_guard.dirty() and not nested:return None
    return {'descriptor':window.recovery_descriptor, 'controls':controls(window),
        'extra':window.recovery_get() if hasattr(window, 'recovery_get') else None,
        'children':nested}


class Recovery:
    def __init__(self, manager, *, interval=1500):
        self.manager = manager;self.store = DraftStore(manager.path);self.interval = interval
        self.timer = None;self.last = None;self.error = None;self.closed = False
        self.note = ui.StringVar(manager.window, value='配置草稿每 1.5 秒加密暂存；密钥输入不暂存。' if os.name == 'nt'
            else '当前系统不支持 Windows 加密草稿；配置仍须手动保存。')
        if any(self.store.directory.glob('*.dpapi')):
            self.note.set('发现加密草稿；点击“恢复配置草稿”查看。恢复不会自动保存或生成。')
        manager.window.bind('<Destroy>', self.destroyed, add='+')
        self.schedule()

    def schedule(self):
        if not self.closed:self.timer = self.manager.window.after(self.interval, self.tick)

    def tick(self):
        self.timer = None
        try:self.checkpoint()
        except (OSError, ValueError, tk.TclError):
            self.error = True;self.note.set('加密草稿暂存失败；当前输入仍在窗口中，请保存配置。')
        self.schedule()

    def checkpoint(self):
        if os.name != 'nt':return False
        manager = self.manager
        forms = [item for window in children(manager.window) if (item := capture(window)) is not None]
        if manager.value == manager.record['config'] and not forms:
            self.store.discard();self.last = None;self.error = None
            old = any(path != self.store.target for path in self.store.directory.glob('*.dpapi'))
            self.note.set('发现其他会话的加密草稿；点击“恢复配置草稿”查看。' if old
                else '配置草稿每 1.5 秒加密暂存；密钥输入不暂存。');return True
        payload = {'base':manager.record['token'], 'value':manager.value, 'forms':forms}
        token = fingerprint(payload)
        if token != self.last:
            self.store.save(manager.record['token'], manager.value, forms);self.last = token
        self.error = None;self.note.set('未保存配置与配置表单已加密暂存；未提交密钥仅在内存中。')
        return True

    def destroyed(self, event):
        if event.widget is not self.manager.window:return
        self.closed = True
        if self.timer is not None:self.manager.window.after_cancel(self.timer);self.timer = None

    def restore_window(self, packet, parent=None):
        descriptor = packet['descriptor'];manager = self.manager
        if parent is None:
            if descriptor['kind'] == 'upstream':
                window = manager.edit_upstream(descriptor['uid'], copy_from=descriptor['copy_from'], recovery_original=descriptor['original'])
            elif descriptor['kind'] == 'binding':window = manager.edit_binding(descriptor['bid'], recovery_original=descriptor['original'])
            elif descriptor['kind'] == 'media':window = manager.media_panel()
            else:raise ConfigError('Unsupported recovery form')
        elif descriptor['kind'] == 'price':window = parent.recovery_price(descriptor['index'])
        else:raise ConfigError('Unsupported nested recovery form')
        if packet['extra'] is not None:window.recovery_put(packet['extra'])
        apply_controls(window, packet['controls'])
        for child in packet['children']:self.restore_window(child, window)
        return window

    def restore(self, session):
        manager = self.manager
        from .manager_drafts import guards
        if manager.value != migrate(manager.record['config']) or any(g.dirty() for g in guards(manager.window)):
            raise ConfigError('Save or discard current edits before recovering another session')
        packet = self.store.recover(session)
        if packet['base_token'] != manager.record['token']:raise ConfigError('Reload the current configuration before recovery')
        if validate_config(packet['value']):raise ConfigError('Recovery configuration is invalid; snapshot retained')
        before = copy.deepcopy(manager.value);dirty = manager.dirty
        existing = set(guards(manager.window))
        try:
            manager.value = copy.deepcopy(packet['value']);manager.dirty = manager.value != manager.record['config']
            manager.refresh()
            for form in packet['forms']:self.restore_window(form)
            if not self.checkpoint():raise ConfigError('Could not preserve recovered edits in this session')
        except Exception:
            for guard in guards(manager.window):
                if guard not in existing:guard.window.destroy()
            manager.value = before;manager.dirty = dirty;manager.refresh()
            raise ConfigError('Recovery did not complete; original encrypted snapshot retained') from None
        for guard in existing:
            if guard.scope == 'configuration':guard.window.destroy()
        self.note.set('已恢复到待保存配置/表单；请核对后应用并保存。原草稿保留，可在列表中丢弃。')

    def panel(self):
        win = tk.Toplevel(self.manager.window);win.title('恢复加密配置草稿');win.geometry('820x400')
        ttk.Label(win,text='恢复只放回待保存配置和表单，不写配置、不执行生成。活动编辑器、配置冲突或版本不符时禁止恢复。',
            wraplength=770,padding=12).pack(fill='x')
        table = ttk.Treeview(win,columns=('time','status','forms'),show='headings')
        for key,title in [('time','保存时间'),('status','状态'),('forms','表单数')]:table.heading(key,text=title)
        table.pack(fill='both',expand=True,padx=12)
        labels = {'stopped':'可恢复','active':'原编辑器仍运行','unknown':'未能确认已退出','conflict':'配置已改变',
            'other-version':'需要原管理器版本','unreadable':'无法解密或文件损坏'}
        def refresh():
            table.delete(*table.get_children())
            for row in self.store.inventory():table.insert('','end',iid=row['session'],values=(row['saved_at'],labels[row['status']],row['forms']))
        def action(discard=False):
            selected = table.selection()
            if not selected:return
            try:
                if discard:
                    if messagebox.askyesno('丢弃加密草稿','永久丢弃所选草稿？现有配置和任务保持。',parent=win):self.store.discard(selected[0])
                else:self.restore(selected[0])
                refresh()
            except (OSError, ValueError) as exc:self.manager.error(exc)
        bar = ttk.Frame(win,padding=12);bar.pack(fill='x')
        for title,command in [('恢复所选',action),('丢弃所选',lambda:action(True)),('刷新',refresh)]:
            ttk.Button(bar,text=title,command=command).pack(side='left',padx=6)
        refresh();return win
