"""Task-shaped catalog view; applying changes this window's view only."""
import copy
import json
from tkinter import ttk

from . import manager_lifecycle as ui
from .catalog.presentation import OPERATIONS
from .catalog.suitability import query,scenario
from .config.storage import ConfigError
from .manager_drafts import DraftGuard


class TaskFilterPanel:
    def __init__(self,manager):
        self.manager=manager
        self.win,book,page=manager.dialog('按任务筛选型号')
        self.win.task_filter_panel=self;self.win.geometry('920x750')
        ttk.Label(page,text='只核对配置参数和参考数量，不读取素材或密钥、不生成。填写的条件共同生效；空白参数不参与筛选。',wraplength=800).pack(anchor='w',pady=8)
        form=ttk.Frame(page);form.pack(fill='x')
        current=manager.task_scenario or {'operation':'text-to-video'}
        self.fields={}
        fields=[('operation','操作',list(OPERATIONS.values())),('seconds','生成时长（秒）',None),
            ('resolution','分辨率（如 720p）',None),('aspect_ratio','画幅（如 16:9）',None),
            ('generate_audio','声音开关（空白不筛选）',['','是','否'])]
        for index,(key,label,choices) in enumerate(fields):
            value=current.get(key,'')
            if key=='operation':value=OPERATIONS[value]
            if key=='generate_audio' and value!='':value='是' if value else '否'
            var=ui.StringVar(self.win,value=str(value));self.fields[key]=var
            ttk.Label(form,text=label).grid(row=index,column=0,sticky='w',pady=5)
            control=ttk.Combobox(form,textvariable=var,values=choices,state='readonly') if choices else ttk.Entry(form,textvariable=var)
            control.grid(row=index,column=1,sticky='ew',padx=12,pady=5)
        form.columnconfigure(1,weight=1)
        self.check_counts=ui.BooleanVar(self.win,value='reference_counts' in current)
        ttk.Checkbutton(page,text='核对参考数量（0 表示明确不使用该类素材）',variable=self.check_counts).pack(anchor='w',pady=10)
        counts=ttk.Frame(page);counts.pack(fill='x')
        self.counts={}
        for index,(key,label) in enumerate([('image','图片'),('video','视频'),('audio','音频')]):
            ttk.Label(counts,text=label).grid(row=0,column=index*2,padx=5)
            var=ui.StringVar(self.win,value=str(current.get('reference_counts',{}).get(key,0)));self.counts[key]=var
            ttk.Entry(counts,textvariable=var,width=10).grid(row=0,column=index*2+1,padx=5)
        self.excluded=ui.BooleanVar(self.win,value=manager.task_exclusions)
        ttk.Checkbutton(page,text='同时显示不符合和未核实的条目及原因',variable=self.excluded).pack(anchor='w',pady=10)
        self.note=ui.StringVar(self.win)
        ttk.Label(page,textvariable=self.note,wraplength=800).pack(anchor='w',pady=8)
        self.report=manager.json_tab(book,'全部条目与原因',{});self.report.configure(state='disabled')
        self.pending=None
        actions=ttk.Frame(page);actions.pack(fill='x',pady=10)
        ttk.Button(actions,text='预览筛选结果',command=self.preview).pack(side='left')
        self.apply_button=ttk.Button(actions,text='应用到目录视图',command=self.apply,state='disabled');self.apply_button.pack(side='left',padx=10)
        for var in [*self.fields.values(),*self.counts.values(),self.check_counts,self.excluded]:
            var.trace_add('write',lambda *_:self.invalidate())
        DraftGuard(self.win,label='任务筛选条件（尚未应用到目录视图）')

    def invalidate(self):
        self.pending=None;self.apply_button.configure(state='disabled')

    def read(self):
        value={'operation':next(k for k,v in OPERATIONS.items() if v==self.fields['operation'].get())}
        for key in ('seconds','resolution','aspect_ratio','generate_audio'):
            raw=self.fields[key].get().strip()
            if raw:value[key]=float(raw) if key=='seconds' else raw=='是' if key=='generate_audio' else raw
        if self.check_counts.get():value['reference_counts']={k:int(v.get()) for k,v in self.counts.items()}
        return scenario(value)

    def preview(self):
        try:
            value=self.read();report=query(self.manager.value,value)
            self.report.configure(state='normal');self.report.delete('1.0','end')
            self.report.insert('1.0',json.dumps(report,ensure_ascii=False,indent=2));self.report.configure(state='disabled')
            n=report['counts'];self.note.set(f"全部目录：参数范围相符 {n['parameters-match']}，不符合 {n['excluded']}，未核实 {n['unverified']}。应用后仍叠加主窗口的上游/家族/搜索条件。")
            self.pending=copy.deepcopy(value);self.apply_button.configure(state='normal')
        except (ConfigError,ValueError) as exc:self.invalidate();self.note.set(str(exc))

    def apply(self):
        if self.pending is None:return
        try:
            if self.read()!=self.pending:raise ConfigError('筛选条件已变化，请重新预览')
            self.manager.task_scenario=copy.deepcopy(self.pending);self.manager.task_exclusions=self.excluded.get()
            self.manager.refresh_models();self.win.draft_guard.reset();self.win.destroy()
        except (ConfigError,ValueError) as exc:self.invalidate();self.note.set(str(exc))
