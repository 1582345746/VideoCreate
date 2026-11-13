"""Native edit decisions and a proportional timeline; never dispatch generation."""
import copy
import tkinter as tk
from . import manager_lifecycle as ui
from pathlib import Path
from tkinter import ttk, filedialog

from .config.storage import ConfigError
from .manager_screenplay import ExactFields, OrderedItems, identity
from .timeline_authoring import inspect


def set_field(form,key,value):
    for path,var,kind in form.fields:
        if path==key:var.set(value);return


class FileFields(ExactFields):
    def __init__(self,manager,book,title,value,fields,root,explanation=''):
        super().__init__(book,title,value,fields,explanation)
        self.root=Path(root);self.manager=manager
        page=ttk.Frame(book,padding=12);book.add(page,text='关联本地文件');self.page=page
        ttk.Label(page,text='只关联已保存到项目内的文件；不复制、不上传。渲染时重新检查实际媒体及文件哈希。',wraplength=700).pack(anchor='w',pady=8)
        ttk.Button(page,text='选择项目内文件',command=self.choose).pack(anchor='w')

    def choose(self,source=None):
        try:
            if source is None:source=filedialog.askopenfilename(parent=self.page,initialdir=str(self.root),title='选择项目内文件')
            if not source:return
            from .planning.project import within
            try:relative=Path(source).resolve().relative_to(self.root.resolve()).as_posix()
            except ValueError:raise ConfigError('先将文件导入到项目；此处只关联已有项目内文件') from None
            if not within(self.root,relative).is_file():raise ConfigError('请选择项目内的普通文件')
            set_field(self,'path',relative)
        except (ConfigError,OSError,ValueError) as exc:
            self.manager.error(exc)


class ClipEditor:
    def __init__(self,manager,book,value,root,sources):
        self.sources=sources
        self.form=FileFields(manager,book,'来源映射',value,[('id','剪辑素材 ID','text'),
            ('job_id','生成任务 / 已登记本地来源 ID',tuple(sources)),('path','显式项目内素材路径（生成结果通常留空）','text')],root,
            '生成任务默认读取已选候选；本地来源必须使用登记路径。改变映射不会下载、复制或创建素材。')
        page=ttk.Frame(book,padding=12);book.add(page,text='来源选择')
        ttk.Button(page,text='使用所选来源的默认素材',command=self.match).pack(anchor='w',pady=8)

    def match(self):
        source=self.form.read().get('job_id')
        if source in self.sources:set_field(self.form,'path',self.sources[source].get('path',''))

    def read(self):return self.form.read()


class SubtitleEditor:
    def __init__(self,book,value,segments):
        self.original=copy.deepcopy(value);self.initial='源片区间' if 'segment_id' in value else '成片时间'
        page=ttk.Frame(book,padding=12);book.add(page,text='定位方式')
        self.mode=ui.StringVar(page,value=self.initial)
        ttk.Combobox(page,textvariable=self.mode,values=('源片区间','成片时间'),state='readonly').pack(anchor='w',pady=8)
        ttk.Label(page,text='源片区间随对应片段的排序、裁切及速度映射；成片时间固定在成片秒数。切换方式后填写对应字段，不自动换算。',wraplength=700).pack(anchor='w')
        self.form=ExactFields(book,'字幕',value,[('text','实际听到并核对的字幕','multiline'),
            ('segment_id','片段 ID（源片区间模式）',tuple(segments)),('source_start','源片开始秒','number'),
            ('source_end','源片结束秒','number'),('start','成片开始秒','number'),('end','成片结束秒','number')],
            '按所选定位方式消费字段。原生对白的剧本不等于实际台词；字幕保存不会批准音轨。')

    def read(self):
        value=self.form.read()
        source=self.mode.get()=='源片区间'
        # Retain ignored legacy coordinates exactly until an explicit anchor
        # switch, and never let an inactive field silently choose the mode.
        inactive=('start','end') if source else ('segment_id','source_start','source_end')
        for key in inactive:
            if self.mode.get()==self.initial and key in self.original:value[key]=copy.deepcopy(self.original[key])
            else:value.pop(key,None)
        if source:value.setdefault('segment_id','')
        return value


