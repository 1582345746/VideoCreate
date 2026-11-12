"""Readable side-by-side binding comparison; no selection changes or generation."""
import tkinter as tk
from tkinter import ttk

from .catalog.presentation import compare, OPERATIONS
from .config.storage import ConfigError


def open_panel(manager, identities):
    # Validate the selected count before opening an empty dialog.
    compare(manager.value, identities)
    win, book, basic = manager.dialog('型号并排比较')
    win.geometry('1160x800')
    book.forget(0)
    page = ttk.Frame(book, padding=12)
    book.add(page, text='报价与参数')
    controls = ttk.Frame(page)
    controls.pack(fill='x', pady=(0,10))
    operation = tk.StringVar(value='text-to-video' if manager.value['models'][manager.value['bindings'][identities[0]]['model']]['kind']=='video' else 'text-to-image')
    seconds = tk.StringVar(value='5')
    resolution = tk.StringVar(value=manager.value['defaults'].get('resolution','720p'))
    ratio = tk.StringVar(value=manager.value['defaults'].get('aspect_ratio','16:9'))
    for label,var,options,width in [('操作',operation,list(OPERATIONS),23),('秒数',seconds,None,6),
            ('分辨率',resolution,None,9),('画幅',ratio,None,8)]:
        ttk.Label(controls,text=label).pack(side='left',padx=(0,5))
        widget=ttk.Combobox(controls,textvariable=var,values=options,state='readonly',width=width) if options else ttk.Entry(controls,textvariable=var,width=width)
        widget.pack(side='left',padx=(0,12))
    ttk.Label(page,text='统一参数仅用于估算与范围比较。参考素材、账户凭据和完整请求仍由生成预检核对；实际账单另计。',wraplength=1080).pack(anchor='w',pady=(0,8))
    frame=ttk.Frame(page)
    frame.pack(fill='both',expand=True)
    canvas=tk.Canvas(frame,highlightthickness=0,background='#ffffff')
    vertical=ttk.Scrollbar(frame,orient='vertical',command=canvas.yview)
    horizontal=ttk.Scrollbar(frame,orient='horizontal',command=canvas.xview)
    canvas.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
    frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
    canvas.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
    inner=ttk.Frame(canvas)
    canvas.create_window((0,0),window=inner,anchor='nw')
    inner.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
    win.bind('<MouseWheel>',lambda event:canvas.yview_scroll(-int(event.delta/120),'units'))
    note=tk.StringVar()
    ttk.Label(page,textvariable=note,wraplength=1080,foreground='#64748b').pack(anchor='w',pady=(10,0))
    def refresh():
        try:
            result=compare(manager.value,identities,store_root=manager.path.parent,
                scenario={'operation':operation.get(),'seconds':float(seconds.get()),'resolution':resolution.get().strip(),'aspect_ratio':ratio.get().strip()})
            for child in inner.winfo_children():child.destroy()
            cards=result['cards']
            for col,title in enumerate(['比较项目',*[c['name'] for c in cards]]):
                tk.Label(inner,text=title,wraplength=150 if col==0 else 260,anchor='w',justify='left',
                    font=('Microsoft YaHei UI',11,'bold'),background='#dce9f6',padx=12,pady=14).grid(row=0,column=col,sticky='nsew')
                inner.columnconfigure(col,minsize=170 if col==0 else 290)
            for row,key in enumerate(cards[0]['fields'],1):
                for col,value in enumerate([key,*[c['fields'].get(key,'不适用') for c in cards]]):
                    tk.Label(inner,text=value,wraplength=150 if col==0 else 260,anchor='nw',justify='left',
                        font=('Microsoft YaHei UI',10),background='#f1f5f9' if row%2 else '#ffffff',
                        foreground='#334155',padx=12,pady=10).grid(row=row,column=col,sticky='nsew')
            note.set(result['note'])
            win.comparison_result=result  # Also inspectable by the offscreen acceptance check.
        except (ConfigError,OSError,ValueError) as exc:manager.error(exc)
    ttk.Button(controls,text='更新估算',command=refresh).pack(side='left')
    refresh()
    return win
