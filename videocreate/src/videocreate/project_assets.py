"""Project-owned reference snapshots, scoped asset context and local comparisons."""
from __future__ import annotations

import copy
import html
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

from .asset_library import KINDS, digest, inspect_reference
from .config.storage import ConfigError
from .planning.project import content_hash, load_project, within


def stage_reference(root, source, *, kind):
    """Copy and inspect outside any task lock; never edit a plan or publish media."""
    root=Path(root).resolve();load_project(root);source=Path(source).resolve()
    if kind not in KINDS:raise ConfigError('Unknown project asset kind')
    suffix=source.suffix.lower()
    allowed={'.wav','.mp3','.m4a','.flac','.ogg'} if kind=='voice' else {'.png','.jpg','.jpeg','.webp','.gif'}
    if not source.is_file() or suffix not in allowed:raise ConfigError('Choose a supported local image or voice reference')
    maximum=(256 if kind=='voice' else 48)*1024*1024
    if not 0<source.stat().st_size<=maximum:raise ConfigError('Reference exceeds the local import size limit or is empty')
    expected=digest(source)
    folder=within(root,'assets/references/snapshots',exists=False);folder.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.staging-',suffix=suffix,dir=folder);temporary=Path(temporary)
    try:
        with os.fdopen(fd,'wb') as outgoing,source.open('rb') as incoming:
            total=0
            while True:
                block=incoming.read(1024*1024)
                if not block:break
                total+=len(block)
                if total>maximum:raise ConfigError('Reference grew beyond the local import size limit')
                outgoing.write(block)
            outgoing.flush();os.fsync(outgoing.fileno())
        if digest(temporary)!=expected:raise ConfigError('Source reference changed while copying; retry from stable bytes')
        inspection=inspect_reference(temporary,kind)
        if digest(temporary)!=expected:raise ConfigError('Staged reference changed during inspection')
        target=within(root,'assets/references/snapshots/'+expected+suffix,exists=False)
        try:os.link(temporary,target)
        except FileExistsError:
            if not target.is_file() or digest(target)!=expected:
                raise ConfigError('Existing reference snapshot bytes changed; it was preserved') from None
        return {'ok':True,'path':target.relative_to(root).as_posix(),'sha256':expected,'bytes':total,
            'inspection':inspection,'content_status':'unverified','paid_creates':0,
            'note':'Local snapshot only. Save the asset card to attach it; cancelled edits leave the unreferenced snapshot intact. No model reference or public URL was created.'}
    finally:
        temporary.unlink(missing_ok=True)


def reference_context(root, asset):
    """Retain missing/invalid evidence as unavailable rather than silently dropping it."""
    result=[];root=Path(root).resolve()
    for ref in asset.get('references',[]):
        item={'path':ref}
        try:
            path=within(root,ref);item['sha256']=digest(path)
            addressed=(path.parent==within(root,'assets/references/snapshots',exists=False)
                or path.is_relative_to(within(root,'assets/library',exists=False)))
            if addressed and re.fullmatch(r'[0-9a-f]{64}',path.stem) and path.stem!=item['sha256']:
                raise ConfigError('Snapshot content differs from its address')
            item['status']='available'
        except (ConfigError,OSError,ValueError):item['status']='unavailable'
        result.append(item)
    return result


def asset_context(root, assets):
    return [{'descriptor':copy.deepcopy(asset),'reference_files':reference_context(root,asset)}
        for asset in sorted({a['id']:a for a in assets}.values(),key=lambda a:a['id'])]


