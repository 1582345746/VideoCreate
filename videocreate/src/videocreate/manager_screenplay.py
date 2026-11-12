"""Director-layer screenplay forms; no parallel script, task or timeline state."""
import copy
import tkinter as tk
from tkinter import ttk

from .config.storage import ConfigError
from .manager_forms import Fields
from .manager_authoring import StateMap


class ExactFields(Fields):
    """Retain explicit empty and numerically equivalent original values on no-op."""
    def __init__(self,book,title,value,fields,explanation=''):
        self.original=copy.deepcopy(value)
        super().__init__(book,title,value,fields,explanation)
        self.initial_raw={path:self.raw(var,kind) for path,var,kind in self.fields}

    @staticmethod
    def raw(var,kind):return var.get('1.0','end-1c') if kind=='multiline' else var.get()

    def read(self):
        value=super().read()
        for key,item in self.original.items():
            if key not in value and item in ('',[],{}):value[key]=copy.deepcopy(item)
            elif key in value and value[key]==item:value[key]=copy.deepcopy(item)
        for path,var,kind in self.fields:
            if path in self.original and self.raw(var,kind)==self.initial_raw[path]:
                value[path]=copy.deepcopy(self.original[path])
        return value


def identity(items,prefix):
    known={item.get('id') for item in items};number=1
    while prefix+'-'+str(number).zfill(3) in known:number+=1
    return prefix+'-'+str(number).zfill(3)


