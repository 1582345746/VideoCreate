"""Desktop controls for the local reference-file service."""
import copy
import json
import tkinter as tk
from . import manager_lifecycle as ui
import urllib.request
from pathlib import Path
from tkinter import ttk, filedialog

from . import media_server
from .config.schema import validate_config
from .config.storage import ConfigError


def _check_public(store_root, base):
    local = media_server.status(store_root)
    if not local['running']:
        raise ConfigError('请先启动本机服务')
    from .media_references import public_url
    public_url(base, resolve=True)
    try:
        with urllib.request.urlopen(base.rstrip('/') + '/health', timeout=20) as response:
            matched = response.status == 204 and response.headers.get('X-VideoCreate-Instance') == local['instance_id']
    except OSError:
        raise ConfigError('公网尚未到达本机服务；核对转发全部路径，Windows 目标 127.0.0.1:'
            + str(local['port']) + '，Docker 目标 host.docker.internal:' + str(local['port'])) from None
    if not matched:
        raise ConfigError('公网响应与当前本机服务不一致；请核对域名映射')
    return '公网 HTTPS 已到达当前素材服务；文件直链还需分别校验。'


def open_panel(manager):
    win, book, page = manager.dialog('本机素材与 HTTPS 直链')
    win.geometry('1000x740')
    book.tab(0, text='素材文件服务')
    options = media_server.settings(manager.value)
    url = ui.StringVar(win, value=options['public_base_url'])
    port = ui.StringVar(win, value=str(options['port']))
    form = ttk.Frame(page)
    form.pack(fill='x')
    ttk.Label(form, text='公网 HTTPS 域名').grid(row=0, column=0, sticky='w', pady=6)
    ttk.Entry(form, textvariable=url, width=60).grid(row=0, column=1, sticky='ew', padx=12)
    ttk.Label(form, text='本机端口').grid(row=1, column=0, sticky='w', pady=6)
    ttk.Entry(form, textvariable=port, width=12).grid(row=1, column=1, sticky='w', padx=12)
    form.columnconfigure(1, weight=1)
    ttk.Label(page, text='穿透运行在 Windows：HTTP 127.0.0.1:端口；运行在 Docker：HTTP host.docker.internal:端口。'
              '公网使用 HTTPS 并转发全部路径。', wraplength=910).pack(anchor='w', pady=(8, 0))
    note = ui.StringVar(win, value='仅提供选定文件。')
    ttk.Label(page, textvariable=note, wraplength=910).pack(anchor='w', pady=12)
    tree = ttk.Treeview(page, columns=('kind', 'bytes', 'expiry', 'status'), show='headings', height=9)
    for key, label, width in [('kind', '素材类型', 100), ('bytes', '大小（字节）', 140),
                              ('expiry', '链接到期时间', 260), ('status', '状态', 160)]:
        tree.heading(key, text=label)
        tree.column(key, width=width)
    tree.pack(fill='both', expand=True, pady=8)
    details = tk.Text(page, height=7, wrap='word', font=('Microsoft YaHei UI', 10))
    details.pack(fill='x', pady=8)
    details.insert('1.0', '关闭管理器不会停止已启动的素材服务。生成期间请保持电脑、服务与内网穿透运行。\n'
                        '链接可被上游直接读取；有效期和撤销只控制后续读取，不能撤回已经取得的文件。')
    details.configure(state='disabled')
    background = ui.BackgroundCall(win)
    config_path, store_root = manager.path, manager.path.parent
    buttons = []

    def refresh():
        from datetime import datetime
        tree.delete(*tree.get_children())
        for item in media_server.published(manager.path.parent):
            status = '已撤销' if item['revoked'] else '已过期' if item['expired'] else '可用'
            tree.insert('', 'end', iid=item['publication_id'], values=(item['kind'], item['bytes'],
                datetime.fromtimestamp(item['expires_at']).strftime('%Y-%m-%d %H:%M:%S'), status))
        state = media_server.status(manager.path.parent)
        note.set(('本机服务运行中 · ' if state['running'] else '本机服务未运行 · ') +
                 '127.0.0.1:' + str(state.get('port', options['port'])))

    def task(function, *arguments, completed, **options):
        if background.busy:
            return
        for button in buttons:
            button.configure(state='disabled')
        def finish(callback, result):
            for button in buttons:
                button.configure(state='normal')
            callback(result)
        background.start(function, *arguments, **options,
            completed=lambda result: finish(completed, result),
            failed=lambda error: finish(manager.error, error))

    def save_settings():
        try:
            value = copy.deepcopy(manager.value)
            value['local_media_server'] = {'port': int(port.get()), 'public_base_url': url.get().strip().rstrip('/'),
                'max_link_seconds': options['max_link_seconds']}
            errors = validate_config(value)
            if errors:
                raise ConfigError('; '.join(errors))
            manager.value = value
            manager.changed()
            if manager.save():
                options.update(media_server.settings(manager.value))
                refresh()
        except (ConfigError, ValueError, OSError) as exc:
            manager.error(exc)

    def check_public():
        base = media_server.settings(manager.record['config'])['public_base_url']
        task(_check_public, store_root, base, completed=note.set)

    def publish():
        source = filedialog.askopenfilename(parent=win, title='选择要提供直链的素材', filetypes=[
            ('图片、视频、音频', '*.png *.jpg *.jpeg *.webp *.mp4 *.mp3 *.wav')])
        if not source:
            return
        picker = tk.Toplevel(win)
        picker.title('生成素材链接')
        picker.geometry('640x320')
        inner = ttk.Frame(picker, padding=20)
        inner.pack(fill='both', expand=True)
        ttk.Label(inner, text=Path(source).name, wraplength=580).pack(anchor='w')
        kind = ui.StringVar(picker, value='video' if Path(source).suffix.lower()=='.mp4' else
                             'audio' if Path(source).suffix.lower() in {'.mp3','.wav'} else 'image')
        ttk.Combobox(inner, values=('image','video','audio'), textvariable=kind, state='readonly').pack(fill='x', pady=10)
        hours = ui.StringVar(picker, value='4')
        ttk.Label(inner, text='有效期（小时）').pack(anchor='w')
        ttk.Entry(inner, textvariable=hours).pack(fill='x', pady=10)
        def create():
            try:
                lifetime = float(hours.get()) * 3600
                selected_kind = kind.get()
                if not media_server.status(manager.path.parent)['running']:
                    raise ConfigError('请先启动本机素材服务')
                current = media_server.settings(manager.record['config'])
                picker.destroy()
                def ready(item):
                    refresh()
                    result = tk.Toplevel(win)
                    result.title('素材直链')
                    result.geometry('760x200')
                    frame = ttk.Frame(result, padding=20)
                    frame.pack(fill='both', expand=True)
                    ttk.Label(frame, text='链接仅在本窗口显示；关闭后可重新生成。请勿公开转发。').pack(anchor='w')
                    field = ttk.Entry(frame)
                    field.pack(fill='x', pady=12)
                    field.insert(0, item['url'])
                    field.configure(state='readonly')
                    def copy_link():
                        result.clipboard_clear()
                        result.clipboard_append(item['url'])
                    ttk.Button(frame, text='复制链接', command=copy_link).pack(anchor='w')
                task(media_server.publish, store_root, Path(source), kind=selected_kind,
                    public_base_url=current['public_base_url'], lifetime_seconds=lifetime,
                    maximum_seconds=current['max_link_seconds'], completed=ready)
            except (ConfigError, ValueError, OSError) as exc:
                manager.error(exc)
        ttk.Button(inner, text='仅为这个文件生成链接', command=create).pack(pady=10)

    def revoke():
        chosen = tree.selection()
        if chosen:
            media_server.revoke(manager.path.parent, chosen[0])
            refresh()

    bar = ttk.Frame(page)
    bar.pack(fill='x', pady=8)
    for label, action in [('保存域名与端口', save_settings),
        ('启动服务', lambda: task(media_server.start, config_path, completed=lambda _: refresh())),
        ('停止服务', lambda: task(media_server.stop, store_root, completed=lambda _: refresh())),
        ('检查公网', check_public), ('生成文件直链', publish), ('撤销所选链接', revoke), ('刷新', refresh)]:
        button = ttk.Button(bar, text=label, command=action)
        button.pack(side='left', padx=(0, 6))
        buttons.append(button)
    refresh()
    return win
