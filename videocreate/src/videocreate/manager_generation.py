"""Native generation jobs; edits share the token-bound authoring save service."""
import copy
import json
from pathlib import Path
from tkinter import filedialog,ttk

from .config.storage import ConfigError,load_json
from .manager_assets import local_work
from .manager_screenplay import ExactFields,OrderedItems,identity


def set_field(form,key,value):
    for path,var,kind in form.fields:
        if path==key:var.set(value);return


class Route:
    def __init__(self,book,value,config,kind):
        self.config=config
        models=tuple(key for key,item in config.get('models',{}).items() if item['kind']==kind)
        bindings=tuple(key for key,item in config.get('bindings',{}).items() if item['model'] in models)
        self.form=ExactFields(book,'型号与上游接入',value,[('model','内部型号 ID（留空沿用项目选择）',models),
            ('binding_id','接入 ID（确定上游与账户）',bindings)],
            '这里读取本机已保存配置；草稿/禁用接入也显示供规划，保存不代表可执行。已有任务继续使用原快照，改路线只作用于明确的新尝试。')
        page=ttk.Frame(book,padding=12);book.add(page,text='接入说明')
        ttk.Button(page,text='由所选接入填写型号',command=self.match).pack(anchor='w',pady=6)
        import tkinter as tk
        self.details=tk.Text(page,wrap='word',font=('Microsoft YaHei UI',10));self.details.pack(fill='both',expand=True)
        cards=[]
        for key in bindings:
            item=config['bindings'][key];upstream=config['upstreams'][item['upstream']]
            cards.append({'binding_id':key,'model':item['model'],'upstream':item['upstream'],
                'display_name':item.get('display_name',key),'upstream_name':upstream.get('display_name',item['upstream']),
                'remote_model':item['remote_model'],'enabled':item['enabled'],'adapter':item['adapter'],
                'notes':item.get('notes','')})
        self.details.insert('1.0',json.dumps(cards,ensure_ascii=False,indent=2));self.details.configure(state='disabled')

    def match(self):
        binding=self.form.read().get('binding_id')
        if binding in self.config.get('bindings',{}):set_field(self.form,'model',self.config['bindings'][binding]['model'])

    def read(self):return self.form.read()


class ReferenceEditor:
    def __init__(self,manager,book,value,root,image):
        self.manager=manager;self.root=Path(root);self.image=image
        fields=[('path','项目内参考路径','text'),('sha256','完整 SHA256','text')]
        if not image:fields += [('kind','媒体类型（旧图片参考可留空）',('image','video','audio')),
            ('role','参考作用',('opening-frame','identity','prop','scene','style','motion','sound'))]
        self.form=ExactFields(book,'参考文件',value,fields,
            '顺序按此列表保存；首帧、身份、动作和声音有各自作用。HTTPS 发布与链接检查由素材服务单独执行，保存参考不会上传。')
        page=ttk.Frame(book,padding=12);book.add(page,text='选择本地文件')
        ttk.Label(page,text='选择已在项目内保存的文件，读取实际媒体与哈希。项目外文件先通过素材导入或 media-ref register 保存快照。',wraplength=700).pack(anchor='w',pady=10)
        ttk.Button(page,text='选取项目内参考文件',command=self.choose).pack(anchor='w')
        self.page=page

    def choose(self,source=None):
        try:
            if source is None:source=filedialog.askopenfilename(parent=self.page,initialdir=str(self.root/'assets'),title='选择项目内参考')
            if not source:return
            source=Path(source).resolve()
            try:relative=source.relative_to(self.root).as_posix()
            except ValueError:raise ConfigError('先把项目外参考导入到项目；此按钮只关联已有本地文件') from None
            root=self.root;image=self.image;kind='image' if image else self.form.read().get('kind','image')
            def work():
                from .planning.project import within
                path=within(root,relative)
                if image:
                    from .media.gif import probe_image
                    media=probe_image(path)
                    return {'path':relative,'sha256':media['sha256']}
                from .media_references import inspect
                media=inspect(path,kind)
                return {'path':relative,'sha256':media['sha256']}
            def done(result):
                for key,value in result.items():set_field(self.form,key,value)
            return local_work(self.manager,self.page,work,done)
        except (ConfigError,OSError,ValueError) as exc:self.manager.error(exc)

    def read(self):return self.form.read()


