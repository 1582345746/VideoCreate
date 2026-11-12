"""Read the current production step and explicitly record plan-only checkpoints."""
import queue
import threading
import tkinter as tk
from tkinter import ttk

from . import production


def _checkpoint(channel, root, stage, reason, expected_hash):
    try:
        channel.put((True, production.checkpoint(root, stage, reason=reason, expected_hash=expected_hash)))
    except Exception as exc:
        channel.put((False, exc))


def open_inspection(manager, root, decision, *, edit_layer, completed, import_video=None, import_gif=None, open_tasks=None):
    win, book, basic = manager.dialog('继续制作 · ' + decision['name'])
    # Reserve controls before giving the notebook its remaining space.
    book.pack_forget()
    footer = ttk.Frame(win, padding=12);footer.pack(side='bottom', fill='x')
    book.pack(fill='both', expand=True, padx=18, pady=14)
    ttk.Label(basic, text=decision['note'], wraplength=680).pack(anchor='w', pady=8)
    ttk.Label(basic, text=str(root), wraplength=680).pack(anchor='w')
    details = manager.json_tab(book, '当前内容与任务', decision)
    details.configure(state='disabled')
    busy = [False]
    scheduled = [None]
    note = tk.StringVar()
    ttk.Label(footer, textvariable=note, wraplength=680).pack(anchor='w')
    buttons = ttk.Frame(footer);buttons.pack(fill='x', pady=8)
    stage = decision['stage']
    layer = decision.get('edit_layer')
    if layer:
        ttk.Button(buttons, text='编辑本阶段计划',
            command=lambda: edit_layer(layer, assets_only=decision.get('assets_only', False))).pack(side='left', padx=4)
    if decision['action'] == 'inspect-authoring':
        if not layer:
            ttk.Label(basic, text='此阶段使用动画创作源或本地 GIF 配方，请通过原创作入口修改。', wraplength=680).pack(anchor='w', pady=8)
        ttk.Label(basic, text='请在“当前内容与任务”阅读本阶段内容，并填写本次核对结论。', wraplength=680).pack(anchor='w', pady=8)
        reason = tk.StringVar()
        ttk.Label(basic, text='核对理由').pack(anchor='w')
        ttk.Entry(basic, textvariable=reason, width=76).pack(fill='x', pady=6)
        channel = queue.Queue()

        def finish():
            scheduled[0] = None
            if not win.winfo_exists():
                return
            try:
                ok, value = channel.get_nowait()
            except queue.Empty:
                scheduled[0] = win.after(100, finish)
                return
            busy[0] = False
            submit.configure(state='normal')
            if not ok:
                note.set('未登记：' + str(value));manager.error(value)
                return
            completed(value)
            win.destroy()

        def record():
            if busy[0]:
                return
            explanation = reason.get().strip()
            if not explanation:
                note.set('请填写本阶段实际核对理由。')
                return
            busy[0] = True;submit.configure(state='disabled')
            note.set('正在重新核对内容版本并登记计划检查。')
            threading.Thread(target=_checkpoint,
                args=(channel, root, stage, explanation, decision['input_hash']), daemon=False).start()
            scheduled[0] = win.after(100, finish)

        submit = ttk.Button(buttons, text='登记本阶段计划已核对', command=record)
        submit.pack(side='left', padx=4)
    elif decision['action'] in {'generation', 'repair-plan', 'choose-mixed-sources'}:
        for label, selected in [('编辑主题与规格', 'brief'), ('生成任务与参考', 'generation-plan')]:
            if selected in decision['editable_layers']:
                ttk.Button(buttons, text=label, command=lambda key=selected: edit_layer(key)).pack(side='left', padx=4)
    if decision['action'] in {'generation', 'reconcile'} and open_tasks:
        ttk.Button(buttons, text='打开任务执行面板', command=open_tasks).pack(side='left', padx=4)
    if decision['action'] in {'import-video', 'choose-mixed-sources'} and import_video:
        ttk.Button(buttons, text='导入本地视频', command=import_video).pack(side='left', padx=4)
    if decision['action'] == 'import-gif' and import_gif:
        ttk.Button(buttons, text='视频转 GIF', command=lambda: import_gif(False)).pack(side='left', padx=4)
        ttk.Button(buttons, text='静帧转 GIF', command=lambda: import_gif(True)).pack(side='left', padx=4)
    ttk.Button(buttons, text='关闭', command=win.destroy).pack(side='right', padx=4)

    def destroyed(event):
        if event.widget == win and scheduled[0] is not None:
            win.after_cancel(scheduled[0]);scheduled[0] = None
    win.bind('<Destroy>', destroyed, add='+')
    return win
