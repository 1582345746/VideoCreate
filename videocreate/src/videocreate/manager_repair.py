"""Local JSON editor and preview for configurations that cannot open normally."""
import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk,filedialog,messagebox

from . import manager_lifecycle as ui
from .config import repair
from .manager_drafts import DraftGuard


class RepairPanel:
    def __init__(self,window,path,*,completed=lambda result:None):
        self.window,self.path,self.completed=window,Path(path).resolve(),completed
        self.snapshot=repair.inspect(self.path);self.pending=None
        window.title('VideoCreate · 配置检查与修复');window.geometry('1040x780')
        self.body=ttk.Frame(window,padding=16);self.body.pack(fill='both',expand=True)
        ttk.Label(self.body,text=str(self.path),wraplength=970).pack(anchor='w')
        self.note=ui.StringVar(self.body,value='当前状态：'+self.snapshot['status']+'。原文件未修改。')
        ttk.Label(self.body,textvariable=self.note,wraplength=970).pack(anchor='w',pady=8)
        ttk.Label(self.body,text='在本机编辑原文，或从有效备份载入草稿。先预览并核对，再保存；损坏原文将逐字节备份。'
            '凭据文件、项目和任务不会被修改。无法解析的原文不能证明全部历史身份，请对照已有备份。',wraplength=970).pack(anchor='w',pady=8)
        book=ttk.Notebook(self.body);book.pack(fill='both',expand=True)
        edit=ttk.Frame(book);book.add(edit,text='本机 JSON 草稿')
        self.editor=tk.Text(edit,wrap='none',undo=True,font=('Consolas',10));self.editor.pack(fill='both',expand=True)
        self.editor.bind('<<Modified>>',self.changed)
        info=ttk.Frame(book);book.add(info,text='检查与预览')
        self.report=tk.Text(info,wrap='word',font=('Consolas',10));self.report.pack(fill='both',expand=True)
        self.show(self.snapshot)
        self.baseline=ui.StringVar(self.body);self.baseline.trace_add('write',lambda *_:self.invalidate())
        row=ttk.Frame(self.body);row.pack(fill='x',pady=8)
        ttk.Label(row,text='基准备份（可选）').pack(side='left')
        ttk.Entry(row,textvariable=self.baseline,state='readonly').pack(side='left',fill='x',expand=True,padx=8)
        actions=ttk.Frame(self.body);actions.pack(fill='x')
        self.buttons={}
        for label,fn in [('读取原文到编辑器',self.original),('载入有效备份为草稿',self.backup),('清除基准',lambda:self.baseline.set('')),
                         ('预览修复',self.preview),('按此预览保存修复',self.apply)]:
            button=ttk.Button(actions,text=label,command=fn);button.pack(side='left',padx=4);self.buttons[label]=button
        self.call=ui.BackgroundCall(self.body)
        self.guard=DraftGuard(window,read=lambda:repair.sha(json.dumps(
            (self.editor.get('1.0','end-1c'),self.baseline.get()),ensure_ascii=False).encode('utf-8')),
            label='本机配置修复草稿',busy=lambda:self.call.busy)
        self.enabled()

    def show(self,value):
        self.report.configure(state='normal');self.report.delete('1.0','end')
        self.report.insert('1.0',json.dumps(value,ensure_ascii=False,indent=2));self.report.configure(state='disabled')

    def enabled(self):
        ready=self.snapshot['can_repair'] and not self.call.busy
        for name,button in self.buttons.items():
            button.configure(state='normal' if ready and (name!='按此预览保存修复' or self.pending) else 'disabled')
        self.editor.configure(state='normal' if ready else 'disabled')

    def invalidate(self):
        self.pending=None
        if hasattr(self,'call'):self.enabled()

    def changed(self,_=None):
        if self.editor.edit_modified():self.editor.edit_modified(False);self.invalidate()

    def original(self):
        if self.call.busy or not self.replace_draft():return
        try:
            raw=self.path.read_bytes()
            if repair.sha(raw)!=self.snapshot['source_token']:raise ValueError('配置已变化，请关闭后重新打开检查')
            self.editor.delete('1.0','end');self.editor.insert('1.0',raw.decode('utf-8-sig'))
            self.baseline.set('');self.editor.edit_modified(False);self.invalidate();self.guard.reset()
            self.note.set('已在本机载入原文；修改后先预览。原文可能含旧式明文凭据，请仅在本机编辑。')
        except (OSError,ValueError) as exc:self.failed(exc)

    def backup(self,path=None):
        if self.call.busy:return
        if path is None:path=filedialog.askopenfilename(parent=self.window,title='选择有效配置备份',
            initialdir=self.path.parent/'backups',filetypes=[('JSON','*.json')])
        if not path:return
        if not self.replace_draft():return
        try:
            state=repair.inspect(path)
            if state['status']!='valid':raise ValueError('请选择有效的受支持版本配置备份')
            text=Path(path).read_text(encoding='utf-8-sig')
            self.editor.delete('1.0','end');self.editor.insert('1.0',text);self.editor.edit_modified(False)
            self.baseline.set(str(Path(path).resolve()));self.note.set('已载入备份草稿；尚未替换当前配置。')
        except (OSError,ValueError) as exc:self.failed(exc)

    def replace_draft(self):
        return not self.guard.dirty() or messagebox.askyesno('替换当前修复草稿',
            '载入文件将替换尚未保存的本机修复草稿。是否继续？',parent=self.window)

    def failed(self,error):
        self.pending=None;self.note.set('修复未完成：'+str(error));self.enabled()

    def start(self,function,done,**options):
        if self.call.busy:return
        text=self.editor.get('1.0','end-1c')
        self.call.start(function,self.path,text,source_token=self.snapshot['source_token'],
            baseline=self.baseline.get() or None,completed=lambda value:self.finish(done,value),failed=self.failed,**options)
        self.enabled()

    def finish(self,done,value):
        done(value)
        # Successful startup recovery replaces this panel with the manager.
        if not self.call.closed:self.enabled()

    def preview(self):
        def shown(value):self.pending=value;self.show(value);self.note.set('预览完成；核对保留条目、已知身份及未核实范围后保存。')
        self.start(repair.preview,shown)

    def apply(self):
        if not self.pending:return
        def saved(value):
            self.pending=None;self.snapshot=repair.inspect(self.path);self.show(value)
            self.note.set('修复已保存，原始字节已备份。');self.guard.reset();self.completed(value)
        self.start(repair.apply,saved,preview_token=self.pending['preview_token'])

    def dispose(self):
        if getattr(self.window,'draft_guard',None) is self.guard:del self.window.draft_guard
        self.body.destroy()