class References:
    def __init__(self,manager,book,value,root,image):
        self.manager=manager;self.root=Path(root);self.image=image
        page=ttk.Frame(book);book.add(page,text='有序参考');self.page=page
        ttk.Button(page,text='导入已登记参考 JSON',command=self.import_json).pack(anchor='w',padx=8,pady=6)
        def new(items):return {'path':'','sha256':''} if image else {'path':'','sha256':'','kind':'image','role':'identity'}
        self.items=OrderedItems(manager,page,value,'参考',lambda b,v:ReferenceEditor(manager,b,v,root,image),new)

    def import_json(self,source=None):
        try:
            self.items.commit()
            if source is None:source=filedialog.askopenfilename(parent=self.page,title='已登记参考 JSON',filetypes=[('JSON','*.json')])
            if not source:return
            value=load_json(Path(source));root=self.root;image=self.image
            def work():
                from .generation_authoring import reference_from_json
                return reference_from_json(root,value,image=image)
            def done(reference):
                self.items.items.append(reference);self.items.refresh(len(self.items.items)-1)
            return local_work(self.manager,self.page,work,done)
        except (ConfigError,OSError,ValueError) as exc:self.manager.error(exc)

    def read(self):return self.items.read()


class JobEditor:
    def __init__(self,manager,book,value,root,config,*,image=False):
        self.original=copy.deepcopy(value);basic=copy.deepcopy(value)
        route={key:basic.pop(key) for key in ('model','binding_id') if key in basic};refs=basic.pop('references',[])
        fields=[('id','稳定任务 ID','text')]
        fields += [('operation','操作',('text-to-image','image-edit')),('prompt','图片提示词','multiline'),
            ('size','请求尺寸','text'),('quality','质量档位','text'),('output_format','输出格式',('png','jpeg','webp','gif'))] if image else [
            ('shot_ids','对应镜头 ID（逗号分隔，顺序保留）','list'),
            ('operation','操作',('text-to-video','image-to-video','reference-to-video')),('seconds','上游生成秒数','number'),
            ('depends_on','依赖任务/已登记本地来源 ID','list'),('required_quality_checks','需已有观察证据的检查项','list')]
        self.form=ExactFields(book,'生成任务',basic,fields,
            '生成时长和剪辑保留时长分开；视频画幅与分辨率来自主题规格，声音由关联镜头决定。增删任务不会自动修改镜头或时间线。')
        self.route=Route(book,route,config,'image' if image else 'video')
        self.references=References(manager,book,refs,root,image)

    def read(self):
        value={**self.form.read(),**self.route.read()};refs=self.references.read()
        if refs or 'references' in self.original:value['references']=refs
        return value


class GenerationEditor:
    def __init__(self,manager,book,value,root,bundle):
        self.original=copy.deepcopy(value)
        from .config.management import load
        self.config=load(manager.path)['config']
        pure=bundle['brief'].get('workflow_profile') in {'image-only','gif-only','gif-local'}
        self.jobs=None;self.images=None
        if not pure:
            page=ttk.Frame(book);book.add(page,text='视频生成任务')
            self.jobs=OrderedItems(manager,page,value['jobs'],'视频任务',
                lambda b,v:JobEditor(manager,b,v,root,self.config),
                lambda items:{'id':identity(items,'job'),'shot_ids':[],'operation':'text-to-video','seconds':5})
        animated=bundle['brief'].get('workflow_profile') in {'gif-only','gif-local'}
        if pure:
            page=ttk.Frame(book);book.add(page,text='图片与原生 GIF 任务')
            self.images=OrderedItems(manager,page,value.get('image_jobs',[]),'图片任务',
                lambda b,v:JobEditor(manager,b,v,root,self.config,image=True),
                lambda items:{'id':identity(items,'image'),'operation':'text-to-image','prompt':'','size':'1024x1024',
                    'quality':'auto','output_format':'gif' if animated else 'png'})
        book.select(page)
        page=ttk.Frame(book,padding=12);book.add(page,text='关联查询')
        import tkinter as tk
        text=tk.Text(page,wrap='word');text.pack(fill='both',expand=True)
        text.insert('1.0',json.dumps({'shots':[{'id':s['id'],'information_goal':s['information_goal']} for s in bundle['director']['shots']],
            'local_sources':value.get('local_sources',[]),'local_gifs':value.get('local_gifs',[]),
            'note':'本地视频/GIF 由各自导入服务管理；此处保留原值。任务顺序不改变播放顺序。'},ensure_ascii=False,indent=2))
        text.configure(state='disabled')

    def read(self):
        result=copy.deepcopy(self.original)
        if self.jobs is not None:result['jobs']=self.jobs.read()
        if self.images is not None:
            images=self.images.read()
            if images or 'image_jobs' in self.original:result['image_jobs']=images
        return result
