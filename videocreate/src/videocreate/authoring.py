"""Offline creation and versioned editing of authoritative authoring layers."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .config.management import changed_paths
from .config.storage import ConfigError, atomic_json
from .planning.profiles import create as profile_plan
from .planning.project import content_hash, load_project, save_bundle, validate_plan, within
from .planning.schema import schema_errors
from .runtime.state import read_state, state_lock

LAYERS = ('brief', 'story', 'director', 'generation-plan', 'timeline')


def create(root, *, profile, title, topic='', audience='', viewer_goal='', seconds=None, aspect_ratio='16:9'):
    root = Path(root).resolve()
    if not isinstance(title,str) or not title.strip():
        raise ConfigError('A new project needs a nonempty title')
    if any(not isinstance(value,str) for value in (topic,audience,viewer_goal)):
        raise ConfigError('Topic, audience and viewer goal must be text')
    bundle = profile_plan(profile,title=title.strip(),topic=topic,seconds=seconds,aspect_ratio=aspect_ratio)
    bundle['brief'].update(topic=topic.strip(),audience=audience.strip(),viewer_goal=viewer_goal.strip())
    errors = schema_errors(bundle)
    if errors:
        raise ConfigError('; '.join(errors))
    # Claim the directory exclusively. Existing empty directories and partial
    # projects are also preserved; project.json is written last by save_bundle.
    root.parent.mkdir(parents=True,exist_ok=True)
    try:
        root.mkdir()
    except FileExistsError:
        raise ConfigError('Project destination already exists; choose a new directory or open the existing project') from None
    save_bundle(root,bundle)
    return {'ok':True,'project':str(root),'status':'draft_plan','paid_creates':0,
        'plan_validation':validate_plan(bundle,root),
        'note':'Editable starting plan only; author the actual story and shots before generation. No model was selected or called.'}


def describe(root, layer):
    if layer not in LAYERS:
        raise ConfigError('Unsupported authoring layer')
    root = Path(root).resolve()
    bundle = load_project(root)
    if layer=='timeline' and bundle['brief'].get('workflow_profile') in {'image-only','gif-only','gif-local'}:
        raise ConfigError('Image/GIF collection projects have no video timeline; edit their jobs or conversion recipes instead')
    if layer in {'story','director','generation-plan'} and 'animation' in bundle:
        raise ConfigError('Animation story/director/generation-plan is projected from its animation sidecar; edit that authoring source instead')
    return {'ok':True,'layer':layer,'title':bundle['project']['title'],
        'source_token':content_hash(bundle),'value':copy.deepcopy(bundle[layer]),'paid_creates':0}


def _preview(root, layer, value, source_token):
    current = describe(root,layer)
    bundle = load_project(root)
    if current['source_token']!=content_hash(bundle) or source_token!=current['source_token']:
        raise ConfigError('Project content changed; reload the authoring form before previewing or saving')
    if not isinstance(value,dict):
        raise ConfigError('Authoring value must be an object')
    if layer=='brief' and value.get('workflow_profile')!=bundle['brief'].get('workflow_profile'):
        raise ConfigError('This editor preserves the workflow profile; create or explicitly convert a project separately')
    candidate = copy.deepcopy(bundle)
    candidate[layer] = copy.deepcopy(value)
    errors = schema_errors(candidate)
    if errors:
        raise ConfigError('; '.join(errors))
    from .production import impact
    report = impact(root,candidate=candidate)
    state = read_state(root)
    generation_changes=None
    if layer=='generation-plan':
        from .generation_authoring import changes
        generation_changes=changes(bundle,candidate,state)
    changed = report.get('changed_job_inputs',[])
    tasks = [{'job_id':jid,'status':item.get('status','unknown'),
              'inputs_changed':jid in changed,'has_task_id':bool(item.get('task_id'))}
             for jid,item in state['jobs'].items()]
    result = {'ok':True,'layer':layer,'source_token':source_token,
        'changed_paths':changed_paths(bundle[layer],value),
        'plan_validation':validate_plan(candidate,root),'impact':report,'existing_tasks':tasks,
        'paid_creates':0,'approval_scope':'authoring edit only; no stage or media approval',
        'note':'Semantic errors may be saved as a draft. Execution remains blocked until plan validation passes. Existing tasks and candidates are preserved.'}
    if generation_changes is not None:result['generation_changes']=generation_changes
    if layer=='timeline':
        from .timeline_authoring import inspect
        result['timeline_edit']={'before':inspect(bundle[layer]),'after':inspect(value),
            'note':'Only the edit plan changes. Source-time captions follow their segment; absolute cues and audio events keep their authored timeline times. Render and review the changed edit separately.'}
    result['preview_token'] = content_hash({'project':str(root),'layer':layer,'source_token':source_token,
        'value':value,'state':state,'report':result})
    return result,bundle,candidate,state


def preview(root, layer, value, *, source_token):
    return _preview(Path(root).resolve(),layer,value,source_token)[0]


def save(root, layer, value, *, source_token, preview_token):
    root = Path(root).resolve()
    # Hash/probe work must stay outside the short task-state lock.
    result,bundle,candidate,state = _preview(root,layer,value,source_token)
    if preview_token!=result['preview_token']:
        raise ConfigError('The edit or task state changed after preview; preview the current edit again')
    with state_lock(root):
        if content_hash(load_project(root))!=source_token or content_hash(read_state(root))!=content_hash(state):
            raise ConfigError('Project or task state changed during save preparation; preview the current edit again')
        target = within(root,bundle['project'].get('files',{}).get(layer,layer+'.json'))
        if not result['changed_paths']:
            return {**result,'changed':False,'backup':None,'status':'unchanged'}
        backup = root/'production/backups'/(content_hash(bundle[layer])+'.'+layer+'.json')
        atomic_json(backup,bundle[layer])
        atomic_json(target,candidate[layer])
    return {**result,'changed':True,'backup':str(backup),'status':'authoring_saved',
        'source_token':content_hash(candidate)}


def outline(root):
    root = Path(root).resolve()
    bundle = load_project(root)
    brief,story = bundle['brief'],bundle['story']
    lines = ['# '+bundle['project']['title']+' · 制作主题与大纲','',
        '只读阅读稿，来源为 brief/story；修改此文不会写回项目，也不表示素材已验收。',
        '来源版本：'+content_hash({'brief':brief,'story':story}),'',
        '主题：'+brief.get('topic',''),'受众：'+brief.get('audience',''),
        '观众应理解：'+brief.get('viewer_goal',''),
        '生成规格：'+brief['aspect_ratio']+' · '+brief['resolution'],
        '声音策略：'+brief.get('audio_policy','按分镜设置'),'']
    for key,label in [('logline','一句话故事'),('goal','目标'),('obstacle','阻碍'),
                      ('choice','选择'),('consequence','结果'),('payoff','落点')]:
        if story.get(key):lines.extend([label+'：'+story[key],''])
    shots = bundle['director']['shots']
    for beat in story['beats']:
        lines.extend(['## '+beat['id'],'',beat['audience_learns'],
            '前因：'+('、'.join(beat['causes']) or '开端'),
            '发生前：'+json.dumps(beat['requires'],ensure_ascii=False),
            '发生后：'+json.dumps(beat['effects'],ensure_ascii=False),
            '需要看见：'+'；'.join(beat['visible_evidence_needed']),
            '覆盖镜头：'+('、'.join(s['id'] for s in shots if s.get('beat_id')==beat['id']) or '尚未安排'),''])
    target = root/'production/outline.md'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('\n'.join(lines),encoding='utf-8')
    return {'ok':True,'reading_copy':str(target),'source_hash':content_hash({'brief':brief,'story':story}),
        'read_only_projection':True,'paid_creates':0}