class OrderedItems:
    """Keep edits attached to their selected row while reordering stable IDs."""
    def __init__(self,manager,parent,items,label,editor_factory,new_factory):
        self.manager=manager;self.items=copy.deepcopy(items);self.current=None;self.editor=None;self.busy=False
        self.editor_factory=editor_factory;self.new_factory=new_factory
        left=ttk.Frame(parent,padding=8);left.pack(side='left',fill='y')
        self.tree=ttk.Treeview(left,show='tree',selectmode='browse',height=12)
        self.tree.pack(fill='both',expand=True)
        for text,fn in [('增加'+label,self.add),('删除'+label,self.delete),('上移',lambda:self.move(-1)),('下移',lambda:self.move(1))]:
            ttk.Button(left,text=text,command=fn).pack(fill='x',pady=3)
        self.right=ttk.Frame(parent);self.right.pack(side='left',fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',self.select)
        self.refresh(0 if items else None)

    @staticmethod
    def title(item):
        text=item.get('id') or (item.get('speaker','')+'：'+item['text'] if 'text' in item else item.get('description','未填写'))
        return str(text)[:65]

    def commit(self):
        if self.current is None or self.editor is None:return
        self.items[self.current]=self.editor.read()
        self.tree.item(str(self.current),text=str(self.current+1)+' · '+self.title(self.items[self.current]))

    def refresh(self,index):
        self.busy=True;self.tree.delete(*self.tree.get_children())
        for n,item in enumerate(self.items):self.tree.insert('','end',iid=str(n),text=str(n+1)+' · '+self.title(item))
        self.current=index;self.editor=None
        for child in self.right.winfo_children():child.destroy()
        if index is not None:
            self.tree.selection_set(str(index));self.tree.focus(str(index))
            book=ttk.Notebook(self.right);book.pack(fill='both',expand=True)
            self.editor=self.editor_factory(book,copy.deepcopy(self.items[index]))
        self.busy=False

    def select(self,_=None):
        if self.busy or not self.tree.selection():return
        target=int(self.tree.selection()[0])
        if target==self.current:return
        try:self.commit();self.refresh(target)
        except (ConfigError,ValueError) as exc:
            self.manager.error(exc)
            if self.current is not None:self.tree.selection_set(str(self.current))

    def add(self):
        try:
            self.commit();self.items.append(self.new_factory(self.items));self.refresh(len(self.items)-1)
        except (ConfigError,ValueError) as exc:self.manager.error(exc)

    def delete(self):
        if self.current is None:return
        del self.items[self.current];self.refresh(min(self.current,len(self.items)-1) if self.items else None)

    def move(self,delta):
        if self.current is None:return
        target=self.current+delta
        if not 0<=target<len(self.items):return
        try:
            self.commit();self.items[self.current],self.items[target]=self.items[target],self.items[self.current]
            self.refresh(target)
        except (ConfigError,ValueError) as exc:self.manager.error(exc)

    def read(self):self.commit();return copy.deepcopy(self.items)


class OptionalFields:
    def __init__(self,book,title,value,fields):
        page=ttk.Frame(book);book.add(page,text=title)
        self.enabled=tk.BooleanVar(page,value=value is not None)
        ttk.Checkbutton(page,text='填写'+title,variable=self.enabled).pack(anchor='w',padx=12,pady=8)
        nested=ttk.Notebook(page);nested.pack(fill='both',expand=True)
        self.form=ExactFields(nested,title,value or {},fields)

    def read(self):return self.form.read() if self.enabled.get() else None


class StateValue:
    """Optional shot state can remain either prose or an exact structured map."""
    def __init__(self,book,title,value):
        page=ttk.Frame(book,padding=12);book.add(page,text=title)
        self.mode=tk.StringVar(page,value='未设置' if value is None else '状态表' if isinstance(value,dict) else '文字描述')
        choice=ttk.Combobox(page,textvariable=self.mode,values=('未设置','文字描述','状态表'),state='readonly')
        choice.pack(anchor='w')
        self.text=tk.Text(page,height=6,wrap='word',undo=True);self.text.insert('1.0',value if isinstance(value,str) else '')
        self.state_page=ttk.Frame(page);self.states=StateMap(self.state_page,value if isinstance(value,dict) else {})
        def changed(_=None):
            self.text.pack_forget();self.state_page.pack_forget()
            if self.mode.get()=='文字描述':self.text.pack(fill='both',expand=True,pady=10)
            elif self.mode.get()=='状态表':self.state_page.pack(fill='both',expand=True,pady=10)
        choice.bind('<<ComboboxSelected>>',changed);changed()

    def read(self):
        if self.mode.get()=='未设置':return None
        return self.states.read() if self.mode.get()=='状态表' else self.text.get('1.0','end-1c')


class SceneEditor:
    def __init__(self,book,value):
        self.original=copy.deepcopy(value);basic=copy.deepcopy(value);positions=basic.pop('positions',{})
        self.form=ExactFields(book,'场景',basic,[('id','场景 ID','text'),('map','地理与物件布局','multiline'),
            ('axis','摄影轴线与方向','multiline')],'镜头用 scene_id 引用场景；改名或删除后不会自动改写镜头。')
        page=ttk.Frame(book,padding=12);book.add(page,text='角色与物件位置');self.positions=StateMap(page,positions)

    def read(self):
        value=self.form.read();positions=self.positions.read()
        if positions or 'positions' in self.original:value['positions']=positions
        return value


SHOT_FIELDS=[('id','镜头 ID','text'),('beat_id','对应事件 ID','text'),('scene_id','场景 ID','text'),
    ('information_goal','观众在此镜获得的信息','multiline'),('role','镜头用途','text'),
    ('planned_seconds','计划镜头秒数','number'),('asset_ids','入镜素材 ID（逗号分隔）','list'),
    ('actors','表演角色 ID（逗号分隔）','list'),('opening_frame','开场画面','multiline'),
    ('framing','景别与构图','multiline'),('camera_position','机位','text'),('camera_motion','摄影机运动','text'),
    ('screen_direction','画面运动方向','text'),('eyeline','视线对象与方向','text'),
    ('visible_evidence','呈现的证据 ID（逗号分隔）','list'),('cut_motivation','为何在此处切镜','multiline')]
PERFORMANCE=[('trigger','触发事件','multiline'),('attention','注意到什么','multiline'),
    ('visible_response','可见反应与情绪表现','multiline'),('decision','随后作出的选择','multiline')]
TIMING=[('motion_tempo','动作节奏',('brisk','natural','slow')),('action_start_by','最晚开始动作（秒）','number'),
    ('action_complete_by','最晚可见结果（秒）','number'),('max_reaction_hold','反应停顿上限（秒）','number')]
LINE_FIELDS=[('speaker','说话者素材 ID','text'),('text','台词','multiline'),('on_screen','是否在画面中','boolean'),
    ('start','镜头内开始秒数','number'),('end','镜头内结束秒数','number'),('voice_asset_id','声音素材 ID（选填）','text')]


class AudioEditor:
    def __init__(self,manager,book,value):
        self.original=copy.deepcopy(value);page=ttk.Frame(book);book.add(page,text='声音与对白')
        self.enabled=tk.BooleanVar(page,value=value is not None)
        ttk.Checkbutton(page,text='填写声音设计',variable=self.enabled).pack(anchor='w',padx=12,pady=8)
        nested=ttk.Notebook(page);nested.pack(fill='both',expand=True)
        basic=copy.deepcopy(value) if value is not None else {'mode':'ambience'};lines=basic.pop('lines',[])
        self.form=ExactFields(nested,'声音策略',basic,[('mode','声音方式',('native-dialogue','offscreen','ambience','mute','independent-voice')),
            ('ambience','环境音与声音说明','multiline')],'台词是制作意图；生成后的实际文字、声音与口型仍须播放核验。')
        pane=ttk.Frame(nested);nested.add(pane,text='有序台词')
        self.lines=OrderedItems(manager,pane,lines,'台词',lambda book,item:ExactFields(book,'台词',item,LINE_FIELDS),
            lambda items:{'speaker':'','text':'','on_screen':True,'start':0,'end':1})

    def read(self):
        if not self.enabled.get():return None
        value=self.form.read();lines=self.lines.read()
        if lines or self.original is not None and 'lines' in self.original:value['lines']=lines
        return value


class ShotEditor:
    def __init__(self,manager,book,value):
        basic=copy.deepcopy(value)
        actions=basic.pop('actions',[]);audio=basic.pop('audio',None)
        performance=basic.pop('performance',None);timing=basic.pop('timing',None)
        entry=basic.pop('entry_state',None);exit_state=basic.pop('exit_state',None)
        self.form=ExactFields(book,'镜头与画面',basic,SHOT_FIELDS,
            '镜头 ID 连接生成任务和时间线；改名、增删与排序不会自动改写它们。实际生成时长由 job 单独决定。')
        page=ttk.Frame(book);book.add(page,text='动作顺序')
        self.actions=OrderedItems(manager,page,actions,'动作',lambda b,item:ExactFields(b,'动作',item,
            [('kind','动作类型',('physical','reaction','camera','hold')),('description','可见动作','multiline')]),
            lambda items:{'kind':'physical','description':''})
        self.performance=OptionalFields(book,'表演设计',performance,PERFORMANCE)
        self.timing=OptionalFields(book,'动作时间约束',timing,TIMING)
        self.audio=AudioEditor(manager,book,audio)
        self.entry=StateValue(book,'开场状态',entry);self.exit=StateValue(book,'结束状态',exit_state)

    def read(self):
        value=self.form.read();value['actions']=self.actions.read()
        for key,editor in [('performance',self.performance),('timing',self.timing),('audio',self.audio),
                           ('entry_state',self.entry),('exit_state',self.exit)]:
            item=editor.read()
            if item is not None:value[key]=item
        return value


class DirectorEditor:
    def __init__(self,manager,book,value,story,root):
        self.original=copy.deepcopy(value)
        from .manager_assets import AssetListEditor
        self.assets=AssetListEditor(manager,book,value['assets'],root)
        page=ttk.Frame(book);book.add(page,text='场景与布局')
        self.scenes=OrderedItems(manager,page,value['scenes'],'场景',SceneEditor,
            lambda items:{'id':identity(items,'scene'),'map':'','axis':''})
        page=ttk.Frame(book);book.add(page,text='剧本与分镜')
        def new_shot(items):
            scenes=self.scenes.read()
            return {'id':identity(items,'shot'),'scene_id':scenes[0]['id'] if scenes else '',
                'beat_id':story['beats'][0]['id'] if story.get('beats') else '',
                'information_goal':'','framing':'','planned_seconds':5,'cut_motivation':'',
                'actions':[{'kind':'physical','description':''}]}
        self.shots=OrderedItems(manager,page,value['shots'],'镜头',lambda b,item:ShotEditor(manager,b,item),new_shot)
        page=ttk.Frame(book,padding=12);book.add(page,text='现有素材与事件')
        ttk.Label(page,text='按下面的稳定 ID 填写镜头引用。新素材先在角色与项目素材页填写；此处可刷新未保存的 ID。',wraplength=850).pack(anchor='w',pady=8)
        text=tk.Text(page,wrap='word',font=('Microsoft YaHei UI',10));text.pack(fill='both',expand=True)
        def refresh():
            try:
                assets=self.assets.read();text.configure(state='normal');text.delete('1.0','end')
                text.insert('1.0','\n'.join(['素材：']+[a['id']+' · '+a['kind']+' · '+a['description'] for a in assets]+
                    ['','事件：']+[b['id']+' · '+b['audience_learns'] for b in story['beats']]))
                text.configure(state='disabled')
            except (ConfigError,ValueError) as exc:manager.error(exc)
        ttk.Button(page,text='刷新引用列表',command=refresh).pack(anchor='w',pady=8);refresh()

    def read(self):
        return {**copy.deepcopy(self.original),'assets':self.assets.read(),'scenes':self.scenes.read(),'shots':self.shots.read()}
