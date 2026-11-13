"""Preview and export offline, allowlisted diagnostics from saved configuration."""
import json
from tkinter import ttk,filedialog

from . import diagnostics,manager_lifecycle as ui
from .manager_drafts import DraftGuard


class DiagnosticsPanel:
    def __init__(self,manager):
        self.manager=manager;self.selected_upstream=manager.current_upstream
        self.win,book,page=manager.dialog('脱敏诊断预览与导出');self.win.geometry('1020x780')
        self.win.diagnostics_panel=self;self.pending=None;self.phase=None
        ttk.Label(page,text='读取磁盘上已保存的配置和本地证据；未保存的编辑不包含。不查询环境密钥、不解密 DPAPI、不联网、不生成媒体。',wraplength=930).pack(anchor='w',pady=8)
        ttk.Label(page,text='默认隐藏接入标识；可选择加入型号 ID 和 API 主机。密钥、账户标识、备注、素材链接、任务号、本机路径和原始日志始终省略。',wraplength=930).pack(anchor='w',pady=8)
        ttk.Label(page,text='旧配置中的明文密钥仅在本机用于清理标识中的误填内容；勾选标识后请核对实际导出内容。',wraplength=930).pack(anchor='w',pady=4)
        controls=ttk.Frame(page);controls.pack(fill='x',pady=8)
        self.one=ui.BooleanVar(self.win,value=bool(self.selected_upstream))
        self.names=ui.BooleanVar(self.win,value=False)
        self.scope_button=ttk.Checkbutton(controls,text='仅当前选中上游',variable=self.one)
        self.scope_button.pack(side='left')
        if not self.selected_upstream:self.scope_button.configure(state='disabled')
        self.names_button=ttk.Checkbutton(controls,text='加入型号 ID 与 API 主机',variable=self.names);self.names_button.pack(side='left',padx=12)
        self.summary=ui.StringVar(self.win,value='先生成本机预览，核对报告内容后导出新的 JSON 文件。')
        ttk.Label(page,textvariable=self.summary,wraplength=930).pack(anchor='w',pady=10)
        self.tree=ttk.Treeview(page,columns=('ref','adapter','state','issues'),show='headings',height=12)
        for key,title,width in [('ref','报告接入代号',160),('adapter','协议',180),('state','本地状态',140),('issues','诊断项',450)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width)
        scroll=ttk.Scrollbar(page,orient='vertical',command=self.tree.yview);self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True,pady=8)
        self.editor=manager.json_tab(book,'实际导出内容',{});self.editor.configure(state='disabled')
        actions=ttk.Frame(page);actions.pack(fill='x',pady=10)
        self.preview_button=ttk.Button(actions,text='生成 / 更新预览',command=self.preview);self.preview_button.pack(side='left')
        self.export_button=ttk.Button(actions,text='导出当前预览为 JSON',command=self.export,state='disabled');self.export_button.pack(side='right')
        self.call=ui.BackgroundCall(self.win)
        self.guard=DraftGuard(self.win,read=self.options,label='诊断范围与标识设置',busy=lambda:self.call.busy and self.phase=='export')
        self.one.trace_add('write',self.changed);self.names.trace_add('write',self.changed)

    def options(self):return {'upstream':self.selected_upstream if self.one.get() else None,'include_identifiers':self.names.get()}

    def changed(self,*_):
        self.pending=None;self.tree.delete(*self.tree.get_children())
        self.editor.configure(state='normal');self.editor.delete('1.0','end');self.editor.configure(state='disabled')
        self.summary.set('设置已变化，请重新预览后导出。');self.enabled()

    def enabled(self):
        self.preview_button.configure(state='disabled' if self.call.busy else 'normal')
        self.export_button.configure(state='normal' if self.pending and not self.call.busy else 'disabled')
        self.names_button.configure(state='disabled' if self.call.busy else 'normal')
        self.scope_button.configure(state='normal' if self.selected_upstream and not self.call.busy else 'disabled')

    def preview(self):
        if self.call.busy:return
        self.pending=None;self.phase='preview';self.summary.set('正在读取已保存配置与本地证据摘要。')
        self.call.start(diagnostics.preview,self.manager.path,**self.options(),completed=self.show,failed=self.failed)
        self.enabled()

    def show(self,value):
        if value['options']!=self.options():self.changed();return
        self.pending=value;report=value['report'];config=report['configuration'];count=report.get('counts',{})
        self.tree.delete(*self.tree.get_children())
        for row in report['bindings']:
            self.tree.insert('','end',values=(row['ref'],row['adapter'],row['local_contract_status'],', '.join(row['issues'])))
        self.editor.configure(state='normal');self.editor.delete('1.0','end')
        self.editor.insert('1.0',json.dumps(report,ensure_ascii=False,indent=2));self.editor.configure(state='disabled')
        self.summary.set(f"配置：{config['status']}；上游 {count.get('upstreams',0)}，接入 {count.get('bindings',0)}。"
            '报告中的未核实项不代表失败，目录/合同/小样/质量独立；请核对“实际导出内容”。')
        self.guard.reset();self.enabled()

    def export(self,output=None):
        if self.call.busy or not self.pending:return
        if self.pending['options']!=self.options():self.changed();return
        if output is None:
            output=filedialog.asksaveasfilename(parent=self.win,title='选择新的诊断 JSON 文件（不覆盖已有文件）',
                initialfile='videocreate-diagnostics.json',defaultextension='.json',filetypes=[('JSON','*.json')],confirmoverwrite=False)
        if not output:return
        self.phase='export';self.summary.set('正在重新核对配置与证据摘要，并写入新的诊断文件。')
        self.call.start(diagnostics.export,self.manager.path,self.pending,output,token=self.pending['preview_token'],
            completed=self.exported,failed=self.failed)
        self.enabled()

    def exported(self,value):
        self.summary.set('已导出：'+value['output']+'。文件只包含预览报告，没有修改配置或生成任务。')
        self.guard.reset();self.enabled()

    def failed(self,error):
        self.pending=None
        self.summary.set('未完成：'+str(error)+'。请重新预览或选择新文件名；原配置与已有导出保持。')
        self.enabled()
