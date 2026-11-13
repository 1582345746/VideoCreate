"""Pure image/GIF plans reuse existing image attempts, budgets and review receipts."""
from pathlib import Path
import hashlib
import html
import json
import re

from .config.storage import ConfigError, atomic_json, load_json
from .planning.project import content_hash, within

PROFILES = {'image-only', 'gif-only', 'gif-local'}


def is_image(bundle):
    return bundle['brief'].get('workflow_profile') in PROFILES


def references(root, job):
    paths=[]
    for reference in job.get('references', []):
        path=within(root,reference['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=reference['sha256']:
            raise ConfigError('Image reference bytes changed: '+job['id'])
        from .media.gif import probe_image
        probe_image(path)
        paths.append(path)
    return paths


def validate(bundle, root=None):
    errors=[]
    generation=bundle['generation-plan']
    jobs=generation.get('image_jobs',[])
    if generation['jobs'] or generation.get('local_sources') or bundle['director']['shots'] or bundle['story']['beats']:
        errors.append('Pure image/GIF plans must not contain video jobs, local videos, shots or story beats')
    if any(bundle['timeline'].get(k) for k in ('clips','segments','audio_tracks','subtitles','overlays')):
        errors.append('Pure image/GIF plans do not use a video timeline')
    if not jobs and not generation.get('local_gifs'):
        errors.append('At least one planned image or local GIF is required; use production gif-video/gif-frames for local sources')
    from . import local_gifs
    errors.extend(local_gifs.validate(bundle, root))
    ids=set()
    for job in jobs:
        identity=job['id']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',identity) or identity in ids or identity=='final':
            errors.append('Image jobs need unique IDs; final is reserved')
        ids.add(identity)
        if not job['prompt'].strip():errors.append(identity+': author a nonempty image prompt')
        if len(job['prompt'].encode('utf-8'))>4096:errors.append(identity+': image adapter prompt exceeds 4096 UTF-8 bytes')
        if bool(job.get('references')) != (job['operation']=='image-edit'):
            errors.append(identity+': image-edit requires references; text-to-image must omit them')
        animated=bundle['brief']['workflow_profile'] in {'gif-only','gif-local'}
        if (job['output_format']=='gif') != animated:
            errors.append(identity+': output format must match the static-image/GIF workflow')
        if not job['size'].strip() or not job['quality'].strip():errors.append(identity+': size and quality must not be empty')
        if root:
            try:references(Path(root).resolve(),job)
            except (ConfigError,OSError,ValueError) as exc:errors.append(str(exc))
    return {'ok':not errors,'structural':'fail' if errors else 'pass','content':'unverified',
        'errors':errors,'warnings':[],'coverage':[],'paid_creates':0}


def items(root,bundle,job_ids=None):
    from .runtime.state import read_state
    selected=set(job_ids or [j['id'] for j in bundle['generation-plan']['image_jobs']])
    if selected-{j['id'] for j in bundle['generation-plan']['image_jobs']}:
        raise ConfigError('Unknown planned image job ID')
    state=read_state(root)
    result=[]
    for job in bundle['generation-plan']['image_jobs']:
        if job['id'] not in selected:continue
        prior=state['jobs'].get(job['id'],{})
        if prior and prior.get('kind')!='image':raise ConfigError('Image ID conflicts with a saved non-image task')
        value={k:job[k] for k in ('prompt','size','quality','output_format','model','binding_id') if k in job}
        snapshot=prior.get('binding_snapshot',{})
        if snapshot and (not value.get('model') or value['model']==snapshot.get('model')):
            value.setdefault('model',snapshot['model'])
            value.setdefault('binding_id',snapshot['binding_id'])
        result.append({'job_id':job['id'],'references':references(root,job),**value})
    return result


def compile_plan(root,bundle,config,store_root,job_ids=None,binding_override=None):
    from .assets import _select_image_route
    from .selection import resolve
    from .runtime.state import read_state
    from .adapters.image import BindingImageClient
    from .runtime.budget import estimate
    rows=[]
    state=read_state(root)
    for item in items(root,bundle,job_ids):
        prior=state['jobs'].get(item['job_id'],{})
        if prior.get('status') in {'submitting','submission_unknown'}:
            rows.append({'job_id':item['job_id'],'status':'held','binding':prior.get('binding_snapshot',{}).get('binding_id'),
                'reason':'Reconcile the original image attempt; no new route or request was prepared'})
            continue
        if binding_override:
            item['binding_id']=binding_override
        pair=resolve(root,config,kind='image',store_root=store_root,model=item.get('model'),binding=item.get('binding_id'),
            operation='image-edit' if item['references'] else 'text-to-image')
        model,binding_id=pair if pair else (item.get('model'),item.get('binding_id'))
        model,candidates,selection=_select_image_route(config,requested_model=model,binding_id=binding_id,
            prompt=item['prompt'],references=item['references'],size=item['size'],quality=item['quality'],
            output_format=item['output_format'],store_root=store_root)
        binding=candidates[0]
        prepared=BindingImageClient(binding).prepare(item['prompt'],item['references'],size=item['size'],
            quality=item['quality'],output_format=item['output_format'])
        rows.append({'job_id':item['job_id'],'model':model,'binding':binding.id,'prepared':prepared,
            'estimate':estimate(binding,0,config.get('budget',{}).get('currency','CNY'),parameters={
                'operation':'image-edit' if item['references'] else 'text-to-image'}),'selection':selection})
    from . import local_gifs
    return {'ok':True,'kind':bundle['brief']['workflow_profile'],'jobs':rows,'local_gifs':local_gifs.rows(root,bundle),'paid_creates':0,
        'provider_configuration_required':bool(bundle['generation-plan'].get('image_jobs')),
        'verification':'offline-preflight; no generation or content acceptance'}


def run(root,bundle,config,store_root,*,job_ids=None,retry=None,reason=''):
    from .assets import generate_images,generate_image
    from .planning.project import validate_plan
    checked=validate_plan(bundle,root)
    if not is_image(bundle) or not checked['ok']:raise ConfigError('; '.join(checked['errors']) or 'Use a pure image/GIF plan')
    if not bundle['generation-plan'].get('image_jobs'):
        raise ConfigError('This project uses local GIF derivations; use gif-video/gif-frames/gif-rebuild, without provider configuration')
    batch=items(root,bundle,job_ids)
    if retry:
        if retry not in {'content','replan'} or not job_ids or len(batch)!=1 or not reason.strip():
            raise ConfigError('Image retry requires one explicit --job, content/replan and a reason')
        return generate_image(root,config,store_root=store_root,**batch[0],retry=retry,reason=reason)
    return generate_images(root,config,store_root=store_root,items=batch)


def rows(root,bundle,state):
    from .assets import _image_input_hash
    from .media.gif import probe_image
    result=[]
    for job in bundle['generation-plan'].get('image_jobs',[]):
        record=state['jobs'].get(job['id'],{})
        snapshot=record.get('binding_snapshot',{})
        row={'job_id':job['id'],'kind':'image','status':record.get('status','not-submitted'),
            'original_status':record.get('status','not-submitted'),'task_id':record.get('task_id'),
            'binding':snapshot.get('binding_id'),'model':snapshot.get('model'),'upstream':snapshot.get('upstream_id'),
            'candidate_count':len(record.get('history',[]))+bool(record),'content_status':'unverified',
            'artifact':record.get('artifact',{}),'error':''}
        if row['status']=='completed':
            try:
                if record.get('kind')!='image':raise ConfigError('Saved task is not an image task')
                if (job.get('model') and job['model']!=snapshot.get('model') or
                        job.get('binding_id') and job['binding_id']!=snapshot.get('binding_id')):
                    raise ConfigError('Planned image route changed; explicit replan required')
                current=_image_input_hash(root,model=snapshot['model'],prompt=job['prompt'],size=job['size'],
                    quality=job['quality'],output_format=job['output_format'],references=references(root,job))
                if current!=record.get('input_hash'):raise ConfigError('Image inputs changed; explicit replan required')
                path=within(root,row['artifact']['path'])
                media=probe_image(path)
                if media['sha256']!=row['artifact'].get('sha256'):raise ConfigError('Image output bytes changed')
                if media['format']!=job['output_format'] or job['output_format']=='gif' and not media['animated']:
                    raise ConfigError('Actual image format/animation does not match the plan')
                row['media']=media
                if record.get('content_status') in {'reviewed','rejected'} and record.get('reviewed_sha256')==media['sha256']:
                    try:receipt=load_json(within(root,record.get('review_receipt','')))
                    except (ConfigError,OSError,ValueError):receipt={}
                    if (receipt.get('job_id')==job['id'] and receipt.get('artifact',{}).get('sha256')==media['sha256']
                            and receipt.get('input_hash')==current and receipt.get('reviewer_id') and receipt.get('observation')
                            and receipt.get('status') in {'pass','fail'} and (not media['animated'] or receipt.get('temporal_observation') is True)):
                        row['content_status']='rejected' if record['content_status']=='rejected' or receipt['status']=='fail' else 'reviewed'
            except (ConfigError,OSError,ValueError,KeyError) as exc:
                row.update(status='stale',error=str(exc))
        result.append(row)
    return result


def review_summary(task_rows):
    rejected=any(r['content_status']=='rejected' for r in task_rows)
    complete=bool(task_rows) and all(r['status']=='completed' for r in task_rows)
    accepted=complete and all(r['content_status']=='reviewed' for r in task_rows)
    return {'status':'rejected' if rejected else 'accepted_delivery' if accepted else 'review_pending' if complete else 'draft_preview',
        'assets':{r.get('job_id') or r['gif_id']:{'image_content':r['content_status']} for r in task_rows if r['status']=='completed'},
        'valid_receipts':sum(r['content_status'] in {'reviewed','rejected'} for r in task_rows),
        'structural_is_content_approval':False}


def impact(root,bundle,state):
    from .assets import _image_input_hash
    changed,unchanged,pending=[],[],[]
    for job in bundle['generation-plan'].get('image_jobs',[]):
        prior=state['jobs'].get(job['id'])
        if not prior:
            pending.append(job['id']);continue
        snapshot=prior.get('binding_snapshot',{})
        try:
            current=_image_input_hash(root,model=snapshot['model'],prompt=job['prompt'],size=job['size'],
                quality=job['quality'],output_format=job['output_format'],references=references(root,job))
            same=current==prior.get('input_hash') and (not job.get('model') or job['model']==snapshot['model']) and (
                not job.get('binding_id') or job['binding_id']==snapshot['binding_id'])
        except (ConfigError,KeyError,OSError,ValueError):same=False
        (unchanged if same else changed).append(job['id'])
    from . import local_gifs
    local_rows=local_gifs.rows(root,bundle)
    return {'ok':True,'changed_job_inputs':changed,'dependent_jobs_to_check':[],
        'changed_local_gifs':[r['gif_id'] for r in local_rows if r['status']=='stale'],
        'reusable_local_gifs':[r['gif_id'] for r in local_rows if r['status']=='completed'],
        'reusable_inputs':unchanged,'not_submitted':pending,'paid_creates':0,
        'note':'No request was created. Changed image inputs require an explicit replan.'}


def status(root,bundle,state,record,check,stages):
    from .production import NAMES,next_for_policy
    from .runtime.budget import summary
    task_rows=rows(root,bundle,state)
    from . import local_gifs
    local_rows=local_gifs.rows(root,bundle)
    affected=impact(root,bundle,state)
    ambiguous=[r['job_id'] for r in task_rows if r['status'] in {'submitting','submission_unknown'}]
    complete=bool(task_rows) and all(r['status']=='completed' for r in task_rows)
    review=review_summary([*task_rows,*local_rows])
    stages.extend([
        {'id':'generation','name':NAMES['generation'],'status':'skipped' if not task_rows else 'blocked' if ambiguous else 'stale' if affected['changed_job_inputs'] else 'complete' if complete else 'pending','blocked_by':ambiguous,
            'reason':'This collection has no provider image jobs; local GIF recipes use source imports' if not task_rows else ''},
        {'id':'editing','name':NAMES['editing'],'status':'stale' if affected['changed_local_gifs'] else 'complete' if local_rows else 'ready' if bundle['brief']['workflow_profile']=='gif-local' else 'skipped',
            'reason':'Local GIF conversion uses source snapshots and explicit recipes; no video timeline' if local_rows or bundle['brief']['workflow_profile']=='gif-local' else 'Pure image/GIF deliverables have no video timeline'},
        {'id':'review','name':NAMES['review'],'status':'complete' if review['status']=='accepted_delivery' else 'blocked' if review['status']=='rejected' else 'pending','reason':review['status']},
        {'id':'delivery','name':NAMES['delivery'],'status':'ready' if review['status']=='accepted_delivery' else 'pending'}])
    next_step=next_for_policy(stages,record)
    if ambiguous:next_step={'id':'reconcile','name':'核对原图片提交；不重复创建','jobs':ambiguous}
    elif bundle['brief']['workflow_profile']=='gif-local' and not local_rows:
        next_step={'id':'import-gif-source','name':'导入视频或有序静帧，制作本地 GIF'}
    elif not check['ok']:next_step={'id':'repair-plan','name':'完善图片提示词与计划','errors':check['errors']}
    return {'ok':check['ok'],'project':str(root),'title':bundle['project']['title'],'branch':bundle['brief']['workflow_profile'],
        'policy':record.get('policy','assisted'),'required_authoring_stages':record.get('required_authoring_stages',[]),
        'stages':stages,'next':next_step,'jobs':task_rows,'local_sources':[], 'local_gifs':local_rows,
        'impact':affected,'budget':summary(state),'review':review,'errors':check['errors'],'warnings':check['warnings'],'paid_creates':0}


def deliver(root,bundle):
    from .planning.project import validate_plan
    from .runtime.state import read_state
    from .runtime.budget import summary
    check=validate_plan(bundle,root)
    if not check['ok']:raise ConfigError('; '.join(check['errors']))
    state=read_state(root);task_rows=rows(root,bundle,state)
    from . import local_gifs
    local_rows=local_gifs.rows(root,bundle)
    all_rows=[*task_rows,*local_rows]
    if not all_rows or any(r['status']!='completed' for r in all_rows):
        raise ConfigError('Every planned image must have a current, hash-valid completed output before delivery')
    review=review_summary(all_rows)
    value={'schema_version':1,'kind':bundle['brief']['workflow_profile'],'status':review['status'],
        'plan_hash':content_hash(bundle),'jobs':task_rows,'local_gifs':local_rows,'review':review,'budget':summary(state),
        'artifacts':[{**({'job_id':r['job_id']} if 'job_id' in r else {'gif_id':r['gif_id']}),**r['artifact'],'media':r['media']} for r in all_rows],
        'source_references':{j['id']:j.get('references',[]) for j in bundle['generation-plan'].get('image_jobs',[])},
        'unverified':[] if review['status']=='accepted_delivery' else ['Actual image/GIF review is incomplete or rejected'],
        'paid_creates':0}
    path=root/'deliverables/images.delivery.json';atomic_json(path,value)
    return {'ok':True,'manifest':str(path),**value}


def brief_export(root,bundle):
    value={'schema_version':1,'kind':bundle['brief']['workflow_profile'],'title':bundle['project']['title'],
        'source':'generation-plan.image_jobs/local_gifs','source_hash':content_hash(bundle['generation-plan'].get('image_jobs',[])),
        'image_jobs':bundle['generation-plan'].get('image_jobs',[]), 'local_gifs':bundle['generation-plan'].get('local_gifs',[]),'read_only':True}
    value['source_hash']=content_hash({'image_jobs':value['image_jobs'],'local_gifs':value['local_gifs']})
    target=root/'production/image-brief.json';atomic_json(target,value)
    lines=['# '+value['title'],'','图片 / GIF 创作单：只读导出；在 generation-plan.json 编辑 image_jobs 或 local_gifs 配方。','']
    for job in value['image_jobs']:
        lines.extend(['## '+job['id'],'',job['prompt'],'',
            '规格：'+job['size']+' / '+job['quality']+' / '+job['output_format'],
            '参考：'+', '.join(r['path'] for r in job.get('references',[])),''])
    for item in value['local_gifs']:
        lines.extend(['## '+item['id'],'','本地 GIF 配方：'+json.dumps(item['recipe'],ensure_ascii=False),
            '派生记录：'+item['derivation']['path'],''])
    reading=target.with_suffix('.md');reading.write_text('\n'.join(lines),encoding='utf-8')
    return {'ok':True,'image_brief':str(target),'reading_copy':str(reading),
        'source_hash':value['source_hash'],'read_only':True,'paid_creates':0}


def page(root,bundle):
    from .runtime.state import read_state
    current=rows(root,bundle,read_state(root))
    from . import local_gifs
    current.extend(local_gifs.rows(root,bundle))
    output=root/'deliverables/image-review.html';output.parent.mkdir(parents=True,exist_ok=True)
    cards=[]
    for row in current:
        if row['status']!='completed':continue
        uri=within(root,row['artifact']['path']).as_uri()
        cards.append('<article><h2>'+html.escape(row.get('job_id') or row['gif_id'])+'</h2><img src="'+html.escape(uri,quote=True)+'"><p>'
            +html.escape(row['content_status'])+'</p><code>'+html.escape(row['artifact']['sha256'])+'</code></article>')
    output.write_text('<!doctype html><meta charset="utf-8"><title>Image/GIF review</title>'
        '<style>body{font:18px system-ui;max-width:1000px;margin:40px auto}img{max-width:100%;max-height:70vh}article{margin:40px 0}code{overflow-wrap:anywhere}</style>'
        '<h1>'+html.escape(bundle['project']['title'])+'</h1><p>Opening this page approves nothing. Inspect actual imagery; play the entire GIF. '
        'Record observations with review image (generated) or review gif (local); animated GIFs require --temporal-observation.</p>'+''.join(cards),encoding='utf-8')
    return {'ok':True,'page':str(output),'items':len(cards),'status':'review_pending','paid_creates':0}
