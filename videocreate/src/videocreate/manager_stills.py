"""Import a static image hold through the shared local source service."""
import queue
import threading
import tkinter as tk
from . import manager_lifecycle as ui
from pathlib import Path
from tkinter import filedialog, ttk

from .config.storage import ConfigError, safe_error
from .manager_forms import Fields


def _import(channel, root, source, values):
    try:
        from .local_sources import import_image
        result = import_image(root, source, source_id=values.get('source_id', ''),
            seconds=values.get('seconds', 3), description=values.get('description', ''),
            shot_id=values.get('shot_id') or None)
        channel.put((True, result))
    except Exception as exc:
        channel.put((False, safe_error(exc)))


def open_form(manager, root, *, parent=None, source=None, completed=lambda result: None):
    if source is None:
        source = filedialog.askopenfilename(parent=parent, title='选择静态图片',
            filetypes=[('静态图片', '*.png *.jpg *.jpeg *.webp')])
    if not source:
        return
    win, book, basic = manager.dialog('静态图片加入视频时间线')
    book.pack_forget()
    footer = ttk.Frame(win, padding=12);footer.pack(side='bottom', fill='x')
    book.pack(fill='both', expand=True, padx=18, pady=14)
    ttk.Label(basic, text=str(source), wraplength=680).pack(anchor='w', pady=8)
    form = Fields(book, '图片停留', {'source_id':'image-001', 'seconds':3},
        [('source_id','来源标识（唯一 ASCII）','text'), ('seconds','停留秒数','number'),
            ('shot_id','已有镜头 ID（混合项目可选）','text'), ('description','画面用途（新建镜头）','multiline')],
        '复制完整原图并校验哈希；EXIF 方向在渲染时归正，透明区域以黑色显示。停留时间由时间线设置，不生成动作；配音使用独立音轨。')
    book.select(form.section)
    note = ui.StringVar(win)
    ttk.Label(footer, textvariable=note, wraplength=680).pack(anchor='w', pady=5)
    channel, busy, scheduled = queue.Queue(), [False], [None]

    def finish():
        scheduled[0] = None
        if not win.winfo_exists():
            return
        try:
            ok, result = channel.get_nowait()
        except queue.Empty:
            scheduled[0] = win.after(100, finish)
            return
        busy[0] = False;submit.configure(state='normal')
        if not ok:
            note.set('导入未完成：' + str(result));manager.error(result)
            return
        completed(result);win.destroy()

    def apply():
        if busy[0]:
            return
        try:
            values = form.read()
        except (ConfigError, ValueError) as exc:
            manager.error(exc);return
        busy[0] = True;submit.configure(state='disabled');note.set('正在复制和完整解码图片。')
        threading.Thread(target=_import, args=(channel, Path(root), Path(source), values), daemon=False).start()
        scheduled[0] = win.after(100, finish)

    submit = ttk.Button(footer, text='导入并加入时间线', command=apply);submit.pack(anchor='e', pady=8)

    def destroyed(event):
        if event.widget == win and scheduled[0] is not None:
            win.after_cancel(scheduled[0]);scheduled[0] = None
    win.bind('<Destroy>', destroyed, add='+')
    # Expose the form for the existing manager smoke and actual control tests.
    win.still_form, win.still_submit = form, submit
    from .manager_drafts import DraftGuard
    DraftGuard(win,read=form.read,label='静态图片导入参数',busy=lambda:busy[0])
    return win
