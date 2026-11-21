"""Typed catalog fields; preserve advanced values without parallel UI schemas."""
import copy
import json
import tkinter as tk
from . import manager_lifecycle as ui
from tkinter import ttk

from .config.storage import ConfigError, parse_json


def get_path(value, path):
    for key in path.split('.'):
        value = value.get(key, {}) if isinstance(value, dict) else {}
    return '' if value is None or isinstance(value, dict) else value


def set_path(value, path, item):
    keys = path.split('.')
    node = value
    for key in keys[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            raise ConfigError('Expected an object at ' + path)
    if item == '':
        node.pop(keys[-1], None)
    else:
        node[keys[-1]] = item


def prune(value):
    return {k: prune(v) if isinstance(v, dict) else v for k, v in value.items()
            if not isinstance(v, dict) or prune(v)}


def converted(raw, kind):
    if not raw.strip():
        return ''
    if kind == 'integer':
        return int(raw)
    if kind == 'number':
        return float(raw)
    if kind == 'list':
        return [v.strip() for v in raw.split(',') if v.strip()]
    if kind == 'boolean':
        if raw not in {'是','否','true','false','True','False'}:
            raise ConfigError('Choose yes, no or leave unknown')
        return raw in {'是','true','True'}
    if kind == 'combinations':
        return json.loads(raw)
    return raw.strip()


class CombinationChoices:
    """Seven supported subsets; retain existing order when the form is unchanged."""
    def __init__(self, parent, initial):
        import itertools
        self.initial = initial if isinstance(initial,list) else []
        kinds = ['image','video','audio']
        self.choices = []
        for length in range(1,4):
            for combo in itertools.combinations(kinds,length):
                var = ui.BooleanVar(parent, value=any(set(combo)==set(item) for item in self.initial))
                self.choices.append((list(combo),var))
                ttk.Checkbutton(parent,text=' + '.join({'image':'图片','video':'视频','audio':'音频'}[k] for k in combo),
                    variable=var).pack(anchor='w',pady=2)

    def get(self):
        selected = [combo for combo,var in self.choices if var.get()]
        values = [item for item in self.initial if any(set(item)==set(combo) for combo in selected)]
        values += [combo for combo in selected if not any(set(combo)==set(item) for item in values)]
        return json.dumps(values) if values or self.initial else ''


class Fields:
    """Common fields on a scrollable page, uncommon fields in an advanced page."""
    def __init__(self, book, title, value, fields, explanation=''):
        section = ttk.Notebook(book)
        self.section = section
        book.add(section, text=title)
        page = ttk.Frame(section)
        section.add(page, text='常用字段')
        canvas = tk.Canvas(page, highlightthickness=0)
        scroll = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        inner = ttk.Frame(canvas, padding=16)
        item = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
        inner.columnconfigure(1, weight=1)
        ttk.Label(inner, text=explanation, wraplength=640, foreground='#64748b').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 12))
        self.fields = []
        remainder = copy.deepcopy(value)
        for row, (path, label, kind) in enumerate(fields, 1):
            initial = get_path(value, path)
            if isinstance(initial, list) and kind != 'combinations':
                initial = ','.join(map(str, initial))
            if kind=='boolean' and isinstance(initial,bool):initial='是' if initial else '否'
            var = ui.StringVar(inner, value=str(initial))
            ttk.Label(inner, text=label).grid(row=row, column=0, sticky='w', padx=(0, 15), pady=7)
            if kind=='combinations':
                widget=ttk.Frame(inner)
                var=CombinationChoices(widget,initial)
            elif kind=='multiline':
                widget=tk.Text(inner,height=5,wrap='word',font=('Microsoft YaHei UI',10),undo=True)
                widget.insert('1.0',str(initial))
                var=widget
            elif kind=='boolean':
                widget=ttk.Combobox(inner,textvariable=var,values=('','是','否'),state='readonly')
            elif isinstance(kind, tuple):
                widget = ttk.Combobox(inner, textvariable=var, values=('', *kind), state='readonly')
            else:
                widget = ttk.Entry(inner, textvariable=var)
            widget.grid(row=row, column=1, sticky='ew', pady=7)
            self.fields.append((path, var, kind))
            set_path(remainder, path, '')
        advanced = ttk.Frame(section, padding=12)
        section.add(advanced, text='高级字段')
        ttk.Label(advanced, text='仅保存未列入普通表单的字段；重复字段会被拒绝。').pack(anchor='w', pady=(0, 8))
        self.extra = tk.Text(advanced, wrap='word', font=('Consolas', 10), undo=True)
        self.extra.pack(fill='both', expand=True)
        self.extra.insert('1.0', json.dumps(prune(remainder), ensure_ascii=False, indent=2))

    def read(self):
        result = parse_json(self.extra.get('1.0', 'end').strip() or '{}')
        for path, var, kind in self.fields:
            if get_path(result, path) != '':
                raise ConfigError('Duplicate field in advanced page: ' + path)
            try:
                raw = var.get('1.0','end-1c') if kind=='multiline' else var.get()
                set_path(result, path, converted(raw, kind))
            except ValueError:
                raise ConfigError('Invalid value for ' + path) from None
        return prune(result)


