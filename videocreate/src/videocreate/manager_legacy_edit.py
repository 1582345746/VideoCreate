"""Migration preview bound to actual source files; no in-place rewrite."""
import json
from pathlib import Path
from tkinter import filedialog,ttk
from . import legacy_edit_import
from . import manager_lifecycle as ui
from .manager_screenplay import ExactFields


def open_form(manager,*,source=None,completed=lambda result:None):
    if source is None:source=filedialog.askdirectory(parent=manager.window,title='选择含 edit-plan.json 的旧项目')
    if not source:return
    win,book,basic=manager.dialog('旧原生剪辑迁移到 v3')
    book.pack_forget();footer=ttk.Frame(win,padding=12);footer.pack(side='bottom',fill='x')
    book.pack(fill='both',expand=True,padx=18,pady=14)
    form=ExactFields(book,'迁移位置',{'source':str(source),'destination':str(Path(source).with_name(Path(source).name+'-v3'))},
        [('source','旧项目目录','text'),('destination','新项目目录（必须不存在）','text')],
        '读取旧原生 edit-plan v1/v2，预览实际文件、字段映射与差异，再复制到独立项目。'
        '原计划、任务和成片保留；不继承任务账本及审核。字幕样式、响度和编码可能不同，请迁移后渲染对照。')
    report_box=manager.json_tab(book,'迁移预览',{})
    state={'report':None};call=ui.BackgroundCall(win);note=ui.StringVar(win)
    ttk.Label(footer,textvariable=note,wraplength=760).pack(anchor='w')
    def failed(error):note.set('迁移未完成：'+str(error));manager.error(error)
    def described(report):
        state['report']=report;report_box.configure(state='normal');report_box.delete('1.0','end')
        report_box.insert('1.0',json.dumps(report,ensure_ascii=False,indent=2));report_box.configure(state='disabled')
        note.set('预览完成；核对映射和差异后创建新项目。修改位置或源文件需重新预览。')
    def describe():
        if call.busy:return
        try:
            value=form.read();state['report']=None;note.set('正在读取文件哈希和媒体信息，不复制或生成。')
            call.start(legacy_edit_import.preview,Path(value.get('source','')),Path(value.get('destination','')),
                       completed=described,failed=failed)
        except Exception as exc:failed(exc)
    def imported(result):note.set('新项目已建立：'+result['project']);completed(result)
    def apply():
        if call.busy:return
        try:
            value=form.read();report=state['report']
            if (not report or str(Path(value.get('source','')).resolve())!=report['source']
                    or str(Path(value.get('destination','')).resolve())!=report['destination']):
                raise ValueError('请先预览当前源目录和目标目录')
            note.set('正在复制并完整解码素材；关闭窗口后已开始的本地操作继续完成。')
            call.start(legacy_edit_import.execute,Path(report['source']),Path(report['destination']),
                       expected_token=report['preview_token'],completed=imported,failed=failed)
        except Exception as exc:failed(exc)
    ttk.Button(footer,text='预览迁移',command=describe).pack(side='left',padx=5)
    ttk.Button(footer,text='按此预览创建 v3 项目',command=apply).pack(side='left',padx=5)
    book.select(form.section)
    win.migration_form,win.migration_call,win.migration_state=form,call,state
    return win
