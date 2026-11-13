"""Common price fields plus editable conditional tiers, sharing schema validation."""
import copy
import math
import tkinter as tk
from . import manager_lifecycle as ui
from tkinter import ttk, messagebox

from .catalog.presentation import OPERATIONS, conditions, rates
from .config.storage import ConfigError
from .manager_forms import Fields, PRICES, converted


class Prices(Fields):
    def __init__(self, book, value):
        initial = copy.deepcopy(value)
        self.tiers = initial.get('pricing', {}).pop('tiers', [])
        super().__init__(book, '价格', initial, PRICES,
            '展示价与预算价分开，币种需明确；按次与按秒同时填写会相加。条件档位单独编辑，重叠报价不会任意取值。')
        page = ttk.Frame(self.section, padding=12)
        self.section.add(page, text='条件档位')
        ttk.Label(page,text='档位按操作、分辨率、画幅和时长匹配；同时匹配多档时估算保持未知。',wraplength=650).pack(anchor='w',pady=(0,10))
        self.table = ttk.Treeview(page,columns=('when','rate'),show='headings',selectmode='browse',height=12)
        for key,title,width in [('when','适用条件',430),('rate','费率（使用常用字段中的预算币种）',240)]:
            self.table.heading(key,text=title);self.table.column(key,width=width,minwidth=90)
        self.table.pack(fill='both',expand=True)
        self.table.bind('<Double-1>',lambda _:self.edit_selected())
        actions=ttk.Frame(page);actions.pack(fill='x',pady=12)
        for label,fn in [('新增档位',lambda:self.edit()),('编辑所选',self.edit_selected),('移除所选',self.remove_selected)]:
            ttk.Button(actions,text=label,command=fn).pack(side='left',padx=(0,10))
        self.refresh()

    def refresh(self):
        self.table.delete(*self.table.get_children())
        for index,tier in enumerate(self.tiers):
            self.table.insert('','end',iid=str(index),values=(conditions(tier['when']),rates(tier)))

    def edit_selected(self):
        selected=self.table.selection()
        if selected:self.edit(int(selected[0]))

    def remove_selected(self):
        selected=self.table.selection()
        if selected:
            self.tiers.pop(int(selected[0]));self.refresh()

    def edit(self,index=None):
        original=self.tiers[index] if index is not None else {}
        win=tk.Toplevel(self.table)
        win.title('编辑价格档位' if index is not None else '新增价格档位')
        win.geometry('630x535');win.transient(self.table.winfo_toplevel());win.grab_set()
        frame=ttk.Frame(win,padding=18);frame.pack(fill='both',expand=True)
        variables={}
        spec=[('operation','操作（空白表示不限定）','text'),('resolution','分辨率（空白表示不限定）','text'),
            ('aspect_ratio','画幅（空白表示不限定）','text'),('minimum_seconds','最少秒数（可空）','number'),
            ('maximum_seconds','最多秒数（可空）','number'),('per_request','每次 / 每张金额（可为 0）','number'),
            ('per_second','每秒金额（可为 0）','number')]
        for row,(key,label,kind) in enumerate(spec):
            raw=original.get(key, '') if key.startswith('per_') else original.get('when',{}).get(key,'')
            var=ui.StringVar(frame,value=str(raw));variables[key]=var
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',padx=(0,14),pady=9)
            widget=ttk.Combobox(frame,textvariable=var,values=('',*OPERATIONS),state='readonly') if key=='operation' else ttk.Entry(frame,textvariable=var)
            widget.grid(row=row,column=1,sticky='ew',pady=9)
        frame.columnconfigure(1,weight=1)
        ttk.Label(frame,text='留空表示无该条件；0 是明确的零费率。生效时间、币种和取整仍填写在常用字段。',wraplength=560).grid(row=len(spec),column=0,columnspan=2,sticky='w',pady=10)
        def apply():
            try:
                tier=self.tier({k:v.get() for k,v in variables.items()})
                if index is None:self.tiers.append(tier)
                else:self.tiers[index]=tier
                self.refresh();win.destroy()
            except (ConfigError,ValueError) as exc:messagebox.showerror('档位未保存',str(exc),parent=win)
        ttk.Button(frame,text='应用档位',command=apply).grid(row=len(spec)+1,column=0,columnspan=2,pady=12)
        from .manager_drafts import DraftGuard
        DraftGuard(win,label='价格档位（尚未应用到型号表单）',scope='configuration')
        return win

    @staticmethod
    def tier(values):
        tier={'when':{}}
        for key,raw in values.items():
            value=converted(raw,'number' if key in {'minimum_seconds','maximum_seconds','per_request','per_second'} else 'text')
            if value=='':continue
            if isinstance(value,(int,float)) and (not math.isfinite(value) or value<0):
                raise ConfigError('秒数和金额必须是有限的非负数')
            (tier if key.startswith('per_') else tier['when'])[key]=value
        if not any(k in tier for k in ('per_request','per_second')):
            raise ConfigError('至少填写每次或每秒费率；允许明确的 0')
        when=tier['when']
        if when.get('minimum_seconds',0)>when.get('maximum_seconds',float('inf')):
            raise ConfigError('最少秒数不能超过最多秒数')
        return tier

    def read(self):
        result=super().read()
        if 'tiers' in result.get('pricing',{}):
            raise ConfigError('条件档位已有专用表单，请移除高级页中的重复 tiers')
        if self.tiers:result.setdefault('pricing',{})['tiers']=copy.deepcopy(self.tiers)
        return result