DECLARED = [
    ('references.images', '参考图片数量（声明）', 'integer'),
    ('references.videos', '参考视频数量（声明）', 'integer'),
    ('references.audios', '参考音频数量（声明）', 'integer'),
    ('references.combined_total', '混合参考总数（未知留空）', 'integer'),
    ('duration.minimum', '最短秒数', 'number'), ('duration.maximum', '最长秒数', 'number'),
    ('duration.step', '时长步长（秒）', 'number'), ('resolutions', '分辨率（逗号分隔）', 'list'),
    ('aspect_ratios.raw', '画幅说明原文', 'text'), ('prompt.limit', '提示词上限', 'integer'),
    ('prompt.unit', '上限单位', ('characters', 'bytes', 'tokens', 'unknown')),
    ('prompt.counting_rule', '计数规则', ('unknown', 'unicode-codepoints', 'utf16-code-units', 'utf8-bytes')),
    ('human_reference_note', '真人参考说明', 'text'), ('audio_note', '声音说明', 'text'),
    ('source.kind', '资料来源', ('user', 'screenshot', 'documentation', 'catalog', 'observed')),
    ('source.url', '来源链接', 'text'), ('source.observed_at', '记录日期', 'text')]

CAPABILITIES = [
    ('duration.minimum', '最短秒数', 'number'), ('duration.maximum', '最长秒数', 'number'),
    ('duration.step', '时长步长', 'number'), ('resolutions', '可发送分辨率', 'list'),
    ('aspect_ratios', '可发送画幅（逗号分隔）', 'list'),
    ('max_reference_images', '图片总数上限', 'integer'),
    ('max_additional_reference_images', '附加图片上限', 'integer'),
    ('prompt_limit.maximum', '提示词上限（v4）', 'integer'),
    ('prompt_limit.counting_rule', '实际计数规则', ('unicode-codepoints', 'utf16-code-units', 'utf8-bytes')),
    ('audio_control', '声音开关', ('explicit', 'model-default', 'unsupported', 'unknown', 'not-applicable'))]

MEDIA_REFERENCE_LIMITS = [('maximum_total_count', '所有素材合计数量', 'integer'),
    ('maximum_total_bytes', '所有素材合计字节', 'integer'),
    ('minimum_url_validity_seconds', '链接至少剩余有效秒数', 'integer'),
    ('audio_reference_with_generated_audio','音频参考可与声音生成同时使用','boolean'),
    ('allowed_combinations','允许的参考组合（仅按明确合同勾选）','combinations')]
for kind, label in [('image', '图片'), ('video', '视频'), ('audio', '音频')]:
    MEDIA_REFERENCE_LIMITS += [(kind + '.' + key, label + ' · ' + title, data_type) for key, title, data_type in [
        ('maximum_count', '数量上限', 'integer'), ('maximum_bytes', '单文件字节上限', 'integer'),
        ('maximum_total_bytes', '合计字节上限', 'integer'), ('mime_types', 'MIME 类型（逗号分隔）', 'list'),
        ('roles', '用途角色（逗号分隔）', 'list')]]
    if kind != 'image':
        MEDIA_REFERENCE_LIMITS += [(kind + '.maximum_duration_seconds', label + ' · 单文件秒数上限', 'number'),
            (kind + '.maximum_total_duration_seconds', label + ' · 合计秒数上限', 'number')]

PRICES = [
    ('listed_pricing.amount', '供应商展示金额', 'number'),
    ('listed_pricing.display_symbol', '展示货币符号', 'text'),
    ('listed_pricing.currency', '展示币种（未知留空）', 'text'),
    ('listed_pricing.unit', '展示单位', ('request', 'second', 'image', 'unknown')),
    ('listed_pricing.account_group', '展示报价账户组', 'text'),
    ('listed_pricing.notes', '报价备注', 'text'),
    ('pricing.currency', '预算币种（确认后填写）', 'text'),
    ('pricing.per_request', '每请求', 'number'), ('pricing.per_second', '每秒', 'number'),
    ('pricing.per_image', '每张金额（仅图片）', 'number'),
    ('pricing.status', '价格可信状态', ('confirmed', 'unverified')),
    ('pricing.version', '价格版本', 'text'),
    ('pricing.account_group', '预算报价账户组', 'text'),
    ('pricing.billing_event', '计费事件说明', 'text'),
    ('pricing.minimum_seconds', '最低计费秒数', 'number'),
    ('pricing.round_seconds', '秒数向上取整步长', 'number'),
    ('pricing.effective_at', '价格生效 ISO 时间', 'text'),
    ('pricing.valid_until', '价格有效截止 ISO 时间', 'text')]