def board(root, asset_id):
    """Export a local, read-only board using exact current candidates and files."""
    root=Path(root).resolve();bundle=load_project(root)
    if not isinstance(asset_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',asset_id):
        raise ConfigError('Invalid project asset ID')
    asset=next((a for a in bundle['director']['assets'] if a['id']==asset_id),None)
    if not asset:raise ConfigError('Save the project asset before exporting its comparison board')
    from .runtime.state import read_state
    from .runtime.candidates import selected
    from .asset_library import impact
    usage=impact(root,asset_id);shot_ids=set(usage['shots']);media=[];unavailable=[]
    for item in reference_context(root,asset):
        if item['status']=='available':media.append({**item,'kind':'audio' if asset['kind']=='voice' else 'image','role':'角色/素材参考'})
        else:unavailable.append(item['path'])
    def append(path,expected,kind,role,identity):
        try:
            resolved=within(root,path)
            if digest(resolved)!=expected:raise ConfigError('Comparison file changed')
            media.append({'path':path,'sha256':expected,'kind':kind,'role':role,'source_id':identity})
        except (ConfigError,OSError,ValueError):unavailable.append(identity)
    state=read_state(root)
    for job in bundle['generation-plan']['jobs']:
        if job['id'] not in usage['jobs']:continue
        for ref in job.get('references',[]):
            if ref.get('role')=='opening-frame':append(ref['path'],ref['sha256'],'image','任务首帧参考',job['id'])
        try:record=selected(state['jobs'].get(job['id'],{}))
        except ConfigError:unavailable.append(job['id']);continue
        if record.get('status')=='completed':
            artifact=record.get('artifact',{})
            append(artifact.get('path',''),artifact.get('sha256'),'video','已选生成候选原片',job['id'])
    for source in bundle['generation-plan'].get('local_sources',[]):
        if shot_ids & set(source['shot_ids']):append(source['path'],source['sha256'],'video','本地来源原片',source['id'])
    source_hash=content_hash({'asset':asset,'usage':usage,'media':media,'unavailable':unavailable})
    output=within(root,'review/asset-boards/'+asset_id+'-'+source_hash+'.html',exists=False);output.parent.mkdir(parents=True,exist_ok=True)
    esc=html.escape
    cards=[]
    for item in media:
        path=within(root,item['path'])
        url=quote(os.path.relpath(path,output.parent).replace('\\','/'),safe='/.-_')
        if item['kind']=='image':player='<img loading="lazy" src="'+esc(url,quote=True)+'" alt="参考素材">'
        else:player='<'+item['kind']+' controls preload="metadata" src="'+esc(url,quote=True)+'"></'+item['kind']+'>'
        cards.append('<article><h2>'+esc(item['role']+' '+item.get('source_id',''))+'</h2>'+player+'<p>'+esc(item['path'])+'</p><code>'+item['sha256']+'</code></article>')
    details=json.dumps(asset,ensure_ascii=False,indent=2)
    body='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>角色与素材对照</title><style>body{font:16px system-ui,sans-serif;max-width:1400px;margin:auto;padding:24px;background:#f6f7fb;color:#182032}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}article{background:white;padding:16px;border-radius:12px;overflow-wrap:anywhere}img,video,audio{width:100%;max-height:520px;object-fit:contain}pre{white-space:pre-wrap}code{font-size:12px}</style>'''
    body+='<h1>'+esc(asset_id)+' · 角色与素材对照</h1><p>本页供查看与试听，打开或播放不会批准身份、动作、声音或成片。首帧参考不等于视频实际首帧；文件哈希匹配不代表内容合格。</p>'
    body+='<details><summary>当前资料与固定特征</summary><pre>'+esc(details)+'</pre></details>'
    body+='<p>涉及镜头：'+esc('、'.join(usage['shots']) or '暂无')+'；涉及任务：'+esc('、'.join(usage['jobs']) or '暂无')+'</p>'
    if unavailable:body+='<p>文件缺失、改变或不可读：'+esc('、'.join(unavailable))+'</p>'
    body+='<section>'+''.join(cards)+'</section><p>导出来源版本：'+source_hash+'</p></html>'
    if content_hash(load_project(root))!=content_hash(bundle) or content_hash(read_state(root))!=content_hash(state):
        raise ConfigError('Project or task state changed during comparison export; export the current version again')
    for item in media:
        if digest(within(root,item['path']))!=item['sha256']:
            raise ConfigError('Media changed during comparison export; export the current version again')
    output.write_text(body,encoding='utf-8')
    return {'ok':True,'page':str(output),'source_hash':source_hash,'media':media,'unavailable':unavailable,
        'comparison_only':True,'content_status':'unverified','paid_creates':0}
