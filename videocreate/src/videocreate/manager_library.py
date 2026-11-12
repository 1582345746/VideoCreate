"""Local asset cards and explicit snapshot imports for the manager."""
import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, simpledialog

from . import asset_library as library
from .config.storage import ConfigError
from .planning.project import load_project

KIND_NAMES = {'character': '角色', 'scene': '场景', 'prop': '道具', 'voice': '声音'}


def open_panel(manager):
    win, book, page = manager.dialog('跨项目素材库')
    win.geometry('1020x760')
    book.tab(0, text='素材与版本')
    store = manager.path.parent
    bar = ttk.Frame(page); bar.pack(fill='x')
    query = tk.StringVar()
    ttk.Label(bar, text='搜索名称 / 标签 / 说明').pack(side='left')
    ttk.Entry(bar, textvariable=query).pack(side='left', fill='x', expand=True, padx=8)
    tree = ttk.Treeview(page, columns=('title', 'kind', 'version', 'media'), show='headings', height=10)
    for key, title, width in [('title', '名称', 320), ('kind', '类型', 90), ('version', '版本', 300), ('media', '素材数', 80)]:
        tree.heading(key, text=title); tree.column(key, width=width)
    tree.pack(fill='both', expand=True, pady=10)
    detail = tk.Text(page, height=10, wrap='word', font=('Microsoft YaHei UI', 10))
    detail.pack(fill='both', expand=True)
    note = tk.StringVar(value='导入会复制所选版本。卡片与素材保留说明，不继承其他项目的内容审核。')
    ttk.Label(page, textvariable=note, wraplength=940).pack(anchor='w', pady=10)
    rows = {}

    def choose():
        selected = tree.selection()
        if not selected:
            raise ConfigError('请先选择一个素材版本')
        return rows[selected[0]]

    def show(_=None):
        if not tree.selection():
            return
        try:
            row = choose()
            # Verifies original bytes only on selection, not on every search keystroke.
            result = library.describe(store, row['library_id'], row['version'])
            payload = result['payload']
            text = payload['descriptor']['description'] + '\n\n备注：' + payload['notes']
            text += '\n固定特征：' + '；'.join(payload['descriptor'].get('invariants', []))
            text += '\n\n' + json.dumps({'素材': payload['media'], '版本': row['version'], '状态': '未审核'}, ensure_ascii=False, indent=2)
            detail.configure(state='normal'); detail.delete('1.0', 'end'); detail.insert('1.0', text); detail.configure(state='disabled')
        except (ConfigError, OSError, ValueError) as exc:
            manager.error(exc)

    def refresh():
        result = library.catalog(store, query=query.get())
        rows.clear(); tree.delete(*tree.get_children())
        for n, row in enumerate(result['items']):
            rows[str(n)] = row
            tree.insert('', 'end', iid=str(n), values=(row['title'], KIND_NAMES[row['kind']], row['version'][:16], row['media_count']))
        note.set(f"共 {len(rows)} 个版本；{len(result['unavailable'])} 个记录不可读取。导入复制快照，已存在的角色不会被覆盖。")
        if result['unavailable']:
            detail.configure(state='normal'); detail.delete('1.0', 'end')
            detail.insert('1.0', json.dumps(result['unavailable'], ensure_ascii=False, indent=2)); detail.configure(state='disabled')

    def add():
        folder = filedialog.askdirectory(parent=win, title='选择素材来源 v3 项目')
        if not folder:
            return
        try:
            assets = load_project(Path(folder))['director']['assets']
            if not assets:
                raise ConfigError('该项目还没有角色、道具、场景或声音卡片')
            picker = tk.Toplevel(win); picker.title('保存到素材库'); picker.geometry('680x450')
            pane = ttk.Frame(picker, padding=18); pane.pack(fill='both', expand=True)
            labels = [a['id'] + ' · ' + KIND_NAMES[a['kind']] for a in assets]
            asset = ttk.Combobox(pane, values=labels, state='readonly'); asset.pack(fill='x'); asset.current(0)
            fields = {}
            for key, title in [('id', '素材库 ID（小写英文、数字、横线）'), ('title', '展示名称'), ('tags', '标签（中文逗号分隔）'), ('notes', '备注')]:
                ttk.Label(pane, text=title).pack(anchor='w', pady=(10, 0))
                fields[key] = tk.StringVar(); ttk.Entry(pane, textvariable=fields[key]).pack(fill='x')
            def save():
                try:
                    aid = assets[asset.current()]['id']
                    value = library.publish(Path(folder), store, aid, fields['id'].get().strip(),
                        title=fields['title'].get().strip() or aid,
                        tags=[t.strip() for t in fields['tags'].get().replace(',', '，').split('，') if t.strip()], notes=fields['notes'].get())
                    refresh(); note.set('已保存版本：' + value['version'][:16]); picker.destroy()
                except (ConfigError, OSError, ValueError) as exc:
                    manager.error(exc)
            ttk.Button(pane, text='复制素材并保存新版本', command=save).pack(pady=18)
        except (ConfigError, OSError, ValueError) as exc:
            manager.error(exc)

    def import_selected():
        try:
            row = choose()
            folder = filedialog.askdirectory(parent=win, title='选择导入目标 v3 项目')
            if not folder:
                return
            aid = simpledialog.askstring('项目素材 ID', '输入新素材 ID；不会覆盖已有素材。', parent=win, initialvalue=row['library_id'])
            if not aid:
                return
            result = library.import_asset(Path(folder), store, row['library_id'], row['version'], aid)
            note.set('已导入快照：' + result['asset_id'] + '。请在分镜中明确引用；不会自动提交生成。')
        except (ConfigError, OSError, ValueError) as exc:
            manager.error(exc)

    ttk.Button(bar, text='搜索 / 刷新', command=refresh).pack(side='left')
    actions = ttk.Frame(page); actions.pack(fill='x')
    ttk.Button(actions, text='从项目保存素材', command=add).pack(side='left', padx=5)
    ttk.Button(actions, text='导入所选版本到项目', command=import_selected).pack(side='left', padx=5)
    tree.bind('<<TreeviewSelect>>', show)
    refresh()
    return win
