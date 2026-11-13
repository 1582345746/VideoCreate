"""Inspect cached/live catalog differences and import source-bound drafts."""
import copy
import json
from tkinter import ttk

from . import manager_lifecycle as ui
from .catalog import discovery,observations
from .config.management import fingerprint
from .config.storage import ConfigError
from .manager_drafts import DraftGuard


class CatalogPanel:
    def __init__(self,manager,upstream,*,refresh=True):
        self.manager,self.upstream=manager,upstream
        self.win,book,page=manager.dialog('上游目录变化与草稿导入');self.win.geometry('1040x790')
        self.win.catalog_panel=self
        ttk.Label(page,text='目录只反映该账户在观察时间返回的型号名称。未再出现不代表下线，配置和旧任务保留；导入只新增禁用草稿。',wraplength=940).pack(anchor='w',pady=8)
        self.note=ui.StringVar(self.win,value='尚未读取目录。')
        ttk.Label(page,textvariable=self.note,wraplength=940).pack(anchor='w',pady=8)
        bar=ttk.Frame(page);bar.pack(fill='x')
        self.query=ui.StringVar(self.win);self.view=ui.StringVar(self.win,value='全部')
        ttk.Label(bar,text='搜索型号').pack(side='left');ttk.Entry(bar,textvariable=self.query).pack(side='left',fill='x',expand=True,padx=8)
        ttk.Combobox(bar,textvariable=self.view,values=['全部','可导入','相比上次新增','相比上次未再出现','本地未出现在目录'],state='readonly',width=22).pack(side='left')
        table=ttk.Frame(page);table.pack(fill='both',expand=True,pady=10)
        self.tree=ttk.Treeview(table,columns=('model','change','local','importable'),show='headings',height=10,selectmode='extended')
        for key,title,width in [('model','远端型号（原样 ID）',380),('change','目录观察',180),('local','本地接入',190),('importable','可导入',80)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width)
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview)
        horizontal=ttk.Scrollbar(table,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        self.tree.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns')
        horizontal.grid(row=1,column=0,sticky='ew');table.rowconfigure(0,weight=1);table.columnconfigure(0,weight=1)
        form=ttk.Frame(page);form.pack(fill='x')
        self.kind=ui.StringVar(self.win,value='video');self.family=ui.StringVar(self.win,value='custom')
        ttk.Label(form,text='导入媒体类型').pack(side='left')
        ttk.Combobox(form,textvariable=self.kind,values=['video','image'],state='readonly',width=10).pack(side='left',padx=8)
        ttk.Label(form,text='家族').pack(side='left');ttk.Entry(form,textvariable=self.family,width=18).pack(side='left',padx=8)
        self.details=manager.json_tab(book,'来源与变化记录',{});self.details.configure(state='disabled')
        actions=ttk.Frame(page);actions.pack(fill='x',pady=12)
        self.refresh_button=ttk.Button(actions,text='刷新目录（只读 GET）',command=self.refresh);self.refresh_button.pack(side='left')
        self.saved_button=ttk.Button(actions,text='查看已保存目录',command=self.saved);self.saved_button.pack(side='left',padx=8)
        self.import_button=ttk.Button(actions,text='导入所选为草稿',command=self.apply,state='disabled');self.import_button.pack(side='right')
        self.background=ui.BackgroundCall(self.win);self.result=None;self.items={};self.config_token=None
        self.query.trace_add('write',lambda *_:self.draw());self.view.trace_add('write',lambda *_:self.draw())
        DraftGuard(self.win,read=lambda:(self.kind.get(),self.family.get()),label='目录导入类型与家族（尚未应用）')
        if refresh:self.refresh()
        else:self.saved()

    def show(self,result):
        self.result=result
        self.details.configure(state='normal');self.details.delete('1.0','end')
        self.details.insert('1.0',json.dumps(result,ensure_ascii=False,indent=2));self.details.configure(state='disabled')
        if result.get('status')=='no-observation':self.note.set('该地址/账户尚无完整目录观察；可执行只读刷新。历史无账户范围的目录文件保留。')
        else:
            changes=result['changes'];added=changes['added_since_previous'];missing=changes['not_in_latest_since_previous']
            self.note.set('观察时间 '+result['observed_at']+'；'+('首份有效观察，无上一份可比。' if added is None else
                f"相比上次新增 {len(added)}，未再出现 {len(missing)}。")+
                f"本地未出现在目录 {len(changes['local_not_in_observation'])}；均保留。来源仅为目录，不证明能力或可用。")
        self.draw();self.enabled()

    def draw(self):
        selected={self.items.get(key) for key in self.tree.selection()};self.tree.delete(*self.tree.get_children());self.items={}
        terms=self.query.get().casefold().split();view=self.view.get()
        for index,row in enumerate((self.result or {}).get('rows',[])):
            remote=row['remote_model']
            if not all(term in remote.casefold() for term in terms):continue
            if view=='可导入' and not row['importable']:continue
            if view=='相比上次新增' and row['change']!='added':continue
            if view=='相比上次未再出现' and row['change']!='not-in-latest':continue
            if view=='本地未出现在目录' and (row['catalog_status']!='absent' or not row['local_bindings']):continue
            key=str(index);self.items[key]=remote
            self.tree.insert('','end',iid=key,values=(remote,
                {'added':'相比上次新增','unchanged':'本次仍出现','first-observation':'首次观察','not-in-latest':'本次未再出现','not-observed':'本次未观察到'}[row['change']],
                '、'.join(row['local_bindings']) if row['local_bindings'] else '未配置','是（禁用草稿）' if row['importable'] else '否'))
        self.tree.selection_set([key for key,remote in self.items.items() if remote in selected])

    def enabled(self):
        state='disabled' if self.background.busy else 'normal'
        self.refresh_button.configure(state=state);self.saved_button.configure(state=state)
        self.import_button.configure(state='normal' if not self.background.busy and self.result and self.result.get('observation') else 'disabled')

    def start(self,function):
        if self.background.busy:return
        value=copy.deepcopy(self.manager.value);self.config_token=fingerprint(value)
        self.note.set('正在读取；不会提交生成或改变配置。')
        self.background.start(function,value,self.upstream,store_root=self.manager.path.parent,
            completed=self.show,failed=self.failed);self.enabled()

    def refresh(self):self.start(discovery.models)

    def saved(self):self.start(observations.show)

    def failed(self,error):
        self.note.set('目录未更新：'+str(error)+'。保留此前观察与本地配置。')
        # Any previous observation retains its original configuration binding.
        self.result=None;self.draw();self.enabled()

    def apply(self):
        if self.background.busy or not self.result or not self.result.get('observation'):return
        try:
            if fingerprint(self.manager.value)!=self.config_token:raise ConfigError('配置已变化，请重新读取或刷新目录后导入')
            selected=[self.items[key] for key in self.tree.selection()]
            if not selected:raise ConfigError('请选择需要导入的目录型号')
            if set(selected)-set(self.result['ids']):raise ConfigError('本次目录未观察到的本地型号不能作为新增项导入；原接入保留')
            source=observations.show(self.manager.value,self.upstream,store_root=self.manager.path.parent,file=self.result['evidence'])
            if source['observation']!=self.result['observation']:raise ConfigError('目录观察文件已变化，请重新读取后导入')
            value,added=discovery.import_models(self.manager.value,self.upstream,selected,kind=self.kind.get(),
                family=self.family.get().strip() or 'custom',observation=self.result['observation'])
            result=observations.show(value,self.upstream,store_root=self.manager.path.parent,file=self.result['evidence'])
            if added:
                self.manager.value=value;self.manager.changed()
            self.config_token=fingerprint(self.manager.value)
            self.show(result);self.win.draft_guard.reset()
            self.note.set(f'已新增 {len(added)} 个禁用草稿，已有接入及备注保持；请在主窗口保存配置。')
        except (ConfigError,OSError,ValueError) as exc:self.manager.error(exc)
