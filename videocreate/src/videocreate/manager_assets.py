"""Editable project cards and asynchronous local reference snapshot imports."""
import copy
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog,ttk

from . import project_assets
from .config.storage import ConfigError
from .manager_screenplay import ExactFields,OptionalFields,OrderedItems,identity


def local_work(manager,parent,work,done):
    progress=tk.Toplevel(parent);progress.title('整理本地素材');progress.transient(parent.winfo_toplevel());progress.grab_set()
    ttk.Label(progress,text='正在复制、校验本地素材，请稍候。',padding=24).pack(fill='both',expand=True)
    progress.protocol('WM_DELETE_WINDOW',lambda:None)
    channel=queue.Queue();timer=[None]
    def destroyed(event):
        if event.widget is progress and timer[0] is not None:
            progress.after_cancel(timer[0]);timer[0]=None
    progress.bind('<Destroy>',destroyed,add='+')
    def worker():
        try:channel.put((True,work()))
        except Exception as exc:channel.put((False,exc))
    def receive():
        timer[0]=None
        if not progress.winfo_exists():return
        try:ok,result=channel.get_nowait()
        except queue.Empty:timer[0]=progress.after(30,receive);return
        progress.destroy()
        if parent.winfo_exists():
            parent.winfo_toplevel().grab_set()
            if ok:done(result)
            else:manager.error(result)
    threading.Thread(target=worker,daemon=False).start();timer[0]=progress.after(30,receive)
    return progress


class References:
    def __init__(self,manager,book,root,paths,kind,asset_id):
        self.manager=manager;self.root=Path(root);self.paths=copy.deepcopy(paths);self.kind=kind;self.asset_id=asset_id
        page=ttk.Frame(book,padding=12);book.add(page,text='本地参考文件');self.page=page
        ttk.Label(page,text='导入只复制本地文件。保存角色资料后才建立引用；模型参考需在任务中明确关联。',wraplength=800).pack(anchor='w',pady=8)
        self.tree=tk.Listbox(page,height=10,selectmode='browse');self.tree.pack(fill='both',expand=True)
        actions=ttk.Frame(page);actions.pack(fill='x',pady=8)
        for text,fn in [('导入本地参考',self.import_file),('移除引用',self.remove),('上移',lambda:self.move(-1)),('下移',lambda:self.move(1)),('查看已保存资料对照',self.board)]:
            ttk.Button(actions,text=text,command=fn).pack(side='left',padx=4)
        self.note=tk.StringVar(page,value='原文件保留；移除引用不删除文件。声音样本不会自动创建克隆声线。')
        ttk.Label(page,textvariable=self.note,wraplength=820).pack(anchor='w',pady=8);self.refresh()

    def refresh(self,index=None):
        self.tree.delete(0,'end')
        for path in self.paths:self.tree.insert('end',path)
        if index is not None and self.paths:self.tree.selection_set(index)

    def import_file(self,source=None):
        try:
            kind=self.kind()
            if source is None:
                source=filedialog.askopenfilename(parent=self.page,title='选择声音样本' if kind=='voice' else '选择图片参考',
                    filetypes=[('音频','*.wav *.mp3 *.m4a *.flac *.ogg')] if kind=='voice' else [('图片','*.png *.jpg *.jpeg *.webp *.gif')])
            if not source:return
            def done(result):
                if result['path'] not in self.paths:self.paths.append(result['path'])
                self.refresh(self.paths.index(result['path']));self.note.set('已复制到项目；保存角色资料后引用生效，内容仍待查看或试听。')
            root=self.root
            return local_work(self.manager,self.page,lambda:project_assets.stage_reference(root,source,kind=kind),done)
        except (ConfigError,OSError,ValueError) as exc:self.manager.error(exc)

    def remove(self):
        selected=self.tree.curselection()
        if selected:
            del self.paths[selected[0]];self.refresh(min(selected[0],len(self.paths)-1) if self.paths else None)

    def move(self,delta):
        selected=self.tree.curselection()
        if not selected:return
        index=selected[0];target=index+delta
        if not 0<=target<len(self.paths):return
        self.paths[index],self.paths[target]=self.paths[target],self.paths[index];self.refresh(target)

    def board(self):
        try:
            asset_id=self.asset_id()
            def done(result):webbrowser.open(Path(result['page']).as_uri())
            root=self.root
            return local_work(self.manager,self.page,lambda:project_assets.board(root,asset_id),done)
        except (ConfigError,OSError,ValueError) as exc:self.manager.error(exc)

    def read(self):return copy.deepcopy(self.paths)


class AssetEditor:
    def __init__(self,manager,book,value,root):
        self.original=copy.deepcopy(value);basic=copy.deepcopy(value);references=basic.pop('references',[])
        visual=basic.pop('visual_design',None);physical=basic.pop('physical_design',None)
        self.form=ExactFields(book,'基本资料',basic,[('id','素材 ID（稳定）','text'),
            ('kind','类型',('character','scene','prop','voice')),('description','描述','multiline'),
            ('identity_origin','身份或资料来源说明','multiline'),('invariants','固定特征（逗号分隔）','list')],
            '镜头和声音用 ID 引用资料。改名或删除不会自动改写原任务、镜头和素材映射。')
        self.visual=OptionalFields(book,'身份与美术',visual,[('identity','身份与面部/物种结构','multiline'),
            ('wardrobe','服装与配饰','multiline'),('expression_range','表情范围','multiline'),('visual_style','美术风格','multiline')])
        self.physical=OptionalFields(book,'物理与摆放',physical,[('scale','大小与尺度','multiline'),
            ('placement','初始摆放与可达性','multiline'),('contact_constraints','接触与承重条件','multiline')])
        self.references=References(manager,book,root,references,lambda:self.form.read().get('kind'),lambda:self.form.read().get('id'))

    def read(self):
        value=self.form.read();refs=self.references.read()
        if refs or 'references' in self.original:value['references']=refs
        for key,form in [('visual_design',self.visual),('physical_design',self.physical)]:
            content=form.read()
            if content is not None:value[key]=content
        return value


class AssetListEditor:
    def __init__(self,manager,book,value,root):
        page=ttk.Frame(book);book.add(page,text='角色与项目素材');self.page=page
        self.items=OrderedItems(manager,page,value,'素材',lambda b,item:AssetEditor(manager,b,item,root),
            lambda items:{'id':identity(items,'asset'),'kind':'character','description':''})

    def read(self):return self.items.read()


class DirectorAssetsEditor:
    def __init__(self,manager,book,value,root):
        self.original=copy.deepcopy(value);self.assets=AssetListEditor(manager,book,value['assets'],root)
        book.select(self.assets.page)

    def read(self):return {**copy.deepcopy(self.original),'assets':self.assets.read()}
