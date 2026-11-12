"""Production, imported-source and task panels for the local manager."""
import json
import queue as queue_module
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import webbrowser

from . import production
from .config.storage import ConfigError

STATUS = {'ready':'可继续', 'complete':'已完成', 'pending':'待执行', 'blocked':'有阻塞',
    'available':'本地可用',
    'stale':'内容已变更', 'skipped':'本项目不适用', 'not-submitted':'未提交',
    'queued':'排队中', 'in_progress':'生成中', 'read_pending':'等待恢复读取',
    'submission_unknown':'提交结果未知', 'completed':'生成完成', 'failed':'失败'}


def open_panel(manager, root):
    root = Path(root).resolve()
    win, book, steps = manager.dialog('项目与制作步骤')
    win.geometry('1040x760')
    book.tab(0, text='制作步骤')
    title = tk.StringVar()
    ttk.Label(steps, textvariable=title, font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w')
    ttk.Label(steps, text=str(root), wraplength=920).pack(anchor='w', pady=8)
    table = ttk.Treeview(steps, columns=('name','status','reason'), show='headings', height=11)
    for key, text, width in [('name','制作步骤',180),('status','状态',120),('reason','说明',600)]:
        table.heading(key,text=text);table.column(key,width=width)
    table.pack(fill='both',expand=True)
    next_step = tk.StringVar()
    ttk.Label(steps,textvariable=next_step,wraplength=920).pack(anchor='w',pady=12)
    tasks = ttk.Frame(book,padding=16);book.add(tasks,text='任务与路线')
    queue = ttk.Treeview(tasks,columns=('job','status','route','content'),show='headings',height=15)
    for key,text,width in [('job','任务 / 来源',160),('status','状态',140),('route','原始路线 / 本地路径',390),('content','内容审核',150)]:
        queue.heading(key,text=text);queue.column(key,width=width)
    queue.pack(fill='both',expand=True)
    budget = tk.StringVar();ttk.Label(tasks,textvariable=budget,wraplength=920).pack(anchor='w',pady=10)
    evidence = manager.json_tab(book,'版本与影响',{})
    metrics = manager.json_tab(book,'制作统计',{})
    message = tk.StringVar()
    ttk.Label(win,textvariable=message,wraplength=980).pack(anchor='w',padx=18,pady=5)
    actions = ttk.Frame(win,padding=12);actions.pack(fill='x')
    def refresh():
        try:
            result=production.status(root)
            title.set(result['title'])
            table.delete(*table.get_children());queue.delete(*queue.get_children())
            for step in result['stages']:
                table.insert('','end',values=(step['name'],STATUS.get(step['status'],step['status']),
                    step.get('reason','') or ', '.join(step.get('blocked_by',[]))))
            for item in result['jobs']:
                queue.insert('','end',values=(item['job_id'],STATUS.get(item['status'],item['status']),
                    item.get('binding') or '尚未提交',item['content_status']))
            for item in result.get('local_sources',[]):
                queue.insert('','end',values=(item['source_id'],STATUS.get(item['status'],item['status']),
                    '本地：'+item['path'],item['content_status']))
            for item in result.get('local_gifs',[]):
                queue.insert('','end',values=(item['gif_id'],STATUS.get(item['status'],item['status']),
                    '本地 GIF：'+item.get('artifact',{}).get('path',item.get('error','待转换')),item['content_status']))
            next_step.set('下一步：'+(result['next'] or {}).get('name','查看交付清单'))
            b=result['budget']
            budget.set(f"已记录 {b['requests']} 次创建；报价未知 {b['unknown_price_requests']} 次；实际账单待核实 {b['actual_unverified_requests']} 次。")
            evidence.configure(state='normal');evidence.delete('1.0','end')
            evidence.insert('1.0',json.dumps({'impact':result['impact'],'budget':b,'review':result['review']},ensure_ascii=False,indent=2))
            evidence.configure(state='disabled')
            from .production_metrics import report
            metrics.configure(state='normal');metrics.delete('1.0','end')
            if result['ok']:
                measured = report(root)
                seconds = measured['seconds']
                header = ('纯图 / GIF：'+json.dumps(measured['images'],ensure_ascii=False)+'\n\n') if 'images' in measured else (
                    f"已生成（可核实）：{seconds['generated_known']:.2f} 秒\n"
                    f"已保留（当前素材可用）：{seconds['retained_available_playback']:.2f} 秒\n"
                    f"源片审核通过的保留时长：{seconds['reviewed_usable_playback']} 秒\n"
                    "源片审核不代表成片已验收；以下保留样本范围、费用未知项与分币种明细。\n\n")
                metrics.insert('1.0',header+json.dumps(measured,ensure_ascii=False,indent=2))
            else:
                metrics.insert('1.0','完成导入或修复计划后可查看有效时长统计。\n\n'+json.dumps(result['errors'],ensure_ascii=False,indent=2))
            metrics.configure(state='disabled')
            message.set('此面板直接读取项目文件；查看与导出不提交生成。')
        except (ConfigError,OSError,ValueError) as exc:
            manager.error(exc)
    def reading():
        try:
            result=production.script_export(root)
            message.set('已导出剧本阅读稿：'+result['reading_copy'])
        except (ConfigError,OSError,ValueError) as exc:manager.error(exc)
    def review():
        try:
            from . import image_production
            bundle=production.load_project(root)
            if image_production.is_image(bundle):
                result=image_production.page(root,bundle)
            else:
                from .review.page import export
                result=export(root)
            webbrowser.open(Path(result['page']).as_uri())
            message.set('已打开图片 / GIF 审核页；用 review image 记录生成图、review gif 记录本地动图，动图需完整播放。' if image_production.is_image(bundle) else '已打开本地审片页。完成观察后导出记录，用 review apply 导入校验。')
        except (ConfigError,OSError,ValueError) as exc:manager.error(exc)
    def import_local():
        from tkinter import filedialog
        from .manager_forms import Fields
        path=filedialog.askopenfilename(parent=win,title='选择已有本地视频',filetypes=[('视频','*.mp4 *.mov *.mkv *.webm')])
        if not path:return
        dialog,form_book,basic=manager.dialog('导入本地视频（仅剪辑 / 混合项目）')
        ttk.Label(basic,text=path,wraplength=700).pack(anchor='w',pady=12)
        form=Fields(form_book,'保留区间',{'source_id':'source-001','start':0},
            [('source_id','来源标识（唯一 ASCII）','text'),('start','开始秒','number'),
             ('end','结束秒（留空至片尾）','number'),('shot_id','已有镜头 ID（混合项目可选，留空新建）','text'),
             ('description','实际画面用途（新建镜头）','multiline')],
             '保留原视频和音轨，只登记本地副本；不发送模型请求。源片和剪辑仍需实际审片。')
        channel=queue_module.Queue()
        busy=[False]
        note=tk.StringVar()
        ttk.Label(dialog,textvariable=note,wraplength=700).pack(pady=6)
        def finish():
            if not dialog.winfo_exists():return
            try:
                ok,result=channel.get_nowait()
            except queue_module.Empty:
                dialog.after(100,finish);return
            busy[0]=False
            submit.configure(state='normal')
            if not ok:
                note.set('导入失败；请检查原素材和保留区间。')
                manager.error(result);return
            if win.winfo_exists():
                message.set('已登记本地来源：'+result['source']['id']+'；零模型创建，内容待审。')
                refresh()
            dialog.destroy()
        def apply():
            if busy[0]:return
            try:
                values=form.read()
            except (ConfigError,ValueError) as exc:
                manager.error(exc);return
            busy[0]=True
            submit.configure(state='disabled')
            note.set('正在复制、校验哈希并完整解码；大文件可能需要较长时间。')
            def worker():
                try:
                    from .local_sources import import_clip
                    result=import_clip(root,Path(path),source_id=values.get('source_id',''),
                        start=values.get('start',0),end=values.get('end'),description=values.get('description',''),
                        shot_id=values.get('shot_id') or None)
                    channel.put((True,result))
                except Exception as exc:channel.put((False,exc))
            # Finish a started local transaction even if the application window closes.
            threading.Thread(target=worker,daemon=False).start()
            dialog.after(100,finish)
        submit=ttk.Button(dialog,text='导入并加入时间线',command=apply)
        submit.pack(pady=12)
        dialog.protocol('WM_DELETE_WINDOW',lambda:note.set('正在导入，请等待完成。') if busy[0] else dialog.destroy())
    def edit_layer(layer,assets_only=False):
        try:
            from .manager_authoring import open_editor
            open_editor(manager,root,layer,completed=lambda _:refresh() if win.winfo_exists() else None,assets_only=assets_only)
        except (ConfigError,OSError,ValueError) as exc:manager.error(exc)
    def outline():
        try:
            from .authoring import outline as export
            result=export(root);message.set('已导出主题与大纲阅读稿：'+result['reading_copy'])
        except (ConfigError,OSError,ValueError) as exc:manager.error(exc)
    for text,fn in [('刷新状态',refresh),('编辑主题与规格',lambda:edit_layer('brief')),
                    ('导出剧本阅读稿',reading),('打开实际审片页',review)]:
        ttk.Button(actions,text=text,command=fn).pack(side='left',padx=6)
    bundle=production.load_project(root)
    if 'animation' not in bundle:
        asset_actions=ttk.Frame(win,padding=(12,0,12,8));asset_actions.pack(fill='x')
        ttk.Button(asset_actions,text='角色与项目素材',command=lambda:edit_layer('director',assets_only=True)).pack(side='left',padx=6)
        if bundle['brief'].get('workflow_profile')!='edit-only':
            ttk.Button(asset_actions,text='生成任务与参考',command=lambda:edit_layer('generation-plan')).pack(side='left',padx=6)
    if bundle['brief'].get('workflow_profile') not in {'edit-only','image-only','gif-only','gif-local'} and 'animation' not in bundle:
        outline_actions=ttk.Frame(win,padding=(12,0,12,12));outline_actions.pack(fill='x')
        ttk.Button(outline_actions,text='编辑故事大纲',command=lambda:edit_layer('story')).pack(side='left',padx=6)
        ttk.Button(outline_actions,text='编辑剧本与分镜',command=lambda:edit_layer('director')).pack(side='left',padx=6)
        ttk.Button(outline_actions,text='导出主题与大纲',command=outline).pack(side='left',padx=6)
    if production.load_project(root)['brief'].get('workflow_profile') in {'edit-only','mixed-video'}:
        ttk.Button(actions,text='导入本地视频',command=import_local).pack(side='left',padx=6)
    if production.load_project(root)['brief'].get('workflow_profile') in {'gif-only','gif-local'}:
        from .manager_gifs import open_form
        def gif_complete(result):
            if win.winfo_exists():refresh()
        ttk.Button(actions,text='视频转 GIF',command=lambda:open_form(manager,root,parent=win,completed=gif_complete)).pack(side='left',padx=6)
        ttk.Button(actions,text='静帧转 GIF',command=lambda:open_form(manager,root,frames=True,parent=win,completed=gif_complete)).pack(side='left',padx=6)
    refresh()
    return win
