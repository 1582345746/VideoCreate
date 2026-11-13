"""Asynchronous local GIF conversion form; calls the shared production service."""
import queue
import threading
import tkinter as tk
from . import manager_lifecycle as ui
from pathlib import Path
from tkinter import filedialog, ttk

from .config.storage import ConfigError
from .manager_forms import Fields


def open_form(manager, root, *, frames=False, parent=None, completed=lambda result: None, paths=None):
    if paths is None:
        if frames:
            paths=filedialog.askopenfilenames(parent=parent,title='选择静帧；下一页可调整顺序',
                filetypes=[('静态图片','*.png *.jpg *.jpeg *.webp')])
        else:
            value=filedialog.askopenfilename(parent=parent,title='选择视频',filetypes=[('视频','*.mp4 *.mov *.mkv *.webm')])
            paths=[value] if value else []
    if not paths:return
    win, book, basic=manager.dialog('本地静帧制作 GIF' if frames else '本地视频制作 GIF')
    defaults={'gif_id':'gif-001','fps':10,'width':480,'loop':0,
        'paths':'\n'.join(str(p) for p in paths),'start':0,'duration':3}
    fields=[('gif_id','GIF 标识（唯一 ASCII）','text'),
        ('paths','按顺序每行一个静帧路径（可调整）' if frames else '视频路径','multiline'),
        *([] if frames else [('start','开始秒','number'),('duration','转换秒数（最多 30 秒）','number')]),
        ('fps','每秒帧数（1–60）','integer'),('width','输出宽度（64–2048）','integer'),
        ('loop','循环次数（0 无限，-1 不循环）','integer')]
    form=Fields(book,'转换参数',defaults,fields,
        '复制素材、校验哈希并本地转换，不调用模型。旧文件保留，完整播放审核后才能标记通过。')
    book.forget(basic)
    book.select(form.section)
    channel=queue.Queue();busy=[False];note=ui.StringVar(win)
    scheduled=[None]
    def destroyed(event):
        if event.widget is win and scheduled[0] is not None:
            win.after_cancel(scheduled[0]);scheduled[0]=None
    win.bind('<Destroy>',destroyed,add='+')
    ttk.Label(win,textvariable=note,wraplength=700).pack(pady=6)
    def finish():
        scheduled[0]=None
        if not win.winfo_exists():return
        try:ok,result=channel.get_nowait()
        except queue.Empty:
            scheduled[0]=win.after(100,finish);return
        busy[0]=False;submit.configure(state='normal')
        if not ok:
            note.set('转换失败；已保留原素材和项目配置。');manager.error(result);return
        completed(result);win.destroy()
    def apply():
        if busy[0]:return
        try:
            values=form.read()
            selected=[Path(p.strip()) for p in values.get('paths','').splitlines() if p.strip()]
            if not selected or not frames and len(selected)!=1:
                raise ConfigError('请选择一个视频，或按顺序填写静帧路径')
        except (ConfigError,ValueError) as exc:
            manager.error(exc);return
        busy[0]=True;submit.configure(state='disabled');note.set('正在保存素材副本、完整解码和转换。')
        def worker():
            try:
                from .local_gifs import build
                result=build(root,gif_id=values.get('gif_id',''),
                    source=None if frames else selected[0],frames=selected if frames else None,
                    start=values.get('start',0),duration=values.get('duration',3),
                    fps=values.get('fps',10),width=values.get('width',480),loop=values.get('loop',0))
                channel.put((True,result))
            except Exception as exc:channel.put((False,exc))
        threading.Thread(target=worker,daemon=False).start();scheduled[0]=win.after(100,finish)
    submit=ttk.Button(win,text='本地转换并登记到项目',command=apply);submit.pack(pady=12)
    win.protocol('WM_DELETE_WINDOW',lambda:note.set('正在转换，请等待完成。') if busy[0] else win.destroy())
    return win
