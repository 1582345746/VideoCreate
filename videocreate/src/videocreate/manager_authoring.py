"""Native offline project, theme and causal-outline forms."""
import copy
import json
import math
import queue
import threading
import weakref
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from . import authoring
from .config.storage import ConfigError
from .manager_forms import Fields
from .planning.profiles import PROFILES

BRIEF_FIELDS=[('topic','制作主题','multiline'),('audience','目标受众','text'),
    ('viewer_goal','观众应理解什么','multiline'),('intent','观看目标',('narrative','demonstration','montage','single-shot')),
    ('pace_profile','节奏',('comedy','dialogue','suspense','slow-cinema','product-demo','action')),
    ('target_seconds','明确成片目标秒数（可留空）','number'),
    ('aspect_ratio','生成画幅','text'),('resolution','生成分辨率','text'),
    ('audio_policy','声音策略',('silent','ambience','voiceover','dialogue','native-experimental')),
    ('visual_style','美术与画面风格','multiline'),('allowed_elements','明确允许的元素（逗号分隔）','list'),
    ('forbidden_elements','避免的元素（逗号分隔）','list')]
STORY_FIELDS=[('logline','一句话故事','multiline'),('goal','人物目标','multiline'),
    ('obstacle','具体阻碍','multiline'),('choice','人物选择','multiline'),
    ('consequence','可见结果','multiline'),('payoff','落点（可选）','multiline')]
BEAT_FIELDS=[('id','事件 ID（保持稳定）','text'),('audience_learns','观众从这一事件得知什么','multiline'),
    ('visible_evidence_needed','必须看见的证据 ID（逗号分隔）','list'),
    ('causes','前因事件 ID（逗号分隔，开端留空）','list')]


def form_value(form,original):
    value=form.read()
    # Opening an existing draft must preserve its intentionally empty fields.
    for key,item in original.items():
        if key not in value and (item=='' or item==[]):value[key]=copy.deepcopy(item)
    return value


class StateMap:
    """Scalar state conditions; existing nested values survive without conversion."""
    def __init__(self,parent,value):
        self.rows=[]
        ttk.Label(parent,text='用稳定的状态名表示前后变化，例如 gate = closed → open。复杂对象保留原值。',
            wraplength=620).pack(anchor='w',pady=5)
        self.body=ttk.Frame(parent);self.body.pack(fill='both',expand=True)
        ttk.Button(parent,text='增加状态条件',command=lambda:self.add('', '')).pack(anchor='w',pady=6)
        for key,item in value.items():self.add(key,item)

    def add(self,key,value):
        row=ttk.Frame(self.body);row.pack(fill='x',pady=3)
        kind=('空值' if value is None else '是/否' if isinstance(value,bool) else
              '数字' if isinstance(value,(int,float)) else '文字' if isinstance(value,str) else '复杂值（保留）')
        name=tk.StringVar(row,value=key);typevar=tk.StringVar(row,value=kind)
        raw=tk.StringVar(row,value='' if value is None else str(value).lower() if isinstance(value,bool) else
                         value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))
        ttk.Entry(row,textvariable=name,width=22).pack(side='left',padx=(0,6))
        choices=ttk.Combobox(row,textvariable=typevar,values=('文字','数字','是/否','空值'),state='readonly',width=12)
        choices.pack(side='left',padx=(0,6))
        entry=ttk.Entry(row,textvariable=raw);entry.pack(side='left',fill='x',expand=True)
        def mode(_=None):entry.configure(state='disabled' if typevar.get() in {'复杂值（保留）','空值'} else 'normal')
        choices.bind('<<ComboboxSelected>>',mode);mode()
        record=(row,name,typevar,raw,copy.deepcopy(value));self.rows.append(record)
        def remove():self.rows.remove(record);row.destroy()
        ttk.Button(row,text='删除',command=remove).pack(side='left',padx=6)

    def read(self):
        value={}
        for row,name,typevar,raw,original in self.rows:
            key=name.get().strip();text=raw.get();kind=typevar.get()
            if not key or key in value:raise ConfigError('状态名不能为空或重复')
            if kind=='复杂值（保留）':item=copy.deepcopy(original)
            elif kind=='空值':item=None
            elif kind=='是/否':
                if text.strip().lower() not in {'true','false','是','否'}:raise ConfigError('是/否状态值应为 true、false、是或否')
                item=text.strip().lower() in {'true','是'}
            elif kind=='数字':
                try:item=json.loads(text)
                except ValueError:raise ConfigError('数字状态值无效') from None
                if isinstance(item,bool) or not isinstance(item,(int,float)) or isinstance(item,float) and not math.isfinite(item):
                    raise ConfigError('数字状态值必须为有限数字')
            else:item=text
            value[key]=item
        return value