class TimelineEditor:
    def __init__(self,manager,book,value,root,bundle):
        self.manager=manager;self.book=book;self.original=copy.deepcopy(value)
        sources={job['id']:job for job in bundle['generation-plan']['jobs']}
        sources.update({item['id']:item for item in bundle['generation-plan'].get('local_sources',[])})
        remaining={key:item for key,item in value.items() if key not in {'clips','segments','audio_tracks','subtitles','overlays'}}
        self.spec=ExactFields(book,'成片画布',remaining,[('fps','输出帧率（如 24/1）','text'),
            ('width','画布宽（像素）','integer'),('height','画布高（像素）','integer')],
            '成片规格与模型生成规格分开。输出帧率不是源片采样率，也不会补出真实动作细节。')
        def page(title):
            result=ttk.Frame(book);book.add(result,text=title);return result
        self.clips=OrderedItems(manager,page('剪辑素材'),value['clips'],'素材映射',
            lambda b,v:ClipEditor(manager,b,v,root,sources),lambda items:{'id':identity(items,'clip'),'job_id':''})
        shots=tuple(s['id'] for s in bundle['director']['shots'])
        self.segment_page=page('播放片段')
        def segment(b,v):return ExactFields(b,'裁切与播放',v,[('id','片段 ID（字幕定位使用）','text'),
            ('shot_id','镜头 ID',shots),('clip_id','剪辑素材 ID',tuple(c['id'] for c in self.clips.read())),
            ('source_in','保留源片开始秒','number'),('source_out','保留源片结束秒','number'),
            ('rate','播放速度（缺省 1）','number'),('source_audio','原片声音',('mute','retime','preserve')),
            ('cut_reason','剪辑理由','multiline')],
            '按列表顺序连续播放，区间为 [开始,结束)。静态图片使用开始 0、结束=停留秒数、速度 1、原片静音；独立音轨另接配音。有台词的视频保持自然语速。')
        self.segments=OrderedItems(manager,self.segment_page,value['segments'],'片段',segment,
            lambda items:{'id':identity(items,'seg'),'shot_id':'','clip_id':'','source_in':0,'source_out':1,'rate':1,'source_audio':'mute','cut_reason':''})
        self.audio=OrderedItems(manager,page('独立音轨'),value.get('audio_tracks',[]),'声音事件',
            lambda b,v:FileFields(manager,b,'自然语速音轨',v,[('id','声音事件 ID','text'),
                ('kind','用途',('dialogue','ambience','music','effect')),('clip_id','取自剪辑素材（与文件二选一）',tuple(c['id'] for c in self.clips.read())),
                ('path','项目内声音文件（clip_id 非空时优先素材）','text'),('source_in','原声音开始秒','number'),
                ('source_out','原声音结束秒','number'),('timeline_start','成片进入秒','number'),('gain_db','增益 dB','number')],root,
                '独立音轨保持自然语速；画面重排不移动这里的成片进入时间。与原片声音叠加，请明确静音避免双声。'),
            lambda items:{'id':identity(items,'audio'),'kind':'dialogue','source_in':0,'source_out':1,'timeline_start':0})
        self.subtitles=OrderedItems(manager,page('字幕'),value.get('subtitles',[]),'字幕',
            lambda b,v:SubtitleEditor(b,v,[s['id'] for s in self.segments.read()]),
            lambda items:{'text':'','start':0,'end':1})
        self.overlays=OrderedItems(manager,page('文字与图片叠加'),value.get('overlays',[]),'叠加',
            lambda b,v:FileFields(manager,b,'画面叠加',v,[('id','叠加 ID','text'),('text','文字（与图片路径二选一）','multiline'),
                ('path','项目内图片路径','text'),('start','成片开始秒','number'),('end','成片结束秒','number'),
                ('position','位置',('top','center','bottom'))],root,'叠加进入本地渲染；字幕另存为 SRT，字幕不会自动烧录。'),
            lambda items:{'id':identity(items,'overlay'),'text':'','start':0,'end':1,'position':'bottom'})
        self.graph_page=page('时间线示意');self.note=ui.StringVar(self.graph_page)
        ttk.Label(self.graph_page,text='按当前未保存的编辑绘制比例示意；点击画面片段定位表单。此处没有播放视频或声音。',wraplength=850).pack(anchor='w',padx=12,pady=8)
        ttk.Button(self.graph_page,text='更新时间线示意',command=self.draw).pack(anchor='w',padx=12)
        ttk.Button(self.graph_page,text='刷新素材与片段选项',command=self.refresh_links).pack(anchor='w',padx=12,pady=4)
        self.canvas=tk.Canvas(self.graph_page,height=270,background='#f8fafc',highlightthickness=0)
        self.canvas.pack(fill='x',padx=12,pady=12)
        scroll=ttk.Scrollbar(self.graph_page,orient='horizontal',command=self.canvas.xview)
        scroll.pack(fill='x',padx=12);self.canvas.configure(xscrollcommand=scroll.set)
        ttk.Label(self.graph_page,textvariable=self.note,wraplength=850).pack(anchor='w',padx=12)
        self.draw();book.select(self.graph_page)

    def read(self):
        value=self.spec.read();value.update(clips=self.clips.read(),segments=self.segments.read())
        for key,editor in [('audio_tracks',self.audio),('subtitles',self.subtitles),('overlays',self.overlays)]:
            items=editor.read()
            if items or key in self.original:value[key]=items
        return value

    def select_segment(self,index):
        try:
            self.segments.commit();self.segments.refresh(index);self.book.select(self.segment_page)
        except (ConfigError,ValueError) as exc:self.manager.error(exc)

    def refresh_links(self):
        try:
            self.read()
            for editor in (self.clips,self.segments,self.audio,self.subtitles):editor.refresh(editor.current)
            self.draw()
        except (ConfigError,ValueError) as exc:self.manager.error(exc)

    def draw(self):
        try:report=inspect(self.read())
        except (ConfigError,ValueError) as exc:self.manager.error(exc);return
        self.graph_data=report;self.canvas.delete('all')
        if not report['ok']:
            self.note.set('当前示意不可计算：'+'；'.join(report['errors']));return
        duration=report['duration'];width=max(780,self.canvas.winfo_width()-110);left=70
        self.note.set(f'成片 {duration:.3f} 秒；画面条按源区间 / 速度换算。声音与绝对字幕保持成片定位；保存后仍需渲染和实际审片。')
        def x(seconds):return left+width*seconds/duration if duration else left
        for label,y in [('画面',40),('音轨',100),('字幕',160),('叠加',220)]:self.canvas.create_text(32,y+12,text=label)
        for i,item in enumerate(report['segments']):
            tag='segment-'+str(i)
            self.canvas.create_rectangle(x(item['timeline_start']),40,x(item['timeline_end']),76,fill=('#bfdbfe' if i%2==0 else '#c7d2fe'),tags=(tag,))
            self.canvas.create_text((x(item['timeline_start'])+x(item['timeline_end']))/2,58,text=item['id'],tags=(tag,))
            self.canvas.tag_bind(tag,'<Button-1>',lambda event,index=i:self.select_segment(index))
            self.canvas.create_text(x(item['timeline_start']),24,text=f"{item['timeline_start']:.2f}",anchor='w')
        for group,y,color in [('audio_tracks',100,'#a7f3d0'),('subtitles',160,'#fde68a'),('overlays',220,'#fecdd3')]:
            for item in report[group]:
                start=item['timeline_start'] if group=='audio_tracks' else item['start']
                end=start+item['source_out']-item['source_in'] if group=='audio_tracks' else item['end']
                self.canvas.create_rectangle(x(start),y,x(end),y+25,fill=color)
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
