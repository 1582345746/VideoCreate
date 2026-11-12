"""Read-only production and task panels for the local manager."""
import json
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import webbrowser

from . import production
from .config.storage import ConfigError

STATUS = {'ready':'可继续', 'complete':'已完成', 'pending':'待执行', 'blocked':'有阻塞',
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
    for key,text,width in [('job','任务',160),('status','状态',140),('route','原始路线',390),('content','内容审核',150)]:
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
            next_step.set('下一步：'+(result['next'] or {}).get('name','查看交付清单'))
            b=result['budget']
            budget.set(f"已记录 {b['requests']} 次创建；报价未知 {b['unknown_price_requests']} 次；实际账单待核实 {b['actual_unverified_requests']} 次。")
            evidence.configure(state='normal');evidence.delete('1.0','end')
            evidence.insert('1.0',json.dumps({'impact':result['impact'],'budget':b,'review':result['review']},ensure_ascii=False,indent=2))
            evidence.configure(state='disabled')
            from .production_metrics import report
            measured = report(root)
            metrics.configure(state='normal');metrics.delete('1.0','end')
            seconds = measured['seconds']
            metrics.insert('1.0', f"已生成（可核实）：{seconds['generated_known']:.2f} 秒\n"
                f"已保留（当前素材可用）：{seconds['retained_available_playback']:.2f} 秒\n"
                f"源片审核通过的保留时长：{seconds['reviewed_usable_playback']} 秒\n"
                "源片审核不代表成片已验收；以下保留样本范围、费用未知项与分币种明细。\n\n"
                + json.dumps(measured, ensure_ascii=False, indent=2))
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
            from .review.page import export
            result=export(root)
            webbrowser.open(Path(result['page']).as_uri())
            message.set('已打开本地审片页。完成观察后导出记录，用 review apply 导入校验。')
        except (ConfigError,OSError,ValueError) as exc:manager.error(exc)
    for text,fn in [('刷新状态',refresh),('导出剧本阅读稿',reading),('打开实际审片页',review)]:
        ttk.Button(actions,text=text,command=fn).pack(side='left',padx=6)
    refresh()
    return win