class BeatList:
    """Ordered causal events, preserving director and generation mappings by ID."""
    def __init__(self,manager,parent,beats):
        self.manager=manager;self.beats=copy.deepcopy(beats);self.current=None;self.form=None;self.busy=False
        left=ttk.Frame(parent,padding=8);left.pack(side='left',fill='y')
        self.tree=ttk.Treeview(left,show='tree',selectmode='browse',height=15)
        self.tree.pack(fill='both',expand=True)
        for text,fn in [('增加事件',self.add),('删除事件',self.delete),('上移',lambda:self.move(-1)),('下移',lambda:self.move(1))]:
            ttk.Button(left,text=text,command=fn).pack(fill='x',pady=3)
        self.right=ttk.Frame(parent);self.right.pack(side='left',fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',self.select)
        self.refresh(0 if self.beats else None)

    def commit(self):
        if self.current is None or self.form is None:return
        item=self.form.read();item.update(requires=self.requires.read(),effects=self.effects.read())
        item.setdefault('causes',[]);item.setdefault('visible_evidence_needed',[])
        item.setdefault('audience_learns','');item.setdefault('id','')
        self.beats[self.current]=item
        self.tree.item(str(self.current),text=str(self.current+1)+' · '+item['id'])

    def refresh(self,index):
        self.busy=True;self.tree.delete(*self.tree.get_children())
        for n,item in enumerate(self.beats):self.tree.insert('','end',iid=str(n),text=str(n+1)+' · '+item.get('id','未命名'))
        self.current=index;self.form=None
        for child in self.right.winfo_children():child.destroy()
        if index is not None:
            self.tree.selection_set(str(index));self.tree.focus(str(index))
            book=ttk.Notebook(self.right);book.pack(fill='both',expand=True)
            item=copy.deepcopy(self.beats[index]);requires=item.pop('requires',{});effects=item.pop('effects',{})
            self.form=Fields(book,'事件',item,BEAT_FIELDS,'事件 ID 与分镜关联。更改 ID 后须核对受影响的镜头与前因。')
            before=ttk.Frame(book,padding=12);book.add(before,text='发生前的条件')
            after=ttk.Frame(book,padding=12);book.add(after,text='发生后的变化')
            self.requires=StateMap(before,requires);self.effects=StateMap(after,effects)
        self.busy=False

    def select(self,_=None):
        if self.busy or not self.tree.selection():return
        target=int(self.tree.selection()[0])
        if target==self.current:return
        try:self.commit();self.refresh(target)
        except (ConfigError,ValueError) as exc:
            self.manager.error(exc)
            self.busy=True
            if self.current is not None:self.tree.selection_set(str(self.current))
            self.busy=False

    def add(self):
        try:
            self.commit();n=1;known={item.get('id') for item in self.beats}
            while 'beat-'+str(n).zfill(3) in known:n+=1
            self.beats.append({'id':'beat-'+str(n).zfill(3),'requires':{},'effects':{},'causes':[],
                'audience_learns':'','visible_evidence_needed':[]})
            self.refresh(len(self.beats)-1)
        except (ConfigError,ValueError) as exc:self.manager.error(exc)

    def delete(self):
        if self.current is None:return
        del self.beats[self.current];self.refresh(min(self.current,len(self.beats)-1) if self.beats else None)

    def move(self,delta):
        if self.current is None:return
        target=self.current+delta
        if not 0<=target<len(self.beats):return
        try:
            self.commit();self.beats[self.current],self.beats[target]=self.beats[target],self.beats[self.current]
            self.refresh(target)
        except (ConfigError,ValueError) as exc:self.manager.error(exc)

    def read(self):self.commit();return copy.deepcopy(self.beats)


def open_editor(manager,root,layer,completed=None):
    root=Path(root).resolve();snapshot=authoring.describe(root,layer);value=snapshot['value']
    win,book,basic=manager.dialog({'brief':'主题与规格','story':'故事大纲','director':'剧本与分镜'}[layer])
    win.geometry('1100x820')
    ttk.Label(basic,text=snapshot['title'],font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w')
    ttk.Label(basic,text=str(root),wraplength=900).pack(anchor='w',pady=8)
    ttk.Label(basic,text='先预览修改影响再保存。可保存尚未完成的草稿；生成仍须通过完整计划检查。保存不提交任务，也不批准内容。',
        wraplength=900).pack(anchor='w',pady=8)
    if layer=='brief':
        form=Fields(book,'主题与规格',value,BRIEF_FIELDS,
            '生成规格不会自动改写时间线尺寸。主题、受众和理解目标用于策划；实际请求由分镜与已消费参数决定。')
        def read():return form_value(form,value)
    elif layer=='story':
        remaining=copy.deepcopy(value);initial=remaining.pop('initial_state',{});beats=remaining.pop('beats',[])
        form=Fields(book,'故事整体',remaining,STORY_FIELDS,'大纲只写回 story；分镜、剧本和已提交任务保持各自记录。')
        page=ttk.Frame(book,padding=12);book.add(page,text='开场状态');states=StateMap(page,initial)
        page=ttk.Frame(book);book.add(page,text='因果事件');events=BeatList(manager,page,beats)
        def read():return {**form_value(form,remaining),'initial_state':states.read(),'beats':events.read()}
    else:
        from .manager_screenplay import DirectorEditor
        from .planning.project import load_project
        form=DirectorEditor(manager,book,value,load_project(root)['story'])
        def read():return form.read()
    report=manager.json_tab(book,'修改预览',{'提示':'填写后点击“预览修改影响”。'})
    report.configure(state='disabled')
    note=tk.StringVar(win,value='保存仅修改当前创作层；已提交任务、候选和账本不会被替换。')
    ttk.Label(win,textvariable=note,wraplength=1000).pack(anchor='w',padx=16,pady=8)
    actions=ttk.Frame(win,padding=12);actions.pack(fill='x');pending={}
    win.authoring_busy=False
    scheduled=[None]
    def destroyed(event):
        if event.widget is win and scheduled[0] is not None:
            win.after_cancel(scheduled[0]);scheduled[0]=None
    win.bind('<Destroy>',destroyed,add='+')
    def background(work,done):
        if win.authoring_busy:return
        win.authoring_busy=True
        overlay=tk.Toplevel(win);overlay.title('检查制作内容');overlay.transient(win)
        overlay.geometry('420x130');overlay.grab_set()
        label=ttk.Label(overlay,text='正在校验项目素材与修改影响，请稍候。',padding=24,wraplength=370)
        label.pack(fill='both',expand=True)
        overlay.protocol('WM_DELETE_WINDOW',lambda:label.configure(text='操作正在完成，请稍候。'))
        channel=queue.Queue()
        def worker():
            try:channel.put((True,work()))
            except Exception as exc:channel.put((False,exc))
        def receive():
            scheduled[0]=None
            if not win.winfo_exists():return
            try:ok,result=channel.get_nowait()
            except queue.Empty:scheduled[0]=win.after(30,receive);return
            win.authoring_busy=False
            overlay.destroy();win.grab_set()
            if ok:done(result)
            else:
                pending.clear();save_button.configure(state='disabled');manager.error(result)
        threading.Thread(target=worker,daemon=False).start();scheduled[0]=win.after(30,receive)
    def previewed(result):
        pending.clear();pending.update(result)
        report.configure(state='normal');report.delete('1.0','end');report.insert('1.0',json.dumps(result,ensure_ascii=False,indent=2));report.configure(state='disabled')
        book.select(report.master)
        check=result['plan_validation']
        note.set(('完整计划校验通过，内容仍待审。' if check['ok'] else
            '当前有 '+str(len(check['errors']))+' 项计划错误；可以保存草稿，生成会继续受阻。')+
            ' 修改字段：'+(', '.join(result['changed_paths']) or '无')+'；现有任务保持。')
        save_button.configure(state='normal')
    def preview():
        try:
            data=read()
            background(lambda:authoring.preview(root,layer,data,source_token=snapshot['source_token']),previewed)
        except (ConfigError,OSError,ValueError) as exc:
            pending.clear();save_button.configure(state='disabled');manager.error(exc)
    def save():
        try:
            data=read();token=pending.get('preview_token')
            def saved(result):
                if completed:completed(result)
                win.destroy()
            background(lambda:authoring.save(root,layer,data,source_token=snapshot['source_token'],preview_token=token),saved)
        except (ConfigError,OSError,ValueError) as exc:
            save_button.configure(state='disabled');manager.error(exc)
    def close():
        if win.authoring_busy:return
        try:dirty=read()!=value
        except (ConfigError,ValueError):dirty=True
        if dirty and not messagebox.askyesno('未保存的创作修改','关闭并放弃此表单中尚未保存的修改？',parent=win):return
        win.destroy()
    ttk.Button(actions,text='预览修改影响',command=preview).pack(side='left',padx=6)
    save_button=ttk.Button(actions,text='保存当前创作层',command=save,state='disabled');save_button.pack(side='left',padx=6)
    ttk.Button(actions,text='关闭',command=close).pack(side='right')
    win.protocol('WM_DELETE_WINDOW',close)
    # Public widget references support real form interaction without a second UI model.
    win.authoring_read=weakref.proxy(read);win.authoring_form=weakref.proxy(form)
    if layer=='story':win.authoring_events=weakref.proxy(events);win.authoring_states=weakref.proxy(states)
    if layer=='director':win.authoring_director=weakref.proxy(form)
    return win


def open_new(manager,completed=None):
    win,book,basic=manager.dialog('新建制作项目')
    win.geometry('1020x800')
    parent=tk.StringVar(win,value=str(manager.path.parent/'projects'));name=tk.StringVar(win)
    for title,var in [('保存位置',parent),('新文件夹名称',name)]:
        ttk.Label(basic,text=title).pack(anchor='w',pady=(12,3));ttk.Entry(basic,textvariable=var).pack(fill='x')
    def folder():
        selected=filedialog.askdirectory(parent=win,title='选择项目的保存位置')
        if selected:parent.set(selected)
    ttk.Button(basic,text='选择保存位置',command=folder).pack(anchor='w',pady=8)
    labels={p['title']+' · '+key:key for key,p in PROFILES.items()}
    form=Fields(book,'制作需求',{'profile':next(iter(labels)),'aspect_ratio':'16:9'},
        [('profile','制作分支',tuple(labels)),('title','项目名称','text'),('topic','制作主题','multiline'),
         ('audience','目标受众','text'),('viewer_goal','观众应理解什么','multiline'),
         ('aspect_ratio','画幅',('16:9','9:16')),('seconds','目标秒数（选填，纯图/GIF/仅剪辑留空）','number')],
        '创建可编辑起稿，不选择或调用模型。模板内容需要根据当前主题编写，不能直接视为完成的剧本。')
    note=tk.StringVar(win);ttk.Label(win,textvariable=note,wraplength=940).pack(anchor='w',padx=16,pady=8)
    def create():
        try:
            filename=name.get().strip()
            if (not filename or filename in {'.','..'} or any(c in filename for c in '/\\:<>"|?*')
                    or filename.endswith(('.', ' '))):raise ConfigError('请填写单个有效的新文件夹名称')
            values=form.read();profile=labels.get(values.pop('profile',None))
            if profile is None:raise ConfigError('请选择制作分支')
            if not values.get('title'):raise ConfigError('请填写项目名称')
            if not parent.get().strip():raise ConfigError('请选择保存位置')
            result=authoring.create(Path(parent.get()).expanduser()/filename,profile=profile,**values)
            win.destroy()
            if completed:completed(result)
        except (ConfigError,OSError,ValueError,TypeError) as exc:manager.error(exc)
    ttk.Button(win,text='创建草稿项目',command=create).pack(pady=12)
    initial=form.read();initial_parent=parent.get()
    def close():
        try:dirty=bool(name.get()) or parent.get()!=initial_parent or form.read()!=initial
        except (ConfigError,ValueError):dirty=True
        if dirty and not messagebox.askyesno('未保存的制作需求','关闭并放弃尚未创建的制作需求？',parent=win):return
        win.destroy()
    win.protocol('WM_DELETE_WINDOW',close)
    win.authoring_form=weakref.proxy(form);win.authoring_parent=parent;win.authoring_name=name
    return win
